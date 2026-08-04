# -*- coding: utf-8 -*-
"""Task L 검증(Phase 1 게이트): web/data/bundle.json 하나만으로 4개 시나리오의
헤드라인·꼬리지표·3단분해·greedy 추천·[가정치] 파라미터가 원본과 동일하게
재구성되는지 확인. 전부 PASS일 때만 Phase 2(웹앱) 진행.

지도 레이어는 표시용 파생값이라 원본 대조가 불가능하므로 불변식으로 점검:
- 시나리오 클래스는 악화 방향으로만 변화 (속도 저하 → 클래스 ≥ 베이스)
- 트램에서 변한 세그먼트 수 ≤ 모델의 affected 간선 수(3,763)
- greedy 추천 세그먼트의 지오메트리 양끝이 원본 좌표(coord_a/b)와 60m 이내
"""
import csv, json, math, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
DP = Path("data_processed")
checks = []


def check(name, ok, detail=""):
    checks.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol


def hav_m(a, b):
    la1, ln1, la2, ln2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((ln2 - ln1) / 2) ** 2)
    return 12742000 * math.asin(math.sqrt(h))


B = json.loads(Path("web/data/bundle.json").read_text(encoding="utf-8"))
js = Path("web/data/bundle.js").read_text(encoding="utf-8")
tram = json.load(open(DP / "scenario_tram_results.json", encoding="utf-8"))
snow = json.load(open(DP / "scenario_snow_results.json", encoding="utf-8"))
retail = json.load(open(DP / "scenario_retail_closure_results.json", encoding="utf-8"))
yus = json.load(open(DP / "scenario_yuseong_results.json", encoding="utf-8"))["task_G_yuseong"]
summary = json.load(open(DP / "all_scenarios_summary.json", encoding="utf-8"))

print("== 1) 헤드라인·꼬리지표 ==")
for key, src in (("tram", tram["task_D_tram_scenario"]["headline"]),
                 ("snow", snow["delay"]["headline"])):
    h = B["scenarios"][key]["headline"]
    check(f"{key} headline 4값", h == src, f"{h['weighted_mean_delay_min']}분 등")

print("== 2) 3단분해 ==")
for key, src in (("tram", tram["task_D_tram_scenario"]["by_category_3단분해"]),
                 ("snow", snow["delay"]["by_category"])):
    check(f"{key} 3단분해(같은존/존간/외부 × 4값)",
          B["scenarios"][key]["by_category"] == src)

print("== 3) 폐점 — 물류 지형 변화 지표 ==")
r = B["scenarios"]["retail"]
check("removed_demand 그리드(3T×3f×2사이트)",
      r["removed_demand_veh_day"] == retail["removed_demand_veh_day"])
check("사이트 좌표(서대전점·문화+세이)", r["sites"] == retail["sites"])
src10 = retail["top10_load_reduction_edges_f0.4_T2"]
ok10 = (len(r["top10_load_reduction"]) == 10 and
        all(a["road"] == b["road"] and close(a["reduction_pct"], b["reduction_pct"])
            and close(a["load_before"], b["load_before"])
            for a, b in zip(r["top10_load_reduction"], src10)))
check("top10 부하감소(도로명·감소율·이전부하)", ok10)
check("metric_note(지연 아님 명시)", r["metric_note"] == retail["metric_note"])

print("== 4) 유성점 — 수요 스냅샷 ==")
y = B["scenarios"]["yuseong"]
check("발생 건/일 low/mid/high", y["daily_demand"] == yus["snapshot_2031_발생"]["daily_demand_건"])
check("발생 건/년 low/mid/high", y["annual_demand"] == yus["snapshot_2031_발생"]["annual_demand_건"])
check("민감도 기여율", y["sensitivity"] == yus["sensitivity"]["contributions_pct"])
check("최근접 창고 3경로", y["routes"] == yus["snapshot_2031_발생"]["routes"])
check("소멸 스냅샷 [확인 필요] 문구", y["demolition"] == yus["snapshot_2026H2_소멸"]["status"])
check("시점 분리 주석", y["timing_note"] == yus["timing_note"])

print("== 5) greedy 추천 (트램/폭설/폐점) ==")
segments = B["roads"]["segments"]
lat0, lng0, q = B["meta"]["coord"]["lat0"], B["meta"]["coord"]["lng0"], B["meta"]["coord"]["q"]


def seg_endpoints(idx):
    f = segments[idx][0]
    p0 = (lat0 + f[0] / q, lng0 + f[1] / q)
    p1 = (lat0 + f[-2] / q, lng0 + f[-1] / q)
    return p0, p1


for key, src_g in (("tram", tram["task_E_greedy"]),
                   ("snow", snow["greedy"]),
                   ("retail", retail["greedy_on_remaining_demand"])):
    g = B["greedy"][key]
    src_picks = src_g.get("greedy_picks", src_g.get("picks"))
    ok_ids = all(a["segment_id"] == b["segment_id"]
                 and close(a["marginal_gain_veh_h_day"], b["marginal_gain_veh_h_day"])
                 for a, b in zip(g["picks"], src_picks)) and len(g["picks"]) == 5
    check(f"{key} picks 5개 (id·한계이득)", ok_ids)
    src_traj = src_g.get("objective_trajectory", src_g.get("trajectory"))
    base_obj = src_g["baseline_objective_veh_h_day"]
    ok_traj, cum = True, 0.0
    for k in range(1, 6):
        cum += src_picks[k - 1]["marginal_gain_veh_h_day"]
        b_k = g["trajectory"][str(k)]
        if f"K={k}" in src_traj:
            ok_traj &= (not b_k["derived"]) and all(
                close(b_k[f], src_traj[f"K={k}"][f]) for f in
                ("objective_veh_h_day", "improvement_pct", "saved_abs_veh_min_day"))
        else:
            ok_traj &= b_k["derived"] is True
            ok_traj &= close(b_k["objective_veh_h_day"], base_obj - cum, 0.15)
            ok_traj &= close(b_k["improvement_pct"], cum / base_obj * 100, 0.002)
            ok_traj &= close(b_k["saved_abs_veh_min_day"], cum * 60, 1.0)
        # 저장점도 유도식과 정합해야 함 (marginal gain ↔ 궤적 일관성)
        ok_traj &= close(g["trajectory"][str(k)]["saved_abs_veh_min_day"], cum * 60, 1.0)
    check(f"{key} 궤적 K=1..5 (저장값 일치 + K=4 유도 검산 + 누적 정합)", ok_traj)
    check(f"{key} baseline objective", close(g["baseline_objective_veh_h_day"], base_obj))
    ok_geo = all(
        min(hav_m(seg_endpoints(p["seg"])[0], tuple(p["coord_a"])),
            hav_m(seg_endpoints(p["seg"])[1], tuple(p["coord_a"]))) < 60 and
        min(hav_m(seg_endpoints(p["seg"])[0], tuple(p["coord_b"])),
            hav_m(seg_endpoints(p["seg"])[1], tuple(p["coord_b"]))) < 60
        for p in g["picks"])
    check(f"{key} 세그먼트 지오메트리 ↔ 원본 좌표 60m 이내", ok_geo)

print("== 6) [가정치] 파라미터 ==")


def has_param(key, substr):
    return any(substr in f"{p['label']} {p['value']}" and p["assumption"]
               for p in B["scenarios"][key]["params"])


check("트램 반경 500m·×2.0", has_param("tram", "500 m") and has_param("tram", "×2.0"))
check("폭설 -15/-25/-40%", all(has_param("snow", v) for v in ("-15%", "-25%", "-40%")))
check("폐점 f 스윕·세이 지분", has_param("retail", "0.3 / 0.4 / 0.5") and has_param("retail", "0.5"))
check("폐점 f_values 원본 일치",
      B["scenarios"]["retail"]["f_values"] ==
      retail["parameters"]["retail_demand_share_f"]["values_swept"])
check("유성 low/mid/high·균등 주입",
      has_param("yuseong", "low / mid / high") and has_param("yuseong", "균등"))
check("greedy upgrade 30% 감소 가정",
      all(("-30%" in B["greedy"][k]["upgrade_assumption"]
           or "30% 감소" in B["greedy"][k]["upgrade_assumption"])
          for k in ("tram", "snow", "retail")))
check("framing·tone 문구", B["meta"]["framing"] == summary["framing"]
      and "검증된 예측이 아닌" in B["meta"]["tone"])

print("== 7) 지도 레이어 불변식 ==")
n = len(segments)
bad_cls = sum(1 for s in segments if not (1 <= s[4] <= 3 and 1 <= s[5] <= 3 and 1 <= s[6] <= 3))
worse_ok = all(s[5] >= s[4] and s[6] >= s[4] for s in segments)
tram_changed = sum(1 for s in segments if s[5] > s[4])
snow_changed = sum(1 for s in segments if s[6] > s[4])
matched_pct = sum(1 for s in segments if s[3] == 1) / n * 100
lat_ok = lng_ok = True
for s in segments[::37]:
    f = s[0]
    for i in range(0, len(f), 2):
        la, ln = lat0 + f[i] / q, lng0 + f[i + 1] / q
        lat_ok &= 36.0 <= la <= 36.7
        lng_ok &= 127.2 <= ln <= 127.75
check(f"세그먼트 {n:,}개, 클래스 전부 1~3", n > 15000 and bad_cls == 0)
check("시나리오 클래스는 악화 방향으로만 변화", worse_ok)
check(f"트램 변화 세그먼트 {tram_changed:,} ≤ affected 3,763",
      0 < tram_changed <= tram["task_D_tram_scenario"]["meta"]["n_affected_edges"])
check(f"폭설 변화 세그먼트 {snow_changed:,} (전역 충격)", snow_changed > 5000)
check(f"실측 세그먼트 비율 {matched_pct:.1f}% (간선 기준 23.6% 근방)",
      18 <= matched_pct <= 30)
check("좌표 대전 bbox 내 (표본 1/37)", lat_ok and lng_ok)

print("== 8) 마커·오버레이 ==")
rows = list(csv.DictReader(open(DP / "shock_and_hub_coords.csv", encoding="utf-8-sig")))
n_tram_csv = sum(1 for r_ in rows if r_["구분"] == "트램")
n_wh_csv = sum(1 for r_ in rows if r_["구분"] == "물류창고")
check(f"트램 지점 {len(B['overlays']['tram_points'])} = CSV {n_tram_csv}",
      len(B["overlays"]["tram_points"]) == n_tram_csv == 15)
check(f"물류창고 {len(B['overlays']['warehouses'])} = CSV {n_wh_csv}",
      len(B["overlays"]["warehouses"]) == n_wh_csv)
check("확장 데모 사이트(좌표 보유 4곳)", len(B["overlays"]["expansion_sites"]) == 4)
check("유성 사이트 좌표", close(y["site"]["lat"], 36.358402) and close(y["site"]["lng"], 127.354168))
check("cross_cutting 3분류", set(B["cross_cutting"]) == {"가정치", "확인_필요", "검증됨"})
check("bundle.js = window.__BUNDLE__ 래퍼",
      js.startswith("window.__BUNDLE__=") and js.endswith(";")
      and json.loads(js[len("window.__BUNDLE__="):-1]) == B)

n_pass = sum(checks)
print(f"\n{'='*50}\n총 {len(checks)}개 검사 중 {n_pass}개 통과"
      + ("" if n_pass == len(checks) else f" — {len(checks)-n_pass}개 실패"))
if n_pass < len(checks):
    sys.exit(1)
print("Phase 1 게이트 통과 → Phase 2 진행 가능")
