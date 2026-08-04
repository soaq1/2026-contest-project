# -*- coding: utf-8 -*-
import os, sys, requests, json, time
from pyproj import Transformer

url = "https://data.ex.co.kr/openapi/vdsinfo/vdsList"
key = os.environ.get("EX_VDS_API_KEY")
if not key:
    sys.exit("EX_VDS_API_KEY 미설정")
all_records = []

res = requests.get(url, params={"key": key, "type": "json", "numOfRows": 99, "pageNo": 1}, timeout=30)
data = res.json()
total_pages = data["pageSize"]
total_count = data["count"]
all_records.extend(data["list"])
print(f"count={total_count}, pageSize={total_pages}")

for page in range(2, total_pages + 1):
    for attempt in range(3):
        try:
            res = requests.get(url, params={"key": key, "type": "json", "numOfRows": 99, "pageNo": page}, timeout=30)
            all_records.extend(res.json()["list"])
            break
        except Exception as e:
            print(f"page {page} attempt {attempt+1} failed: {e}")
            time.sleep(1)
    else:
        raise SystemExit(f"FAIL: page {page} could not be fetched")
    time.sleep(0.2)
    if page % 20 == 0:
        print(f"  ... page {page}/{total_pages}, records={len(all_records)}")

print(f"collected: {len(all_records)} (expected ~{total_count})")

# 좌표 변환: EPSG:5186 우선, 한국 영토 범위 검증 후 인접 좌표계 폴백
KOREA = lambda lon, lat: 124 <= lon <= 132 and 33 <= lat <= 39

def convert_ratio(epsg):
    tr = Transformer.from_crs(epsg, "EPSG:4326", always_xy=True)
    ok = 0
    sample = [r for r in all_records if r.get("grs80x") and r.get("grs80y")][:200]
    for r in sample:
        lon, lat = tr.transform(float(r["grs80x"]), float(r["grs80y"]))
        if KOREA(lon, lat):
            ok += 1
    return ok / max(len(sample), 1), tr

best_epsg, best_tr = None, None
for epsg in ["EPSG:5186", "EPSG:5185", "EPSG:5187", "EPSG:5188", "EPSG:5179"]:
    ratio, tr = convert_ratio(epsg)
    print(f"{epsg}: {ratio:.1%} of sample inside Korea bounds")
    if ratio > 0.99:
        best_epsg, best_tr = epsg, tr
        break

if best_epsg is None:
    raise SystemExit("FAIL: no candidate CRS puts coordinates inside Korea")

n_missing = 0
for r in all_records:
    if r.get("grs80x") and r.get("grs80y"):
        lon, lat = best_tr.transform(float(r["grs80x"]), float(r["grs80y"]))
        r["lon_wgs84"] = round(lon, 7)
        r["lat_wgs84"] = round(lat, 7)
    else:
        r["lon_wgs84"] = None
        r["lat_wgs84"] = None
        n_missing += 1

inside = sum(1 for r in all_records if r["lon_wgs84"] and KOREA(r["lon_wgs84"], r["lat_wgs84"]))
print(f"CRS used: {best_epsg}; converted inside-Korea: {inside}/{len(all_records)} (missing coords: {n_missing})")

with open("output/vds_installation_info.json", "w", encoding="utf-8") as f:
    json.dump(all_records, f, ensure_ascii=False)
print("saved output/vds_installation_info.json")
