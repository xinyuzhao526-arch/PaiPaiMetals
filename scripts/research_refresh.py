#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究数据定期刷新（RANK 榜单 / TRACK 产量追踪 / SOURCES 来源总表 / CHANGES 重大供给事件）

设计边界（重要）：
  · 这四类数据是「逐条核过口径」的研究快照，数字不能由机器无审写入——
    季报是财年还是日历年、产量是精矿还是金属量、单点资产还是企业合计，机器判不准。
  · 因此本脚本做的是：每交易日把「该更新的地方」找出来，写成待核对队列
    （data/research_pending.json），并在页面上显示待核条数与各板块时点。
  · 人工确认后，用 scripts/apply_research.py 一条命令写入 data/research_overlay.json，
    页面自动并入并推进该板块的 as_of，不需要再动 400KB 的 index.html。

用法：
  python3 scripts/research_refresh.py                 # 默认增量扫描（近 45 天新闻）
  python3 scripts/research_refresh.py --days 120      # 放宽新闻回看窗口
  python3 scripts/research_refresh.py --out data/research_pending.json
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, 'index.html')
EVENTS = os.path.join(ROOT, 'data', 'events.json')

TODAY = dt.date.today()
SECTIONS = ('RANK', 'TRACK', 'SOURCES', 'CHANGES')

# 名称里出现这些词时不足以定位到具体矿山/企业，做匹配时剔除
GENERIC = {
    'mine', 'mines', 'mining', 'group', 'district', 'operation', 'operations', 'project',
    'company', 'holdings', 'resources', 'limited', 'corp', 'corporation', 'plc', 'ltd',
    'national', 'total', 'global', 'world', 'output', 'production', 'metal', 'metals',
    '全国', '全球', '集团', '矿山', '公司', '产量', '合计', '样本', '基准',
    # 品种名/产品名：出现在几乎每条新闻里，不能作为定位主体的依据
    'copper', 'aluminium', 'aluminum', 'nickel', 'zinc', 'lead', 'tin', 'iron',
    'lithium', 'bauxite', 'alumina', 'spodumene', 'concentrate', 'brine', 'cathode',
    'ore', 'metal', 'refined', 'smelter', 'refinery', 'minerals', 'mining',
    '锂', '铜', '铝', '镍', '锌', '铅', '锡', '铁', '精矿', '碳酸锂', '氧化铝',
}

# 季报/年报常用期间表述；解析不出来就返回 None，宁可漏报也不瞎猜
RE_DATE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')
RE_H1 = re.compile(r'\bH1\s*(\d{4})\b', re.I)
RE_FY = re.compile(r'\bFY\s*(\d{2,4})\b', re.I)
RE_YEAR = re.compile(r'\b(20\d{2})\b')
RE_NUM = re.compile(
    r'(\d[\d,]*(?:\.\d+)?)\s*(blb|mlb|kt|Mt|mt|tonnes|tons)\b', re.I)


def load_metal_data():
    """从 index.html 里取出 METAL_DATA（单页应用，数据内联在 JS 常量里）"""
    src = open(INDEX, encoding='utf-8').read()
    m = re.search(r'(?:var|const|let)\s+METAL_DATA\s*=\s*\{', src)
    if not m:
        raise SystemExit('index.html 里找不到 METAL_DATA')
    i = m.end() - 1
    depth, instr, esc = 0, False, False
    for j in range(i, len(src)):
        c = src[j]
        if instr:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c in '[{':
                depth += 1
            elif c in ']}':
                depth -= 1
                if depth == 0:
                    return json.loads(src[i:j + 1])
    raise SystemExit('METAL_DATA 括号未闭合')


def parse_as_of(text):
    """把 actualAsOf 这类期间标签折成一个「最近一天」的日期，用于判断是否过期。
    财年按 6 月止处理（BHP/Fortescue 等），日历年按 12 月 31 日处理，解析不了返回 None。
    这里只用于「提醒过期」，不用于任何数值换算。"""
    s = (text or '').strip()
    if not s:
        return None
    m = RE_DATE.match(s)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None
    m = RE_H1.search(s)
    if m:
        return dt.date(int(m.group(1)), 6, 30)
    m = RE_FY.search(s)
    if m:
        y = int(m.group(1))
        y = y + 2000 if y < 100 else y
        return dt.date(y, 6, 30)
    m = RE_YEAR.search(s)
    if m:
        return dt.date(int(m.group(1)), 12, 31)
    return None


def aliases(name):
    """把主体名拆成可用于新闻匹配的词元，去掉过于宽泛的词"""
    parts = re.split(r'[\s/·、,，()（）\-–—]+', name or '')
    out = []
    for p in parts:
        p = p.strip().lower()
        if len(p) < 4 or p in GENERIC:
            continue
        if re.fullmatch(r'[\d\.]+', p):
            continue
        out.append(p)
    return out


def parse_figure(text):
    """从新闻标题/摘要里摘出产量数字，统一折算成 kt；换算不了的原样返回"""
    for m in RE_NUM.finditer(text or ''):
        raw = m.group(1).replace(',', '')
        unit = m.group(2).lower()
        try:
            v = float(raw)
        except ValueError:
            continue
        if unit in ('blb', 'mlb'):          # 十亿磅 / 百万磅 → 万吨(kt) 含铜量口径不成立，只做量级提示
            continue
        if unit == 'kt':
            return v, 'kt', m.group(0)
        if unit in ('mt',):
            return v * 1000, 'kt', m.group(0)
        if unit in ('tonnes', 'tons'):
            return v / 1000.0, 'kt', m.group(0)
    return None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=45, help='新闻回看天数')
    ap.add_argument('--out', default=os.path.join(ROOT, 'data', 'research_pending.json'))
    ap.add_argument('--stale-days', type=int, default=270, help='产量口径超过多少天视为过期')
    args = ap.parse_args()

    dismissed = set()
    dpath = os.path.join(ROOT, 'data', 'research_dismissed.json')
    if os.path.exists(dpath):
        try:
            dismissed = set(json.load(open(dpath, encoding='utf-8')).get('ids', []))
        except Exception:
            dismissed = set()

    data = load_metal_data()
    events = []
    if os.path.exists(EVENTS):
        j = json.load(open(EVENTS, encoding='utf-8'))
        events = j.get('events', j if isinstance(j, list) else [])
    cutoff = TODAY - dt.timedelta(days=args.days)

    items = []
    report = {'track_rows': 0, 'stale': {}, 'oldest': None, 'coverage': {}}

    # ── 一、TRACK 过期体检：产量口径多久没换过 ────────────────────────────
    for metal, d in data.items():
        track = d.get('TRACK') or []
        report['track_rows'] += len(track)
        stale = []
        oldest = None
        for row in track:
            asof = parse_as_of(row.get('actualAsOf'))
            if asof is None:
                continue
            if oldest is None or asof < oldest:
                oldest = asof
            age = (TODAY - asof).days
            if age > args.stale_days:
                stale.append({
                    'name': row.get('name'),
                    'asof': row.get('actualAsOf'),
                    'age': age,
                    'latest': row.get('latest'),
                })
        if stale:
            report['stale'][metal] = {'n': len(stale), 'of': len(track),
                                      'oldest': oldest.isoformat() if oldest else None}
            items.append({
                'id': 'stale-%s' % metal.lower(),
                'kind': 'stale_rows',
                'metal': metal,
                'section': 'TRACK',
                'count': len(stale),
                'names': [s['name'] for s in stale][:12],
                'reason': '%s 有 %d/%d 行产量口径超过 %d 天未更新，最早到 %s；需按最新季报/年报核定后改数' % (
                    metal, len(stale), len(track), args.stale_days,
                    oldest.isoformat() if oldest else '未知'),
            })
            if oldest and (report['oldest'] is None or oldest.isoformat() < report['oldest']):
                report['oldest'] = oldest.isoformat()

    # ── 二、新闻里出现的产量数字 → 与榜单/追踪主体对上号 ─────────────────
    # 这些只作为候选，不自动改数：新闻口径多为媒体转述，且期间长度不一
    name_index = {}
    for metal, d in data.items():
        for sec in ('RANK', 'TRACK'):
            for row in (d.get(sec) or []):
                for a in aliases(row.get('name')):
                    name_index.setdefault(a, []).append((metal, sec, row))
        report['coverage'][metal] = {
            'RANK': len(d.get('RANK') or []),
            'TRACK': len(d.get('TRACK') or []),
            'SOURCES': len(d.get('SOURCES') or []),
            'CHANGES': len(d.get('CHANGES') or []),
        }

    seen = set()
    for ev in events:
        try:
            ed = dt.date.fromisoformat(str(ev.get('d') or ev.get('when') or '')[:10])
        except ValueError:
            continue
        if ed < cutoff:
            continue
        text = '%s %s' % (ev.get('title') or '', ev.get('desc') or '')
        low = text.lower()
        val, unit, raw = parse_figure(text)
        if val is None:
            continue
        hits = []
        for a in set(re.findall(r'[a-z0-9一-龥\-]{4,}', low)):
            for metal, sec, row in name_index.get(a, []):
                hits.append((metal, sec, row))
        for metal, sec, row in hits[:3]:
            key = (ev.get('id'), metal, row.get('name'))
            if key in seen:
                continue
            seen.add(key)
            items.append({
                'id': 'news-%s' % hashlib.sha1(('%s|%s|%s' % (ev.get('id'), metal, row.get('name'))).encode()).hexdigest()[:10],
                'kind': 'news_number',
                'metal': metal,
                'section': sec,
                'target': row.get('name'),
                'field': 'kt' if sec == 'RANK' else 'actual',
                'current': row.get('kt') if sec == 'RANK' else row.get('actual'),
                'suggested': round(val, 3),
                'unit': unit,
                'raw': raw,
                'period': str(ev.get('d') or ''),
                'source': ev.get('src') or 'media',
                'url': ((ev.get('links') or [{}])[0] or {}).get('url'),
                'reason': '新闻披露 %s（%s 口径，期间以原文为准），与「%s」对得上；确认期间与口径后决定是否改数' % (
                    raw, unit, row.get('name')),
            })

    # ── 三、重大供给事件：把强信号新闻整理成时间轴草稿 ───────────────────
    STRONG_TAGS = {'供给扰动', '政策监管'}
    STRONG_WORDS = ('停产', '复产', '罢工', '事故', '不可抗力', '减产', '禁令', '配额', '关税',
                    '国有化', '吊销', '关闭', '暂停', 'shut', 'strike', 'suspend', 'resume',
                    'force majeure', 'ban', 'quota', 'tariff', 'halt')
    for ev in events:
        if (ev.get('tag') or '') not in STRONG_TAGS:
            continue
        try:
            ed = dt.date.fromisoformat(str(ev.get('d') or '')[:10])
        except ValueError:
            continue
        if ed < cutoff:
            continue
        eid = 'chg-' + hashlib.sha1(('%s|%s' % (ev.get('id'), ev.get('title'))).encode()).hexdigest()[:10]
        if any(i['id'] == eid for i in items):
            continue
        metals = ev.get('metals') or []
        body = '%s %s' % (ev.get('title') or '', ev.get('desc') or '')
        val, unit, raw = parse_figure(body)
        # 只要「有明确数字」或「强事件词」的条目，避免把常规行业稿塞进时间轴
        if val is None and not any(w in body.lower() for w in STRONG_WORDS):
            continue
        items.append({
            'id': eid,
            'kind': 'changes_draft',
            'metal': metals[0] if metals else '',
            'section': 'CHANGES',
            'target': ev.get('title_zh') or ev.get('title'),
            'suggested': raw,
            'period': str(ev.get('d') or ''),
            'source': ev.get('src') or 'media',
            'url': ((ev.get('links') or [{}])[0] or {}).get('url'),
            'row': {
                'id': 'auto-' + eid[4:],
                'when': str(ev.get('d') or '')[:7],
                'title': ev.get('title_zh') or ev.get('title') or '',
                'desc': ev.get('summary_zh') or (ev.get('desc') or '')[:160],
                'tag': ev.get('tag') or '供给扰动',
                'status': 'pend',
                'detail': '媒体口径（%s），数值未并入榜单/追踪，确认后补 detail' % (ev.get('src') or 'media'),
                'links': ev.get('links') or [],
                'd': str(ev.get('d') or '')[:10],
            },
            'reason': '强信号供给事件，建议人工确认后并入重大供给事件时间轴',
        })

    # 去重：同一 id 只留一条
    uniq = {}
    for it in items:
        uniq.setdefault(it['id'], it)
    items = [it for it in uniq.values() if it['id'] not in dismissed]

    payload = {
        'schema': 1,
        'generated_at': dt.datetime.now().replace(microsecond=0).isoformat(),
        'window_days': args.days,
        'count': len(items),
        'report': report,
        'items': items,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    by_kind = {}
    for it in items:
        by_kind[it['kind']] = by_kind.get(it['kind'], 0) + 1
    print('待核对 %d 条 %s' % (len(items), json.dumps(by_kind, ensure_ascii=False)))
    print('TRACK 行数 %d，过期（>%d 天）分布：%s' % (
        report['track_rows'], args.stale_days,
        json.dumps({k: v['n'] for k, v in report['stale'].items()}, ensure_ascii=False)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
