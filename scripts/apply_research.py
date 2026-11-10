#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把研究数据的待核对条目写入覆盖层 data/research_overlay.json

页面会在渲染每个品种时把覆盖层叠到内置快照之上，并把该板块的 as_of 推进到写入日，
所以确认之后不需要再手改 index.html 里的 METAL_DATA。

用法：
  python3 scripts/apply_research.py --list                 # 看队列
  python3 scripts/apply_research.py --ids news-ab12,chg-cd34
  python3 scripts/apply_research.py --kind changes_draft    # 按类型批量
  python3 scripts/apply_research.py --all --dry-run
  python3 scripts/apply_research.py --ack stale-...         # 只清队列，不改数据
"""
import argparse
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PENDING = os.path.join(ROOT, 'data', 'research_pending.json')
OVERLAY = os.path.join(ROOT, 'data', 'research_overlay.json')
TODAY = dt.date.today().isoformat()

SKELETON = {
    'schema': 1,
    'generated_at': TODAY,
    'note': '人工确认后的研究数据修订。页面渲染时叠加到 index.html 的 METAL_DATA 之上；as_of 为该板块最后一次确认更新的日期。',
    'sections': {s: {'as_of': None} for s in ('RANK', 'TRACK', 'SOURCES', 'CHANGES')},
    'patch': {},
}


def load(path, default):
    if not os.path.exists(path):
        return json.loads(json.dumps(default))
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def append_note(row, key, text):
    old = row.get(key) or ''
    if text in old:
        return
    row[key] = (old + '｜' if old else '') + text


def apply_item(ov, it):
    metal = it.get('metal') or ''
    sec = it.get('section')
    if not metal or not sec:
        return False
    patch = ov['patch'].setdefault(metal, {}).setdefault(sec, [])

    if it['kind'] == 'news_number':
        field = it.get('field') or ('kt' if sec == 'RANK' else 'actual')
        if it.get('suggested') is None:
            return False
        note = '已核 %s：%s（%s，%s 口径）%s' % (
            TODAY, it.get('raw') or it.get('suggested'), it.get('period') or '',
            it.get('source') or 'media', (' ' + it['url']) if it.get('url') else '')
        note_key = 'note' if sec == 'RANK' else 'latestNote'
        patch.append({'name': it['target'],
                      'set': {field: it['suggested']},
                      'append': {note_key: note}})
        return True

    if it['kind'] == 'changes_draft':
        row = it.get('row')
        if not row:
            return False
        row = dict(row)
        row['status'] = 'ok'
        row['detail'] = (row.get('detail') or '') + '｜%s 人工确认并入' % TODAY
        patch.append({'row': row})
        return True

    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ids', default='')
    ap.add_argument('--kind', default='')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--ack', default='', help='仅把条目从队列移除，不改数据')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true', help='允许写入期间不可比或与原文对不上的条目')
    args = ap.parse_args()

    pend = load(PENDING, {'schema': 1, 'items': [], 'count': 0})
    items = pend.get('items', [])

    if args.list:
        for it in items:
            print('%-14s %-6s %-10s %-28s %s' % (
                it['id'], it.get('metal', ''), it['kind'],
                (it.get('target') or '')[:26], (it.get('reason') or '')[:70]))
        print('共 %d 条' % len(items))
        return 0

    ack_ids = set(x for x in args.ack.split(',') if x)
    sel = []
    if args.ids:
        want = set(x for x in args.ids.split(',') if x)
        sel = [i for i in items if i['id'] in want]
    elif args.kind:
        sel = [i for i in items if i['kind'] == args.kind]
    elif args.all:
        sel = [i for i in items if i['kind'] in ('news_number', 'changes_draft')]

    if not sel and not ack_ids:
        print('没有选中任何条目；用 --list 查看队列')
        return 1

    ov = load(OVERLAY, SKELETON)
    ov.setdefault('sections', {s: {'as_of': None} for s in ('RANK', 'TRACK', 'SOURCES', 'CHANGES')})
    ov.setdefault('patch', {})

    applied = []
    for it in sel:
        if it.get('grounded') is False and not args.force:
            print('  ! 与原文对不上，已跳过：%s %s（确认后加 --force）' % (it['id'], it.get('target') or ''))
            continue
        if it.get('comparable') is False and not args.force:
            print('  ! 期间不可比，已跳过：%s %s（确认要改数请加 --force）' % (it['id'], it.get('target') or ''))
            continue
        if args.dry_run:
            print('[dry-run] 将写入 %s %s %s' % (it['id'], it['kind'], it.get('target')))
            continue
        if apply_item(ov, it):
            applied.append(it)
            ov['sections'].setdefault(it['section'], {'as_of': None})['as_of'] = TODAY

    skipped = [i for i in sel if i not in applied]
    # 只有真正写进覆盖层（或显式 --ack）的条目才出队；未处理的留在队列里等下次
    removed = set(i['id'] for i in applied) | ack_ids
    if ack_ids and not args.dry_run:
        dpath = os.path.join(ROOT, 'data', 'research_dismissed.json')
        dis = load(dpath, {'schema': 1, 'ids': []})
        dis['ids'] = sorted(set(dis.get('ids', [])) | ack_ids)
        dis['updated_at'] = dt.datetime.now().replace(microsecond=0).isoformat()
        with open(dpath, 'w', encoding='utf-8') as f:
            json.dump(dis, f, ensure_ascii=False, indent=1)
    if not args.dry_run:
        pend['items'] = [i for i in items if i['id'] not in removed]
        pend['count'] = len(pend['items'])
        pend['updated_at'] = dt.datetime.now().replace(microsecond=0).isoformat()
        # 清掉为“不可写入条目”顺手建出来的空数组
        for m in list(ov['patch']):
            for sec in list(ov['patch'][m]):
                if not ov['patch'][m][sec]:
                    del ov['patch'][m][sec]
            if not ov['patch'][m]:
                del ov['patch'][m]
        ov['generated_at'] = TODAY
        with open(OVERLAY, 'w', encoding='utf-8') as f:
            json.dump(ov, f, ensure_ascii=False, indent=1)
        with open(PENDING, 'w', encoding='utf-8') as f:
            json.dump(pend, f, ensure_ascii=False, indent=1)

    print('已写入 %d 条，队列剩余 %d 条' % (len(applied), len(pend['items'])))
    for it in skipped:
        print('  - 未处理（保留在队列）：%s %s %s' % (it['id'], it['kind'], it.get('target') or ''))
    for it in applied:
        print('  + %-12s %-8s %s' % (it['id'], it.get('metal', ''), it.get('target') or ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
