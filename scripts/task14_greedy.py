# -*- coding: utf-8 -*-
"""Task E: Greedy K=1,2,3,5 개입 선택 + 사후 타당성 점검 → data_processed/greedy_results.json

- 목적함수: 트램 시나리오 그래프에서 OD가중 총 소요시간 감소량
- 한계효과 평가(정확식): 세그먼트 e=(u,v) 증설 후
  new(o,d) = min(cur(o,d), S[o,u]+tt'+T[v,d], S[o,v]+tt'+T[u,d])
  — S(출발지→전노드), T(전노드→도착지, 역그래프)를 매 반복 재계산하므로
  단일 후보 한계효과는 정확. 반복마다 후보 전체 재평가(greedy 원칙)
- 증설 tt' = 현재(공사 반영) travel_time × 0.7 [가정치 30% — 민감도 분석 대상]
- 사후 점검: 상위 10개(1차 반복 한계효과 기준) 세그먼트가
  (1) 트램 지점 2km 이내 [가정치] (2) 베이스라인 최단경로에 등장(부하>0)
  둘 다 아니면 '의심 사례' 플래그(제거하지 않음)
"""
import json, sys, time
from collections import defaultdict
import numpy as np
import networkx as nx
import osmnx as ox
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
t0 = time.time()
K_LIST = [1, 2, 3, 5]

# ── 트램 시나리오 그래프 재구성 (task13과 동일 규칙)
G = ox.load_graphml("data_processed/daejeon_weighted.graphml")
tram_sc = json.load(open("data_processed/tram_scenario.json", encoding="utf-8"))
affected = set(tram_sc["affected_edges"])
for u, v, k, d in G.edges(keys=True, data=True):
    d["travel_time"] = float(d["travel_time"])
    if f"{u}_{v}_{k}" in affected:
        d["travel_time"] *= 2.0

od = json.load(open("data_processed/od_decomposed.json", encoding="utf-8"))
pairs = od["pairs"]
origins = sorted({p["o"] for p in pairs})
dests = sorted({p["d"] for p in pairs})
oi = {n: i for i, n in enumerate(origins)}
di = {n: i for i, n in enumerate(dests)}
nodes = list(G.nodes)
ni = {n: i for i, n in enumerate(nodes)}
N, nO, nD = len(nodes), len(origins), len(dests)
print(f"origins {nO} / dests {nD} / nodes {N:,}")

W = np.zeros((nO, nD))
for p in pairs:
    W[oi[p["o"]], di[p["d"]]] += p["veh_day"]

Grev = G.reverse(copy=False)

def compute_ST():
    S = np.full((nO, N), np.inf)
    for o in origins:
        dist = nx.single_source_dijkstra_path_length(G, o, weight="travel_time")
        row = S[oi[o]]
        for n, t in dist.items():
            row[ni[n]] = t
    T = np.full((N, nD), np.inf)
    for d in dests:
        dist = nx.single_source_dijkstra_path_length(Grev, d, weight="travel_time")
        col = T[:, di[d]]
        for n, t in dist.items():
            col[ni[n]] = t
    D = S[:, [ni[d] for d in dests]]
    return S, T, D

# ── 후보 로드
cands = json.load(open("data_processed/intervention_candidates.json", encoding="utf-8"))["candidates"]
edge_lookup = {}
for u, v, k, d in G.edges(keys=True, data=True):
    edge_lookup[f"{u}_{v}_{k}"] = d
cand_edges = []
for c in cands:
    des = [(e, edge_lookup[e]) for e in c["directed_edges"] if e in edge_lookup]
    cand_edges.append(des)

S, T, D = compute_ST()
reach = np.isfinite(D)
Wm = np.where(reach, W, 0.0)
base_obj = float((Wm * np.where(reach, D, 0)).sum())
print(f"초기 목적함수(가중 총시간): {base_obj/3600:,.0f} 대·시간/일 "
      f"({time.time()-t0:.0f}초)")

def eval_gain(des, S, T, D):
    new = D
    for eid, d in des:
        u, v = int(eid.split("_")[0]), int(eid.split("_")[1])
        tt_up = d["travel_time"] * 0.7
        new = np.minimum(new, S[:, ni[u]][:, None] + tt_up + T[ni[v], :][None, :])
    return float((Wm * np.maximum(0.0, np.where(reach, D - new, 0.0))).sum())

picks, gains_first, obj_traj = [], None, {}
picked_idx = set()
for it in range(1, max(K_LIST) + 1):
    g = np.zeros(len(cand_edges))
    for ci, des in enumerate(cand_edges):
        if ci in picked_idx or not des:
            continue
        g[ci] = eval_gain(des, S, T, D)
    if gains_first is None:
        gains_first = g.copy()
    best = int(np.argmax(g))
    picked_idx.add(best)
    picks.append({"segment_id": cands[best]["segment_id"],
                  "highway": cands[best]["highway"],
                  "length_m": cands[best]["length_m"],
                  "marginal_gain_veh_h_day": round(g[best] / 3600, 2),
                  "coord_a": cands[best]["coord_a"], "coord_b": cands[best]["coord_b"]})
    for eid, d in cand_edges[best]:
        d["travel_time"] *= 0.7
    S, T, D = compute_ST()
    reach = np.isfinite(D)
    Wm = np.where(reach, W, 0.0)
    obj = float((Wm * np.where(reach, D, 0)).sum())
    if it in K_LIST:
        obj_traj[f"K={it}"] = {"objective_veh_h_day": round(obj / 3600, 1),
                               "improvement_pct": round((base_obj - obj) / base_obj * 100, 3),
                               "saved_abs_veh_min_day": round((base_obj - obj) / 60, 0)}
    print(f"  반복{it}: {cands[best]['segment_id']} ({cands[best]['highway']}, "
          f"{cands[best]['length_m']}m) 한계효과 {g[best]/3600:,.1f} 대·시간/일")

# ── 사후 점검: 1차 반복 한계효과 상위 10개
loads = json.load(open("data_processed/edge_loads_baseline.json", encoding="utf-8"))
def seg_baseline_load(c):
    tot = 0.0
    for e in c["directed_edges"]:
        u, v = e.split("_")[:2]
        tot += loads.get(f"{u}_{v}", 0.0)
    return tot

coords = pd.read_csv("data_processed/shock_and_hub_coords.csv", encoding="utf-8-sig")
tram_pts = coords[coords["구분"] == "트램"][["lat", "lng"]].to_numpy(float)
def dist_to_tram(c):
    mlat = (c["coord_a"][0] + c["coord_b"][0]) / 2
    mlng = (c["coord_a"][1] + c["coord_b"][1]) / 2
    p = np.pi / 180
    a = (np.sin((tram_pts[:, 0] - mlat) * p / 2) ** 2
         + np.cos(mlat * p) * np.cos(tram_pts[:, 0] * p)
         * np.sin((tram_pts[:, 1] - mlng) * p / 2) ** 2)
    return float((12742 * np.arcsin(np.sqrt(a))).min())

top10_idx = np.argsort(-gains_first)[:10]
audit = []
for ci in top10_idx:
    c = cands[int(ci)]
    d_tram = dist_to_tram(c)
    on_base = seg_baseline_load(c) > 0
    gain_pos = gains_first[ci] > 0
    suspect = (d_tram > 2.0) and not on_base
    audit.append({"segment_id": c["segment_id"], "highway": c["highway"],
                  "gain_veh_h_day": round(float(gains_first[ci]) / 3600, 2),
                  "dist_to_tram_km": round(d_tram, 2),
                  "on_baseline_path": bool(on_base),
                  "gain_positive(신경로 등장)": bool(gain_pos),
                  "suspect_flag": bool(suspect)})
n_suspect = sum(a["suspect_flag"] for a in audit)

out = {"meta": {"objective": "트램 시나리오 OD가중 총 소요시간 감소",
                "framing": "cardinality-constrained K개 개입 우선순위 — greedy 휴리스틱 "
                           "(서브모듈러 성질 단정하지 않음)",
                "upgrade": "[가정치] 현재 travel_time × 0.7 (30% 감소, 민감도 분석 대상)",
                "audit_rule": "[가정치] 트램 2km 이내 & 베이스라인 경로 등장 기준"},
       "baseline_objective_veh_h_day": round(base_obj / 3600, 1),
       "greedy_picks": picks, "objective_trajectory": obj_traj,
       "posthoc_audit_top10": audit, "n_suspect": n_suspect}
json.dump(out, open("data_processed/greedy_results.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"\nK별 개선율: " + " / ".join(f"{k} {v['improvement_pct']}%" for k, v in obj_traj.items()))
print(f"사후 점검: 상위 10개 중 의심 사례 {n_suspect}건")
print(f"완료 ({time.time()-t0:.0f}초) → data_processed/greedy_results.json")
