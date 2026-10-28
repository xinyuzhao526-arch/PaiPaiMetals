#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 Actions 环境里探测多个可能的模型接口（不打印任何凭据）。"""
import json
import os
import urllib.error
import urllib.request

TOKEN = (os.environ.get("ACTIONS_TOKEN") or "").strip()
TRANSLATE_KEY = (os.environ.get("TRANSLATE_API_KEY") or "").strip()

TARGETS = [
    ("models.github.ai/inference", "https://models.github.ai/inference/chat/completions", "openai/gpt-4o-mini"),
    ("models.github.ai/inference/v1", "https://models.github.ai/inference/v1/chat/completions", "openai/gpt-4o-mini"),
    ("models.inference.ai.azure.com", "https://models.inference.ai.azure.com/chat/completions", "gpt-4o-mini"),
    ("api.githubcopilot.com", "https://api.githubcopilot.com/chat/completions", "gpt-4o-mini"),
]


def _is_json(body):
    try:
        json.loads(body)
        return True
    except Exception:  # noqa: BLE001
        return False


def call(url, model, key):
    payload = {"model": model, "max_tokens": 16,
               "messages": [{"role": "user", "content": "只回复两个字：可用"}]}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json",
                                          "Authorization": "Bearer " + key},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            body = r.read().decode("utf-8", "ignore")
            return {"status": r.status, "ctype": r.headers.get("Content-Type"),
                    "head": body[:200], "json": _is_json(body)}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        return {"status": e.code, "ctype": e.headers.get("Content-Type"),
                "head": body[:200], "json": _is_json(body)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:160]}


out = {"env": {"actions_token": bool(TOKEN), "translate_key": bool(TRANSLATE_KEY)}, "results": {}}
for key_name, key in (("actions", TOKEN), ("translate", TRANSLATE_KEY)):
    if not key:
        out["results"][key_name] = {"skipped": "empty"}
        continue
    for name, url, model in TARGETS:
        out["results"][key_name + "|" + name] = call(url, model, key)

os.makedirs("probe", exist_ok=True)
with open("probe/models_probe.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
for k, v in out["results"].items():
    if isinstance(v, dict) and "status" in v:
        print(k, v["status"], "json=" + str(v.get("json")))
    else:
        print(k, v)
