# -*- coding: utf-8 -*-
"""Task L: 웹앱 데이터 번들 → web/data/bundle.json (+ bundle.js)

Phase 1 — 기존 결과 JSON들을 웹앱 전용 단일 포맷으로 정리 (새 모델 계산 없음).
- 도로망 형상+속성: daejeon_weighted.graphml (drive와 동일 토폴로지 45,094 간선,
  geometry·speed_kph·tt_source 포함 — drive를 따로 파싱할 필요 없음)
- 시나리오 지표·greedy: scenario_*_results.json / all_scenarios_summary.json 그대로
- 트램 채색: tram_scenario.json의 affected_edges(모델이 실제 적용한 간선) ×2.0
- 폭설 채색: task19와 동일 규칙 (motorway/trunk -15% / primary/secondary -25% /
  그 외 -40%, "_link" 제거·리스트는 첫 원소)
- 혼잡 3색 임계값: 실측 교통링크(speed, congestion)에서 일치율 최대화로 보정
  [표시용 가정치 — 메타에 기록]
- K=4 궤적: 저장된 marginal gain 누적으로 유도(derived 플래그) — K=1,2,3,5는
  저장값 그대로, 유도식이 저장값을 재현하는지는 task23에서 검증
"""
import ast, csv, json, math, sys, time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
t0 = time.time()
DP = Path("data_processed")
OUT_DIR = Path("web/data")
NS = "{http://graphml.graphdrawing.org/xmlns}"
Q = 1e5  # 좌표 양자화 (1e-5도 ≈ 1.1m)
RDP_TOL = 1e-5  # 폴리라인 단순화 허용오차 (도 단위)

SNOW_REDUCTION = {"motorway_trunk": 0.15, "primary_secondary": 0.25, "tertiary_below": 0.40}
TRAM_FACTOR = 2.0


def first_of(raw):
    """graphml 속성값이 "['a','b']" 리스트 문자열이면 첫 원소 (task19 hw[0]과 동일)."""
    if raw and raw.startswith("["):
        try:
            v = ast.literal_eval(raw)
            return str(v[0]) if v else raw
        except (ValueError, SyntaxError):
            return raw
    return raw


def name_display(raw):
    """도로명 표시용: 리스트 문자열이면 ' / '로 결합."""
    if raw and raw.startswith("["):
        try:
            v = ast.literal_eval(raw)
            seen = list(dict.fromkeys(str(x) for x in v))
            return " / ".join(seen)
        except (ValueError, SyntaxError):
            return raw
    return raw


def snow_group(highway_raw):
    h = first_of(highway_raw or "").replace("_link", "")
    if h in ("motorway", "trunk"):
        return "motorway_trunk"
    if h in ("primary", "secondary"):
        return "primary_secondary"
    return "tertiary_below"


def parse_wkt_linestring(wkt):
    """'LINESTRING (lng lat, ...)' → [(lat, lng), ...]"""
    body = wkt[wkt.index("(") + 1: wkt.rindex(")")]
    pts = []
    for pair in body.split(","):
        x, y = pair.split()
        pts.append((float(y), float(x)))
    return pts


def rdp(points, tol):
    """Douglas-Peucker 단순화 (스택 방식, 도 단위 평면 근사)."""
    if len(points) <= 2:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i0, i1 = stack.pop()
        ax, ay = points[i0]
        bx, by = points[i1]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        dmax, imax = 0.0, -1
        for i in range(i0 + 1, i1):
            px, py = points[i]
            if seg2 == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
                d2 = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d2 > dmax:
                dmax, imax = d2, i
        if dmax > tol * tol:
            keep[imax] = True
            stack.append((i0, imax))
            stack.append((imax, i1))
    return [p for p, k in zip(points, keep) if k]


def parse_graph(path):
    """graphml → (nodes {id:(lat,lng)}, edges [{u,v,k,highway,name,length,speed,src,geom}])"""
    keys, nodes, edges = {}, {}, []
    for ev, el in ET.iterparse(path, events=("end",)):
        tag = el.tag.replace(NS, "")
        if tag == "key":
            keys[el.get("id")] = el.get("attr.name")
        elif tag == "node":
            d = {keys.get(c.get("key")): c.text for c in el}
            nodes[el.get("id")] = (float(d["y"]), float(d["x"]))
            el.clear()
        elif tag == "edge":
            d = {keys.get(c.get("key")): c.text for c in el}
            edges.append({
                "u": el.get("source"), "v": el.get("target"),
                "key": el.get("id") or "0",
                "highway": d.get("highway", ""), "name": d.get("name"),
                "speed": float(d["speed_kph"]), "src": d.get("tt_source", "imputed"),
                "geom": d.get("geometry"),
            })
            el.clear()
    return nodes, edges


def calibrate_thresholds(links_path):
    """실측 링크(speed, congestion)로 표시용 3분류 임계값 (t2<t1) 보정."""
    recs = json.load(open(links_path, encoding="utf-8"))
    if isinstance(recs, dict):
        recs = recs["records"]
    obs = []
    for r in recs:
        try:
            sp, cg = float(r.get("speed")), int(float(r.get("congestion")))
        except (TypeError, ValueError):
            continue
        if 5 <= sp <= 130 and cg in (1, 2, 3):
            obs.append((sp, cg))
    best = (0.0, 30.0, 15.0)
    for t2i in range(16, 41):          # 8.0 ~ 20.0 km/h
        t2 = t2i / 2.0
        for t1i in range(t2i + 4, 81):  # t2+2 ~ 40.0 km/h
            t1 = t1i / 2.0
            acc = sum(1 for sp, cg in obs
                      if (1 if sp >= t1 else 2 if sp >= t2 else 3) == cg) / len(obs)
            if acc > best[0]:
                best = (acc, t1, t2)
    return best[1], best[2], round(best[0] * 100, 1), len(obs)


def main():
    # ── 1) 원본 로드 ──────────────────────────────────────────────
    summary = json.load(open(DP / "all_scenarios_summary.json", encoding="utf-8"))
    tram_res = json.load(open(DP / "scenario_tram_results.json", encoding="utf-8"))
    snow_res = json.load(open(DP / "scenario_snow_results.json", encoding="utf-8"))
    retail_res = json.load(open(DP / "scenario_retail_closure_results.json", encoding="utf-8"))
    yus_res = json.load(open(DP / "scenario_yuseong_results.json", encoding="utf-8"))
    cand_meta = json.load(open(DP / "intervention_candidates.json", encoding="utf-8"))
    cand_ids = {c["segment_id"] for c in cand_meta["candidates"]}
    affected = set(json.load(open(DP / "tram_scenario.json", encoding="utf-8"))["affected_edges"])

    t1, t2, acc, n_obs = calibrate_thresholds(DP / "daejeon_traffic_links_full.json")
    print(f"혼잡 표시 임계값 보정: 원활 ≥{t1} / 서행 ≥{t2} / 정체 <{t2} km/h "
          f"(실측 링크 {n_obs:,}건 대비 일치율 {acc}%)")

    def cls(speed):
        return 1 if speed >= t1 else 2 if speed >= t2 else 3

    nodes, edges = parse_graph(DP / "daejeon_weighted.graphml")
    print(f"그래프: 노드 {len(nodes):,} / 방향 간선 {len(edges):,} ({time.time()-t0:.0f}초)")

    # ── 2) 물리 세그먼트로 병합 + 시나리오별 표시 클래스 ─────────────
    seg_map = {}   # (a,b,key,len_round) -> seg dict
    for e in edges:
        u, v = e["u"], e["v"]
        eid = f"{u}_{v}_{e['key']}"
        tram_speed = e["speed"] / TRAM_FACTOR if eid in affected else e["speed"]
        snow_speed = e["speed"] * (1 - SNOW_REDUCTION[snow_group(e["highway"])])
        a, b = (u, v) if int(u) <= int(v) else (v, u)
        geom_pts = parse_wkt_linestring(e["geom"]) if e["geom"] else [nodes[u], nodes[v]]
        mk = (a, b, e["key"])
        s = seg_map.get(mk)
        if s is None:
            seg_map[mk] = {
                "geom": geom_pts if (u, v) == (a, b) else geom_pts[::-1],
                "name": e["name"], "highway": e["highway"], "src": e["src"],
                "cb": cls(e["speed"]), "ct": cls(tram_speed), "cs": cls(snow_speed),
            }
        else:  # 역방향 — 더 나쁜(큰) 클래스, 실측 우선
            s["cb"] = max(s["cb"], cls(e["speed"]))
            s["ct"] = max(s["ct"], cls(tram_speed))
            s["cs"] = max(s["cs"], cls(snow_speed))
            if e["src"] == "traffic_link":
                s["src"] = "traffic_link"
            if s["name"] is None:
                s["name"] = e["name"]

    seg_keys = list(seg_map.keys())
    seg_index = {mk: i for i, mk in enumerate(seg_keys)}
    pair_index = {}  # (a,b) -> 첫 세그먼트 idx (key 불문 — 폐점 감소 간선 조회용)
    for mk, i in seg_index.items():
        pair_index.setdefault((mk[0], mk[1]), i)

    # ── 3) 좌표 양자화 + 테이블화 ────────────────────────────────
    all_lat = [p[0] for s in seg_map.values() for p in (s["geom"][0], s["geom"][-1])]
    all_lng = [p[1] for s in seg_map.values() for p in (s["geom"][0], s["geom"][-1])]
    lat0, lng0 = min(all_lat), min(all_lng)

    names, name_idx = [], {}
    hws, hw_idx = [], {}
    segments = []
    n_pts_before = n_pts_after = 0
    for mk in seg_keys:
        s = seg_map[mk]
        pts = s["geom"]
        n_pts_before += len(pts)
        pts = rdp(pts, RDP_TOL)
        n_pts_after += len(pts)
        flat = []
        for la, ln in pts:
            flat.append(round((la - lat0) * Q))
            flat.append(round((ln - lng0) * Q))
        nm = name_display(s["name"]) if s["name"] else None
        if nm is not None and nm not in name_idx:
            name_idx[nm] = len(names)
            names.append(nm)
        hw = first_of(s["highway"])
        if hw not in hw_idx:
            hw_idx[hw] = len(hws)
            hws.append(hw)
        segments.append([flat, name_idx[nm] if nm else -1, hw_idx[hw],
                         1 if s["src"] == "traffic_link" else 0,
                         s["cb"], s["ct"], s["cs"]])

    dist = {"base": defaultdict(int), "tram": defaultdict(int), "snow": defaultdict(int)}
    for seg in segments:
        dist["base"][seg[4]] += 1
        dist["tram"][seg[5]] += 1
        dist["snow"][seg[6]] += 1
    print(f"세그먼트 {len(segments):,}개 (지오메트리 점 {n_pts_before:,}→{n_pts_after:,}, "
          f"RDP {RDP_TOL}도)")
    for k, d in dist.items():
        print(f"  {k}: 원활 {d[1]:,} / 서행 {d[2]:,} / 정체 {d[3]:,}")

    # ── 4) greedy 추천 + 폐점 감소 간선 → 세그먼트 참조 ──────────────
    def resolve_pick(p):
        u, v, key = p["segment_id"].rsplit("_", 2)
        a, b = (u, v) if int(u) <= int(v) else (v, u)
        idx = seg_index.get((a, b, key))
        if idx is None:
            idx = pair_index.get((a, b))
        assert idx is not None, f"greedy 세그먼트 미해결: {p['segment_id']}"
        assert p["segment_id"] in cand_ids, f"후보 목록에 없음: {p['segment_id']}"
        return {**p, "seg": idx}

    def derive_trajectory(picks, traj_src, base_obj):
        """저장 K=1,2,3,5 + marginal gain 누적으로 K=4 유도."""
        out = {}
        cum = 0.0
        for k, p in enumerate(picks, start=1):
            cum += p["marginal_gain_veh_h_day"]
            kk = f"K={k}"
            if kk in traj_src:
                out[str(k)] = {**traj_src[kk], "derived": False}
            else:
                out[str(k)] = {
                    "objective_veh_h_day": round(base_obj - cum, 1),
                    "improvement_pct": round(cum / base_obj * 100, 3),
                    "saved_abs_veh_min_day": round(cum * 60),
                    "derived": True,
                }
        return out

    tram_g = tram_res["task_E_greedy"]
    snow_g = snow_res["greedy"]
    retail_g = retail_res["greedy_on_remaining_demand"]
    greedy = {
        "tram": {
            "baseline_objective_veh_h_day": tram_g["baseline_objective_veh_h_day"],
            "upgrade_assumption": tram_g["meta"]["upgrade"],
            "picks": [resolve_pick(p) for p in tram_g["greedy_picks"]],
            "trajectory": derive_trajectory(tram_g["greedy_picks"], tram_g["objective_trajectory"],
                                            tram_g["baseline_objective_veh_h_day"]),
        },
        "snow": {
            "baseline_objective_veh_h_day": snow_g["baseline_objective_veh_h_day"],
            "upgrade_assumption": snow_g["upgrade_assumption"],
            "picks": [resolve_pick(p) for p in snow_g["picks"]],
            "trajectory": derive_trajectory(snow_g["picks"], snow_g["trajectory"],
                                            snow_g["baseline_objective_veh_h_day"]),
        },
        "retail": {
            "baseline_objective_veh_h_day": retail_g["baseline_objective_veh_h_day"],
            "upgrade_assumption": "[가정치] travel_time -30%",
            "picks": [resolve_pick(p) for p in retail_g["picks"]],
            "trajectory": derive_trajectory(retail_g["picks"], retail_g["trajectory"],
                                            retail_g["baseline_objective_veh_h_day"]),
        },
    }

    retail_top10 = []
    for r in retail_res["top10_load_reduction_edges_f0.4_T2"]:
        u, v = r["edge"].split("_")
        a, b = (u, v) if int(u) <= int(v) else (v, u)
        idx = pair_index.get((a, b))
        assert idx is not None, f"감소 간선 미해결: {r['edge']}"
        retail_top10.append({"seg": idx, "road": r["road"], "highway": r["highway"],
                             "load_before": r["load_before"],
                             "reduction_pct": r["reduction_pct"]})

    # ── 5) 마커 (CSV) ────────────────────────────────────────────
    tram_pts, warehouses = [], []
    with open(DP / "shock_and_hub_coords.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["구분"] == "트램":
                tram_pts.append({"name": row["이름"],
                                 "lat": float(row["lat"]), "lng": float(row["lng"])})
            elif row["구분"] == "물류창고":
                warehouses.append({"name": row["이름"],
                                   "lat": float(row["lat"]), "lng": float(row["lng"])})
    expansion = []
    with open(DP / "expansion_demo_sites.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["lat"]:
                expansion.append({"name": row["사이트명"], "gu": row["구"],
                                  "lat": float(row["lat"]), "lng": float(row["lng"]),
                                  "households": row["세대수"] or None,
                                  "status": row["데이터상태"], "demo_type": row["데모유형"]})
    yus = yus_res["task_G_yuseong"]
    exp_demand = yus_res["task_H_expansion_demo"]["demand"]["annual_demand_건"]
    for site in expansion:
        if site["name"] in exp_demand:
            site["annual_demand"] = exp_demand[site["name"]]

    # ── 6) 시나리오 패널 데이터 (원본 값 그대로) ─────────────────────
    scenarios = {
        "tram": {
            "label": "트램 공사", "color_field": 5,
            "shock": summary["scenarios"]["1_트램공사"]["shock"],
            "meta_status": tram_res["task_D_tram_scenario"]["meta"]["construction_status"],
            "n_affected_edges": tram_res["task_D_tram_scenario"]["meta"]["n_affected_edges"],
            "params": [
                {"label": "영향 반경", "value": "500 m", "assumption": True},
                {"label": "통행시간 배율", "value": "×2.0", "assumption": True},
            ],
            "headline": tram_res["task_D_tram_scenario"]["headline"],
            "by_category": tram_res["task_D_tram_scenario"]["by_category_3단분해"],
            "key_finding": summary["scenarios"]["1_트램공사"]["key_finding"],
        },
        "snow": {
            "label": "폭설", "color_field": 6,
            "shock": summary["scenarios"]["2_폭설"]["shock"],
            "scenario_desc": snow_res["scenario"],
            "params": [
                {"label": "고속·간선(motorway/trunk)", "value": "-15%", "assumption": True},
                {"label": "주간선(primary/secondary)", "value": "-25%", "assumption": True},
                {"label": "그 외(tertiary 이하)", "value": "-40%", "assumption": True},
            ],
            "headline": snow_res["delay"]["headline"],
            "by_category": snow_res["delay"]["by_category"],
            "key_finding": summary["scenarios"]["2_폭설"]["key_finding"],
        },
        "retail": {
            "label": "유통 폐점", "color_field": 4,
            "shock": summary["scenarios"]["3_유통폐점"]["shock"],
            "scenario_desc": retail_res["scenario"],
            "metric_note": retail_res["metric_note"],
            "composite_note": retail_res["composite_note"],
            "params": [
                {"label": "수요 흡수비중 f", "value": "0.3 / 0.4 / 0.5 스윕",
                 "assumption": True, "slider": True},
                {"label": "세이 지분(복합 내)", "value": "0.5", "assumption": True},
            ],
            "f_values": retail_res["parameters"]["retail_demand_share_f"]["values_swept"],
            "f_representative": retail_res["parameters"]["retail_demand_share_f"]["representative"],
            "sites": retail_res["sites"],
            "removed_demand_veh_day": retail_res["removed_demand_veh_day"],
            "top10_load_reduction": retail_top10,
            "key_finding": summary["scenarios"]["3_유통폐점"]["key_finding"],
        },
        "yuseong": {
            "label": "유성점 재개발", "color_field": 4,
            "shock": summary["scenarios"]["4_유성점(봉명1지구)"]["shock"],
            "params": [
                {"label": "성장률 프록시", "value": "low / mid / high",
                 "assumption": True, "slider": True},
                {"label": "주입 방식", "value": "최근접 창고 3곳 균등", "assumption": True},
                {"label": "세대수", "value": "998 (확정)", "assumption": False},
            ],
            "site": yus["site"],
            "demolition": yus["snapshot_2026H2_소멸"]["status"],
            "daily_demand": yus["snapshot_2031_발생"]["daily_demand_건"],
            "annual_demand": yus["snapshot_2031_발생"]["annual_demand_건"],
            "vehicle_conversion": yus["snapshot_2031_발생"]["vehicle_conversion"],
            "routes": yus["snapshot_2031_발생"]["routes"],
            "sensitivity": yus["sensitivity"]["contributions_pct"],
            "timing_note": yus["timing_note"],
            "key_finding": summary["scenarios"]["4_유성점(봉명1지구)"]["key_finding"],
        },
    }

    bundle = {
        "meta": {
            "built": time.strftime("%Y-%m-%d %H:%M"),
            "framing": summary["framing"],
            "tone": "검증된 예측이 아닌 시나리오 기반 의사결정 지원 분석",
            "baseline_note": summary["baseline"],
            "coord": {"lat0": round(lat0, 6), "lng0": round(lng0, 6), "q": Q},
            "congestion_display_rule": {
                "t1_kmh": t1, "t2_kmh": t2, "agreement_pct": acc, "n_obs_links": n_obs,
                "note": "[표시용 가정치] 지도 3색은 간선 speed_kph를 실측 링크 보정 임계값으로 "
                        "구간화한 것 — 모델 지표(지연 등)와 별개의 표시 규칙",
            },
            "graph_note": "실측 매칭은 도로명 단위 평균속도 (전체 간선의 23.6%) / 나머지 "
                          "osmnx 등급별 평균 imputation [가정치]",
            "counts": {"segments": len(segments), "directed_edges": len(edges),
                       "nodes": len(nodes)},
            "attribution": "도로망 © OpenStreetMap contributors (ODbL)",
        },
        "roads": {"names": names, "highways": hws, "segments": segments},
        "scenarios": scenarios,
        "greedy": greedy,
        "overlays": {
            "tram_points": tram_pts, "tram_radius_m": 500,
            "warehouses": warehouses, "expansion_sites": expansion,
        },
        "cross_cutting": summary["cross_cutting_labels"],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    js_text = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    (OUT_DIR / "bundle.json").write_text(js_text, encoding="utf-8")
    (OUT_DIR / "bundle.js").write_text("window.__BUNDLE__=" + js_text + ";",
                                       encoding="utf-8")
    kb = len(js_text.encode("utf-8")) / 1024
    print(f"저장: web/data/bundle.json + bundle.js ({kb:,.0f} KB, {time.time()-t0:.0f}초)")


if __name__ == "__main__":
    main()
