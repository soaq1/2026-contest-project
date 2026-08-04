# -*- coding: utf-8 -*-
"""Task H: 확장 데모 4지점 → data_processed/expansion_demo_sites.csv

- 봉명1지구(중첩: 소멸+발생)를 기준행으로 포함, 3개 신규 지점은 발생-only
- 은행1구역은 위치-only(세대수 미주입), 대덕구는 threshold 초과 사이트
  미확인을 명시행으로 기록(침묵 금지 원칙)
- 발생 성분 프록시 사슬 = 세대수 × 2.05인 × low/mid/high 프록시(2031)
  → 산출 수치는 yuseong_components.json과 동일 사슬, 결과는 별도 JSON에 저장
"""
import json, os, sys, time
import requests
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
KEY = os.environ.get("KAKAO_API_KEY")
if not KEY:
    sys.exit("KAKAO_API_KEY 미설정")
HEADERS = {"Authorization": f"KakaoAK {KEY}"}
BBOX = dict(lat=(36.0, 36.7), lng=(127.1, 127.7))

def keyword_daejeon(*queries):
    for q in queries:
        r = requests.get("https://dapi.kakao.com/v2/local/search/keyword.json",
                         headers=HEADERS, params={"query": q, "size": 5}, timeout=15)
        r.raise_for_status()
        for d in r.json()["documents"]:
            lat, lng = float(d["y"]), float(d["x"])
            if BBOX["lat"][0] <= lat <= BBOX["lat"][1] and BBOX["lng"][0] <= lng <= BBOX["lng"][1]:
                return lat, lng, q, d.get("place_name", "")
        time.sleep(0.2)
    return None

sites = [
    ("동구", "대전역세권 복합2구역", 1184, "정량",
     ["대전역세권 복합2구역", "대전 동구 소제동", "대전 동구 정동"]),
    ("서구", "도마변동3구역", 3446, "정량",
     ["도마변동3구역", "대전 서구 변동 재개발", "대전 서구 변동"]),
    ("중구", "은행1구역", None, "위치only",
     ["은행1구역 재개발", "대전 중구 은행동"]),
]

proxy = json.load(open("data_processed/delivery_proxy_range.json", encoding="utf-8"))
per_capita = {k: proxy[f"{k}_per_capita_2031"] for k in ("low", "mid", "high")}
HSIZE = 2.05

rows = [{"구": "유성구", "사이트명": "봉명1지구(홈플러스 유성점)", "lat": 36.358402,
         "lng": 127.354168, "세대수": 998, "데이터상태": "정밀", "데모유형": "중첩"}]
demand = {}
for gu, name, units, status, queries in sites:
    hit = keyword_daejeon(*queries)
    if hit is None:
        rows.append({"구": gu, "사이트명": name, "lat": "", "lng": "", "세대수": units or "",
                     "데이터상태": "미확인", "데모유형": "발생-only"})
        print(f"{name}: 지오코딩 실패 — 수작업 확인 필요")
        continue
    lat, lng, used_q, place = hit
    rows.append({"구": gu, "사이트명": name, "lat": lat, "lng": lng,
                 "세대수": units if units else "", "데이터상태": status,
                 "데모유형": "발생-only"})
    print(f"{name}: ({lat:.6f}, {lng:.6f}) ← '{used_q}' ({place})")
    if units:
        demand[name] = {k: round(units * HSIZE * v) for k, v in per_capita.items()}

rows.append({"구": "대덕구", "사이트명": "(해당 없음)", "lat": "", "lng": "", "세대수": "",
             "데이터상태": "미확인",
             "데모유형": "해당없음 — 규모기준(threshold) 초과 대규모 재개발 사이트가 확인되지 않음"})

pd.DataFrame(rows).to_csv("data_processed/expansion_demo_sites.csv",
                          index=False, encoding="utf-8-sig")
json.dump({"chain": "세대수 × 2.05인 × 1인당 프록시(2031 low/mid/high) — "
                    "[확인 필요] 차량 환산계수 미확보(건/년 단위)",
           "annual_demand_건": demand},
          open("data_processed/expansion_demo_demand.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"저장: expansion_demo_sites.csv ({len(rows)}행) + expansion_demo_demand.json")
print("발생-only 연간 수요(건):", demand)
