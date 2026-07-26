"""
watchlistテーブルに全資産クラスの銘柄をupsertするスクリプト。

前提:
  - supabase_setup.sql を先にSupabase側で実行済みであること
  - ark_universe.json が同じディレクトリにあること(fetch_ark_universe.pyの出力)
  - 環境変数 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY が設定されていること

実行:
  pip install supabase
  export SUPABASE_URL="https://xxxx.supabase.co"
  export SUPABASE_SERVICE_ROLE_KEY="ey..."
  python3 seed_watchlist.py
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

# スクリプトと同じディレクトリの .env を明示的に指定して読み込む
ENV_PATH = Path(__file__).resolve().parent / ".env"
loaded = load_dotenv(dotenv_path=ENV_PATH)

if not loaded:
    print(f"[WARN] .env が見つかりませんでした: {ENV_PATH}")
elif "SUPABASE_URL" not in os.environ:
    print(f"[WARN] .env は読み込めましたが SUPABASE_URL が見つかりません。"
          f"ファイルの中身を確認してください: {ENV_PATH}")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

ARK_UNIVERSE_PATH = Path("ark_universe.json")

# --- 固定の監視対象(ema_signal.py と同じ内容を使う) ---
FX_TICKERS = {
    "USDJPY": "USDJPY=X",
    "EURJPY": "EURJPY=X",
    "GBPJPY": "GBPJPY=X",
}

FUTURES_TICKERS = {
    "SP500":     "ES=F",
    "NIKKEI225": "NIY=F",
    "GOLD":      "GC=F",
    "SILVER":    "SI=F",
    "PLATINUM":  "PL=F",
    "CORN":      "ZC=F",
    "SOYBEANS":  "ZS=F",
    "WTI":       "CL=F",
}

CRYPTO_TICKERS = {
    "BTCJPY": "BTC-JPY",
}


def load_ark_universe() -> dict[str, str]:
    if not ARK_UNIVERSE_PATH.exists():
        print(f"[WARN] {ARK_UNIVERSE_PATH} が見つかりません。ARK銘柄はスキップします。")
        return {}
    return json.loads(ARK_UNIVERSE_PATH.read_text())


def build_rows() -> list[dict]:
    rows = []

    for symbol, ticker in FX_TICKERS.items():
        rows.append({"symbol": symbol, "ticker": ticker, "asset_class": "fx"})

    for symbol, ticker in FUTURES_TICKERS.items():
        rows.append({"symbol": symbol, "ticker": ticker, "asset_class": "futures"})

    for symbol, ticker in CRYPTO_TICKERS.items():
        rows.append({"symbol": symbol, "ticker": ticker, "asset_class": "crypto"})

    ark_universe = load_ark_universe()
    for symbol, ticker in ark_universe.items():
        rows.append({"symbol": symbol, "ticker": ticker, "asset_class": "stock"})

    return rows


def main():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    rows = build_rows()

    print(f"upsert対象: {len(rows)}件")

    # 大量件数を一度に送るとタイムアウトしやすいので100件ずつに分割
    batch_size = 100
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        client.table("trend_watchlist").upsert(batch, on_conflict="symbol").execute()
        print(f"  {i + len(batch)}/{len(rows)} 件 upsert完了")

    print("完了しました。")


if __name__ == "__main__":
    main()
