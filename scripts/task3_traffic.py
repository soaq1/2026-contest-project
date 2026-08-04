# -*- coding: utf-8 -*-
import os, sys, requests, xmltodict, json, time

url = "https://apis.data.go.kr/6300000/rest/getTrafficInfoAll"
key = os.environ.get("DATA_GO_KR_SERVICE_KEY")
if not key:
    sys.exit("DATA_GO_KR_SERVICE_KEY 미설정")
all_records = []
total_cnt = None

for page in range(1, 16):
    for attempt in range(3):
        try:
            res = requests.get(url, params={"serviceKey": key, "type": "xml", "pageNo": page, "numOfRows": 1000}, timeout=60)
            parsed = xmltodict.parse(res.text)
            header = parsed["response"]["header"]
            if header["resultCode"] != "00":
                raise RuntimeError(f"resultCode={header['resultCode']} msg={header.get('resultMsg')}")
            total_cnt = int(header["totalCnt"])
            items = parsed["response"]["body"]["TRAFFIC-LIST"]["TRAFFIC"]
            if isinstance(items, dict):
                items = [items]
            all_records.extend(items)
            break
        except Exception as e:
            print(f"page {page} attempt {attempt+1} failed: {e}")
            time.sleep(1)
    else:
        raise SystemExit(f"FAIL: page {page} could not be fetched")
    print(f"page {page}: cumulative {len(all_records)}")
    time.sleep(0.2)

print(f"collected {len(all_records)} / totalCnt {total_cnt}")
uniq = len({r["linkID"] for r in all_records})
print(f"unique linkID: {uniq}")

with open("output/daejeon_traffic_links_full.json", "w", encoding="utf-8") as f:
    json.dump(all_records, f, ensure_ascii=False)
print("saved output/daejeon_traffic_links_full.json")
