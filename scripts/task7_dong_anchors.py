# -*- coding: utf-8 -*-
"""Task 7: 행정동 인구 가중치 앵커 테이블 → data_processed/dong_population_anchors.csv

다지점 분해(목적지 앵커)용. 주민등록 인구 CSV(cp949)에서 행정동 82개를 추출해
카카오 키워드 검색으로 대표 좌표를 얻고, destination_weight = 동 인구/대전 전체 인구.
- 요약행(시/구)은 '괄호 앞 공백' 유무로 구분하며 검증에만 사용
- 검색 1순위: "대전 {구} {동명}", 좌표가 대전 범위 밖이거나 0건이면
  "대전 {구} {동명} 행정복지센터"로 폴백
"""
import os, re, sys, time
import requests
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
KEY = os.environ.get("KAKAO_API_KEY")
if not KEY:
    sys.exit("KAKAO_API_KEY 미설정")
HEADERS = {"Authorization": f"KakaoAK {KEY}"}
BBOX = dict(lat=(36.0, 36.7), lng=(127.1, 127.7))

def in_bbox(lat, lng):
    return BBOX["lat"][0] <= lat <= BBOX["lat"][1] and BBOX["lng"][0] <= lng <= BBOX["lng"][1]

def keyword_first_in_daejeon(query):
    r = requests.get("https://dapi.kakao.com/v2/local/search/keyword.json",
                     headers=HEADERS, params={"query": query, "size": 5}, timeout=15)
    r.raise_for_status()
    for d in r.json()["documents"]:
        if in_bbox(float(d["y"]), float(d["x"])):
            return d
    return None

df = pd.read_csv("data_raw/주민등록인구및세대현황_대전광역시_2026_06.csv", encoding="cp949")
df = df.dropna(subset=["행정구역"])

def to_int(s):
    return int(str(s).replace(",", ""))

city_total = None
gu_totals = {}
dongs = []
for _, r in df.iterrows():
    name = str(r["행정구역"])
    m = re.match(r"^대전광역시\s+(.*?)(\s*)\((\d+)\)", name)
    if not m:
        continue
    label, gap, code = m.group(1).strip(), m.group(2), m.group(3)
    pop, hh = to_int(r["2026년06월_총인구수"]), to_int(r["2026년06월_세대수"])
    if label == "":  # 시 전체 행 (\s+가 공백을 전부 소비해 gap이 비는 경우 포함)
        city_total = pop
    elif gap:        # 괄호 앞 공백 = 구 요약행
        gu_totals[label] = pop
    else:            # 행정동 행
        gu, dong = label.split(" ", 1)
        dongs.append({"구": gu, "행정동": dong, "총인구수": pop, "세대수": hh})

print(f"파싱: 시 전체 {city_total:,} | 구 {len(gu_totals)}개 | 행정동 {len(dongs)}개")
assert city_total == 1_442_034 and len(gu_totals) == 5 and len(dongs) == 82
dong_sum = sum(d["총인구수"] for d in dongs)
gu_sum = sum(gu_totals.values())
print(f"검증(요약행 대조): 구 합계 {gu_sum:,} / 동 합계 {dong_sum:,} / 시 전체 {city_total:,}")

rows, fallback_used, fail = [], [], []
for d in dongs:
    q1 = f"대전 {d['구']} {d['행정동']}"
    doc = keyword_first_in_daejeon(q1)
    if doc is None:
        doc = keyword_first_in_daejeon(f"{q1} 행정복지센터")
        if doc:
            fallback_used.append(d["행정동"])
    if doc is None:
        fail.append(d["행정동"])
        rows.append({**d, "lat": "", "lng": ""})
    else:
        rows.append({**d, "lat": float(doc["y"]), "lng": float(doc["x"])})
    time.sleep(0.15)

out = pd.DataFrame(rows)
out["destination_weight"] = out["총인구수"] / city_total
out = out[["구", "행정동", "lat", "lng", "총인구수", "세대수", "destination_weight"]]
out.to_csv("data_processed/dong_population_anchors.csv", index=False, encoding="utf-8-sig")

w_sum = out["destination_weight"].sum()
n_in = sum(1 for _, r in out.iterrows()
           if r["lat"] != "" and in_bbox(float(r["lat"]), float(r["lng"])))
print(f"\n저장: {len(out)}행 | weight 합 = {w_sum:.6f}")
print(f"대전 범위 내 좌표: {n_in}/82 | 폴백 사용: {len(fallback_used)}건 {fallback_used}")
if fail:
    print(f"실패(좌표 없음): {fail}")
    sys.exit(1)
