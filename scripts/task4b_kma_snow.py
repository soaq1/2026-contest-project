# -*- coding: utf-8 -*-
"""Task 4b: 기상청 적설관측 일자료(kma_snow_day.php) → output/kma_snow.json

실측 확정 명세 (2026-07-18):
- 필수 파라미터는 sd=tot(최심적설) / sd=day(최심신적설) — help=1 문서에 없고,
  obs=/snow=/item=/mode= 등은 전부 무시됨(빈 응답). sd= 없이는 항상 0행
- tm_st(시작)/tm(끝): YYYYMMDDHHMI. stn/stn_id 파라미터는 **무시되고 항상
  전국(약 560지점/일)이 반환**되므로 클라이언트에서 지점 필터 필요
- 무강설일도 0.0으로 행이 존재(일 단위 전 지점 완전 커버)
- 응답: EUC-KR, #주석 + CSV — TM,STN_ID,STN_KO,LON,LAT,STN_SP,SD(cm),HH:MI,=
- 3.5년 전범위 1회 호출은 타임아웃 → 분기 단위 청크(1분기 전국 약 5.1만행, ~18초)
"""
import os, sys, time, json
import requests

AUTH_KEY = os.environ.get("KMA_AUTH_KEY")
if not AUTH_KEY:
    sys.exit("KMA_AUTH_KEY 미설정")
URL = "https://apihub.kma.go.kr/api/typ01/url/kma_snow_day.php"
STATIONS = {133: "대전", 378: "정림", 642: "오월드", 643: "세천", 648: "장동"}
SD_TYPES = {"tot": "최심적설(cm)", "day": "최심신적설(cm)"}

def quarters():
    """2023-01-01 ~ 2026-07-17 분기 청크 (겹침 없음)"""
    qs = []
    for y in (2023, 2024, 2025):
        for m1, m2, d2 in ((1, 3, 31), (4, 6, 30), (7, 9, 30), (10, 12, 31)):
            qs.append((f"{y}{m1:02d}010000", f"{y}{m2:02d}{d2}2300"))
    qs += [("202601010000", "202603312300"), ("202604010000", "202606302300"),
           ("202607010000", "202607172300")]
    return qs

def fetch(tm_st, tm, sd):
    for attempt in range(3):
        try:
            r = requests.get(URL, params={"tm_st": tm_st, "tm": tm, "sd": sd,
                                          "authKey": AUTH_KEY}, timeout=120)
            r.raise_for_status()
            rows = []
            for line in r.content.decode("euc-kr").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                f = [x.strip() for x in line.split(",")]
                stn = int(f[1])
                if stn not in STATIONS:
                    continue
                rows.append({"date": f[0], "stn": stn, "stn_name": f[2],
                             "lon": float(f[3]), "lat": float(f[4]),
                             "sd_type": sd, "val_cm": float(f[6]), "peak_time": f[7]})
            return rows
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  재시도 {attempt+1}: {e}", flush=True)
            time.sleep(5)

records = []
for sd in SD_TYPES:
    for tm_st, tm in quarters():
        rows = fetch(tm_st, tm, sd)
        records.extend(rows)
        print(f"sd={sd} {tm_st[:8]}~{tm[:8]}: 대전권 {len(rows)}행", flush=True)
        time.sleep(0.5)

# 지점별 커버리지 요약 (적설 관측망에 없는 지점 확인용)
cov = {}
for r in records:
    cov.setdefault((r["stn"], r["sd_type"]), 0)
    cov[(r["stn"], r["sd_type"])] += 1
print("\n지점별 일수:")
for stn, name in STATIONS.items():
    print(f"  {stn} {name}: tot={cov.get((stn,'tot'),0)}일, day={cov.get((stn,'day'),0)}일")

n_snow = sum(1 for r in records if r["val_cm"] > 0)
out = {"meta": {"source": "기상청 API허브 kma_snow_day.php (적설관측 일자료)",
                "collected_at": "2026-07-18",
                "period": "2023-01-01 ~ 2026-07-17",
                "stations": {str(k): v for k, v in STATIONS.items()},
                "sd_types": SD_TYPES,
                "note": "stn 파라미터가 서버에서 무시되어 전국 수신 후 로컬 필터. "
                        "무강설일은 0.0으로 존재. 적설 관측망에 없는 지점은 행 자체가 없음",
                "n_records": len(records), "n_snow_days": n_snow},
       "records": records}
with open("output/kma_snow.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print(f"\n총 {len(records)}건 저장 | 적설>0 관측 {n_snow}건")
