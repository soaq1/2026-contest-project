# -*- coding: utf-8 -*-
"""Task A: 가중치 그래프 구성 → data_processed/daejeon_weighted.graphml

travel_time 부여 우선순위:
1) 대전교통정보 링크(14,452건)의 실측 speed — 링크에 좌표가 없어(노드명·도로명만)
   **도로명(roadName) 단위 평균속도**로 OSM 간선 name과 매칭 [한계: 링크 단위가
   아니라 도로 단위 평균]
2) 미매칭 간선은 osmnx add_edge_speeds의 도로등급별 평균속도 imputation [가정치]
- VDS 설치정보(615건)는 좌표·노선만 있고 속도가 없어 travel_time 부여에는
  사용 불가 — 고속도로는 OSM maxspeed/등급 평균 기반 [한계 보고].
  VDS는 Task F(부하 검증)에서 교통량 실측과의 조인 키로만 활용
"""
import json, sys
from collections import defaultdict
import numpy as np
import osmnx as ox

sys.stdout.reconfigure(encoding="utf-8")

G = ox.load_graphml("data_processed/daejeon_drive.graphml")
G = ox.routing.add_edge_speeds(G)
G = ox.routing.add_edge_travel_times(G)

links = json.load(open("data_processed/daejeon_traffic_links_full.json", encoding="utf-8"))
recs = links if isinstance(links, list) else links["records"]
road_speed = defaultdict(list)
for r in recs:
    try:
        sp = float(r.get("speed"))
    except (TypeError, ValueError):
        continue
    if 5 <= sp <= 130 and r.get("roadName"):
        road_speed[str(r["roadName"]).replace(" ", "")].append(sp)
road_speed = {k: float(np.mean(v)) for k, v in road_speed.items()}

# 도로명 별칭 (확실 사례만 — 로/길 계열·부분문자열 우연 일치는 추가 금지)
ALIAS = {"갑천도시고속도로": "천변도시고속화도로"}
n_alias = 0
for osm_name, link_name in ALIAS.items():
    if link_name in road_speed and osm_name not in road_speed:
        road_speed[osm_name] = road_speed[link_name]
        n_alias += 1

# 동명이도로 배제 [확인됨, 2026-08]: OSM에서 5km 이상 떨어진 서로 다른 실제 도로가
# 같은 이름을 공유 — 대학로(유성구 어은동/동구 용운동), 동서대로(중구 용두동 도심
# 대간선/유성구 덕명동 외곽 소구간). 실측 링크는 교차로명만 있고 좌표가 없어 어느
# 물리적 도로의 관측인지 판별 불가(동서대로 실측 7건은 교차로명 지오코딩상 덕명동
# 소구간으로 추정되나 확정 불가) → 이름 매칭에서 제외, 표준 임퓨테이션으로 폴백
AMBIGUOUS_NAMES = {"대학로", "동서대로"}
n_ambiguous_removed = 0
for nm in AMBIGUOUS_NAMES:
    if nm in road_speed:
        del road_speed[nm]
        n_ambiguous_removed += 1
print(f"교통링크 도로명 {len(road_speed)}개 (유효속도 링크 기반, 별칭 {n_alias}건 추가, "
      f"동명이도로 배제 {n_ambiguous_removed}건: {sorted(AMBIGUOUS_NAMES)})")

n_match, n_total = 0, 0
for u, v, k, d in G.edges(keys=True, data=True):
    n_total += 1
    names = d.get("name")
    if names is None:
        continue
    if not isinstance(names, list):
        names = [names]
    for nm in names:
        key = str(nm).replace(" ", "")
        if key in road_speed:
            sp = road_speed[key]
            d["speed_kph"] = sp
            d["travel_time"] = float(d["length"]) / 1000.0 / sp * 3600.0
            d["tt_source"] = "traffic_link"
            n_match += 1
            break
    else:
        d["tt_source"] = "imputed"
for u, v, k, d in G.edges(keys=True, data=True):
    d.setdefault("tt_source", "imputed")

print(f"간선 {n_total:,}개 중 실측 매칭 {n_match:,} ({n_match/n_total*100:.1f}%) / "
      f"imputation {n_total-n_match:,} ({(n_total-n_match)/n_total*100:.1f}%)")

# 도로등급별 매칭 분포 (가설: 실측은 간선급, imputation은 세부도로에 집중)
cls_stat = defaultdict(lambda: [0, 0])  # class -> [matched, total]
for u, v, k, d in G.edges(keys=True, data=True):
    hw = d.get("highway")
    cls = (hw if isinstance(hw, str) else hw[0])
    cls_stat[cls][1] += 1
    if d["tt_source"] == "traffic_link":
        cls_stat[cls][0] += 1
print(f"\n{'도로등급':<16}{'실측':>8}{'전체':>8}{'실측비율':>9}")
for cls, (m, t) in sorted(cls_stat.items(), key=lambda x: -x[1][1]):
    if t >= 50:
        print(f"{cls:<16}{m:>8,}{t:>8,}{m/t*100:>8.1f}%")

ox.save_graphml(G, "data_processed/daejeon_weighted.graphml")
print("저장: data_processed/daejeon_weighted.graphml")
