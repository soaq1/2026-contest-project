# -*- coding: utf-8 -*-
"""Task J: 폭설 시나리오 (2025-01-28, 대전ASOS 12.3cm) → scenario_snow_results.json

- 전역 충격: 도로등급별 차등 속도저하 [가정치 — 상식적 가정, 근거 문헌 없음]
  motorway/trunk -15% / primary/secondary -25% / tertiary 이하 -40%
  (제설 우선순위 반영. travel_time 배율 = 1/(1-저하율))
- 지표·greedy·사후점검·부하검증은 트램 시나리오와 동일 방식
- 사후점검 기준 대체: '충격 간선 인접' → '저하율 큰 등급(-40%) 간선과 노드 공유'
  ※ 후보가 거의 전부 residential(-40% 등급 자체)이라 이 기준은 판별력이 낮음을 명시
"""
import json, sys, time
from collections import defaultdict
import numpy as np
import osmnx as ox
sys.path.insert(0, "scripts")
from pipeline_common import all_times, delay_metrics, edge_loads, greedy_select, load_od, spearman

sys.stdout.reconfigure(encoding="utf-8")
t0 = time.time()

REDUCTION = {  # 속도 저하율 [가정치] — 웹앱 슬라이더 파라미터 후보
    "motorway_trunk": 0.15, "primary_secondary": 0.25, "tertiary_below": 0.40}

def group_of(hw):
    h = (hw if isinstance(hw, str) else hw[0]).replace("_link", "")
    if h in ("motorway", "trunk"):
        return "motorway_trunk"
    if h in ("primary", "secondary"):
        return "primary_secondary"
    return "tertiary_below"

G = ox.load_graphml("data_processed/daejeon_weighted.graphml")
n_by_group = defaultdict(int)
for u, v, k, d in G.edges(keys=True, data=True):
    g = group_of(d.get("highway"))
    d["travel_time"] = float(d["travel_time"]) / (1 - REDUCTION[g])
    n_by_group[g] += 1
print(f"전역 저하 적용: {dict(n_by_group)}")

pairs, origins, dests = load_od()
base = json.load(open("data_processed/baseline_times.json", encoding="utf-8"))["times_s"]
times = all_times(G, pairs)
dm = delay_metrics(pairs, base, times)
h = dm["headline"]
print(f"헤드라인: 평균지연 {h['weighted_mean_delay_min']}분 | "
      f"상위10% {h['top10pct_weighted_delay_min']}분 | P95 {h['p95_weighted_delay_min']}분")
for c, m in dm["by_category"].items():
    print(f"  {c}: 평균 {m['weighted_mean_delay_min']} / 상위10% "
          f"{m['top10pct_weighted_delay_min']} / P95 {m['p95_weighted_delay_min']}분")

# greedy (폭설 그래프 기준)
cands = json.load(open("data_processed/intervention_candidates.json", encoding="utf-8"))["candidates"]
picks, traj, gains_first, base_obj = greedy_select(G, pairs, cands, [1, 2, 3, 5])
print("K별:", {k: f"{v['improvement_pct']}% ({v['saved_abs_veh_min_day']:.0f} 차량·분/일)"
              for k, v in traj.items()})

# 사후 점검: -40% 등급 간선과 노드 공유 + 베이스라인 부하 등장
loads_base = json.load(open("data_processed/edge_loads_baseline.json", encoding="utf-8"))
heavy_nodes = set()
for u, v, k, d in G.edges(keys=True, data=True):
    if group_of(d.get("highway")) == "tertiary_below":
        heavy_nodes.update((u, v))
audit = []
for ci in np.argsort(-gains_first)[:10]:
    c = cands[int(ci)]
    a, b = c["node_a"], c["node_b"]
    near_heavy = a in heavy_nodes or b in heavy_nodes
    on_base = any(loads_base.get(f"{e.split('_')[0]}_{e.split('_')[1]}", 0) > 0
                  for e in c["directed_edges"])
    audit.append({"segment_id": c["segment_id"], "highway": c["highway"],
                  "gain_veh_h_day": round(float(gains_first[ci]) / 3600, 2),
                  "adjacent_to_high_reduction_class": bool(near_heavy),
                  "on_baseline_path": bool(on_base),
                  "suspect_flag": bool(not near_heavy and not on_base)})
n_suspect = sum(x["suspect_flag"] for x in audit)
print(f"사후 점검: 의심 사례 {n_suspect}건 (※ 인접 기준은 판별력 낮음 — 메타에 명시)")

# 부하 검증 (폭설 시나리오 경로 기준)
Gs = ox.load_graphml("data_processed/daejeon_weighted.graphml")
for u, v, k, d in Gs.edges(keys=True, data=True):
    d["travel_time"] = float(d["travel_time"]) / (1 - REDUCTION[group_of(d.get("highway"))])
loads_snow = edge_loads(Gs, pairs)
links = json.load(open("data_processed/daejeon_traffic_links_full.json", encoding="utf-8"))
name_load, obs_cong = defaultdict(list), defaultdict(list)
edge_names = {}
for u, v, k, d in Gs.edges(keys=True, data=True):
    nm = d.get("name")
    if nm is not None:
        edge_names[(u, v)] = str(nm[0] if isinstance(nm, list) else nm).replace(" ", "")
for (u, v), w in loads_snow.items():
    if (u, v) in edge_names:
        name_load[edge_names[(u, v)]].append(w)
for r in links:
    try:
        obs_cong[str(r["roadName"]).replace(" ", "")].append(float(r["congestion"]))
    except (KeyError, TypeError, ValueError):
        pass
common = sorted(set(name_load) & set(obs_cong))
rho = spearman([np.mean(name_load[k]) for k in common],
               [np.mean(obs_cong[k]) for k in common])
print(f"부하-혼잡 스피어만(폭설): {rho:.3f} (공통 {len(common)}개 도로)")

out = {
    "framing": "의사결정 지원용 what-if 분석 (검증된 예측 모델 아님)",
    "scenario": "폭설 (2025-01-28 대전ASOS 최심적설 12.3cm 사례 기반 전역 충격)",
    "parameters": {
        "snow_speed_reduction": {k: -v for k, v in REDUCTION.items()},
        "assumption": True,
        "note": "[가정치] 저하율은 제설 우선순위를 반영한 상식적 가정이며 근거 문헌 "
                "없음. 웹앱 슬라이더 파라미터 후보",
    },
    "delay": dm,
    "greedy": {"baseline_objective_veh_h_day": round(base_obj / 3600, 1),
               "picks": picks, "trajectory": traj,
               "upgrade_assumption": "[가정치] travel_time -30%"},
    "posthoc_audit_top10": audit,
    "audit_note": "[가정치] 인접 기준을 '-40% 등급 간선과 노드 공유'로 대체 — 후보가 "
                  "대부분 residential(-40% 등급)이라 이 기준의 판별력은 낮음",
    "flow_validation": {"spearman_load_vs_congestion": round(rho, 3),
                        "n_common_roads": len(common),
                        "congestion_direction": "[검증됨] 숫자 클수록 정체"},
}
json.dump(out, open("data_processed/scenario_snow_results.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"완료 ({time.time()-t0:.0f}초) → scenario_snow_results.json")
