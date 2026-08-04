# -*- coding: utf-8 -*-
"""Task D: 트램 시나리오 → data_processed/tram_scenario.json

- 공구 선별(2026 하반기): 웹 확인 결과 2024-12 착공, 2026-03에 4·5·9·14공구까지
  착공하여 **14개 전 공구 공사 중** (출처: 대전시 보도, 2026-06 개통 지연 보도)
  → 트램 지점 15곳 전부 적용
- 공사 반영: 트램 지점 반경 500m 내 간선 travel_time ×2.0
  [가정치] 반경 500m·×2.0 모두 임의값 — 공구는 선형인데 지점 좌표만 보유,
  '통행 시간 대폭 증가'의 정도 미상. 민감도 분석 대상
- 지표: OD가중 평균 지연(헤드라인) + 상위 10% OD쌍 가중지연·P95(꼬리)
  + 3단 분해(같은존/존간/외부) 표
"""
import json, sys, time
from collections import defaultdict
import numpy as np
import networkx as nx
import osmnx as ox

sys.stdout.reconfigure(encoding="utf-8")
RADIUS_KM, FACTOR = 0.5, 2.0
t0 = time.time()

G = ox.load_graphml("data_processed/daejeon_weighted.graphml")
import pandas as pd
coords = pd.read_csv("data_processed/shock_and_hub_coords.csv", encoding="utf-8-sig")
tram = coords[coords["구분"] == "트램"][["lat", "lng"]].to_numpy(float)

def hav(lat1, lon1, lat2, lon2):
    p = np.pi / 180
    a = (np.sin((lat2 - lat1) * p / 2) ** 2
         + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * np.arcsin(np.sqrt(a))

node_ids = list(G.nodes)
lat = np.array([G.nodes[n]["y"] for n in node_ids])
lng = np.array([G.nodes[n]["x"] for n in node_ids])
near = np.zeros(len(node_ids), bool)
for tlat, tlng in tram:
    near |= hav(lat, lng, tlat, tlng) <= RADIUS_KM
near_set = {n for n, f in zip(node_ids, near) if f}

affected = []
for u, v, k, d in G.edges(keys=True, data=True):
    if u in near_set or v in near_set:
        d["travel_time"] = float(d["travel_time"]) * FACTOR
        affected.append(f"{u}_{v}_{k}")
print(f"공사 영향 간선: {len(affected):,}개 (전체의 {len(affected)/G.number_of_edges()*100:.1f}%)")

od = json.load(open("data_processed/od_decomposed.json", encoding="utf-8"))
pairs = od["pairs"]
base = json.load(open("data_processed/baseline_times.json", encoding="utf-8"))["times_s"]
origins = sorted({p["o"] for p in pairs})
dests_by_o = defaultdict(set)
for p in pairs:
    dests_by_o[p["o"]].add(p["d"])

times = {}
for o in origins:
    dist = nx.single_source_dijkstra_path_length(G, o, weight="travel_time")
    for d in dests_by_o[o]:
        times[f"{o}_{d}"] = round(dist[d], 2) if d in dist else None

def metrics(rows):
    """rows: (weight, delay_s) — OD가중 평균 / 상위10% 가중지연 / P95(가중)"""
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

all_rows, by_cat = [], defaultdict(list)
n_skip = 0
for p in pairs:
    k = f"{p['o']}_{p['d']}"
    if base.get(k) is None or times.get(k) is None:
        n_skip += 1
        continue
    row = (p["veh_day"], times[k] - base[k])
    all_rows.append(row)
    by_cat[p["cat"]].append(row)

result = {
    "meta": {
        "construction_status": "14개 전 공구 공사 중(2026-03 전 구간 착공 완료, "
            "개통 2030 하반기 전망) — 웹 확인 사실, 트램 지점 15곳 전부 적용",
        "impact_model": f"[가정치] 트램 지점 반경 {RADIUS_KM}km 내 간선 travel_time ×{FACTOR} "
            "— 반경·배율 모두 임의값, 민감도 분석 대상",
        "n_affected_edges": len(affected),
        "n_skipped_od": n_skip,
    },
    "headline": metrics(all_rows),
    "by_category": {c: metrics(by_cat[c]) for c in ("same_zone", "inter_zone", "external")},
}
json.dump({**result, "times_s": times, "affected_edges": affected},
          open("data_processed/tram_scenario.json", "w", encoding="utf-8"), ensure_ascii=False)

h = result["headline"]
print(f"헤드라인: OD가중 평균지연 {h['weighted_mean_delay_min']}분 | "
      f"상위10% {h['top10pct_weighted_delay_min']}분 | P95 {h['p95_weighted_delay_min']}분")
print("3단 분해:")
for c, m in result["by_category"].items():
    print(f"  {c}: 평균 {m['weighted_mean_delay_min']}분 / 상위10% "
          f"{m['top10pct_weighted_delay_min']}분 / P95 {m['p95_weighted_delay_min']}분 "
          f"(n={m['n_pairs']:,})")
print(f"완료 ({time.time()-t0:.0f}초) → data_processed/tram_scenario.json")
