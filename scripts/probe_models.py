#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 Actions 运行环境里探测 GitHub Models 通道（不打印任何凭据）。"""
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("PROBE_BASE", "https://models.github.ai/inference")
MODELS = ["openai/gpt-4o-mini", "openai/gpt-4.1-mini"]
KEYS = [("github_token", (os.environ.get("ACTIONS_TOKEN") or "").strip()),
        ("translate_key", (os.environ.get("TRANSLATE_API_KEY") or "").strip())]


def probe(tag, key, model):
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "只回复两个字：可用"}],
    }
    req = urllib.request.Request(
        BASE.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read().decode("utf-8", "ignore")
            return {"ok": True, "status": r.status, "head": raw[:300]}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "head": e.read().decode("utf-8", "ignore")[:300]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": None, "error": str(e)[:200]}


out = {"base": BASE, "env": {"github_token": bool(KEYS[0][1]), "translate_key": bool(KEYS[1][1])}, "results": {}}
for tag, key in KEYS:
    if not key:
        out["results"][tag] = {"skipped": "empty"}
        continue
    for model in MODELS:
        out["results"][tag + "|" + model] = probe(tag, key, model)

os.makedirs("probe", exist_ok=True)
with open("probe/models_probe.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(json.dumps({k: (v.get("status") if isinstance(v, dict) else v) for k, v in out["results"].items()}, ensure_ascii=False))
