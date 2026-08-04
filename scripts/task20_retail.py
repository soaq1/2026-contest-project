# -*- coding: utf-8 -*-
"""Task K: 대형유통 폐점 시나리오 → scenario_retail_closure_results.json

- 충격 지점 2개: ① 홈플러스 서대전점 ② [복합] 홈플러스 문화점+세이백화점 본점
  (약 100m 인접·지하통로 연결 → 하나의 복합 지점으로 합산, 중복 계산 금지)
- 수요 프록시: 프록시1(면적당 물동량) 자료 없음 [확인 필요] → 프록시2 사용:
  해당 행정동 destination_weight의 f ∈ {0.30, 0.40, 0.50} 를 지점이 흡수했다고
  가정하고 스윕 [가정치 — 웹앱 슬라이더 파라미터 후보]
- 시점 스냅샷: T0(폐점 전) / T1(2024-05: 서대전점+세이 지분 소멸) /
  T2(2026-01: 복합 지점 전체 소멸). 세이 지분 = 복합 수요의 50% [가정치]
- 핵심 지표: 지연이 아니라 **물류 지형 변화** — 본 모델은 혼잡 피드백이 없어
  수요 소멸은 travel_time을 바꾸지 않음(지연 지표 0). 대신 폐점 전후
  간선 화물부하 감소 상위 10개 구간을 산출
"""
import json, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd
import osmnx as ox
sys.path.insert(0, "scripts")
from pipeline_common import edge_loads, greedy_select, load_od, spearman

sys.stdout.reconfigure(encoding="utf-8")
t0 = time.time()
F_SWEEP = [0.30, 0.40, 0.50]
F_REP = 0.40  # 부하 비교 대표값
SEI_SHARE = 0.50  # [가정치] 복합 수요 중 세이 지분

G = ox.load_graphml("data_processed/daejeon_weighted.graphml")
nodes = list(G.nodes)
nx_ = np.array([G.nodes[n]["x"] for n in nodes])
ny_ = np.array([G.nodes[n]["y"] for n in nodes])
def nearest_node(lat, lng):
    return nodes[int(np.argmin((nx_ - lng) ** 2 + (ny_ - lat) ** 2))]

coords = pd.read_csv("data_processed/shock_and_hub_coords.csv", encoding="utf-8-sig")
def site(name):
    r = coords[coords["이름"] == name].iloc[0]
    return float(r["lat"]), float(r["lng"])
sdj = site("홈플러스 서대전점")
mh = site("홈플러스 문화점")
sei = site("세이백화점 본점")
comp = ((mh[0] + sei[0]) / 2, (mh[1] + sei[1]) / 2)
sites = {"서대전점": sdj, "문화+세이 복합": comp}

dong = pd.read_csv("data_processed/dong_population_anchors.csv", encoding="utf-8-sig")
meta = json.load(open("data_processed/od_decomposed.json", encoding="utf-8"))["meta"]
dong_nodes = meta["dong_nodes"]

def nearest_dong(lat, lng):
    p = np.pi / 180
    d2 = (dong["lat"] - lat) ** 2 + ((dong["lng"] - lng) * np.cos(lat * p)) ** 2
    return dong.iloc[int(np.argmin(d2))]["행정동"]

site_dong = {s: nearest_dong(*ll) for s, ll in sites.items()}
site_node = {s: nearest_node(*ll) for s, ll in sites.items()}
print(f"지점→행정동 매핑 [가정치: 최근접 앵커]: {site_dong}")

pairs, origins, dests = load_od()
target_nodes = {s: int(dong_nodes[d]) for s, d in site_dong.items()}

# 구조(2026-07-19 확정): 클러스터1 = 문화점+세이본점(인접·지하통로, 복합 1지점),
# 서대전점 = 유성구 대정동(모다아울렛 옆) 독립 지점 — 100% 독립 수요.
# 서대전점 좌표는 언론보도+홈플러스 공식 앱으로 원좌표가 정확함이 확인됨
# (07-18의 계백로 방면 '수정'은 오판이어서 철회).
# 같은 행정동에 지점이 겹치는 경우에만 f-지분을 매장 수 비례로 분할 —
# 현 구조에선 두 지점이 서로 다른 동이라 각자 해당 동 f-지분 100%를 가짐
STORE_COUNT = {"서대전점": 1, "문화+세이 복합": 2}
sites_by_node = defaultdict(list)
for s, tn in target_nodes.items():
    sites_by_node[tn].append(s)
alloc = {}
for tn, ss in sites_by_node.items():
    tot = sum(STORE_COUNT[s] for s in ss)
    for s in ss:
        alloc[s] = STORE_COUNT[s] / tot

def build_pairs(f, closed):
    """closed: 소멸된 지점별 소멸 비중 {site: 0~1}. 반환: (pairs, 지점별 수요 대/일)"""
    out, demand = [], defaultdict(float)
    for p in pairs:
        ss = sites_by_node.get(p["d"])
        if not ss:
            out.append(p)
            continue
        out.append({**p, "veh_day": p["veh_day"] * (1 - f)})
        for s in ss:
            store_w = p["veh_day"] * f * alloc[s] * (1 - closed.get(s, 0.0))
            if store_w > 1e-12:
                out.append({"o": p["o"], "d": site_node[s], "cat": p["cat"],
                            "veh_day": store_w})
                demand[s] += store_w
    return out, demand

snapshots = {"T0_폐점전": {}, "T1_2024-05": {"서대전점": 1.0, "문화+세이 복합": SEI_SHARE},
             "T2_2026-01": {"서대전점": 1.0, "문화+세이 복합": 1.0}}
removed = {}
for snap, closed in snapshots.items():
    row = {}
    for f in F_SWEEP:
        _, dem = build_pairs(f, {})
        _, dem_now = build_pairs(f, closed)
        row[f"f={f}"] = {s: round(dem[s] - dem_now.get(s, 0.0), 1) for s in sites}
    removed[snap] = row
print("소멸 수요(대/일, f별):", json.dumps(removed["T2_2026-01"], ensure_ascii=False))

# 부하 비교 (f=0.40 대표): T0 vs T2
p_pre, _ = build_pairs(F_REP, snapshots["T0_폐점전"])
p_post, _ = build_pairs(F_REP, snapshots["T2_2026-01"])
load_pre = edge_loads(G, p_pre)
load_post = edge_loads(G, p_post)
deltas = []
for e, w0 in load_pre.items():
    w1 = load_post.get(e, 0.0)
    if w0 - w1 > 1e-9:
        d_edge = None
        for k in G[e[0]][e[1]]:
            d_edge = G[e[0]][e[1]][k]
            break
        deltas.append({"edge": f"{e[0]}_{e[1]}",
                       "road": str(d_edge.get("name", "(무명)")),
                       "highway": str(d_edge.get("highway")),
                       "load_before": round(w0, 1), "load_after": round(w1, 1),
                       "reduction_abs": round(w0 - w1, 1),
                       "reduction_pct": round((w0 - w1) / w0 * 100, 1)})
deltas.sort(key=lambda x: (-x["reduction_pct"], -x["reduction_abs"]))
top10 = deltas[:10]
print(f"부하 감소 간선 {len(deltas):,}개 | 상위: "
      f"{[(t['road'], t['reduction_pct']) for t in top10[:3]]}")

# greedy: 폐점 후(T2) 남은 수요 기준 개입 우선순위 (평시 그래프)
cands = json.load(open("data_processed/intervention_candidates.json", encoding="utf-8"))["candidates"]
picks, traj, gains_first, base_obj = greedy_select(G, p_post, cands, [1, 2, 3, 5])
print("K별:", {k: f"{v['improvement_pct']}%" for k, v in traj.items()})

# 사후 점검: 폐점 지점 2km 이내 or 베이스라인 부하 등장
loads_base = json.load(open("data_processed/edge_loads_baseline.json", encoding="utf-8"))
def dist_site_km(c):
    mlat = (c["coord_a"][0] + c["coord_b"][0]) / 2
    mlng = (c["coord_a"][1] + c["coord_b"][1]) / 2
    p = np.pi / 180
    best = 1e9
    for lat, lng in sites.values():
        a = (np.sin((lat - mlat) * p / 2) ** 2
             + np.cos(mlat * p) * np.cos(lat * p) * np.sin((lng - mlng) * p / 2) ** 2)
        best = min(best, 12742 * np.arcsin(np.sqrt(a)))
    return best
audit = []
for ci in np.argsort(-gains_first)[:10]:
    c = cands[int(ci)]
    near = dist_site_km(c) <= 2.0
    on_base = any(loads_base.get("_".join(e.split("_")[:2]), 0) > 0
                  for e in c["directed_edges"])
    audit.append({"segment_id": c["segment_id"],
                  "gain_veh_h_day": round(float(gains_first[ci]) / 3600, 2),
                  "within_2km_of_site": bool(near), "on_baseline_path": bool(on_base),
                  "suspect_flag": bool(not near and not on_base)})

# 부하 검증 (T2 부하 vs 혼잡)
links = json.load(open("data_processed/daejeon_traffic_links_full.json", encoding="utf-8"))
edge_names = {}
for u, v, k, d in G.edges(keys=True, data=True):
    nm = d.get("name")
    if nm is not None:
        edge_names[(u, v)] = str(nm[0] if isinstance(nm, list) else nm).replace(" ", "")
name_load, obs_cong = defaultdict(list), defaultdict(list)
for e, w in load_post.items():
    if e in edge_names:
        name_load[edge_names[e]].append(w)
for r in links:
    try:
        obs_cong[str(r["roadName"]).replace(" ", "")].append(float(r["congestion"]))
    except (KeyError, TypeError, ValueError):
        pass
common = sorted(set(name_load) & set(obs_cong))
rho = spearman([np.mean(name_load[k]) for k in common],
               [np.mean(obs_cong[k]) for k in common])

out = {
    "framing": "의사결정 지원용 what-if 분석 (검증된 예측 모델 아님)",
    "scenario": "대형유통 폐점 (서대전점 2024-05 / 세이본점 2024-05-19 / 문화점 2026-01)",
    "metric_note": "본 모델은 혼잡 피드백이 없어 수요 소멸은 travel_time을 바꾸지 "
                   "않음 — 회복탄력성(지연) 지표가 아니라 **물류 지형 변화** 지표임",
    "parameters": {
        "retail_demand_share_f": {"values_swept": F_SWEEP, "representative": F_REP,
                                  "assumption": True,
                                  "note": "[가정치] 프록시2: 해당 행정동 물동량 중 지점 흡수 "
                                          "비중. 프록시1(면적당 물동량)은 자료 없음 [확인 필요]"},
        "sei_share_of_complex": {"value": SEI_SHARE, "assumption": True,
                                 "note": "[가정치] 문화+세이 복합 수요 중 세이 지분"},
    },
    "sites": {s: {"lat": ll[0], "lng": ll[1], "dong": site_dong[s]}
              for s, ll in sites.items()},
    "composite_note": "클러스터1 = 문화점+세이본점(인접·지하통로 연결, 복합 1지점). "
                      "서대전점은 유성구 대정동(모다아울렛 옆) 독립 지점으로 해당 동 "
                      "f-지분 100% — 언론보도+공식 앱 대조로 좌표 확정(2026-07-19)",
    "removed_demand_veh_day": removed,
    "top10_load_reduction_edges_f0.4_T2": top10,
    "greedy_on_remaining_demand": {
        "baseline_objective_veh_h_day": round(base_obj / 3600, 1),
        "picks": picks, "trajectory": traj},
    "posthoc_audit_top10": audit,
    "flow_validation": {"spearman_load_vs_congestion_T2": round(rho, 3),
                        "n_common_roads": len(common)},
}
json.dump(out, open("data_processed/scenario_retail_closure_results.json", "w",
                    encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"완료 ({time.time()-t0:.0f}초) → scenario_retail_closure_results.json")
