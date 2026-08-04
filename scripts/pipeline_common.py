# -*- coding: utf-8 -*-
"""시나리오 파이프라인 공통 로직 (task13/14에서 확립한 방식을 모듈화)

- 지표: OD가중 평균(헤드라인) + 상위10% 가중지연 + P95(가중) — 3단 분해 지원
- greedy: 정확 한계효과식 min(현재, S[o,u]+tt'+T[v,d]) — 반복마다 S/T 재계산
- 성능: (a) 캐싱 단계로 충분함이 트램 시나리오에서 확인됨
"""
import json
from collections import defaultdict
import numpy as np
import networkx as nx


def load_od(path="data_processed/od_decomposed.json"):
    od = json.load(open(path, encoding="utf-8"))
    pairs = od["pairs"]
    origins = sorted({p["o"] for p in pairs})
    dests = sorted({p["d"] for p in pairs})
    return pairs, origins, dests


def dests_by_origin(pairs):
    d = defaultdict(set)
    for p in pairs:
        d[p["o"]].add(p["d"])
    return d


def all_times(G, pairs):
    """모든 OD쌍 최단 소요시간(초). 도달불가는 None"""
    times = {}
    dbo = dests_by_origin(pairs)
    for o in sorted(dbo):
        dist = nx.single_source_dijkstra_path_length(G, o, weight="travel_time")
        for d in dbo[o]:
            times[f"{o}_{d}"] = round(dist[d], 2) if d in dist else None
    return times


def edge_loads(G, pairs):
    """최단경로 적재 간선부하(대/일). predecessor 첫 항 채택 [가정치]"""
    w_od = defaultdict(float)
    for p in pairs:
        w_od[(p["o"], p["d"])] += p["veh_day"]
    dbo = dests_by_origin(pairs)
    load = defaultdict(float)
    for o in sorted(dbo):
        pred, dist = nx.dijkstra_predecessor_and_distance(G, o, weight="travel_time")
        for d in dbo[o]:
            if d not in dist:
                continue
            node = d
            while node != o:
                prev = pred[node][0]
                load[(prev, node)] += w_od[(o, d)]
                node = prev
    return load


def metrics(rows):
    """rows: (weight, delay_s) 리스트"""
    if not rows:
        return None
    w = np.array([r[0] for r in rows]); dl = np.array([r[1] for r in rows])
    mean = float((w * dl).sum() / w.sum())
    order = np.argsort(-dl)
    top = order[: max(1, int(np.ceil(len(rows) * 0.10)))]
    tail = float((w[top] * dl[top]).sum() / w[top].sum())
    srt = np.argsort(dl); cw = np.cumsum(w[srt]) / w.sum()
    p95 = float(dl[srt][np.searchsorted(cw, 0.95)])
    return {"weighted_mean_delay_min": round(mean / 60, 3),
            "top10pct_weighted_delay_min": round(tail / 60, 3),
            "p95_weighted_delay_min": round(p95 / 60, 3), "n_pairs": len(rows)}


def delay_metrics(pairs, base_times, scen_times):
    all_rows, by_cat, n_skip = [], defaultdict(list), 0
    for p in pairs:
        k = f"{p['o']}_{p['d']}"
        if base_times.get(k) is None or scen_times.get(k) is None:
            n_skip += 1
            continue
        row = (p["veh_day"], scen_times[k] - base_times[k])
        all_rows.append(row)
        by_cat[p["cat"]].append(row)
    return {"headline": metrics(all_rows),
            "by_category": {c: metrics(by_cat[c])
                            for c in ("same_zone", "inter_zone", "external") if by_cat[c]},
            "n_skipped": n_skip}


def greedy_select(G, pairs, cands, k_list, upgrade_factor=0.7):
    """G를 제자리 수정하며 greedy 선택. 반환: picks, trajectory, gains_first"""
    origins = sorted({p["o"] for p in pairs})
    dests = sorted({p["d"] for p in pairs})
    oi = {n: i for i, n in enumerate(origins)}
    di = {n: i for i, n in enumerate(dests)}
    nodes = list(G.nodes)
    ni = {n: i for i, n in enumerate(nodes)}
    N, nO, nD = len(nodes), len(origins), len(dests)
    W = np.zeros((nO, nD))
    for p in pairs:
        W[oi[p["o"]], di[p["d"]]] += p["veh_day"]
    Grev = G.reverse(copy=False)
    didx = [ni[d] for d in dests]

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
        return S, T, S[:, didx]

    edge_lookup = {f"{u}_{v}_{k}": dd for u, v, k, dd in G.edges(keys=True, data=True)}
    cand_edges = [[(e, edge_lookup[e]) for e in c["directed_edges"] if e in edge_lookup]
                  for c in cands]

    S, T, D = compute_ST()
    reach = np.isfinite(D)
    Wm = np.where(reach, W, 0.0)
    Dm = np.where(reach, D, 0.0)
    base_obj = float((Wm * Dm).sum())

    def eval_gain(des, S, T, Dm):
        new = Dm.copy()
        for eid, dd in des:
            u, v = int(eid.split("_")[0]), int(eid.split("_")[1])
            via = S[:, ni[u]][:, None] + dd["travel_time"] * upgrade_factor + T[ni[v], :][None, :]
            np.minimum(new, np.where(np.isfinite(via), via, np.inf), out=new)
        return float((Wm * np.maximum(0.0, Dm - np.where(np.isfinite(new), new, Dm))).sum())

    picks, gains_first, traj, picked = [], None, {}, set()
    for it in range(1, max(k_list) + 1):
        g = np.zeros(len(cand_edges))
        for ci, des in enumerate(cand_edges):
            if ci in picked or not des:
                continue
            g[ci] = eval_gain(des, S, T, Dm)
        if gains_first is None:
            gains_first = g.copy()
        best = int(np.argmax(g))
        picked.add(best)
        picks.append({"segment_id": cands[best]["segment_id"],
                      "highway": cands[best]["highway"],
                      "length_m": cands[best]["length_m"],
                      "marginal_gain_veh_h_day": round(g[best] / 3600, 2),
                      "coord_a": cands[best]["coord_a"], "coord_b": cands[best]["coord_b"]})
        for eid, dd in cand_edges[best]:
            dd["travel_time"] *= upgrade_factor
        S, T, D = compute_ST()
        reach = np.isfinite(D)
        Wm = np.where(reach, W, 0.0)
        Dm = np.where(reach, D, 0.0)
        obj = float((Wm * Dm).sum())
        if it in k_list:
            traj[f"K={it}"] = {"objective_veh_h_day": round(obj / 3600, 1),
                               "improvement_pct": round((base_obj - obj) / base_obj * 100, 3),
                               "saved_abs_veh_min_day": round((base_obj - obj) / 60, 0)}
    return picks, traj, gains_first, base_obj


def spearman(a, b):
    def rank(x):
        x = np.asarray(x)
        vals, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
        cum = np.cumsum(cnt) - cnt
        return (cum + (cnt - 1) / 2.0)[inv]
    ra, rb = rank(a), rank(b)
    ra -= ra.mean(); rb -= rb.mean()
    den = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / den) if den else float("nan")
