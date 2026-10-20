#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
矿端公开核验台 · 库存历史回补

用途：把「交易所公开库存」从单点快照扩成时间序列，供页面画折线。
  - LME：westmetall 公开镜像表本身就是一张按日的序列表（约 200+ 个交易日），一次请求拿全。
  - SHFE：上期所官网按日公布仓单，逐日取，只走工作日。

输出：data/stocks_history.json
  {"schema":1,"unit":"t","generated_at":...,"sources":{...},
   "LME":{"Al":[["2026-01-02",509250.0], ...]},
   "SHFE":{"Al":[["2026-09-18",184402.0], ...]}}

合规：只访问交易所公开页面与其公开镜像；不碰任何会员制/付费页面。
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (compatible; MineDeskBot/1.0; public-data-only)"
TIMEOUT = 30

LME_FIELDS = {
    "Cu": "LME_Cu_stock", "Al": "LME_Al_stock", "Zn": "LME_Zn_stock",
    "Pb": "LME_Pb_stock", "Ni": "LME_Ni_stock", "Sn": "LME_Sn_stock",
}
SHFE_NAMES = {"Cu": "铜", "Al": "铝", "Zn": "锌", "Pb": "铅", "Ni": "镍", "Sn": "锡"}
WM_URL = "https://www.westmetall.com/en/markdaten.php?action=table&field={f}"
SHFE_URL = "https://www.shfe.com.cn/data/tradedata/future/stockdata/dailystock_{d}/ZH/all.html"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}


def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 2 * i)
    raise last


def num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", (s or "").replace(",", "").replace(" ", ""))
    return float(m.group(0)) if m else None


def wm_date(s):
    """'19. October 2026' -> '2026-10-19'"""
    m = re.match(r"\s*(\d{1,2})\.\s*([A-Za-z]+)\s+(\d{4})", s or "")
    if not m:
        return None
    mo = MONTHS.get(m.group(2))
    if not mo:
        return None
    return dt.date(int(m.group(3)), mo, int(m.group(1))).isoformat()


def fetch_lme(metal):
    field = LME_FIELDS[metal]
    raw = get(WM_URL.format(f=field)).decode("utf-8", "ignore")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", raw, re.S)
    out = []
    for r in rows:
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        if len(cells) < 2:
            continue
        d = wm_date(cells[0])
        v = num(cells[1])
        if d and v is not None:
            out.append([d, v])
    out.sort(key=lambda x: x[0])
    # 去重（同日重复行）
    ded, seen = [], set()
    for d, v in out:
        if d not in seen:
            seen.add(d)
            ded.append([d, v])
    return ded


def shfe_lines(raw_html):
    txt = html.unescape(re.sub(r"<[^>]+>", "\n", raw_html))
    return [l.strip() for l in txt.split("\n") if l.strip()]


def fetch_shfe_day(d):
    ds = d.strftime("%Y%m%d")
    try:
        raw = get(SHFE_URL.format(d=ds), tries=1).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return None
    if "总计" not in raw:
        return None
    lines = shfe_lines(raw)
    out = {}
    for metal, cn in SHFE_NAMES.items():
        if cn not in lines:
            continue
        i = lines.index(cn)
        seg = lines[i:i + 500]
        for k, l in enumerate(seg):
            if l == "总计":
                if k + 1 < len(seg):
                    v = num(seg[k + 1])
                    if v is not None:
                        out[metal] = v
                break
    return out or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/stocks_history.json")
    ap.add_argument("--shfe-days", type=int, default=95, help="SHFE 回溯的自然日数")
    ap.add_argument("--sleep", type=float, default=1.0, help="SHFE 逐日请求间隔（秒）")
    ap.add_argument("--merge", action="store_true", help="与已有文件合并（保留旧点）")
    a = ap.parse_args()

    hist = {"schema": 1, "unit": "t", "LME": {}, "SHFE": {}}
    if a.merge and os.path.exists(a.out):
        try:
            with open(a.out, encoding="utf-8") as f:
                old = json.load(f)
            for k in ("LME", "SHFE"):
                for m, arr in (old.get(k) or {}).items():
                    hist[k][m] = [list(x) for x in arr]
        except Exception:  # noqa: BLE001
            pass

    print("[1/2] LME（westmetall 公开镜像，整表一次取回）")
    for metal in LME_FIELDS:
        try:
            arr = fetch_lme(metal)
        except Exception as e:  # noqa: BLE001
            print("   LME %s 失败：%s" % (metal, e))
            continue
        if not arr:
            print("   LME %s 无数据" % metal)
            continue
        hist["LME"][metal] = arr
        print("   LME %s: %d 点  %s → %s" % (metal, len(arr), arr[0][0], arr[-1][0]))

    print("[2/2] SHFE（上期所官网逐日仓单，回溯 %d 自然日）" % a.shfe_days)
    today = dt.date.today()
    got = fail = 0
    for k in range(a.shfe_days):
        d = today - dt.timedelta(days=k)
        if d.weekday() >= 5:
            continue
        res = fetch_shfe_day(d)
        if not res:
            fail += 1
            continue
        got += 1
        iso = d.isoformat()
        for metal, v in res.items():
            hist["SHFE"].setdefault(metal, []).append([iso, v])
        if got % 10 == 0:
            print("   ... 已取 %d 个交易日（最新 %s）" % (got, iso))
        time.sleep(a.sleep)

    for k in ("LME", "SHFE"):
        for m in hist[k]:
            hist[k][m].sort(key=lambda x: x[0])
            ded, seen = [], set()
            for d, v in hist[k][m]:
                if d not in seen:
                    seen.add(d)
                    ded.append([d, v])
            hist[k][m] = ded

    hist["generated_at"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    hist["sources"] = {
        "LME": WM_URL.format(f="LME_{M}_stock"),
        "SHFE": SHFE_URL.replace("{d}", "YYYYMMDD"),
    }
    hist["note"] = "交易所公开库存日序列，单位吨。LME 经 westmetall 公开镜像；SHFE 取官网每日仓单。仅公开数据。"
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))
    print("[ok] 写入 %s · LME %d 品种 · SHFE %d 品种（%d 日成功 / %d 日无数据）"
          % (a.out, len(hist["LME"]), len(hist["SHFE"]), got, fail))


if __name__ == "__main__":
    main()
