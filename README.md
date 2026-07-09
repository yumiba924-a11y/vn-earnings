# vn-earnings ― VN決算ウォッチ

VN30＋VN100の四半期決算を毎日自動検知・解剖する観察システム。
「未発表の四半期は列自体が現れない」というFireAnt APIの仕様を利用し、
**新しい四半期列の出現＝決算発表** として diff 検知する（シグナル駆動・人手ゼロ）。

## 公開ページ（GitHub Pages / docs）

- `index.html` … 決算ボード（シーズン進捗・新着解剖カード・VN30/Tier2マトリクス・決算前バズ発火）
- `brief.html` … 日本語デイリーブリーフ（本日の新着＋進捗。数字は全て機械集計＝ファクト厳守）
- `calendar.html` … 決算カレンダー（規制期限の枠組み＋銘柄別の状態。実発表日時は検知後に自動記録）

## 三層ユニバース（config/universe.csv）

1. **tier1 = VN30** … フル解剖（YoY/QoQ・業種比較指標・バズ突合）
2. **tier2 = VN100の残り70** … 同じ検知・数字収集
3. **動的ウォッチ** … 未発表なのにバズ平常比≥2.5×の銘柄を「決算前発火」として表出
   （バズは [vn-morning-brief](https://github.com/yumiba924-a11y/vn-morning-brief) の公開CSVと突合）

## 自動運行

- `.github/workflows/earnings.yml` … 毎日 21:15 JST（当日夕方の開示）＋ 08:45 JST（深夜分）の2回。収集→検知→ボード/ブリーフ/カレンダー生成→bot自動コミット
- Secrets不要で全機能が動く。`GEMINI_API_KEY`（無料枠）を登録すると日本語「所感」段落が追加される
- 数字の言い換えはLLMにさせない（所感のみ・カードの数字が正）

## データ

- `data/state.json` … 銘柄ごとの最新判明四半期＋初検知日
- `data/events.jsonl` … 検知イベントの永久ログ（売上/純利益/YoY/QoQ/指標/バズ）
- `data/reports/{SYM}.json` … 四半期損益の生スナップショット（6期分）

## ローカル実行（Windows・Python無し環境）

```bash
cd "/c/Users/Shogo.Yumiba/Desktop/VN決算"
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run --python 3.12 python scripts/earnings_collector.py
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run --python 3.12 python scripts/build_site.py
```

初回のみ `--baseline`（現状焼き付け・イベント発行なし）:

```bash
uv run --python 3.12 python scripts/earnings_collector.py --baseline
```

## 設計メモ

- 伸び率は前年同期が赤字・ゼロ・欠損なら**非表示**（誤解を招く率を出さない）
- 全銘柄の50%以上でAPIエラー時のみ非0終了（＝Actionが赤くなって気付ける）
- 依存は標準ライブラリのみ（requirements不要・供給網リスク最小）
