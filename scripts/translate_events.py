#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
矿端公开核验台 · 供给事件中文编译（title_zh / summary_zh）

背景：data/events.json 里的英文条目来自公开 RSS 标题级抓取，页面默认展示中文
      标题与中文摘要，英文原标题保留在 en 行与详情抽屉里，链接仍指向英文原文。

本脚本做两件事：
  1. --check  统计覆盖率（有多少条还没有中文）
  2. 默认模式  为缺少 title_zh 的条目批量生成中文（标题 + 1~2 句摘要），写回同一个文件

翻译通道（OpenAI 兼容接口，任一可用即可）：
  TRANSLATE_API_BASE   默认 https://models.github.ai/inference
  TRANSLATE_API_KEY    必填；Actions 中可回落到内置 GITHUB_TOKEN
  TRANSLATE_MODEL      默认 openai/gpt-4o-mini

没有可用的 key 时脚本不报错、不写坏文件，只提示「N 条待译」，页面显示英文标题
并标注「待译」——这是设计上的降级路径，不是失败。

用法：
  python3 scripts/translate_events.py --check
  python3 scripts/translate_events.py                 # 编译全部待译条目
  python3 scripts/translate_events.py --limit 20      # 只处理前 20 条
  python3 scripts/translate_events.py --dry-run       # 只打印将发送的条目
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://models.github.ai/inference"
DEFAULT_MODEL = "openai/gpt-4o-mini"
TIMEOUT = 90
BATCH = 8

SYS_PROMPT = (
    "你是大宗商品与矿业研究的中文编译。输入是一批英文矿业/金属新闻的标题与摘要片段。"
    "请为每条生成：title_zh（不超过 30 字的中文财经标题，保留公司名与关键数字）、"
    "summary_zh（1~2 句、不超过 90 字的中文摘要，只陈述标题与摘要中确实出现的事实，"
    "不要补充背景、不要给投资建议、不要臆测未披露的数字）。"
    "若摘要片段被截断，只用可确认的部分，必要时省略而非猜测。"
    "品种用中文习惯写法，公司名保留英文原名。"
    "只输出 JSON 数组，元素为 {\"i\": 序号, \"title_zh\": \"...\", \"summary_zh\": \"...\"}，不要输出其它文字。"
)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pending(events):
    return [e for e in events if e.get("title") and not e.get("title_zh")]


def coverage(d):
    evs = d.get("events", [])
    done = [e for e in evs if e.get("title_zh")]
    return len(done), len(evs)


def call_api(base, key, model, batch):
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": json.dumps(
                [{"i": i, "title": e.get("title", ""), "desc": (e.get("desc") or "")[:400]}
                 for i, e in enumerate(batch)], ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw_body = r.read().decode("utf-8", "ignore")
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError("响应非 JSON（通道被拦截或凭据失效）：" + raw_body[:80].replace("\n", " ")) from exc
    text = body["choices"][0]["message"]["content"]
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise ValueError("no JSON array in response")
    return json.loads(m.group(0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="data/events.json")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--base", default=os.environ.get("TRANSLATE_API_BASE", DEFAULT_BASE))
    ap.add_argument("--model", default=os.environ.get("TRANSLATE_MODEL", DEFAULT_MODEL))
    args = ap.parse_args()

    d = load(args.src)
    done, total = coverage(d)
    todo = pending(d.get("events", []))
    print(f"[zh] 已有中文 {done}/{total}，待译 {len(todo)} 条")
    if args.check or not todo:
        return 0

    keys = [k for k in [(os.environ.get("TRANSLATE_API_KEY") or "").strip(),
                        (os.environ.get("GITHUB_TOKEN") or "").strip()] if k]
    if not keys:
        print("::warning::未配置 TRANSLATE_API_KEY / GITHUB_TOKEN，跳过编译；页面将显示英文标题并标注「待译」")
        return 0
    key = keys[0]

    if args.limit:
        todo = todo[:args.limit]
    if args.dry_run:
        for e in todo[:5]:
            print(" -", e.get("d"), e.get("title"))
        print(f"[zh] dry-run：将发送 {len(todo)} 条")
        return 0

    ok = 0
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        for attempt in range(2):
            try:
                res = call_api(args.base, key, args.model, batch)
                break
            except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError) as exc:
                print(f"[zh] 批次 {start//BATCH+1} 第 {attempt+1} 次失败：{exc}")
                if attempt == 0 and len(keys) > 1 and key != keys[-1]:
                    key = keys[-1]
                    print("[zh] 首通道失败，切换到备用通道（GITHUB_TOKEN）重试")
                res = None
                time.sleep(2)
        if not res:
            continue
        for item in res:
            try:
                e = batch[int(item["i"])]
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            t = (item.get("title_zh") or "").strip()
            s = (item.get("summary_zh") or "").strip()
            if t and s:
                e["title_zh"], e["summary_zh"] = t, s
                e.pop("zh_pending", None)
                ok += 1
        time.sleep(1)

    d["zh_coverage"] = {"translated": sum(1 for e in d.get("events", []) if e.get("title_zh")),
                        "total": len(d.get("events", []))}
    with open(args.src, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.write("\n")
    left = len(pending(d.get("events", [])))
    print(f"[zh] 新编译 {ok} 条，覆盖率 {d['zh_coverage']['translated']}/{d['zh_coverage']['total']}")
    if left:
        print(f"::warning::{left} 条仍无中文，页面将以英文显示并标注「待译」；请检查 TRANSLATE_API_KEY 与翻译通道")
    return 0


if __name__ == "__main__":
    sys.exit(main())
