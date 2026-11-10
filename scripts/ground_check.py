#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引用落地检查：草稿里写的数字、动作、主体，能不能在原文里找到。

为什么需要：媒体稿被抓进事件池后，摘要由模型编译成中文，容易出现「原文没写的
停产」「品种张冠李戴」「把价格评论写成供给事件」。人工逐条点开核对成本高，
这一层先用脚本把「说的和原文不一致」的挑出来。

判定三件事：
  1) 数字 —— 草稿里的吨数、比例、人数，在原文里找得到（支持 万、%、英文数词 1–10）
  2) 动作 —— 草稿说停产/罢工/推迟/收购，原文得有对应词（中英对照表）
  3) 主体 —— 草稿提到的公司，原文得出现同一家的任一名称

结果三态：
  True  三项都过
  False 有明确对不上的项（missing 列出）
  None  原文抓不到（403/超时），交给人工，不算通过

用法：
  python3 scripts/ground_check.py --url URL --title "..." --desc "..."
"""
import argparse
import html
import json
import re
import sys
import urllib.request

UA = 'Mozilla/5.0 (compatible; PaiPaiMetals-groundcheck/1.0)'
TIMEOUT = 20

# 中文动作词 → 原文可能的表述（英文为主，兼顾中文源）
VERB_MAP = {
    '停产': ('halt', 'shut', 'suspend', 'stop', 'idle', 'cease', 'curb'),
    '暂停': ('suspend', 'halt', 'stop', 'pause'),
    '关停': ('shut', 'halt', 'close', 'suspend'),
    '减产': ('cut', 'reduce', 'curb', 'lower', 'decline', 'fall'),
    '复产': ('restart', 'resume', 'restore', 'reopen'),
    '罢工': ('strike', 'walkout', 'labour dispute', 'labor dispute'),
    '事故': ('accident', 'fatality', 'died', 'death', 'killed'),
    '泄漏': ('spill', 'leak'),
    '法院': ('court', 'judge', 'ruling', 'order'),
    '许可': ('licence', 'license', 'permit'),
    '收购': ('acquisition', 'acquire', 'buy'),
    '投产': ('start-up', 'startup', 'commissioning', 'first production'),
    '扩建': ('expansion', 'expand'),
    '推迟': ('delay', 'postpone', 'defer'),
    '达成协议': ('agreement', 'deal', 'accord'),
    '转岗': ('relocat', 'reassign', 'redeploy'),
    '叫停': ('halt', 'suspend', 'idle', 'block', 'order'),
}

# 具体物件/区域：草稿写了「破碎」「尾矿」「选厂」，原文得出现对应词，
# 否则就是拿别处的说法套在这一条上
NOUN_MAP = {
    '破碎': ('crush', 'crusher'),
    '物料处理': ('material handling', 'materials handling'),
    '选厂': ('concentrator', 'processing plant'),
    '尾矿': ('tailings',),
    '露天': ('open-pit', 'open pit'),
    '精矿': ('concentrate',),
    '加工': ('processing',),
    '采矿': ('mining',),
    '库存': ('inventory', 'stockpile'),
    '许可': ('licence', 'license', 'permit'),
}

# 主体别名：草稿里出现任一名，原文里也要出现同一组的任一名
ENTITY_MAP = {
    'Codelco': ('codelco', '智利国家铜业'),
    'Teck': ('teck', '泰克'),
    'BHP': ('bhp', '必和必拓'),
    'Antofagasta': ('antofagasta',),
    'Sigma': ('sigma',),
    'PLS': ('pls', 'pilgangoora'),
    'Sibanye': ('sibanye', 'stillwater', 'keliber'),
    'First Quantum': ('first quantum', 'fqm', 'kansanshi', 'sentinel'),
    'Glencore': ('glencore',),
    'Anglo American': ('anglo american',),
    'Freeport': ('freeport',),
    'Ivanhoe': ('ivanhoe', 'kamoa'),
    'Rio Tinto': ('rio tinto',),
    'MMG': ('mmg', 'las bambas'),
    'Eramet': ('eramet', 'weda bay', 'centenario'),
    'Evolution': ('evolution', 'carnaby'),
    'Metro Mining': ('metro mining', 'bauxite hills'),
}

MONTHS = {1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr', 5: 'may', 6: 'jun',
          7: 'jul', 8: 'aug', 9: 'sept', 10: 'oct', 11: 'nov', 12: 'dec'}
NUM_WORDS = {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five',
             6: 'six', 7: 'seven', 8: 'eight', 9: 'nine', 10: 'ten'}


def fetch_article(url, timeout=TIMEOUT):
    """抓公开页面并转成纯文本；失败返回 None（不抛错，交人工）"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except Exception:
        return None
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('latin-1', 'ignore')
    text = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', text)
    text = re.sub(r'(?s)<[^>]+>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def _norm_num(s):
    s = s.replace(',', '').replace(' ', '')
    if s.endswith('.0'):
        s = s[:-2]
    return s


def _num_variants(v):
    """一个数字在原文里可能的写法"""
    out = set()
    if float(v).is_integer():
        i = int(v)
        out |= {str(i), f'{i:,}'}
        if i in NUM_WORDS:
            out.add(NUM_WORDS[i])
    else:
        out.add(str(v))
    return out


def extract_numbers(text):
    """抽数字，处理 万 / % / 日期；返回 [(原写法, 候选值 float, 类型)]"""
    nums = []
    # 日期：9 月 4 日 / 9月4日
    for m in re.finditer(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日', text):
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            nums.append((m.group(0), f'{MONTHS[mo]} {d}', 'date'))
    cleaned = re.sub(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日', ' ', text)
    for m in re.finditer(r'(\d[\d,]*(?:\.\d+)?)\s*(万|%)?', cleaned):
        raw = m.group(1)
        suffix = m.group(2) or ''
        try:
            v = float(_norm_num(raw))
        except ValueError:
            continue
        if suffix == '万':
            v *= 10000
        nums.append((m.group(0).strip(), v, 'pct' if suffix == '%' else 'num'))
    return nums


def check(title, desc, article):
    """返回 (grounded, missing, detail)"""
    if article is None:
        return None, [], {'reason': '原文抓取失败，未核'}
    draft = (title or '') + ' ' + (desc or '')
    low = article.lower()
    missing = []

    notes = []
    # 1) 数字
    checked = 0
    for raw, val, kind in extract_numbers(draft):
        if kind == 'date':
            # 容忍 Sept. 4 / September 4th 这类写法差异
            token = re.sub(r'[^a-z0-9]', '', val.lower())
            hay = re.sub(r'[^a-z0-9]', '', low)
            if token not in hay and token.replace('sept', 'sep') not in hay:
                # 日期写法差异大，且部分站点正文只给摘要，日期缺失只记录不判错
                notes.append('日期未见于抓取正文：' + raw)
            continue
        if kind == 'pct':
            if abs(val) < 1:      # 个位数百分比多半是噪声，跳过
                continue
            checked += 1
            if f'{val:g}%' not in article and f'{val:g} per cent' not in low:
                missing.append('比例未见于原文：' + raw)
            continue
        if val < 1:
            continue
        checked += 1
        if not any(v in article or v.lower() in low for v in _num_variants(val)):
            missing.append('数字未见于原文：' + raw)

    # 2) 动作
    for zh, alts in VERB_MAP.items():
        if zh in draft and not any(a in low for a in alts):
            missing.append('动作未见于原文：' + zh)

    # 3) 具体物件/区域
    for zh, alts in NOUN_MAP.items():
        if zh in draft and not any(a in low for a in alts):
            missing.append('物件/区域未见于原文：' + zh)

    # 4) 主体
    for canon, names in ENTITY_MAP.items():
        if any(n in draft.lower() or n in draft for n in names):
            if not any(n in low for n in names):
                missing.append('主体未见于原文：' + canon)

    return (len(missing) == 0), missing, {'numbers_checked': checked, 'notes': notes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--title', default='')
    ap.add_argument('--desc', default='')
    args = ap.parse_args()
    art = fetch_article(args.url)
    grounded, missing, detail = check(args.title, args.desc, art)
    print(json.dumps({'grounded': grounded, 'missing': missing, 'detail': detail},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
