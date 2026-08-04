# -*- coding: utf-8 -*-
import os, sys, requests, xmltodict, json, time

key = os.environ.get("DATA_GO_KR_SERVICE_KEY")
if not key:
    sys.exit("DATA_GO_KR_SERVICE_KEY 미설정")
base = "https://apis.data.go.kr/B553530/GHG_LIST_02"
result = {}

for ep in ["GHG_LIST_02_01_VIEW", "GHG_LIST_02_08_VIEW"]:
    records = []
    page = 1
    total = None
    # 서버가 numOfRows를 100으로 강제 고정하고, 범위 밖 페이지는 빈 items를 반환함(실측)
    while True:
        for attempt in range(3):
            try:
                r = requests.get(f"{base}/{ep}", params={"serviceKey": key, "pageNo": page, "numOfRows": 100}, timeout=60)
                parsed = xmltodict.parse(r.text)
                body = parsed["response"]["body"]
                total = int(body["totalCount"])
                items = body["items"]["item"] if body.get("items") else []
                if isinstance(items, dict):
                    items = [items]
                break
            except Exception as e:
                print(f"{ep} page {page} attempt {attempt+1} failed: {e}")
                time.sleep(1)
        else:
            raise SystemExit(f"FAIL: {ep} page {page}")
        if not items:
            break
        records.extend(items)
        if len(records) >= total:
            break
        page += 1
        time.sleep(0.2)
    print(f"{ep}: collected {len(records)} / totalCount {total}")
    result[ep] = records

with open("output/kea_emissions.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False)
print("saved output/kea_emissions.json")
