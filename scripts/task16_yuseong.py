# -*- coding: utf-8 -*-
"""Task G: 봉명1지구(유성점) 소멸+발생 성분 분해 → data_processed/yuseong_components.json

- 시점 분리: 소멸(2026 하반기)·발생(2031)을 별도 스냅샷으로 산출, t=0 순합산 금지
- 소멸: 유성점 매출·물동량 정량 프록시 **[확인 필요]** — 웹 확인으로는
  '2025년까지 전국 최상위권 매출 점포, 매각가 약 600억원'(정성)만 확보.
  단위당(1트럭/일) 네트워크 영향 구조로 산출해 프록시 확보 시 곱하기만 하면 됨
- 발생: delivery_proxy_range.json(수정본: 998세대×2.05인) low/mid/high →
  건/일 환산. 차량 환산계수 **[확인 필요]** — '건/일' 단위 유지, 대안으로
  1대당 취급건수 X를 매개변수로 한 대/일 함수 형태 제공
- 주입 경로: 최근접 창고 3곳 → 봉명1지구 균등 [가정치]
- 민감도: low~high 폭의 지배 입력 분해 (성장률 vs 세대당 인구 vs 세대수)
"""
import json, math, sys
import numpy as np
import pandas as pd
import networkx as nx
import osmnx as ox

sys.stdout.reconfigure(encoding="utf-8")
G = ox.load_graphml("data_processed/daejeon_weighted.graphml")
nodes = list(G.nodes)
nx_ = np.array([G.nodes[n]["x"] for n in nodes])
ny_ = np.array([G.nodes[n]["y"] for n in nodes])
def nearest(lat, lng):
    return nodes[int(np.argmin((nx_ - lng) ** 2 + (ny_ - lat) ** 2))]

coords = pd.read_csv("data_processed/shock_and_hub_coords.csv", encoding="utf-8-sig")
ys = coords[coords["이름"] == "홈플러스 유성점"].iloc[0]
site = (float(ys["lat"]), float(ys["lng"]))
site_node = nearest(*site)

wh = coords[coords["구분"] == "물류창고"].copy()
p = np.pi / 180
d_km = 12742 * np.arcsin(np.sqrt(
    np.sin((wh["lat"].astype(float) - site[0]) * p / 2) ** 2
    + np.cos(site[0] * p) * np.cos(wh["lat"].astype(float) * p)
    * np.sin((wh["lng"].astype(float) - site[1]) * p / 2) ** 2))
wh = wh.assign(dist_km=d_km.values).sort_values("dist_km")
near3 = wh.head(3)

def route_min(o_node, d_node):
    try:
        return nx.dijkstra_path_length(G, o_node, d_node, weight="travel_time") / 60
    except nx.NetworkXNoPath:
        return None

routes = []
for _, w in near3.iterrows():
    t = route_min(nearest(float(w["lat"]), float(w["lng"])), site_node)
    routes.append({"warehouse": w["이름"], "dist_km": round(float(w["dist_km"]), 2),
                   "travel_time_min": round(t, 2) if t else None})

proxy = json.load(open("data_processed/delivery_proxy_range.json", encoding="utf-8"))
gen_year = proxy["yuseong_998units_annual_demand"]
gen_day = {k: round(v / 365, 1) for k, v in gen_year.items()}

# 민감도: low~high 폭 분해 (로그 스케일 기여율)
r_growth = proxy["high_per_capita_2031"] / proxy["low_per_capita_2031"]  # 2.198
r_hsize = 2.12 / 1.92   # 구별 세대당 인구 범위(대전 5개구 1.92~2.12) [가정치]
r_units = 1.0           # 998세대는 사업계획 확정치로 변동 없음
logs = {"프록시 성장률(low~high)": math.log(r_growth),
        "세대당 인구(구별 1.92~2.12)": math.log(r_hsize),
        "세대수(998 확정)": math.log(r_units) if r_units > 1 else 0.0}
tot_log = sum(logs.values())
sens = {k: round(v / tot_log * 100, 1) for k, v in logs.items()}

out = {
    "site": {"name": "봉명1지구(홈플러스 유성점 재개발)", "lat": site[0], "lng": site[1]},
    "snapshot_2026H2_소멸": {
        "status": "[확인 필요] 유성점 매출·화물 물동량 정량 프록시 미확보 — "
                  "확보된 정성 정보: 2025년까지 전국 최상위권 매출 점포, "
                  "매각가 약 600억원(이데일리 2026), 현재 사실상 공실화",
        "unit_impact": "1트럭/일 제거 시 영향 경로(최근접 창고 3곳 기준): "
                       "아래 routes의 travel_time 가중 — 프록시 확보 시 트럭수를 곱해 산출",
        "routes": routes,
    },
    "snapshot_2031_발생": {
        "annual_demand_건": gen_year,
        "daily_demand_건": gen_day,
        "vehicle_conversion": "[확인 필요] 차량 환산계수 미확보 — 1대당 일평균 취급건수 "
                              "X 가정 시 유입 차량 = daily_demand/X 대/일",
        "injection": "[가정치] 최근접 창고 3곳 → 사이트 균등 주입",
        "routes": routes,
    },
    "sensitivity": {
        "method": "low~high 폭(로그 스케일)에 대한 입력별 기여율",
        "contributions_pct": sens,
        "dominant_input": max(sens, key=sens.get),
    },
    "timing_note": "소멸(2026H2)과 발생(2031)은 시점이 달라 순합산하지 않음 — "
                   "각 스냅샷을 해당 시점 네트워크 상태에 별도 적용",
}
json.dump(out, open("data_processed/yuseong_components.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("최근접 창고 3곳:", [f"{r['warehouse']} ({r['travel_time_min']}분)" for r in routes])
print(f"발생 수요(건/일): {gen_day}")
print(f"민감도 지배 입력: {out['sensitivity']['dominant_input']} ({max(sens.values())}%)")
print("저장: data_processed/yuseong_components.json")
