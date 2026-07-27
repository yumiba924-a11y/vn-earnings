# -*- coding: utf-8 -*-
"""発表済み銘柄の「決算カード」データを組み立て docs/data/cards.json を書く。

数字は全てFireAntからの機械計算（VND＋円換算）。背景・見通しは会社開示＋報道ベース（narrative）。
ポータル「決算ウォッチ」ページはこの cards.json を読んで描画する（表示はあちら・データはこちら）。
"""
import csv
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import fireant
import fx as fxmod
import narrative as narr
from earnings_collector import parse_is, pick, growth, quarter_key, jst_today, load_buzz

# 「最高益/記録更新」を会社開示・報道タイトルから拾うキーワード（越/日/英）
RECORD_KW = ("kỷ lục", "lập kỷ", "cao nhất lịch sử", "cao nhất từ", "record",
             "過去最高", "最高益", "最高益更新")


def compute_tags(card, buzz, median_today):
    """カードに立てる見どころタグ。数字と出典から機械的に。"""
    tags = []
    # 🏆 最高益: 会社開示・報道が記録更新を明言 or 純益が取得履歴でピーク（増益時のみ）
    titles = " ".join((s.get("title") or "") for s in card.get("sources", [])).lower()
    sourced = any(k.lower() in titles for k in RECORD_KW)
    if (sourced or card.get("npat_peak")) and (card.get("npat_yoy") or 0) > 0:
        tags.append({"label": "最高益", "icon": "🏆", "cls": "rec"})
    # 🔥 ホット: バズ急上昇 or 発表組内で突出して話題
    b = buzz.get(card["symbol"])
    if b and b.get("avg10"):
        ratio = b["today"] / b["avg10"] if b["avg10"] else 0
        hot = (ratio >= 2.0 and b["today"] >= 10) or \
              (median_today and b["today"] >= max(1.5 * median_today, 15))
        if hot:
            tags.append({"label": "ホット", "icon": "🔥", "cls": "hot"})
            card["buzz_today"] = b["today"]
            card["buzz_ratio"] = round(ratio, 1)
    # 💎 割安: PER・PBRとも業種平均未満
    if (card.get("per") is not None and card.get("per_ind") is not None and card["per"] < card["per_ind"]
            and card.get("pbr") is not None and card.get("pbr_ind") is not None and card["pbr"] < card["pbr_ind"]):
        tags.append({"label": "割安", "icon": "💎", "cls": "cheap"})
    return tags

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "data", "state.json")
COMPANIES = os.path.join(ROOT, "config", "companies.csv")
REPORTS_DIR = os.path.join(ROOT, "data", "reports")
NARR_CACHE = os.path.join(ROOT, "data", "narratives.json")
OUT = os.path.join(ROOT, "docs", "data", "cards.json")
THROTTLE = 0.3
GEMINI_GAP = 6.0  # 新規生成どうしの間隔（無料枠の分間制限対策）


def awaited_quarter(today):
    q = (today.month - 1) // 3 + 1
    return (today.year - 1, 4) if q == 1 else (today.year, q - 1)


def load_companies():
    m = {}
    if os.path.exists(COMPANIES):
        with open(COMPANIES, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                m[r["symbol"]] = r
    return m


def indicators(sym):
    """PER/PBR/ROE を業種平均つきで取得（取れなければ空）。"""
    try:
        data = fireant.financial_indicators(sym)
    except Exception:
        return {}
    out = {}
    for it in data or []:
        n = it.get("shortName") or it.get("name")
        if n in ("P/E", "P/B", "ROE"):
            out[n] = (it.get("value"), it.get("industryValue"))
        if n and "Lãi ròng" in n:  # 売上高純利益率の業種平均
            out["net_ind"] = it.get("industryValue")
    return out


def build_card(sym, comp, parsed, label, fx_rate, fx_asof):
    yy, qq = quarter_key(label)
    yoy = f"Q{qq}/{yy - 1}"
    idx = parsed["quarters"].index(label)
    qoq = parsed["quarters"][idx - 1] if idx > 0 else None

    sales = pick(parsed, "Sales", label)
    npat = pick(parsed, "NetProfit", label)
    op = pick(parsed, "OperatingProfit", label)

    def jpy(v):
        return None if v is None else v / fx_rate  # VND → JPY

    ind = indicators(sym)
    per = ind.get("P/E", (None, None))
    pbr = ind.get("P/B", (None, None))
    roe = ind.get("ROE", (None, None))
    npat_yoy = growth(npat, pick(parsed, "NetProfit", yoy))
    peg = round(per[0] / npat_yoy, 2) if (per[0] and npat_yoy and npat_yoy > 0) else None
    net_margin = round(npat / sales * 100, 1) if (npat and sales) else None
    op_margin = round(op / sales * 100, 1) if (op and sales) else None

    try:
        fund = fireant.fundamental(sym) or {}
    except Exception:
        fund = {}

    card = {
        "symbol": sym,
        "name": comp.get("name", sym),
        "intl": comp.get("intl", ""),
        "sector": comp.get("sector", ""),
        "tier": comp.get("tier", "tier2"),
        "quarter": label,
        "sales": sales, "sales_jpy": jpy(sales),
        "sales_yoy": growth(sales, pick(parsed, "Sales", yoy)),
        "npat": npat, "npat_jpy": jpy(npat),
        "npat_yoy": npat_yoy,
        "npat_qoq": growth(npat, pick(parsed, "NetProfit", qoq)) if qoq else None,
        "per": round(per[0], 1) if per[0] else None,
        "per_ind": round(per[1], 1) if per[1] else None,
        "pbr": round(pbr[0], 2) if pbr[0] else None,
        "pbr_ind": round(pbr[1], 2) if pbr[1] else None,
        "roe": round(roe[0], 1) if roe[0] else None,
        "roe_ind": round(roe[1], 1) if roe[1] else None,
        "peg": peg,
        "net_margin": net_margin,
        "net_margin_ind": round(ind["net_ind"], 1) if ind.get("net_ind") else None,
        "op_margin": op_margin,
        "foreign": round(fund.get("foreignOwnership", 0) * 100, 1) if fund.get("foreignOwnership") else None,
        "mktcap": fund.get("marketCap"),
        "mktcap_jpy": jpy(fund.get("marketCap")) if fund.get("marketCap") else None,
    }
    # 一言判定（機械）
    sy, ny = card["sales_yoy"], card["npat_yoy"]
    cheap = (card["per"] is not None and card["per_ind"] is not None and card["per"] < card["per_ind"])
    if ny is not None and ny >= 30 and (sy or 0) > 0:
        v = "◎ 増収大幅増益" + ("・株価は業種比で割安" if cheap else "")
    elif ny is not None and ny > 0 and (sy or 0) > 0:
        v = "○ 増収増益" + ("・割安" if cheap else "")
    elif ny is not None and ny < 0:
        v = "▲ 減益"
    else:
        v = "△ まちまち"
    card["verdict"] = v

    # 純利益が取得履歴（最大13四半期＝3年超）の中でピークか＝最高益判定の一材料
    npser = [x for x in (parsed["series"].get("NetProfit") or []) if x is not None]
    card["npat_peak"] = bool(npser and npat is not None and npat >= max(npser))
    card["hist_q"] = len(npser)  # 何四半期分で判定したか（正直さのため）
    return card


def main():
    today = jst_today()
    aw = awaited_quarter(today)
    label = f"Q{aw[1]}/{aw[0]}"

    state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    comps = load_companies()
    fx_rate, fx_asof = fxmod.vnd_per_jpy()
    try:
        buzz = load_buzz()
    except Exception as e:
        print(f"[warn] buzz: {e}")
        buzz = {}

    reporters = sorted(s for s, v in state.items() if v.get("latest") == label)
    print(f"対象四半期 {label} / 発表済 {len(reporters)}社 / FX 1JPY={fx_rate:.2f}VND ({fx_asof})")

    # 背景・見通しのキャッシュ（一度Geminiで生成したら再利用＝新規発表分だけ生成）
    cache = json.load(open(NARR_CACHE, encoding="utf-8")) if os.path.exists(NARR_CACHE) else {}
    generated = 0

    cards = []
    for i, sym in enumerate(reporters):
        path = os.path.join(REPORTS_DIR, f"{sym}.json")
        if not os.path.exists(path):
            continue
        parsed = parse_is(json.load(open(path, encoding="utf-8")))
        if not parsed or label not in parsed["quarters"]:
            continue
        # プレースホルダ（売上0・純益0）は発表とみなさず除外（CMG型データ異常の保険）
        if not pick(parsed, "Sales", label) and not pick(parsed, "NetProfit", label):
            print(f"  [skip] {sym} {label} は売上・純益ともゼロ（未提出プレースホルダ）")
            continue
        comp = comps.get(sym, {"name": sym, "sector": "", "tier": state[sym].get("tier", "tier2")})
        detected = state[sym].get("first_seen", {}).get(label, "")
        card = build_card(sym, comp, parsed, label, fx_rate, fx_asof)
        card["detected"] = "" if detected == "baseline" else detected

        # 背景・見通し: gemini成功分はキャッシュ再利用、未生成/前回フォールバックのみ生成
        key = f"{sym}:{label}"
        cached = cache.get(key)
        if cached and cached.get("method") == "gemini":
            narrative = cached
            tag = "cache"
        else:
            if generated:
                time.sleep(GEMINI_GAP)  # 新規生成の間だけ間隔を空ける
            try:
                srcs = narr.collect_sources(sym, label)
            except Exception as e:
                print(f"[warn] sources {sym}: {e}")
                srcs = []
            narrative = narr.build_narrative(card, srcs)
            cache[key] = narrative
            generated += 1
            tag = narrative.get("method", "?")
        card.update(narrative)
        cards.append(card)
        print(f"  [{i+1}/{len(reporters)}] {sym} {card['verdict']} 純利YoY={card['npat_yoy']} "
              f"出典{len(card.get('sources', []))}件 [{tag}]")
        time.sleep(THROTTLE)

    with open(NARR_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    print(f"新規生成 narrative: {generated}件（残りはキャッシュ再利用）")

    # 見どころタグ（発表組内でのバズ中央値を基準に）
    todays = sorted(buzz[c["symbol"]]["today"] for c in cards
                    if c["symbol"] in buzz and buzz[c["symbol"]].get("today") is not None)
    median_today = todays[len(todays) // 2] if todays else 0
    ntag = 0
    for c in cards:
        c["tags"] = compute_tags(c, buzz, median_today)
        ntag += len(c["tags"])
    print(f"タグ付与: {ntag}件（最高益/ホット/割安）")

    # 並び順: VN30優先→純利益YoY降順
    cards.sort(key=lambda c: (0 if c["tier"] == "tier1" else 1, -(c["npat_yoy"] or -999)))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = {
        "quarter": label,
        "updated": (datetime.datetime.now(datetime.timezone.utc)
                    + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M"),
        "fx_vnd_per_jpy": round(fx_rate, 2),
        "fx_asof": fx_asof,
        "count": len(cards),
        "cards": cards,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"cards.json 書出し: {len(cards)}社")


if __name__ == "__main__":
    main()
