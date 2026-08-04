# -*- coding: utf-8 -*-
"""Task 9: 개입(intervention) 후보 집합 → data_processed/intervention_candidates.json

핵심 원칙: 신규 도로를 상상하지 않고, OSM에 이미 존재하는 저등급 도로
(service/track/unclassified/residential)의 '증설(폭 확장·등급 상향)'만 후보로 삼음.
- 길이 2km 이하 간선만 (단일 개입 단위로 타당한 규모)
- 증설 후 travel_time = 현재 × 0.7
  [가정치] 30% 감소는 임의 가정으로 민감도 분석 대상
- travel_time 원본이 graphml에 없어 osmnx add_edge_speeds(도로등급별 평균속도
  보정) → add_edge_travel_times로 산출 [가정치: OSM maxspeed 결측 구간은
  등급별 평균속도로 대체(imputation)됨]
- 후보가 과다하면 시나리오 4종(트램/폭설/폐점/유성점) 충격지점 반경 5km로 1차 축소:
  트램 15 + 홈플러스 6(유성점 포함) + 세이백화점 3 + 기상관측 5지점(폭설) = 29지점.
  물류창고 43곳은 '허브(공급측)'이지 충격지점이 아니므로 제외
- 최종 후보는 물리 세그먼트 단위: (u,v)/(v,u) 양방향 간선쌍을
  (frozenset({u,v}), key)로 묶음 — key를 포함해야 같은 노드쌍 사이의
  평행 간선(서로 다른 실제 도로)이 잘못 합쳐지지 않음.
  greedy는 세그먼트 단위로 선택하고, 적용 시 directed_edges의 모든 간선에
  travel_time 감소를 함께 적용해야 함
"""
import json, sys
import numpy as np
import pandas as pd
import osmnx as ox

sys.stdout.reconfigure(encoding="utf-8")
TARGET = {"service", "track", "unclassified", "residential"}
MAX_LEN = 2000.0
RADIUS_KM = 5.0
REDUCE_THRESHOLD = 3000  # '수천 개 이상' 판단 기준

G = ox.load_graphml("data_processed/daejeon_drive.graphml")
G = ox.routing.add_edge_speeds(G)
G = ox.routing.add_edge_travel_times(G)

def hw_match(hw):
    hws = hw if isinstance(hw, list) else [hw]
    return any(h in TARGET for h in hws)

cands = []
for u, v, k, d in G.edges(keys=True, data=True):
    if not hw_match(d.get("highway")) or float(d["length"]) > MAX_LEN:
        continue
    hw = d["highway"]
    cands.append({
        "edge_id": f"{u}_{v}_{k}",
        "u": u, "v": v, "key": k,
        "start": [round(G.nodes[u]["y"], 7), round(G.nodes[u]["x"], 7)],
        "end": [round(G.nodes[v]["y"], 7), round(G.nodes[v]["x"], 7)],
        "highway": hw if isinstance(hw, str) else "/".join(hw),
        "length_m": round(float(d["length"]), 1),
        "travel_time_s": round(float(d["travel_time"]), 2),
        "upgraded_travel_time_s": round(float(d["travel_time"]) * 0.7, 2),
    })
n_before = len(cands)
print(f"1차 추출(저등급 4종·≤2km): {n_before:,}개")

reduced = False
if n_before > REDUCE_THRESHOLD:
    reduced = True
    shocks = []
    coords = pd.read_csv("data_processed/shock_and_hub_coords.csv", encoding="utf-8-sig")
    sel = coords[coords["구분"].isin(["트램", "홈플러스", "세이백화점"])]
    shocks += [(float(r["lat"]), float(r["lng"])) for _, r in sel.iterrows()]
    snow = json.load(open("data_processed/kma_snow.json", encoding="utf-8"))
    stn_seen = {}
    for r in snow["records"]:
        stn_seen[r["stn"]] = (r["lat"], r["lon"])
    shocks += list(stn_seen.values())
    print(f"충격지점: 트램/폐점/유성점 {len(sel)} + 기상 {len(stn_seen)} = {len(shocks)}지점")

    sh = np.radians(np.array(shocks))            # (S, 2) lat,lng
    mids = np.radians(np.array([[(c["start"][0] + c["end"][0]) / 2,
                                 (c["start"][1] + c["end"][1]) / 2] for c in cands]))
    dlat = mids[:, None, 0] - sh[None, :, 0]
    dlng = mids[:, None, 1] - sh[None, :, 1]
    a = np.sin(dlat / 2) ** 2 + np.cos(mids[:, None, 0]) * np.cos(sh[None, :, 0]) * np.sin(dlng / 2) ** 2
    dist_km = 12742 * np.arcsin(np.sqrt(a))
    keep = (dist_km.min(axis=1) <= RADIUS_KM)
    cands = [c for c, k in zip(cands, keep) if k]
    print(f"5km 축소: {n_before:,} → {len(cands):,}개")

# ── 물리 세그먼트 병합: (frozenset({u,v}), key) 기준
segments = {}
for c in cands:
    a, b = sorted((c["u"], c["v"]))
    sk = (a, b, c["key"])
    s = segments.get(sk)
    if s is None:
        segments[sk] = {
            "segment_id": f"{a}_{b}_{c['key']}",
            "node_a": a, "node_b": b, "key": c["key"],
            "coord_a": c["start"] if c["u"] == a else c["end"],
            "coord_b": c["end"] if c["u"] == a else c["start"],
            "highway": c["highway"], "length_m": c["length_m"],
            "travel_time_s": c["travel_time_s"],
            "upgraded_travel_time_s": c["upgraded_travel_time_s"],
            "oneway": True,
            "directed_edges": [c["edge_id"]],
        }
    else:
        s["oneway"] = False
        s["directed_edges"].append(c["edge_id"])
        # 방향별 속성 불일치 시 보수적으로 큰 travel_time 채택
        if c["travel_time_s"] > s["travel_time_s"]:
            s["travel_time_s"] = c["travel_time_s"]
            s["upgraded_travel_time_s"] = c["upgraded_travel_time_s"]
segs = list(segments.values())
n_mismatch = sum(1 for sk, s in segments.items()
                 if len(s["directed_edges"]) > 2)
print(f"물리 세그먼트 병합: 방향 간선 {len(cands):,} → 세그먼트 {len(segs):,}개 "
      f"(양방향 {sum(1 for s in segs if not s['oneway']):,} / "
      f"일방 {sum(1 for s in segs if s['oneway']):,})")
if n_mismatch:
    print(f"⚠ 3개 이상 간선이 묶인 세그먼트: {n_mismatch}건")

out = {
    "meta": {
        "created_at": "2026-07-18",
        "principle": "OSM 기존 저등급 도로의 증설만 후보로 함(신규 노선 없음)",
        "unit": "물리 세그먼트 — (frozenset({u,v}), key)로 양방향 간선쌍 병합. "
                "key 포함 사유: 같은 노드쌍의 평행 간선(다른 실제 도로) 오병합 방지. "
                "greedy는 세그먼트 단위로 선택하고 적용 시 directed_edges의 "
                "모든 간선에 travel_time 감소를 함께 적용할 것",
        "target_highway": sorted(TARGET),
        "max_length_m": MAX_LEN,
        "upgrade_assumption": "[가정치] 증설 후 travel_time 30% 감소 — 임의값, 민감도 분석 대상",
        "travel_time_source": "[가정치] osmnx add_edge_speeds: maxspeed 결측 구간은 "
                              "도로등급별 평균속도로 imputation 후 travel_time 산출",
        "reduction": {
            "applied": reduced,
            "rule": f"시나리오 4종(트램/폭설/폐점/유성점) 충격지점 29곳 반경 {RADIUS_KM}km",
            "n_directed_before": n_before, "n_directed_after": len(cands),
            "n_segments_final": len(segs),
        },
    },
    "candidates": segs,
}
with open("data_processed/intervention_candidates.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)

from collections import Counter
print("등급별:", dict(Counter(s["highway"] for s in segs).most_common(6)))
print(f"저장: 세그먼트 {len(segs):,}개 → data_processed/intervention_candidates.json")
