# -*- coding: utf-8 -*-
"""VN決算ウォッチ 出力生成（docs/index.html=決算ボード, docs/brief.html=日本語ブリーフ）。

数字は全てFireAnt取得値からの機械計算（テンプレ差込）＝ファクト厳守。
GEMINI_API_KEY があれば「所感」段落だけLLMが書く（無くても壊れない）。
"""
import datetime
import glob
import html
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from earnings_collector import (parse_is, latest_reported, pick, growth,
                                quarter_key, load_buzz, jst_today)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "data", "state.json")
EVENTS = os.path.join(ROOT, "data", "events.jsonl")
REPORTS_DIR = os.path.join(ROOT, "data", "reports")
DOCS = os.path.join(ROOT, "docs")
BUZZ_FIRE = 2.5  # 平常比の暫定発火閾値（morning-brief準拠・正式値はdata-drivenで後決め）


# ---------- data ----------

def awaited_quarter(today):
    """いま市場が待っている決算＝直前に終わった暦四半期。"""
    q = (today.month - 1) // 3 + 1
    y = today.year
    return (y - 1, 4) if q == 1 else (y, q - 1)


def q_label(yq):
    return f"Q{yq[1]}/{yq[0]}"


def load_all():
    state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    events = []
    if os.path.exists(EVENTS):
        with open(EVENTS, encoding="utf-8") as f:
            events = [json.loads(l) for l in f if l.strip()]
    reports = {}
    for p in glob.glob(os.path.join(REPORTS_DIR, "*.json")):
        sym = os.path.splitext(os.path.basename(p))[0]
        parsed = parse_is(json.load(open(p, encoding="utf-8")))
        if parsed:
            reports[sym] = parsed
    return state, events, reports


def row_metrics(parsed, label):
    """指定四半期の 売上/純利益/YoY を機械計算。"""
    yy, qq = quarter_key(label)
    yoy_label = f"Q{qq}/{yy - 1}"
    sales = pick(parsed, "Sales", label)
    npat = pick(parsed, "NetProfit", label)
    return {
        "sales": sales,
        "npat": npat,
        "sales_yoy": growth(sales, pick(parsed, "Sales", yoy_label)),
        "npat_yoy": growth(npat, pick(parsed, "NetProfit", yoy_label)),
    }


# ---------- formatting ----------

def fmt_vnd(v):
    """VND→日本語表記。1e12以上=兆、未満=十億(tỷ相当)。"""
    if v is None:
        return "—"
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e12:
        return f"{sign}{a / 1e12:,.2f}兆"
    return f"{sign}{a / 1e9:,.0f}十億"


def fmt_pct(v, signed=True):
    if v is None:
        return "—"
    s = f"{v:+.1f}%" if signed else f"{v:.1f}%"
    return s


def yoy_class(v):
    if v is None:
        return "na"
    if v >= 30:
        return "up2"
    if v >= 0:
        return "up1"
    if v > -30:
        return "dn1"
    return "dn2"


def esc(s):
    return html.escape(str(s))


# ---------- gemini (optional) ----------

def gemini_comment(day_events, progress):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key or not day_events:
        return None
    lines = [
        f"{e['symbol']} {e['quarter']}: 売上{fmt_vnd(e.get('sales'))}VND({fmt_pct(e.get('sales_yoy'))}), "
        f"純利益{fmt_vnd(e.get('npat'))}VND(YoY {fmt_pct(e.get('npat_yoy'))}, QoQ {fmt_pct(e.get('npat_qoq'))})"
        for e in day_events
    ]
    prompt = (
        "あなたはベトナム株の決算ウォッチ担当。以下は本日検知したVN上場企業の四半期決算の機械集計。"
        "日本の読者向けに、全体観と注目点を日本語3〜4文で。数字の言い換え・新数値の創作は禁止、"
        "与えた数字のみ引用可。誇張なし・断定は控えめに。\n"
        f"シーズン進捗: VN30={progress['vn30_done']}/30, ユニバース全体={progress['all_done']}/{progress['all_n']}\n"
        + "\n".join(lines)
    )
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    for model in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"):
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={key}")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            if text:
                return text
        except Exception as e:
            print(f"[warn] gemini {model}: {e}")
    return None


# ---------- html ----------

CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--tx:#e6edf3;--dim:#8b949e;
--green:#3fb950;--green2:#56d364;--red:#f85149;--red2:#ff7b72;--amber:#d29922;--blue:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);
font-family:'Segoe UI','Hiragino Sans','Noto Sans JP',sans-serif;font-size:14px;line-height:1.6}
.wrap{max-width:1080px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0 2px}h2{font-size:15px;margin:22px 0 8px;color:var(--blue);
border-left:3px solid var(--blue);padding-left:8px}
.sub{color:var(--dim);font-size:12px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px}
.card h3{margin:0 0 6px;font-size:16px}
.kv{display:flex;justify-content:space-between;margin:2px 0;font-size:13px}
.kv .k{color:var(--dim)}
table{border-collapse:collapse;width:100%;font-size:13px}
th{color:var(--dim);font-weight:600;text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
td{padding:5px 8px;border-bottom:1px solid #21262d;text-align:right;font-variant-numeric:tabular-nums}
.sym{font-weight:700}
.up1{color:var(--green)}.up2{color:var(--green2);font-weight:700}
.dn1{color:var(--red)}.dn2{color:var(--red2);font-weight:700}.na{color:var(--dim)}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;border:1px solid var(--line)}
.pill.done{color:var(--green);border-color:var(--green)}
.pill.wait{color:var(--dim)}
.fire{color:var(--amber);font-weight:700}
.bar{background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:10px 14px;display:flex;gap:24px;flex-wrap:wrap;margin:10px 0}
.bar .n{font-size:22px;font-weight:700}.bar .l{font-size:11px;color:var(--dim)}
.note{color:var(--dim);font-size:12px;margin:8px 0}
.scroll{overflow-x:auto}
a{color:var(--blue);text-decoration:none}
.gem{background:#161b2f;border:1px solid #2b3a67;border-radius:8px;padding:12px;margin:10px 0}
"""


def buzz_html(b):
    if not b:
        return '<span class="na">—</span>'
    avg = b.get("avg10") or 0
    today = b.get("today") or 0
    ratio = (today / avg) if avg else None
    r = f"×{ratio:.1f}" if ratio is not None else "—"
    fire = ' <span class="fire">▲発火</span>' if (ratio or 0) >= BUZZ_FIRE else ""
    return f"clean {today}件（10日平均{avg}・平常比{r}）{fire}"


def event_card(e):
    ind = e.get("indicators") or {}
    ind_rows = ""
    for k in ("P/E", "P/B", "ROE", "ROA"):
        if k in ind:
            v, iv = ind[k].get("value"), ind[k].get("industry")
            if v is None:
                continue
            # ROE/ROAはAPIが最初から%値を返す（VCB実測: ROE=16.37）
            unit = "%" if k in ("ROE", "ROA") else ""
            ivs = f"（業種 {iv:.1f}{unit}）" if iv is not None else ""
            ind_rows += f'<div class="kv"><span class="k">{k}</span><span>{v:.1f}{unit}{ivs}</span></div>'
    npat_note = ""
    if e.get("npat_yoy") is None and e.get("npat") is not None:
        npat_note = '<div class="note">※前年同期が赤字等のため伸び率は非表示（絶対値で判断）</div>'
    return f"""<div class="card">
<h3>{esc(e['symbol'])} <span class="sub">{esc(e['quarter'])}・{esc(e['detected'])}検知・{'VN30' if e['tier']=='tier1' else 'Tier2'}</span></h3>
<div class="kv"><span class="k">売上</span><span>{fmt_vnd(e.get('sales'))}VND <span class="{yoy_class(e.get('sales_yoy'))}">{fmt_pct(e.get('sales_yoy'))}</span></span></div>
<div class="kv"><span class="k">純利益</span><span>{fmt_vnd(e.get('npat'))}VND <span class="{yoy_class(e.get('npat_yoy'))}">YoY {fmt_pct(e.get('npat_yoy'))}</span>・QoQ {fmt_pct(e.get('npat_qoq'))}</span></div>
{ind_rows}
<div class="kv"><span class="k">バズ</span><span>{buzz_html(e.get('buzz'))}</span></div>
{npat_note}
</div>"""


def matrix_rows(symbols, state, reports, awaited_label):
    rows = ""
    done = 0
    for sym in symbols:
        st = state.get(sym, {})
        latest = st.get("latest")
        reported = latest == awaited_label
        det = st.get("first_seen", {}).get(awaited_label, "")
        det = "" if det == "baseline" else det
        if reported:
            done += 1
            m = row_metrics(reports[sym], awaited_label) if sym in reports else {}
            rows += (f'<tr><td class="sym">{esc(sym)}</td>'
                     f'<td><span class="pill done">発表済</span></td>'
                     f'<td>{esc(det)}</td>'
                     f'<td>{fmt_vnd(m.get("sales"))}</td>'
                     f'<td class="{yoy_class(m.get("sales_yoy"))}">{fmt_pct(m.get("sales_yoy"))}</td>'
                     f'<td>{fmt_vnd(m.get("npat"))}</td>'
                     f'<td class="{yoy_class(m.get("npat_yoy"))}">{fmt_pct(m.get("npat_yoy"))}</td></tr>')
        else:
            rows += (f'<tr><td class="sym">{esc(sym)}</td>'
                     f'<td><span class="pill wait">未</span></td>'
                     f'<td class="na">{esc(latest or "—")}まで</td>'
                     f'<td class="na">—</td><td class="na">—</td><td class="na">—</td><td class="na">—</td></tr>')
    return rows, done


def page(title, body, updated):
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{esc(title)}</title><style>{CSS}</style></head>
<body><div class="wrap">{body}
<p class="note">最終更新 {esc(updated)} JST ／ データ源: FireAnt（公開API・機械集計）／ バズ: <a href="https://yumiba924-a11y.github.io/vn-morning-brief/">vn-morning-brief</a> ／ 伸び率は前年同期が赤字・欠損の場合非表示 ／ 投資判断は自己責任</p>
</div></body></html>"""


def main():
    today = jst_today()
    now = (datetime.datetime.now(datetime.timezone.utc)
           + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")
    aw = awaited_quarter(today)
    aw_label = q_label(aw)

    state, events, reports = load_all()
    buzz = load_buzz()

    tier1 = sorted(s for s, v in state.items() if v.get("tier") == "tier1")
    tier2 = sorted(s for s, v in state.items() if v.get("tier") == "tier2")

    t1_rows, t1_done = matrix_rows(tier1, state, reports, aw_label)
    t2_rows, t2_done = matrix_rows(tier2, state, reports, aw_label)
    progress = {"vn30_done": t1_done, "all_done": t1_done + t2_done,
                "all_n": len(tier1) + len(tier2)}

    # 直近イベント（新しい順・最大30）
    recent = sorted(events, key=lambda e: (e["detected"], e["symbol"]), reverse=True)[:30]
    cards = "".join(event_card(e) for e in recent) or '<p class="note">検知イベントはまだありません（ベースライン監視中）。</p>'

    # 決算前バズ発火（未発表×平常比≥閾値）
    fire_rows = ""
    for sym in tier1 + tier2:
        if state.get(sym, {}).get("latest") == aw_label:
            continue
        b = buzz.get(sym)
        if not b or not b.get("avg10"):
            continue
        ratio = b["today"] / b["avg10"]
        if ratio >= BUZZ_FIRE and b["today"] >= 5:
            fire_rows += (f'<tr><td class="sym">{esc(sym)}</td>'
                          f'<td>{"VN30" if sym in tier1 else "Tier2"}</td>'
                          f'<td>{b["today"]}件</td><td>{b["avg10"]}</td>'
                          f'<td class="fire">×{ratio:.1f} ▲</td></tr>')
    fire_tbl = (f'<div class="scroll"><table><tr><th>銘柄</th><th>層</th><th>本日clean</th>'
                f'<th>10日平均</th><th>平常比</th></tr>{fire_rows}</table></div>'
                if fire_rows else '<p class="note">本日の発火はありません。</p>')

    board_body = f"""<h1>VN決算ウォッチ｜{esc(aw_label)} シーズン</h1>
<div class="sub">未発表四半期は列が現れない仕様を利用し、新列の出現＝発表として毎日自動検知</div>
<div class="bar">
<div><div class="n">{t1_done}<span class="sub">/30</span></div><div class="l">VN30 発表済</div></div>
<div><div class="n">{progress['all_done']}<span class="sub">/{progress['all_n']}</span></div><div class="l">ユニバース全体</div></div>
<div><div class="n">{len([e for e in events if e['detected'] == str(today)])}</div><div class="l">本日の新規検知</div></div>
</div>
<h2>新着決算（検知順）</h2><div class="cards">{cards}</div>
<h2>決算前バズ発火（未発表なのに騒がれている銘柄）</h2>{fire_tbl}
<h2>VN30 マトリクス</h2>
<div class="scroll"><table><tr><th>銘柄</th><th>状態</th><th>検知日</th><th>売上</th><th>売上YoY</th><th>純利益</th><th>純利YoY</th></tr>{t1_rows}</table></div>
<h2>Tier2（VN100残り）</h2>
<div class="scroll"><table><tr><th>銘柄</th><th>状態</th><th>検知日</th><th>売上</th><th>売上YoY</th><th>純利益</th><th>純利YoY</th></tr>{t2_rows}</table></div>
<p class="note">単位: VND。兆=10^12 / 十億=10^9（越語のtỷ）。<a href="brief.html">日本語ブリーフ →</a></p>"""

    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(page(f"VN決算ウォッチ {aw_label}", board_body, now))

    # ---------- brief ----------
    day_events = [e for e in events if e["detected"] == str(today)]
    if day_events:
        items = ""
        for e in sorted(day_events, key=lambda x: (x["tier"], x["symbol"])):
            items += event_card(e)
        new_sec = f'<div class="cards">{items}</div>'
    else:
        new_sec = '<p class="note">本日の新着決算はありません。</p>'

    gem = gemini_comment(day_events, progress)
    gem_sec = (f'<div class="gem"><b>所感（AI編集・数字は上記カードが正）</b><br>{esc(gem)}</div>'
               if gem else "")

    brief_body = f"""<h1>VN決算ブリーフ｜{esc(str(today))}</h1>
<div class="sub">{esc(aw_label)}決算シーズン ― 本日の新着と進捗（数字は全てFireAnt機械集計）</div>
<div class="bar">
<div><div class="n">{len(day_events)}</div><div class="l">本日の新着決算</div></div>
<div><div class="n">{t1_done}<span class="sub">/30</span></div><div class="l">VN30 発表済</div></div>
<div><div class="n">{progress['all_done']}<span class="sub">/{progress['all_n']}</span></div><div class="l">ユニバース全体</div></div>
</div>
<h2>本日の新着決算</h2>{new_sec}
{gem_sec}
<h2>決算前バズ発火</h2>{fire_tbl}
<p class="note"><a href="index.html">← 決算ボード（全銘柄マトリクス）</a></p>"""

    with open(os.path.join(DOCS, "brief.html"), "w", encoding="utf-8") as f:
        f.write(page(f"VN決算ブリーフ {today}", brief_body, now))

    print(f"built: index.html({t1_done}/30 reported) brief.html({len(day_events)} new, gemini={'on' if gem else 'off'})")


if __name__ == "__main__":
    main()
