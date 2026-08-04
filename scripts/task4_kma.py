# -*- coding: utf-8 -*-
"""Task 4: 기상청 API허브 지상·AWS 일통계(sfc_aws_day.php) → output/kma_observations.json

실측 확정 명세 (2026-07-18):
- tm1/tm2: YYYYMMDD (연 단위 장기 범위 1회 호출 가능, 1년=365행 확인)
- obs: 소문자 통계코드. 작동 확인: ta_max, ta_min, rn_day, ws_max
  (ta_avg/hm_avg/ws_avg/sd_* 등은 0행 반환 — 이 엔드포인트에서 미제공)
- 응답: EUC-KR 텍스트, '#' 주석 제외 CSV — TM,STN,LON,LAT,HT,VAL,지점명=
- 대전권 지점(전 지점 조회 후 경계상자 실측): 133 대전(ASOS), 378 정림,
  642 오월드, 643 세천, 648 장동 (세종·계룡·청남대는 대전 밖이라 제외)
"""
import os, sys, time, json
import requests

AUTH_KEY = os.environ.get("KMA_AUTH_KEY")
if not AUTH_KEY:
    sys.exit("KMA_AUTH_KEY 미설정")
URL = "https://apihub.kma.go.kr/api/typ01/url/sfc_aws_day.php"

STATIONS = {133: "대전", 378: "정림", 642: "오월드", 643: "세천", 648: "장동"}
OBS_CODES = {"ta_max": "일최고기온(C)", "ta_min": "일최저기온(C)",
             "rn_day": "일강수량(mm)", "ws_max": "일최대풍속(m/s)"}
PERIODS = [("20230101", "20231231"), ("20240101", "20241231"),
           ("20250101", "20251231"), ("20260101", "20260717")]
EXPECTED_DAYS = 365 + 366 + 365 + 198  # 1,294일

def fetch(tm1, tm2, obs, stn):
    for attempt in range(3):
        try:
            r = requests.get(URL, params={"tm1": tm1, "tm2": tm2, "obs": obs,
                                          "stn": stn, "disp": 1, "authKey": AUTH_KEY},
                             timeout=30)
            r.raise_for_status()
            rows = []
            for line in r.content.decode("euc-kr").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                f = line.split(",")
                rows.append({"date": f[0], "stn": int(f[1]), "lon": float(f[2]),
                             "lat": float(f[3]), "obs": obs, "val": float(f[5]),
                             "stn_name": f[6].rstrip("=")})
            return rows
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  재시도 {attempt+1}: {e}")
            time.sleep(2)

records = []
for stn, name in STATIONS.items():
    for obs in OBS_CODES:
        got = 0
        for tm1, tm2 in PERIODS:
            rows = fetch(tm1, tm2, obs, stn)
            records.extend(rows)
            got += len(rows)
            time.sleep(0.3)
        flag = "" if got == EXPECTED_DAYS else f"  <-- 기대 {EXPECTED_DAYS}일과 불일치"
        print(f"{stn} {name} {obs}: {got}일{flag}")

n_missing = sum(1 for r in records if r["val"] <= -9)  # KMA 결측 관례(-9, -99 등)
out = {"meta": {"source": "기상청 API허브 sfc_aws_day.php (지상 및 AWS 일통계)",
                "collected_at": "2026-07-18",
                "period": "2023-01-01 ~ 2026-07-17",
                "stations": {str(k): v for k, v in STATIONS.items()},
                "obs_codes": OBS_CODES,
                "missing_convention": "val <= -9 는 결측",
                "n_records": len(records), "n_missing": n_missing},
       "records": records}
with open("output/kma_observations.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print(f"\n총 {len(records)}건 저장 (기대 {EXPECTED_DAYS * len(STATIONS) * len(OBS_CODES)}건) | 결측 표기 {n_missing}건")
