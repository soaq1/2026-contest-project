# -*- coding: utf-8 -*-
"""4개 시나리오 통합 요약 → data_processed/all_scenarios_summary.json
제안서 5절(시나리오 분석 결과) 기초 자료
"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8")

def load(p):
    return json.load(open(f"data_processed/{p}", encoding="utf-8"))

tram = load("scenario_tram_results.json")
snow = load("scenario_snow_results.json")
retail = load("scenario_retail_closure_results.json")
ys = load("scenario_yuseong_results.json")

th = tram["task_D_tram_scenario"]["headline"]
sh = snow["delay"]["headline"]
summary = {
    "framing": "의사결정 지원용 what-if 분석 (검증된 예측 모델 아님)",
    "baseline": "평시 OD가중 평균 11.94분 (2,952 OD쌍, 창고43×행정동82+게이트웨이)",
    "scenarios": {
        "1_트램공사": {
            "shock": "14개 전 공구 공사 중(확인 사실) — 지점 반경 500m 간선 ×2.0 [가정치]",
            "headline_delay_min": th["weighted_mean_delay_min"],
            "tail_top10pct_min": th["top10pct_weighted_delay_min"],
            "p95_min": th["p95_weighted_delay_min"],
            "3단분해": {c: m["weighted_mean_delay_min"]
                       for c, m in tram["task_D_tram_scenario"]["by_category_3단분해"].items()},
            "greedy_K5": tram["task_E_greedy"]["objective_trajectory"]["K=5"],
            "key_finding": "존간(도심 회랑) 타격 최대. greedy 5개가 우회 회랑 형성, "
                           "의심 사례 0건",
        },
        "2_폭설": {
            "shock": "등급별 차등 속도저하 -15/-25/-40% 전역 [가정치, 근거 문헌 없음]",
            "headline_delay_min": sh["weighted_mean_delay_min"],
            "tail_top10pct_min": sh["top10pct_weighted_delay_min"],
            "p95_min": sh["p95_weighted_delay_min"],
            "3단분해": {c: m["weighted_mean_delay_min"]
                       for c, m in snow["delay"]["by_category"].items()},
            "greedy_K5": snow["greedy"]["trajectory"]["K=5"],
            "key_finding": "전역 충격이라 지연 절대값이 시나리오 중 최대",
        },
        "3_유통폐점": {
            "shock": "서대전점 + [문화+세이 복합] 수요 소멸 (f=0.3~0.5 스윕 [가정치])",
            "metric_type": "지연이 아니라 물류 지형 변화(혼잡 피드백 없음 — 지연 불변)",
            "removed_demand_T2_f0.4": retail["removed_demand_veh_day"]["T2_2026-01"]["f=0.4"],
            "top_load_reduction": [
                {"road": t["road"], "pct": t["reduction_pct"]}
                for t in retail["top10_load_reduction_edges_f0.4_T2"][:3]],
            "greedy_K5": retail["greedy_on_remaining_demand"]["trajectory"]["K=5"],
            "key_finding": "폐점 인근 접근로의 화물 의존도 감소 — 상위 감소 구간이 "
                           "지점 주변에 국지화",
        },
        "4_유성점(봉명1지구)": {
            "shock": "소멸(2026H2)+발생(2031) 시점 분리 스냅샷 — 순합산 안 함",
            "metric_type": "수요 주입/제거 (건/일)",
            "발생_건_일": ys["task_G_yuseong"]["snapshot_2031_발생"]["daily_demand_건"],
            "소멸": "[확인 필요] 정량 프록시 미확보(전국 최상위권 매출·매각 600억 정성만)",
            "sensitivity": ys["task_G_yuseong"]["sensitivity"]["contributions_pct"],
            "key_finding": "low~high 폭의 88.8%가 프록시 성장률에서 발생 — "
                           "성장률이 지배 입력",
        },
    },
    "cross_cutting_labels": {
        "가정치": ["트램 500m·×2.0", "폭설 저하율 3단", "증설 -30%", "창고 균등 배분",
                  "retail f=0.3~0.5", "세이 지분 50%", "imputation 76.3%"],
        "확인_필요": ["유성점 소멸 정량 프록시", "택배→차량 환산계수",
                    "프록시1(면적당 물동량)"],
        "검증됨": ["OD 3분류 비율 45.78/17.62/36.60 재현", "congestion 방향(클수록 정체)",
                  "등급별 실측비율 사다리(간선↑ 세부도로↓)"],
    },
}
json.dump(summary, open("data_processed/all_scenarios_summary.json", "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
print("저장: all_scenarios_summary.json")
for k, v in summary["scenarios"].items():
    print(f"  {k}: {v.get('headline_delay_min', v.get('metric_type', ''))}")
