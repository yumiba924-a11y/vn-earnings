# -*- coding: utf-8 -*-
"""VND/JPY 為替（open.er-api.com・キー不要・morning-brief実績）。"""
import json
import urllib.request


def vnd_per_jpy(default=161.0):
    """1 JPY = ? VND。取得失敗時は直近既知値にフォールバック（壊れない）。"""
    try:
        d = json.loads(urllib.request.urlopen(
            "https://open.er-api.com/v6/latest/JPY", timeout=25).read().decode())
        rate = d["rates"]["VND"]
        asof = (d.get("time_last_update_utc") or "")[:16]
        return rate, asof
    except Exception:
        return default, "取得失敗・既定値"
