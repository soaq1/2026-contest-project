# -*- coding: utf-8 -*-
"""Task F: 링크부하 vs 관측혼잡 검증 → data_processed/flow_validation.json

- 추정 부하: edge_loads_baseline.json (OD 최단경로 적재, 대/일)
- 관측: daejeon_traffic_links_full.json의 congestion(1~4)·speed
- 링크에 좌표가 없어 **도로명 단위**로만 비교 가능 [한계]:
  OSM 간선 부하를 도로명별 평균 → 링크 congestion 도로명별 평균과 스피어만 상관
- 상관 약한 구간의 도로등급/특성 보고 (Task B 한계와의 일치 여부 확인)
"""
import json, sys
from collections import defaultdict
import numpy as np
import osmnx as ox

sys.stdout.reconfigure(encoding="utf-8")

def spearman(a, b):
    def rank(x):
        order = np.argsort(x)
        r = np.empty(len(x)); r[order] = np.arange(len(x), dtype=float)
        # 동률 평균 순위
        vals, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
        cum = np.cumsum(cnt) - cnt
        avg = cum + (cnt - 1) / 2.0
        return avg[inv]
    ra, rb = rank(np.asarray(a)), rank(np.asarray(b))
    ra -= ra.mean(); rb -= rb.mean()
    den = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / den) if den else float("nan")

G = ox.load_graphml("data_processed/daejeon_weighted.graphml")
loads = json.load(open("data_processed/edge_loads_baseline.json", encoding="utf-8"))

# OSM 간선 → 도로명별 부하(평균)와 등급
name_load, name_hw = defaultdict(list), {}
edge_by_uv = defaultdict(list)
for u, v, k, d in G.edges(keys=True, data=True):
    edge_by_uv[f"{u}_{v}"].append(d)
for uv, w in loads.items():
    for d in edge_by_uv.get(uv, []):
        names = d.get("name")
        if names is None:
            continue
        for nm in (names if isinstance(names, list) else [names]):
            key = str(nm).replace(" ", "")
            name_load[key].append(w)
            hw = d.get("highway")
            name_hw[key] = hw if isinstance(hw, str) else "/".join(hw)
name_load_m = {k: float(np.mean(v)) for k, v in name_load.items()}

links = json.load(open("data_processed/daejeon_traffic_links_full.json", encoding="utf-8"))
obs_cong, obs_speed = defaultdict(list), defaultdict(list)
for r in links:
    nm = str(r.get("roadName", "")).replace(" ", "")
    if not nm:
        continue
    try:
        obs_cong[nm].append(float(r["congestion"]))
        obs_speed[nm].append(float(r["speed"]))
    except (KeyError, TypeError, ValueError):
        pass
obs_cong_m = {k: float(np.mean(v)) for k, v in obs_cong.items()}
obs_speed_m = {k: float(np.mean(v)) for k, v in obs_speed.items()}

common = sorted(set(name_load_m) & set(obs_cong_m))
fl = [name_load_m[k] for k in common]
cg = [obs_cong_m[k] for k in common]
sp = [obs_speed_m[k] for k in common]
rho_c, rho_s = spearman(fl, cg), spearman(fl, sp)
print(f"공통 도로명 {len(common)}개 | 스피어만: 부하-혼잡 {rho_c:.3f} / 부하-속도 {rho_s:.3f}")

# 등급별 분해
by_class = defaultdict(list)
for k in common:
    by_class[name_hw.get(k, "?").split("/")[0]].append(k)
class_rho = {}
for cls, ks in sorted(by_class.items(), key=lambda x: -len(x[1])):
    if len(ks) >= 8:
        class_rho[cls] = {"n_roads": len(ks),
                          "rho_congestion": round(spearman([name_load_m[k] for k in ks],
                                                           [obs_cong_m[k] for k in ks]), 3)}
print("등급별 부하-혼잡 상관:", {c: v["rho_congestion"] for c, v in class_rho.items()})

# 부하 총량 중 관측 커버리지 (실측 링크가 있는 도로명 위 부하 비율)
tot_load = sum(loads.values())
cov_load = 0.0
for uv, w in loads.items():
    for d in edge_by_uv.get(uv, []):
        if d.get("tt_source") == "traffic_link":
            cov_load += w
            break
print(f"부하 중 실측링크 매칭 간선 비율: {cov_load/tot_load*100:.1f}%")

out = {"meta": {"limitation": "[한계] 교통링크에 좌표가 없어 도로명 단위 평균으로만 "
                              "비교 — 링크 단위 검증 불가",
                "congestion_direction": "[검증됨] 역산 확인: 1=원활(평균 42.7km/h)/"
                    "2=서행(20.2)/3=정체(9.7), speed와 피어슨 -0.503 — 숫자 클수록 정체. "
                    "따라서 부하-혼잡 상관의 부호 해석은 재해석 불필요(음수 = 부하가 "
                    "덜 정체된 도로에 몰림)",
                "n_common_roads": len(common)},
       "spearman_load_vs_congestion": round(rho_c, 3),
       "spearman_load_vs_speed": round(rho_s, 3),
       "by_highway_class": class_rho,
       "load_share_on_matched_edges_pct": round(cov_load / tot_load * 100, 1)}
json.dump(out, open("data_processed/flow_validation.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("저장: data_processed/flow_validation.json")
