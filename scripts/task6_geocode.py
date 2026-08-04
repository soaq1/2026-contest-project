# -*- coding: utf-8 -*-
"""Task 6: 카카오 API 일괄 지오코딩 → output/shock_and_hub_coords.csv

KAKAO_API_KEY 환경변수가 없으면 API 호출(6-1/6-2/6-3)은 건너뛰고
'지오코딩 대기' 상태로 행을 남긴다. 키 설정 후 재실행하면 채워진다.
"""
import os, time, json
import requests
import pandas as pd

KAKAO_KEY = os.environ.get("KAKAO_API_KEY")
HEADERS = {"Authorization": f"KakaoAK {KAKAO_KEY}"} if KAKAO_KEY else None

def kakao_keyword(query):
    r = requests.get("https://dapi.kakao.com/v2/local/search/keyword.json",
                     headers=HEADERS, params={"query": query, "size": 1}, timeout=15)
    r.raise_for_status()
    docs = r.json()["documents"]
    return docs[0] if docs else None

def kakao_address(query):
    r = requests.get("https://dapi.kakao.com/v2/local/search/address.json",
                     headers=HEADERS, params={"query": query}, timeout=15)
    r.raise_for_status()
    docs = r.json()["documents"]
    return docs[0] if docs else None

rows = []  # dicts: 구분, 이름, 주소, lat, lng, 비고

# ── 6-1. 트램 2호선 15개 지점 (키워드 검색, "대전 " 접두)
tram_points = ["연축지구", "대덕경찰서", "한전 대전본부", "오문창순대국밥", "수정타운아파트",
               "정부청사역", "국립중앙과학관", "다솔아파트", "대전시립박물관", "어린이재활병원",
               "가수원교", "도마삼거리", "버드내네거리", "보문교", "우송대학교"]
for name in tram_points:
    if not KAKAO_KEY:
        rows.append({"구분": "트램", "이름": name, "주소": "", "lat": "", "lng": "",
                     "비고": "지오코딩 대기(KAKAO_API_KEY 미설정)"})
        continue
    try:
        doc = kakao_keyword(f"대전 {name}")
        if doc:
            rows.append({"구분": "트램", "이름": name, "주소": doc.get("road_address_name") or doc.get("address_name", ""),
                         "lat": doc["y"], "lng": doc["x"], "비고": f"키워드검색: {doc.get('place_name','')}"})
        else:
            rows.append({"구분": "트램", "이름": name, "주소": "", "lat": "", "lng": "", "비고": "검색결과 없음 - 수작업 확인"})
    except Exception as e:
        rows.append({"구분": "트램", "이름": name, "주소": "", "lat": "", "lng": "", "비고": f"오류: {e}"})
    time.sleep(0.2)

# ── 6-2. 물류창고 대전 소재지 (주소 검색)
df = pd.read_excel("물류창고정보_260717.xls")
daejeon = df[df["소재지"].astype(str).str.contains("대전")].copy()
print(f"물류창고 대전 필터: {len(daejeon)}건")
for _, r in daejeon.iterrows():
    name, addr = str(r["상호명"]), str(r["소재지"])
    if not KAKAO_KEY:
        rows.append({"구분": "물류창고", "이름": name, "주소": addr, "lat": "", "lng": "",
                     "비고": "지오코딩 대기(KAKAO_API_KEY 미설정)"})
        continue
    try:
        doc = kakao_address(addr)
        if doc:
            rows.append({"구분": "물류창고", "이름": name, "주소": addr, "lat": doc["y"], "lng": doc["x"], "비고": ""})
        else:
            rows.append({"구분": "물류창고", "이름": name, "주소": addr, "lat": "", "lng": "", "비고": "좌표 없음 - 수작업 확인"})
    except Exception as e:
        rows.append({"구분": "물류창고", "이름": name, "주소": addr, "lat": "", "lng": "", "비고": f"오류: {e}"})
    time.sleep(0.2)

# ── 6-3. 세이백화점 3개 지점 (주소 검색)
sei = [("세이백화점 본점", "대전 중구 계백로 1700"),
       ("세이백화점 탄방점", "대전 서구 문정로 85"),
       ("세이백화점 대정점", "대전 유성구 대정로 2")]
for name, addr in sei:
    if not KAKAO_KEY:
        rows.append({"구분": "세이백화점", "이름": name, "주소": addr, "lat": "", "lng": "",
                     "비고": "지오코딩 대기(KAKAO_API_KEY 미설정)"})
        continue
    try:
        doc = kakao_address(addr)
        if doc:
            rows.append({"구분": "세이백화점", "이름": name, "주소": addr, "lat": doc["y"], "lng": doc["x"], "비고": ""})
        else:
            rows.append({"구분": "세이백화점", "이름": name, "주소": addr, "lat": "", "lng": "", "비고": "좌표 없음 - 수작업 확인"})
    except Exception as e:
        rows.append({"구분": "세이백화점", "이름": name, "주소": addr, "lat": "", "lng": "", "비고": f"오류: {e}"})
    time.sleep(0.2)

# ── 6-4. 홈플러스 6개 지점 (좌표 기확보, 그대로 통합)
homeplus = [
    ("홈플러스 유성점", 36.358402, 127.354168, "매각 확정, 2026 하반기 폐점 예정"),
    ("홈플러스 동대전점", 36.353819, 127.437369, "2022년 폐점"),
    ("홈플러스익스프레스 봉명점", 36.354993, 127.336182, "정상영업, 충격지점 아님"),
    ("홈플러스 가오점", 36.306970, 127.457984, "전국 임시휴업 중, 리스크 시나리오"),
    ("홈플러스 문화점", 36.320292, 127.407693, "2026년 1월 폐점"),
    ("홈플러스 서대전점", 36.313703, 127.319001, "2024년 폐점"),
]
for name, lat, lng, note in homeplus:
    rows.append({"구분": "홈플러스", "이름": name, "주소": "", "lat": lat, "lng": lng, "비고": note})

out = pd.DataFrame(rows, columns=["구분", "이름", "주소", "lat", "lng", "비고"])
out.to_csv("output/shock_and_hub_coords.csv", index=False, encoding="utf-8-sig")

n_ok = (out["lat"].astype(str) != "").sum()
n_pending = out["비고"].astype(str).str.contains("대기").sum()
n_fail = out["비고"].astype(str).str.contains("수작업|오류").sum()
print(f"총 {len(out)}행 저장 | 좌표확보 {n_ok} | 대기 {n_pending} | 실패/수작업 {n_fail}")
if not KAKAO_KEY:
    print("NOTE: KAKAO_API_KEY 미설정 - 6-1/6-2/6-3은 '지오코딩 대기' 상태")
