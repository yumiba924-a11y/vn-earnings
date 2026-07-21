# -*- coding: utf-8 -*-
"""背景・見通しの「会社発表ベース」生成（L1）。

各銘柄について FireAnt の type=1 投稿から
  ・会社の公式開示「利益変動説明（giải trình）」（postSource=HSX）
  ・主要報道の要約1〜2本
を集め、その文章だけを材料に Gemini で背景・見通しを生成する（勝手に作文しない）。
GEMINI_API_KEY が無い/失敗時は、数字から機械的に導ける背景にフォールバック（壊れない）。
"""
import json
import os
import re
import urllib.request

import fireant

STRIP = re.compile(r"<[^>]+>")


def _clean(h):
    return STRIP.sub(" ", h or "").replace("&nbsp;", " ").replace("​", "").strip()


def _posts(sym, offset=0, limit=50, typ=1):
    return fireant.get(f"/posts?symbol={sym}&type={typ}&offset={offset}&limit={limit}") or []


def collect_sources(sym, quarter, since="2026-01-01", max_news=2):
    """開示(giải trình)＋報道の要約スニペットを集める。
    quarter 例 'Q2/2026' → 越語検索キー 'quý 2/2026'/'quý II'。"""
    qn = quarter.split("/")[0][1:]  # '2'
    kw_earn = re.compile(r"(giải trình|kết quả kinh doanh|báo cáo tài chính|BCTC|KQKD|"
                         r"lợi nhuận|lãi|doanh thu)", re.I)
    disclosures, news = [], []
    for off in (0, 50, 100):
        batch = _posts(sym, off)
        if not batch:
            break
        for p in batch:
            d = (p.get("date") or "")[:10]
            if d < since:
                return _finish(sym, disclosures, news, max_news)
            title = p.get("title") or ""
            srcobj = p.get("postSource") or {}
            is_hsx = srcobj.get("postSourceID") == 1
            body = _clean(p.get("content")) or _clean(p.get("description")) \
                or _clean(p.get("linkDescription"))
            item = {"date": p.get("date", "")[:16], "source": srcobj.get("name", ""),
                    "title": title.strip(), "text": body[:500]}
            if is_hsx and re.search(r"giải trình", title, re.I):
                disclosures.append(item)          # 会社の公式説明（最優先）
            elif kw_earn.search(title) and not is_hsx and body:
                news.append(item)                 # 報道の要約
    return _finish(sym, disclosures, news, max_news)


def _finish(sym, disclosures, news, max_news):
    return (disclosures[:1] + news[:max_news])


def _mechanical_background(card):
    """出典が無い/LLM無しのときの、数字だけから言える背景（作文しない）。"""
    sy, ny, qoq = card.get("sales_yoy"), card.get("npat_yoy"), card.get("npat_qoq")
    bits = []
    if ny is not None and sy is not None:
        if ny > sy:
            bits.append(f"純利益の伸び（{ny:+.1f}%）が売上（{sy:+.1f}%）を上回り、利益率の改善がうかがえる")
        elif ny < sy:
            bits.append(f"売上（{sy:+.1f}%）ほどには純利益（{ny:+.1f}%）が伸びず、費用増の可能性")
        else:
            bits.append(f"売上・純利益とも約{sy:+.1f}%")
    if card.get("net_margin") is not None:
        bits.append(f"売上高純利益率{card['net_margin']:.1f}%")
    if qoq is not None:
        bits.append(f"前期比{qoq:+.1f}%")
    return "（数字ベースの自動要約）" + "、".join(bits) + "。事業要因の詳細は開示・報道の反映待ち。"


def _gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"responseMimeType": "application/json"}}).encode()
    for model in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"):
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={key}")
        try:
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
            txt = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            txt = re.sub(r"^```json|```$", "", txt).strip()
            return json.loads(txt)
        except Exception as e:
            print(f"[warn] gemini {model} ({e})")
    return None


def build_narrative(card, sources):
    """sources（開示＋報道）だけを材料に background/outlook を生成。
    戻り値: {'background':str,'outlook':str,'sources':[{source,date,title}]}"""
    src_meta = [{"source": s["source"], "date": s["date"], "title": s["title"]} for s in sources]

    if sources:
        snip = "\n".join(f"- [{s['source']} {s['date']}] {s['title']}: {s['text']}" for s in sources)
        prompt = (
            "あなたはベトナム株の決算担当。以下は当該企業の『会社の公式開示（giải trình＝利益変動説明）』と"
            "『主要報道の要約』。この資料と与えた数値のみを根拠に、日本語で JSON を返す。"
            "資料に無い事実の創作・具体数値の捏造は禁止。誇張せず、断定は控えめに。\n"
            f"企業: {card['name']}（{card['symbol']}・{card['sector']}）{card['quarter']}\n"
            f"数値: 売上 {card.get('sales_yoy')}%(YoY), 純利益 {card.get('npat_yoy')}%(YoY)/"
            f"{card.get('npat_qoq')}%(QoQ), 売上高純利益率 {card.get('net_margin')}%, "
            f"PER {card.get('per')}(業種{card.get('per_ind')}), ROE {card.get('roe')}%\n"
            f"資料:\n{snip}\n\n"
            '返す形式: {"background":"背景を2〜3文（会社開示・報道の内容を優先して反映）",'
            '"outlook":"見通し・論点を1〜2文"}')
        out = _gemini(prompt)
        if out and out.get("background"):
            return {"background": out["background"].strip(),
                    "outlook": (out.get("outlook") or "").strip(),
                    "sources": src_meta}

    # フォールバック（出典なし or LLM不可）
    return {"background": _mechanical_background(card),
            "outlook": "開示・報道の反映待ち。次に業種内の比較と通期見通しを確認。",
            "sources": src_meta}
