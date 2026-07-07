# -*- coding: utf-8 -*-
"""VN決算ウォッチ 収集エンジン。

毎営業日、ユニバース全銘柄の四半期損益(IS)をFireAntからポーリングし、
前回state(data/state.json)とのdiffで「新しい四半期列の出現＝決算発表」を検知する。
未発表の四半期は列自体が現れない（2026-07-07実測）ので、列ラベルの増分だけ見ればよい。

検知した銘柄は financial-indicators / fundamental を追加取得して解剖し、
vn-morning-brief のバズ履歴（公開CSV）と突合して data/events.jsonl に追記する。

usage: python scripts/earnings_collector.py [--baseline]
  --baseline: 初回用。現状を state に焼き付けるだけでイベントは発行しない
"""
import argparse
import csv
import datetime
import io
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
import fireant

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIVERSE = os.path.join(ROOT, "config", "universe.csv")
STATE = os.path.join(ROOT, "data", "state.json")
EVENTS = os.path.join(ROOT, "data", "events.jsonl")
REPORTS_DIR = os.path.join(ROOT, "data", "reports")
BUZZ_URL = "https://raw.githubusercontent.com/yumiba924-a11y/vn-morning-brief/main/social_history/buzz_daily.csv"

THROTTLE = 0.25  # 100銘柄×1コール≒40秒。FireAntはレート寛容（morning-brief実績）


def jst_today():
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).date()


def boundary_quarter(today):
    """endpointのyear/quarterは『その直前の四半期まで』を返す境界＝今日の暦四半期を渡す。"""
    q = (today.month - 1) // 3 + 1
    return today.year, q


def quarter_key(label):
    """'Q2/2026' → (2026, 2)。ソート・YoY用。"""
    q, y = label.split("/")
    return int(y), int(q[1:])


def parse_is(payload):
    """compact IS → {'quarters': ['Q1/2025',...], 'series': {code: [v,...]}}"""
    if not payload or not payload.get("columns"):
        return None
    quarters = payload["columns"][2:]
    series = {}
    for row in payload.get("rows", []):
        code = row[1]
        series[code] = row[2:]
    return {"quarters": quarters, "series": series}


def latest_reported(parsed):
    """NetProfitが非nullな最新の四半期ラベル（無ければNone）。"""
    npat = parsed["series"].get("NetProfit") or parsed["series"].get("Sales") or []
    for i in range(len(parsed["quarters"]) - 1, -1, -1):
        if i < len(npat) and npat[i] is not None:
            return parsed["quarters"][i]
    return None


def pick(parsed, code, label):
    if label not in parsed["quarters"]:
        return None
    i = parsed["quarters"].index(label)
    vals = parsed["series"].get(code) or []
    return vals[i] if i < len(vals) else None


def growth(cur, base):
    """YoY/QoQ（%）。基準が0・欠損・赤字→黒字等で率が無意味な場合はNone。"""
    if cur is None or base is None or base == 0:
        return None
    if base < 0:
        return None  # 赤字基準の伸び率は誤解を招くので出さない（絶対値で語る）
    return round((cur - base) / abs(base) * 100, 1)


def load_buzz():
    """バズ履歴CSV → {symbol: {'today': clean, 'avg10': float, 'date': 最新日}}"""
    try:
        with urllib.request.urlopen(BUZZ_URL, timeout=30) as r:
            text = r.read().decode("utf-8-sig")
    except Exception as e:
        print(f"[warn] buzz fetch failed: {e}")
        return {}
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return {}
    dates = sorted({r["date"] for r in rows})
    last10 = dates[-10:]
    latest = dates[-1]
    out = {}
    by_sym = {}
    for r in rows:
        if r["date"] in last10:
            by_sym.setdefault(r["symbol"], []).append(r)
    for sym, rs in by_sym.items():
        cleans = [int(r["volume_n_clean"] or 0) for r in rs]
        today = next((int(r["volume_n_clean"] or 0) for r in rs if r["date"] == latest), 0)
        out[sym] = {"today": today, "avg10": round(sum(cleans) / len(cleans), 1), "date": latest}
    return out


def indicator_summary(symbol):
    """financial-indicators → 主要指標と業種平均の対（取れなければ{}）。"""
    try:
        data = fireant.financial_indicators(symbol)
    except Exception as e:
        print(f"[warn] indicators {symbol}: {e}")
        return {}
    if not data:
        return {}
    out = {}
    for item in data:
        name = item.get("shortName") or item.get("name")
        if name in ("P/E", "P/B", "ROE", "ROA"):
            out[name] = {"value": item.get("value"), "industry": item.get("industryValue")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true", help="現状焼き付けのみ・イベント発行なし")
    args = ap.parse_args()

    today = jst_today()
    by, bq = boundary_quarter(today)

    universe = []
    with open(UNIVERSE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            universe.append((row["symbol"].strip(), row["tier"].strip()))

    state = {}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            state = json.load(f)

    buzz = {} if args.baseline else load_buzz()

    os.makedirs(REPORTS_DIR, exist_ok=True)
    events = []
    errors = []

    for i, (sym, tier) in enumerate(universe):
        try:
            payload = fireant.income_statement(sym, by, bq, count=6)
        except Exception as e:
            errors.append(f"{sym}: {e}")
            continue
        finally:
            time.sleep(THROTTLE)

        parsed = parse_is(payload)
        if not parsed:
            errors.append(f"{sym}: empty IS")
            continue

        with open(os.path.join(REPORTS_DIR, f"{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        latest = latest_reported(parsed)
        prev_known = state.get(sym, {}).get("latest")
        first_seen = state.get(sym, {}).get("first_seen", {})

        is_new = (
            latest is not None
            and prev_known is not None
            and quarter_key(latest) > quarter_key(prev_known)
        )

        if is_new and not args.baseline:
            yy, qq = quarter_key(latest)
            yoy_label = f"Q{qq}/{yy - 1}"
            idx = parsed["quarters"].index(latest)
            qoq_label = parsed["quarters"][idx - 1] if idx > 0 else None

            sales = pick(parsed, "Sales", latest)
            npat = pick(parsed, "NetProfit", latest)
            npat_p = pick(parsed, "NetProfit_PCSH", latest)
            ev = {
                "detected": str(today),
                "symbol": sym,
                "tier": tier,
                "quarter": latest,
                "sales": sales,
                "sales_yoy": growth(sales, pick(parsed, "Sales", yoy_label)),
                "npat": npat,
                "npat_pcsh": npat_p,
                "npat_yoy": growth(npat, pick(parsed, "NetProfit", yoy_label)),
                "npat_qoq": growth(npat, pick(parsed, "NetProfit", qoq_label)) if qoq_label else None,
                "npat_yoy_base": pick(parsed, "NetProfit", yoy_label),
                "indicators": indicator_summary(sym),
                "buzz": buzz.get(sym),
            }
            events.append(ev)
            print(f"[EVENT] {sym} {latest} 発表検知 NPAT_YoY={ev['npat_yoy']}")

        if latest and latest not in first_seen:
            # baseline時は「以前から存在」を明示するためdetected扱いにしない
            first_seen[latest] = "baseline" if (args.baseline or prev_known is None) else str(today)
        state[sym] = {"latest": latest, "tier": tier, "first_seen": first_seen,
                      "checked": str(today)}

        if (i + 1) % 25 == 0:
            print(f"  ... {i + 1}/{len(universe)}")

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)

    if events:
        with open(EVENTS, "a", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    print(f"done: {len(universe)}銘柄 / 新規イベント{len(events)}件 / エラー{len(errors)}件")
    for e in errors[:10]:
        print(f"  [err] {e}")
    # エラーが多数＝API側異常の可能性。全滅時のみ非0で落として気付けるように
    if len(errors) >= len(universe) * 0.5:
        sys.exit(1)


if __name__ == "__main__":
    main()
