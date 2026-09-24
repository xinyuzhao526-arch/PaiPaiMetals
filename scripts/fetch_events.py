#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
矿端公开核验台 · 供给事件自动抓取（方案 B：类型白名单过滤 + 自动入库）

来源：均为公开 RSS 源，仅做标题/摘要级抓取，不抓取付费或会员制页面。
输出：data/events.json —— 累积式事件池；已存在条目原样保留，只追加新条目。

与方案 A 的区别：
  方案 A：命中品种关键词即进「待确认」池，等人工逐条确认。
  方案 B：在品种关键词之外再加一道「事件类型」白名单——
          只有真正改变金属供给的事件（停产/事故、扩产/投产、并购/股权、
          包销/长协、政策/监管）才入库，并直接标记为自动发布（status=auto）。
          估值/可研、融资、设备与服务订单、价格行情等一律在抓取阶段丢弃，
          不再占用人工确认环节。

  事件类型判定顺序：先黑名单（EXCLUDE），命中即丢弃；再白名单（INCLUDE），
  命中即入库。黑名单优先，避免「设备订单里出现了 agreement」这类误收。

用法：
  python3 scripts/fetch_events.py --out data/events.json
  python3 scripts/fetch_events.py --out data/events.json --max-keep 300
  python3 scripts/fetch_events.py --audit data/events.json   # 用新规则复核池中现有条目
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

# ---------------------------------------------------------------------------
# 一、品种归类（与方案 A 一致）
# ---------------------------------------------------------------------------
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
# 说明：standalone 的 lead / tin / iron 极易当动词误命中（lead the project 等），故不作关键词；
#       铅锌/锡/铁 另由 zinc-lead、lead-zinc、铅锌、锡、铁矿石、铁矿 等强词覆盖。
STRONG_COMBO = {
    "PbZn": ["lead-zinc", "zinc-lead", "lead and zinc", "lead & zinc"],
    "Sn":   ["tin mine", "tin mining", "tin concentrate", "tin smelter"],
    "Fe":   ["iron ore", "iron-ore", "iron ore mine", "iron ore project"],
}

# 噪声过滤：非事件类内容
BLOCK = ["podcast", "webinar", "listen:", "top 5", "top five", "opinion:", "video:", "quiz",
         "newsletter", "播客", "视频", "直播"]

# ---------------------------------------------------------------------------
# 二、事件类型白名单 / 黑名单
#   黑名单优先：命中 EXCLUDE 直接丢弃，不再看 INCLUDE。
# ---------------------------------------------------------------------------
INCLUDE = [
    ("供给扰动", [
        "halt", "halts", "halted", "suspend", "suspends", "suspended", "suspension",
        "shutdown", "shut down", "shutting", "strike", "stoppage", "force majeure",
        "curtail", "curtailment", "idle", "idled", "accident", "fatal", "collapse",
        "fire", "flood", "blockade", "landslide", "disruption", "outage",
        "mine closure", "closure of", "resumes operations", "restart", "restarted",
        "停产", "停工", "罢工", "事故", "减产", "扰动", "复产",
    ]),
    ("扩产", [
        "expansion", "expand", "expanding", "ramp-up", "ramp up", "ramping",
        "increase output", "boost output", "raising output", "commissioning",
        "commissioned", "first production", "commercial production",
        "new concentrator", "throughput increase", "debottleneck",
        "扩产", "投产", "扩能", "爬坡", "增产", "达产",
    ]),
    ("并购/股权", [
        "acquire", "acquires", "acquired", "acquisition", "merger", "merges",
        "takeover", "buying", "buys", "bought", "to buy", "sells", "sold",
        "sale of", "divest", "divestment", "stake", "controlling interest",
        "joint venture", "spin-off", "spin off",
        "收购", "并购", "出售", "转让", "股权", "易主",
    ]),
    ("长协/包销", [
        "offtake", "supply agreement", "supply deal", "sales agreement",
        "sales deal", "purchase agreement", "binding agreement",
        "long-term agreement", "long term contract", "multi-year",
        "eight-year", "five-year", "three-year", "10-year", "signs deal",
        "包销", "长协", "承购", "供货协议", "采购协议",
    ]),
    ("政策/监管", [
        "export ban", "export tax", "export quota", "export duty", "royalty",
        "mining law", "mining code", "licence revoked", "license revoked",
        "permit revoked", "nationalis", "nationaliz", "government stake",
        "windfall tax", "tariff", "sanction", "smelter closure",
        "export restriction",
        "出口", "关税", "配额", "国有化", "矿业法", "政策", "监管",
    ]),
]

EXCLUDE = [
    ("估值/可研", [
        "npv", "irr", "prefeasibility", "pre-feasibility", "prefeas",
        "feasibility study", "scoping study", "pfs", "mineral resource estimate",
        "resource update", "reserve update", "maiden resource", "drill", "drilling",
        "assay", "intercept", "value worth", "valuation", "cost", "costs",
        "cost overrun", "capex", "economics",
        "可研", "估值", "钻探", "资源量", "储量更新", "成本",
    ]),
    ("融资类", [
        "raises", "raise", "raising", "raised", "placement", "private placement",
        "funding round", "funding", "financing", "finance package", "loan facility",
        "credit facility", "debt facility", "capital raise", "share purchase plan",
        "rights issue", "ipo", "listing",
        "融资", "募资", "定增", "配股",
    ]),
    ("设备/服务订单", [
        "order", "orders", "analyser", "analyzer", "radar", "truck", "trucks",
        "locomotive", "locomotives", "equipment", "services order", "service order",
        "software", "automation", "technology platform", "system", "systems",
        "fleet", "conveyor", "crusher", "mill liner",
        "设备", "订单", "雷达", "机车", "系统", "技术",
    ]),
    ("价格/行情", [
        "price", "prices", "pricing", "record high", "record low", "rallies",
        "rally", "bounce", "bounces", "climbs", "climb", "jumps", "jump",
        "surges", "surge", "soars", "soar", "slides", "slumps", "tumbles",
        "market outlook", "price forecast", "forecast price",
        "铜价", "价格", "行情", "上涨", "下跌", "反弹", "创新高",
    ]),
    ("非供给主题", [
        "emissions", "carbon", "esg", "climate", "credits", "green bond",
        "sustainability report", "appoints", "appointment", "ceo", "cfo",
        "dividend", "agm", "conference", "award", "pilot project",
        "memorandum of understanding", "mou", "pilot",
        "碳", "减排", "人事", "任命", "会议",
    ]),
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


def first_match(text, rules):
    """返回 (标签/理由, 命中的关键词) 或 (None, '')。黑名单与白名单共用。"""
    t = " " + (text or "").lower() + " "
    for label, kws in rules:
        for k in kws:
            if _hit(t, k):
                return label, k
    return None, ""


def screen(text):
    """事件类型过滤。返回 (是否入库, 事件标签, 说明)

    黑名单优先：只要命中「估值/可研、融资、设备订单、价格行情、非供给主题」，
    无论是否命中白名单都丢弃。
    """
    bad, bad_kw = first_match(text, EXCLUDE)
    if bad:
        return False, None, f"{bad}:{bad_kw}"
    good, good_kw = first_match(text, INCLUDE)
    if good:
        return True, good, f"{good}:{good_kw}"
    return False, None, "不在供给事件类型内"


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


NOTE = ("自动抓取的供给事件池。status=auto 为按事件类型白名单自动入库的公开媒体来源条目，"
        "无需人工确认；status=ok 为已回溯一手来源或经人工核定的条目。")


def build_output(events, sources, now, max_keep):
    events = sorted(events, key=lambda e: (e.get("d") or "", e.get("first_seen") or ""), reverse=True)[:max_keep]
    return {
        "generated_at": now.isoformat(),
        "note": NOTE,
        "sources": sources,
        "count": len(events),
        "pending": sum(1 for e in events if e.get("status") == "pend"),
        "auto": sum(1 for e in events if e.get("status") == "auto"),
        "events": events,
    }


def audit(path):
    """用新规则复核池中现有条目，列出保留与剔除（不写文件）。"""
    with open(path, encoding="utf-8") as f:
        evs = json.load(f).get("events", [])
    keep, drop = [], []
    for e in evs:
        text = (e.get("title") or "") + " " + (e.get("desc") or "")
        ok, tag, why = screen(text)
        (keep if ok else drop).append((e, tag, why))
    log(f"复核 {path}：共 {len(evs)} 条 → 保留 {len(keep)} 条，剔除 {len(drop)} 条")
    log("")
    log("== 保留（原标签 → 新标签）==")
    for e, tag, why in keep:
        log(f"  [{tag}] {e.get('when')} {e.get('metals')} | {e.get('tag')} → {tag} | {why}")
        log(f"        {e.get('title')}")
    log("")
    log("== 剔除（原因）==")
    for e, _t, why in drop:
        log(f"  ({why}) {e.get('when')} {e.get('metals')} | {e.get('tag')}")
        log(f"        {e.get('title')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/events.json")
    ap.add_argument("--max-keep", type=int, default=300)
    ap.add_argument("--audit", metavar="PATH", help="用新规则复核现有事件池并打印结果，不写文件")
    args = ap.parse_args()

    if args.audit:
        audit(args.audit)
        return

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
    dropped = {}

    for name, url in FEEDS:
        try:
            raw = get(url)
            items = parse_rss(raw)
            n_new = 0
            n_metal = 0
            n_drop = 0
            for title, link, pub, desc in items:
                if not title or not link:
                    continue
                text = title + " " + desc
                low = text.lower()
                if any(b in low for b in BLOCK):
                    continue
                metals = classify(text)
                if not metals:
                    continue
                n_metal += 1
                # —— 事件类型白名单 / 黑名单 ——
                ok, tag, why = screen(text)
                if not ok:
                    n_drop += 1
                    key = why.split(":")[0]
                    dropped[key] = dropped.get(key, 0) + 1
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
                d = parse_date(pub) or today
                found.append({
                    "id": uid,
                    "when": d.isoformat(),
                    "d": d.isoformat(),
                    "metals": metals,
                    "title": title[:160],
                    "desc": (desc or "")[:220],
                    "tag": tag,
                    "status": "auto",
                    "src_level": "media",
                    "src": name,
                    "links": [{"label": name + " 原文", "url": link}],
                    "first_seen": now.isoformat(),
                })
                n_new += 1
            sources.append({"source": name, "ok": True, "items": len(items),
                            "matched_metal": n_metal, "dropped_screen": n_drop, "new": n_new})
            log(f"[OK]   {name:18s} items={len(items):3d} 品种命中={n_metal:3d} 类型剔除={n_drop:3d} new={n_new}")
        except Exception as ex:  # noqa: BLE001
            sources.append({"source": name, "ok": False, "error": str(ex)[:120]})
            log(f"[FAIL] {name:18s} {str(ex)[:90]}")

    merged = list(old.values()) + found
    out = build_output(merged, sources, now, args.max_keep)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    if dropped:
        log("类型白名单剔除：" + "，".join(f"{k} {v} 条" for k, v in sorted(dropped.items(), key=lambda x: -x[1])))
    log(f"写入 {args.out}：累计 {len(out['events'])} 条（新增 {len(found)}，自动发布 {out['auto']}，待确认 {out['pending']}）")


if __name__ == "__main__":
    main()
