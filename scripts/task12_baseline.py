# -*- coding: utf-8 -*-
"""Task C: 베이스라인 다익스트라 → data_processed/baseline_times.json + edge_loads.json

- OD쌍 2,952개의 평시 최단 소요시간(travel_time 가중)
- 성능 대응: (a) 출발지별 single-source 다익스트라 + predecessor 캐싱으로 충분
  (69개 출발 노드 × 16,122 노드 그래프) — (b)(c) 단계 불필요
- 부수 산출: 간선 부하(edge load, 대/일) — Task F 검증용.
  경로 복원은 predecessor 체인(동률 시 첫 predecessor 채택 [가정치])
"""
import json, sys, time
from collections import defaultdict
import networkx as nx
import osmnx as ox

sys.stdout.reconfigure(encoding="utf-8")
t0 = time.time()
G = ox.load_graphml("data_processed/daejeon_weighted.graphml")

od = json.load(open("data_processed/od_decomposed.json", encoding="utf-8"))
pairs = od["pairs"]
origins = sorted({p["o"] for p in pairs})
dests_by_o = defaultdict(set)
for p in pairs:
    dests_by_o[p["o"]].add(p["d"])
print(f"OD쌍 {len(pairs):,} | 고유 출발노드 {len(origins)}")

times = {}
edge_load = defaultdict(float)
weight_by_od = defaultdict(float)
for p in pairs:
    weight_by_od[(p["o"], p["d"])] += p["veh_day"]

n_unreach = 0
for o in origins:
    pred, dist = nx.dijkstra_predecessor_and_distance(G, o, weight="travel_time")
    for d in dests_by_o[o]:
        if d not in dist:
            n_unreach += 1
            times[f"{o}_{d}"] = None
            continue
        times[f"{o}_{d}"] = round(dist[d], 2)
        w = weight_by_od[(o, d)]
        node = d
        while node != o:
            prev = pred[node][0]
            edge_load[(prev, node)] += w
            node = prev

print(f"다익스트라 {len(origins)}회 + 경로복원 완료 ({time.time()-t0:.0f}초) | "
      f"도달불가 OD쌍 {n_unreach}개")

wsum = tsum = 0.0
for p in pairs:
    t = times[f"{p['o']}_{p['d']}"]
    if t is not None:
        wsum += p["veh_day"]
        tsum += p["veh_day"] * t
print(f"OD가중 평균 소요시간(평시): {tsum/wsum/60:.2f}분")

json.dump({"meta": {"weight": "travel_time(초)", "performance_stage": "(a) 캐싱으로 충분",
                    "n_unreachable": n_unreach},
           "times_s": times},
          open("data_processed/baseline_times.json", "w", encoding="utf-8"),
          ensure_ascii=False)
json.dump({f"{u}_{v}": round(w, 3) for (u, v), w in edge_load.items()},
          open("data_processed/edge_loads_baseline.json", "w", encoding="utf-8"))
print(f"저장: baseline_times.json ({len(times):,}쌍), "
      f"edge_loads_baseline.json ({len(edge_load):,}간선)")
