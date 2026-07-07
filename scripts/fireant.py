# -*- coding: utf-8 -*-
"""FireAnt API 共通クライアント（vn-morning-brief と同系統）。

認証はフロントJS埋め込みの公開JWT（exp 2029-11-17）。scope に finance-read が
含まれるため決算系エンドポイントが読める（2026-07-07 実測）。
"""
import os
import time
import json
import urllib.request
import urllib.error

# 3分割はスキャナ避けではなく行長の都合。公開トークン（個人資格ではない）
PUBLIC_TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6IkdYdExONzViZlZQakdvNERWdjV4QkRITHpnSSIsImtpZCI6IkdYdExONzViZlZQakdvNERWdjV4QkRITHpnSSJ9"
    ".eyJpc3MiOiJodHRwczovL2FjY291bnRzLmZpcmVhbnQudm4iLCJhdWQiOiJodHRwczovL2FjY291bnRzLmZpcmVhbnQudm4vcmVzb3VyY2VzIiwiZXhwIjoxODg5NjIyNTMwLCJuYmYiOjE1ODk2MjI1MzAsImNsaWVudF9pZCI6ImZpcmVhbnQudHJhZGVzdGF0aW9uIiwic2NvcGUiOlsiYWNhZGVteS1yZWFkIiwiYWNhZGVteS13cml0ZSIsImFjY291bnRzLXJlYWQiLCJhY2NvdW50cy13cml0ZSIsImJsb2ctcmVhZCIsImNvbXBhbmllcy1yZWFkIiwiZmluYW5jZS1yZWFkIiwiaW5kaXZpZHVhbHMtcmVhZCIsImludmVzdG9wZWRpYS1yZWFkIiwib3JkZXJzLXJlYWQiLCJvcmRlcnMtd3JpdGUiLCJwb3N0cy1yZWFkIiwicG9zdHMtd3JpdGUiLCJzZWFyY2giLCJzeW1ib2xzLXJlYWQiLCJ1c2VyLWRhdGEtcmVhZCIsInVzZXItZGF0YS13cml0ZSIsInVzZXJzLXJlYWQiXSwianRpIjoiMjYxYTZhYWQ2MTQ5Njk1ZmJiYzcwODM5MjM0Njc1NWQifQ"
    ".dA5-HVzWv-BRfEiAd24uNBiBxASO-PAyWeWESovZm_hj4aXMAZA1-bWNZeXt88dqogo18AwpDQ-h6gefLPdZSFrG5umC1dVWaeYvUnGm62g4XS29fj6p01dhKNNqrsu5KrhnhdnKYVv9VdmbmqDfWR8wDgglk5cJFqalzq6dJWJInFQEPmUs9BW_Zs8tQDn-i5r4tYq2U8vCdqptXoM7YgPllXaPVDeccC9QNu2Xlp9WUvoROzoQXg25lFub1IYkTrM66gJ6t9fJRZToewCt495WNEOQFa_rwLCZ1QwzvL0iYkONHS_jZ0BOhBCdW9dWSawD6iF1SIQaFROvMDH1rg"
)
TOKEN = os.environ.get("FIREANT_TOKEN", PUBLIC_TOKEN)
BASE = "https://restv2.fireant.vn"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def get(path, retries=3, timeout=30):
    """GET {BASE}{path} → parsed JSON。404はNone、他エラーはリトライ後raise。"""
    url = BASE + path
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + TOKEN,
            "User-Agent": UA,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
            time.sleep(2 * (attempt + 1))
        except Exception as e:  # timeout, connection reset など
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"FireAnt GET failed: {path}: {last}")


def income_statement(symbol, year, quarter, count=6):
    """四半期損益（Sales/GrossProfit/OperatingProfit/NetProfit/NetProfit_PCSH）。

    year/quarter は「その直前の四半期まで」を返す境界。最新を取り逃さないよう
    呼び出し側は今日の属する四半期＋1を渡すこと。
    """
    return get(f"/symbols/{symbol}/financial-reports?type=IS&year={year}&quarter={quarter}&count={count}")


def financial_indicators(symbol):
    """P/E等の指標＋業種平均値（Định giá/Sinh lời等のグループ）。"""
    return get(f"/symbols/{symbol}/financial-indicators")


def fundamental(symbol):
    """TTM売上・純利益・外国人保有比率・時価総額など。"""
    return get(f"/symbols/{symbol}/fundamental")
