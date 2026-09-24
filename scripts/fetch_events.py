#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
矿端公开核验台 · 供给事件自动抓取（方案 A：每日一次，新事件进「待确认」池）

来源：均为公开 RSS 源，仅做标题/摘要级抓取，不抓取付费或会员制页面。
输出：data/events.json —— 累积式事件池；已存在条目原样保留（含人工确认结果），只追加新条目。

分类：按标题+摘要中的品种关键词自动归到 Cu/Al/PbZn/Ni/Sn/Li/Fe；
      未命中任何品种的条目直接丢弃（不进入池子）。

用法：
  python3 scripts/fetch_events.py --out data/events.json
  python3 scripts/fetch_events.py --out data/events.json --max-keep 300
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (compatible; MineDeskBot/1.0; public-data-only)"
TIMEOUT = 25
RETRIES = 3

FEEDS = [
    ("mining-technology", "https://www.mining-technology.com/feed/"),
    ("northernminer", "https://www.northernminer.com/feed/"),
    ("australianmining", "https://www.australianmining.com.au/feed/"),
    ("im-mining", "https://im-mining.com/feed/"),
    ("mining.com", "https://www.mining.com/feed/"),  # 偶发被 CDN 拦截，失败即跳过
]

# 强关键词：命中即归类
STRONG = {
    "Cu":   ["copper", "cuprum", "codelco", "escondida", "collahuasi", "grasberg", "las bambas",
             "kansanshi", "kamoa", "quellaveco", "centinela", "oyu tolgoi", "铜"],
    "Fe":   ["iron ore", "iron-ore", "hematite", "magnetite", "pilbara", "simandou", "fortescue",
             "roy hill", "kumba", "minas-rio", "waio", "铁矿石", "铁矿"],
    "Al":   ["bauxite", "alumina", "aluminium", "aluminum", "alcoa", "rusal", "铝土矿", "氧化铝", "电解铝"],
    "Li":   ["lithium", "spodumene", "li2o", "pilgangoora", "greenbushes", "wodgina", "goulamina",
             "碳酸锂", "锂辉石", "氢氧化锂", "锂"],
    "Ni":   ["nickel", "laterite", "nornickel", "ambatovy", "saprolite", "镍"],
    "PbZn": ["zinc", "galena", "red dog", "hindustan zinc", "zinc-lead", "lead-zinc",
             "铅锌", "锌", "铅"],
    "Sn":   ["cassiterite", "timah", "minsur", "alphamin", "renison", "锡"],
}
# 噪声过滤：非事件类内容
BLOCK = ["podcast", "webinar", "listen:", "top 5", "top five", "opinion:", "video:", "quiz",
         "newsletter", "播客", "视频", "直播"]
# 说明：standalone 的 lead / tin / iron 极易当动词误命中（lead the project 等），故不作关键词；
#       铅锌/锡/铁 另由 zinc-lead、lead-zinc、铅锌、锡、铁矿石、铁矿 等强词覆盖。
# 强组合词：命中即归类
STRONG_COMBO = {
    "PbZn": ["lead-zinc", "zinc-lead", "lead and zinc", "lead & zinc"],
    "Sn":   ["tin mine", "tin mining", "tin concentrate", "tin smelter"],
    "Fe":   ["iron ore", "iron-ore", "iron ore mine", "iron ore project"],
}

TAG_RULES = [
    (["halt", "suspend", "strike", "shutdown", "force majeure", "curtail", "停产", "罢工", "扰动"], "供给扰动"),
    (["acquire", "acquisition", "merger", "takeover", "并购", "收购"], "并购"),
    (["deal", "agreement", "contract", "offtake", "协议", "承购"], "合约"),
    (["expansion", "ramp", "increase output", "扩建", "爬坡", "增产"], "扩产"),
    (["resource", "reserve", "drill", "intercept", "资源", "储量", "钻探"], "资源"),
    (["study", "feasibility", "approval", "approve", "permit", "可研", "审批", "许可"], "项目"),
]


def log(*a):
    print(*a, flush=True)


def get(url):
    last = None
    for i in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 3 * i)
    raise last


def strip_tags(s):
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s or "", flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_rss(raw):
    """容错解析：先试 ElementTree，失败则退回正则。返回 [(title, link, pubdate, desc)]"""
    items = []
    try:
        root = ET.fromstring(raw)
        for it in root.iter("item"):
            items.append((
                strip_tags(it.findtext("title") or ""),
                (it.findtext("link") or "").strip(),
                (it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date") or "").strip(),
                strip_tags(it.findtext("description") or ""),
            ))
        if items:
            return items
    except Exception:  # noqa: BLE001
        pass
    txt = raw.decode("utf-8", "replace")
    for m in re.finditer(r"<item>(.*?)</item>", txt, re.S):
        b = m.group(1)

        def pick(tag):
            mm = re.search(r"<%s>(.*?)</%s>" % (tag, tag), b, re.S)
            return mm.group(1) if mm else ""
        items.append((strip_tags(pick("title")), strip_tags(pick("link")), pick("pubDate").strip(), strip_tags(pick("description"))))
    return items


MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def parse_date(s):
    s = (s or "").strip()
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", s)
    if m:
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(2).title()], int(m.group(1)))
        except Exception:  # noqa: BLE001
            pass
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:  # noqa: BLE001
            pass
    return None


def norm_url(u):
    u = (u or "").strip()
    u = re.sub(r"[?#].*$", "", u)
    return u.rstrip("/")


def _hit(t, k):
    if k.isascii():
        return bool(re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", t))
    return k in t


def classify(text):
    """返回命中的品种列表；未命中返回 []"""
    t = " " + text.lower() + " "
    hits = []
    for metal, kws in STRONG.items():
        if any(_hit(t, k) for k in kws):
            hits.append(metal)
    for metal, kws in STRONG_COMBO.items():
        if metal not in hits and any(k in t for k in kws):
            hits.append(metal)
    return hits


def tag_of(text):
    t = text.lower()
    for kws, tag in TAG_RULES:
        if any(k in t for k in kws):
            return tag
    return "供给"


STOP = set("the a an and or of to in on for with at by from as is are was were its it this that new says say said will has have had be been more than over into after before about".split())


def toks(title):
    ws = re.findall(r"[a-z0-9一-鿿]+", (title or "").lower())
    return {w for w in ws if len(w) > 2 and w not in STOP}


def too_similar(t, kept):
    for k in kept:
        if not t or not k:
            continue
        inter = len(t & k)
        if inter >= 4 and inter / max(1, min(len(t), len(k))) >= 0.7:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/events.json")
    ap.add_argument("--max-keep", type=int, default=300)
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    today = now.date()

    old = {}
    if os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as f:
                for e in json.load(f).get("events", []):
                    old[e.get("id")] = e
        except Exception as ex:  # noqa: BLE001
            log("读取已有事件池失败，将重建：", ex)

    seen_titles = {re.sub(r"[^a-z0-9一-鿿]", "", (e.get("title") or "").lower()[:60]) for e in old.values()}
    seen_toks = [toks(e.get("title")) for e in old.values()]
    found, sources = [], []
    for name, url in FEEDS:
        try:
            raw = get(url)
            items = parse_rss(raw)
            n_new = 0
            for title, link, pub, desc in items:
                if not title or not link:
                    continue
                d = parse_date(pub) or today
                text = title + " " + desc
                low = text.lower()
                if any(b in low for b in BLOCK):
                    continue
                metals = classify(text)
                if not metals:
                    continue
                uid = hashlib.sha1(norm_url(link).encode()).hexdigest()[:16]
                if uid in old:
                    continue
                tkey = re.sub(r"[^a-z0-9一-鿿]", "", title.lower()[:60])
                if tkey in seen_titles:
                    continue
                tt = toks(title)
                if too_similar(tt, seen_toks):
                    continue
                seen_titles.add(tkey)
                seen_toks.append(tt)
                found.append({
                    "id": uid,
                    "when": d.isoformat(),
                    "d": d.isoformat(),
                    "metals": metals,
                    "title": title[:160],
                    "desc": (desc or "")[:220],
                    "tag": tag_of(text),
                    "status": "pend",
                    "src": name,
                    "links": [{"label": name + " 原文", "url": link}],
                    "first_seen": now.isoformat(),
                })
                n_new += 1
            sources.append({"source": name, "ok": True, "items": len(items), "matched_new": n_new})
            log(f"[OK]   {name:18s} items={len(items):3d} new={n_new}")
        except Exception as ex:  # noqa: BLE001
            sources.append({"source": name, "ok": False, "error": str(ex)[:120]})
            log(f"[FAIL] {name:18s} {str(ex)[:90]}")

    merged = list(old.values()) + found
    merged.sort(key=lambda e: (e.get("d") or "", e.get("first_seen") or ""), reverse=True)
    merged = merged[: args.max_keep]

    out = {
        "generated_at": now.isoformat(),
        "note": "自动抓取的供给事件池；status=pend 表示待人工确认，确认后改为 ok 并补充口径。",
        "sources": sources,
        "count": len(merged),
        "pending": sum(1 for e in merged if e.get("status") == "pend"),
        "events": merged,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    log(f"写入 {args.out}：累计 {len(merged)} 条（新增 {len(found)}，待确认 {out['pending']}）")


if __name__ == "__main__":
    main()
