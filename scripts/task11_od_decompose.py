# -*- coding: utf-8 -*-
"""Task B: 다지점 OD 분해 → data_processed/od_decomposed.json

- 톤급별 화물자동차 OD(2023, 대/일)에서 대전 5존(66~70) 관련 행만 사용
- 분해 규칙:
  · 출발 앵커: 물류창고 43곳 — 존(구) 내 창고에 균등 배분 [가정치: 창고별
    처리량 자료가 없어 균등 가정]
  · 도착 앵커: 행정동 82곳 — 존(구) 내 destination_weight(인구비) 재정규화 배분
  · 외부 성분: 대전 쪽 끝만 모델링 — 유출은 창고→최근접 고속도로 게이트웨이,
    유입은 게이트웨이→창고 [가정치: 시외 구간은 그래프 범위 밖]
- 검증: 분해 후 재집계가 원본 3분류(같은존/존간/외부) 총량을 보존하는지,
  원본 비율(45.78/17.62/36.60%)과 일치하는지 확인
"""
import json, re, sys, zipfile
from collections import defaultdict
import numpy as np
import pandas as pd
import osmnx as ox

sys.stdout.reconfigure(encoding="utf-8")
ZONE_GU = {66: "동구", 67: "중구", 68: "서구", 69: "유성구", 70: "대덕구"}
DJ = set(ZONE_GU)

# ── OD 로드
with zipfile.ZipFile("data_raw/ton_class_freight_od.zip") as zf:
    name = [n for n in zf.namelist() if "기준년도" in n and n.endswith(".xlsx")][0]
    with zf.open(name) as f:
        od = pd.read_excel(f, sheet_name="2023년", skiprows=1,
                           names=["O", "대존O", "D", "대존D", "소형", "중형", "대형", "전체"])
od = od.dropna(subset=["O", "D"])
od[["O", "D"]] = od[["O", "D"]].astype(int)
dj = od[od["O"].isin(DJ) | od["D"].isin(DJ)].copy()

def cat(r):
    o_in, d_in = r["O"] in DJ, r["D"] in DJ
    if o_in and d_in:
        return "same_zone" if r["O"] == r["D"] else "inter_zone"
    return "external"

dj["cat"] = dj.apply(cat, axis=1)
tot = dj.groupby("cat")["전체"].sum()
share = tot / tot.sum() * 100
print(f"대전 관련 OD {len(dj):,}행 | 총 {tot.sum():,.0f}대/일")
print(f"비율: 같은존 {share['same_zone']:.2f}% / 존간 {share['inter_zone']:.2f}% / "
      f"외부 {share['external']:.2f}% (기대: 45.78/17.62/36.60)")
for k, exp in (("same_zone", 45.78), ("inter_zone", 17.62), ("external", 36.60)):
    assert abs(share[k] - exp) < 0.05, f"{k} 비율 불일치: {share[k]:.2f} vs {exp}"

# ── 앵커 로드 및 그래프 노드 매핑
G = ox.load_graphml("data_processed/daejeon_weighted.graphml")
nodes = list(G.nodes)
nx_ = np.array([G.nodes[n]["x"] for n in nodes])
ny_ = np.array([G.nodes[n]["y"] for n in nodes])

def nearest_node(lat, lng):
    return nodes[int(np.argmin((nx_ - lng) ** 2 + (ny_ - lat) ** 2))]

coords = pd.read_csv("data_processed/shock_and_hub_coords.csv", encoding="utf-8-sig")
wh = coords[coords["구분"] == "물류창고"].copy()
wh["구"] = wh["주소"].str.extract(r"대전광역시\s+(\S+구)")
assert wh["구"].notna().all() and len(wh) == 43
wh["node"] = [nearest_node(r["lat"], r["lng"]) for _, r in wh.iterrows()]

dong = pd.read_csv("data_processed/dong_population_anchors.csv", encoding="utf-8-sig")
dong["node"] = [nearest_node(r["lat"], r["lng"]) for _, r in dong.iterrows()]

# ── 고속도로 게이트웨이: motorway 간선의 노드를 0.02도 격자로 군집
gw_nodes = set()
for u, v, d in G.edges(data=True):
    hw = d.get("highway")
    hws = hw if isinstance(hw, list) else [hw]
    if any(h in ("motorway", "motorway_link") for h in hws):
        gw_nodes.update((u, v))
clusters = defaultdict(list)
for n in gw_nodes:
    clusters[(round(G.nodes[n]["x"] / 0.02), round(G.nodes[n]["y"] / 0.02))].append(n)
gateways = []
for members in clusters.values():
    xs = np.mean([G.nodes[n]["x"] for n in members])
    ys = np.mean([G.nodes[n]["y"] for n in members])
    gateways.append(min(members, key=lambda n: (G.nodes[n]["x"] - xs) ** 2 + (G.nodes[n]["y"] - ys) ** 2))
print(f"게이트웨이(고속도로 진입점 군집): {len(gateways)}개")

gx = np.array([G.nodes[n]["x"] for n in gateways])
gy = np.array([G.nodes[n]["y"] for n in gateways])
wh["gw"] = [gateways[int(np.argmin((gx - r["lng"]) ** 2 + (gy - r["lat"]) ** 2))]
            for _, r in wh.iterrows()]

# ── 분해
wh_by_gu = {g: sub for g, sub in wh.groupby("구")}
dong_by_gu = {g: sub.assign(w=sub["destination_weight"] / sub["destination_weight"].sum())
              for g, sub in dong.groupby("구")}

pairs = defaultdict(float)   # (o_node, d_node, cat) -> 대/일
for _, r in dj.iterrows():
    V, c = float(r["전체"]), r["cat"]
    if c in ("same_zone", "inter_zone"):
        W, Dg = wh_by_gu[ZONE_GU[r["O"]]], dong_by_gu[ZONE_GU[r["D"]]]
        for _, w_ in W.iterrows():
            for _, d_ in Dg.iterrows():
                pairs[(w_["node"], d_["node"], c)] += V / len(W) * d_["w"]
    else:
        gu = ZONE_GU[r["O"] if r["O"] in DJ else r["D"]]
        W = wh_by_gu[gu]
        outbound = r["O"] in DJ
        for _, w_ in W.iterrows():
            key = ((w_["node"], w_["gw"], c) if outbound else (w_["gw"], w_["node"], c))
            pairs[key] += V / len(W)

rows = [{"o": o, "d": d, "cat": c, "veh_day": v} for (o, d, c), v in pairs.items()]
re_tot = defaultdict(float)
for r in rows:
    re_tot[r["cat"]] += r["veh_day"]
print(f"분해: OD쌍 {len(rows):,}개")
for k in ("same_zone", "inter_zone", "external"):
    diff = abs(re_tot[k] - tot[k])
    print(f"  {k}: 원본 {tot[k]:,.1f} → 재집계 {re_tot[k]:,.1f} (오차 {diff:.6f})")
    assert diff < 0.01

out = {
    "meta": {
        "source": "톤급별 화물자동차 OD 2023 (대/일, 전체 톤급 합)",
        "zones": {str(k): v for k, v in ZONE_GU.items()},
        "assumptions": [
            "[가정치] 존 내 창고 균등 배분(창고별 처리량 자료 없음)",
            "[가정치] 도착지는 행정동 인구비(destination_weight) 배분",
            "[가정치] 외부 성분은 창고↔최근접 고속도로 게이트웨이의 시내 구간만 모델링",
        ],
        "original_shares_pct": {k: round(float(share[k]), 2) for k in share.index},
        "n_pairs": len(rows),
        "gateways": [int(g) for g in gateways],
        "warehouse_nodes": {str(r["이름"]): int(r["node"]) for _, r in wh.iterrows()},
        "dong_nodes": {r["행정동"]: int(r["node"]) for _, r in dong.iterrows()},
    },
    "pairs": rows,
}
with open("data_processed/od_decomposed.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print("저장: data_processed/od_decomposed.json")
