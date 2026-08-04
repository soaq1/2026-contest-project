# -*- coding: utf-8 -*-
"""Task I: 종합 결과 → scenario_tram_results.json / scenario_yuseong_results.json"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8")

def load(p):
    return json.load(open(f"data_processed/{p}", encoding="utf-8"))

tram = load("tram_scenario.json")
tram_out = {
    "framing": "의사결정 지원용 what-if 분석 (검증된 예측 모델 아님)",
    "task_D_tram_scenario": {"meta": tram["meta"], "headline": tram["headline"],
                             "by_category_3단분해": tram["by_category"]},
    "task_E_greedy": load("greedy_results.json"),
    "task_F_flow_validation": load("flow_validation.json"),
    "pipeline_inputs": {
        "graph": "daejeon_weighted.graphml (실측 매칭 23.6% / imputation 76.4% [가정치])",
        "od": "od_decomposed.json (2,952쌍, 원본 3분류 총량 보존 검증 완료)",
        "baseline": "baseline_times.json (평시 OD가중 평균 11.70분, 성능 단계 (a)로 충분)",
    },
}
json.dump(tram_out, open("data_processed/scenario_tram_results.json", "w",
                         encoding="utf-8"), ensure_ascii=False, indent=1)

ys = load("yuseong_components.json")
ys_out = {
    "framing": "의사결정 지원용 what-if 분석 (검증된 예측 모델 아님)",
    "task_G_yuseong": ys,
    "task_H_expansion_demo": {
        "sites_csv": "expansion_demo_sites.csv (5행: 중첩 1 + 발생-only 3 + 대덕구 해당없음 명시)",
        "demand": load("expansion_demo_demand.json"),
    },
}
json.dump(ys_out, open("data_processed/scenario_yuseong_results.json", "w",
                       encoding="utf-8"), ensure_ascii=False, indent=1)
print("저장: scenario_tram_results.json / scenario_yuseong_results.json")
