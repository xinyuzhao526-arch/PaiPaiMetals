#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
矿端公开核验台 · 交易所库存自动抓取

来源（均为公开页面）：
  - LME 库存：westmetall.com 公开镜像表（LME 官网对本类请求返回 403，故使用公开镜像）
  - SHFE 期货仓单：上海期货交易所官网每日仓单公布页

输出：data/stocks.json

合规说明：仅抓取交易所公开数据；不抓取任何会员制 / 付费页面。

用法：
  python3 scripts/fetch_stocks.py --out data/stocks.json
  python3 scripts/fetch_stocks.py --shfe-date 20260922
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
    "Cu": ("LME_Cu_stock", "LME Copper stock"),
    "Al": ("LME_Al_stock", "LME Aluminium stock"),
    "Zn": ("LME_Zn_stock", "LME Zinc stock"),
    "Pb": ("LME_Pb_stock", "LME Lead stock"),
    "Ni": ("LME_Ni_stock", "LME Nickel stock"),
    "Sn": ("LME_Sn_stock", "LME Tin stock"),
}
SHFE_NAMES = {"Cu": "铜", "Al": "铝", "Zn": "锌", "Pb": "铅", "Ni": "镍", "Sn": "锡"}
SHFE_URL = "https://www.shfe.com.cn/data/tradedata/future/stockdata/dailystock_{d}/ZH/all.html"


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


def parse_num(s):
    s = (s or "").replace(",", "").replace(" ", " ").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], 1)}


def parse_date_en(s):
    """'22. September 2026' -> '2026-09-22'"""
    s = (s or "").replace(".", " ")
    m = re.match(r"\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s.strip())
    if not m:
        return None
    d, mon, y = m.groups()
    if mon not in _MONTHS:
        return None
    return "%04d-%02d-%02d" % (int(y), _MONTHS[mon], int(d))


def fetch_lme():
    out = {}
    for metal, (field, _label) in LME_FIELDS.items():
        url = "https://www.westmetall.com/en/markdaten.php?action=table&field=%s" % field
        try:
            raw = get(url).decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            print("  [warn] LME %s 抓取失败: %s" % (metal, e), file=sys.stderr)
            continue
        rows = re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", raw, re.I)
        got = None
        for row in rows:
            cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                     for c in re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row, re.I)]
            if len(cells) < 2 or cells[0].lower() == "date":
                continue
            day = parse_date_en(cells[0])
            val = parse_num(cells[1])
            if day and val is not None:
                got = (day, val)
                break
        if got:
            day, tonnes = got
            out[metal] = {"date": day, "t": tonnes, "kt": round(tonnes / 1000.0, 3)}
            print("  LME %s: %s %s t = %s kt" % (metal, day, tonnes, out[metal]["kt"]))
    return out


def shfe_lines(raw_html):
    txt = html.unescape(re.sub(r"<[^>]+>", "\n", raw_html))
    return [l.strip() for l in txt.split("\n") if l.strip()]


def fetch_shfe(start=None, back=10):
    """自指定日向下回退，取最新可用仓单公布日"""
    start = start or dt.date.today()
    for k in range(back):
        d = start - dt.timedelta(days=k)
        ds = d.strftime("%Y%m%d")
        try:
            raw = get(SHFE_URL.format(d=ds), tries=1).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
        if "总计" not in raw:
            continue
        lines = shfe_lines(raw)
        out = {}
        for metal, cn in SHFE_NAMES.items():
            if cn not in lines:
                continue
            i = lines.index(cn)
            seg = lines[i:i + 500]
            tot = None
            for k2, l in enumerate(seg):
                if l == "总计":
                    if k2 + 1 < len(seg):
                        tot = parse_num(seg[k2 + 1])
                    break
            if tot is not None:
                out[metal] = {"date": d.isoformat(), "t": tot, "kt": round(tot / 1000.0, 3)}
                print("  SHFE %s: %s %s t = %s kt" % (metal, d.isoformat(), tot, out[metal]["kt"]))
        if out:
            return d.isoformat(), out
    return None, {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/stocks.json")
    ap.add_argument("--shfe-date", default=None, help="指定仓单日 YYYYMMDD（默认自动回退找最新）")
    args = ap.parse_args()

    print("[1/2] LME 库存（westmetall 公开镜像）")
    lme = fetch_lme()
    print("[2/2] SHFE 期货仓单（上期所官网）")
    start = dt.datetime.strptime(args.shfe_date, "%Y%m%d").date() if args.shfe_date else None
    shfe_date, shfe = fetch_shfe(start=start)

    lme_date = max([v["date"] for v in lme.values()], default=None)
    as_of = max([x for x in [lme_date, shfe_date] if x] or [dt.date.today().isoformat()])

    payload = {
        "schema": 1,
        "as_of": as_of,
        "generated_at": dt.datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "note": "交易所公开库存：LME 经 westmetall 公开镜像；SHFE 取官网每日仓单。仅公开数据。",
        "sources": {
            "LME": "https://www.westmetall.com/en/markdaten.php?action=table&field=LME_{M}_stock",
            "SHFE": SHFE_URL.replace("{d}", "YYYYMMDD"),
        },
        "LME": lme,
        "SHFE": shfe,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("[ok] 写入 %s · as_of=%s · LME %d 项 · SHFE %d 项"
          % (args.out, as_of, len(lme), len(shfe)))


if __name__ == "__main__":
    main()
