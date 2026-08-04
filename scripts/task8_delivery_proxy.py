# -*- coding: utf-8 -*-
"""Task 8: 세대당 배송 프록시 저/중/고 범위 → data_processed/delivery_proxy_range.json

국민1인당 연간 택배 이용 횟수(2000~2025) 기반:
- low  : 2025년 값 고정(이커머스 포화 가정, 2031년까지 불변)
- high : 2020~2025 5개년 CAGR을 2031년까지 6년 복리 연장
- mid  : low·high의 기하평균
- 998세대(유성점 재개발 예상 공급) × 세대당 인구 2.05(대전 2026-06 평균)
  × 1인당 프록시 = 연간 추가 배송 수요(건)

[확인 필요] 택배 건수 → 차량 통행 환산계수(건당 적재율, 소형화물차 1대당
일평균 취급 건수) 미확보. 확보 전까지 수요는 '건' 단위로만 사용 가능.
[수정 이력 2026-07-18] 최초 산출은 세대당 인구(2.05인) 반영이 누락된
998 × 프록시였음(오류·수정전: low 125,249 / mid 185,700 / high 275,327건)
→ 998 × 2.05 × 프록시로 재계산.
"""
import json, math, sys
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
df = pd.read_excel("data_raw/1인당_연간_택배_이용_횟수.xlsx").set_index("연도")
v = df["국민1인당"]
assert v[2025] == 125.5, v[2025]

cagr = (v[2025] / v[2020]) ** (1 / 5) - 1
g_2324 = v[2024] / v[2023] - 1
g_2425 = v[2025] / v[2024] - 1
g_2223 = v[2023] / v[2022] - 1

low = float(v[2025])
high = low * (1 + cagr) ** 6
mid = math.sqrt(low * high)
units = 998
household_size = 2.05  # 대전광역시 2026-06 세대당 인구 (주민등록 CSV 시 전체 행)
persons = units * household_size
demand = {k: round(persons * p) for k, p in (("low", low), ("mid", mid), ("high", high))}

out = {
    "national_per_capita_2025": low,
    "economically_active_per_capita_2025": float(df["경제활동인구1인당"][2025]),
    "economically_active_note": "경제활동인구1인당은 이번 산출에 미사용(가구 전체 인구 "
        "대비 프록시가 목적에 더 적합) — 비교용으로만 병기",
    "cagr_2020_2025": round(cagr, 6),
    "recent_deceleration_note": (
        f"연간 성장률 둔화 추세(참고용): 2022→23 {g_2223*100:.1f}% → "
        f"2023→24 {g_2324*100:.1f}% → 2024→25 {g_2425*100:.1f}%. "
        f"5개년 CAGR({cagr*100:.1f}%) 복리 연장(high)은 최근 둔화를 반영하지 않은 상한임"),
    "low_per_capita_2031": round(low, 2),
    "mid_per_capita_2031": round(mid, 2),
    "high_per_capita_2031": round(high, 2),
    "yuseong_998units_annual_demand": demand,
    "household_size_applied": household_size,
    "correction_note": "[수정 2026-07-18] 최초 산출은 세대당 인구 미반영(998×프록시)이었음 "
        "— 오류(수정전): low 125,249 / mid 185,700 / high 275,327건. "
        "현재 값은 998세대 × 2.05인 × 프록시로 재계산된 것",
    "vehicle_conversion_note": "[확인 필요] 택배 건수→차량 단위 환산계수 미확보: "
        "택배 건당 평균 적재율 및 1톤 이하 소형화물차 1대당 평균 취급 건수 필요. "
        "확보 전까지 본 수요는 '건/년' 단위로만 해석할 것",
    "source": "1인당_연간_택배_이용_횟수.xlsx (2000~2025, 국민1인당/경제활동인구1인당)",
}
with open("data_processed/delivery_proxy_range.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"CAGR 2020~2025: {cagr*100:.2f}%/년")
print(f"성장률 추이: 22→23 {g_2223*100:.1f}% / 23→24 {g_2324*100:.1f}% / 24→25 {g_2425*100:.1f}%")
print(f"2031 프록시: low {low:.1f} / mid {mid:.1f} / high {high:.1f} 회/인·년")
print(f"998세대 × {household_size}인 연간 추가 수요(건): {demand}")
