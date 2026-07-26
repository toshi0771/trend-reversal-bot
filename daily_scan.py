"""
日次スキャンのメイン処理。

フロー:
  1. Supabase の trend_watchlist から監視対象銘柄を全件取得
  2. 各銘柄を yfinance で取得し EMA判定(ema_signal.py のロジックを再利用)
  3. trend_signal_state の現在の is_touched と比較し、
     「False → True」に変わった銘柄だけを新規タッチとして検出
  4. trend_signal_state を更新(タッチ状態が変わった場合のみ)
  5. 新規タッチ銘柄のリストを返す(LINE通知スクリプトに渡す想定)

状態遷移のルール:
  - 前回 False → 今回 True  : 新規タッチ。通知対象。DBを True に更新。
  - 前回 True  → 今回 True  : 既にタッチ済み。通知しない。DBはそのまま。
  - 前回 True  → 今回 False : 条件から外れた。DBを False に戻す
                              (次回また条件を満たした時に再通知できるようにするため)
  - 前回 False → 今回 False : 何もしない。

実行:
  pip install supabase python-dotenv yfinance pandas
  python3 daily_scan.py
"""

import os
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

from ema_signal import fetch_ohlc, judge_trend_reversal

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]


def load_watchlist(client) -> list[dict]:
    """trend_watchlist から is_active=true の銘柄を全件取得する。"""
    resp = client.table("trend_watchlist").select("symbol, ticker, asset_class").eq("is_active", True).execute()
    return resp.data


def load_signal_state(client) -> dict[str, bool]:
    """trend_signal_state から現在のタッチ状態を {symbol: is_touched} で取得する。"""
    resp = client.table("trend_signal_state").select("symbol, is_touched").execute()
    return {row["symbol"]: row["is_touched"] for row in resp.data}


def run_daily_scan() -> list[dict]:
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    watchlist = load_watchlist(client)
    prev_state = load_signal_state(client)
    print(f"監視対象: {len(watchlist)}件")

    newly_touched: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for item in watchlist:
        symbol = item["symbol"]
        ticker = item["ticker"]

        df = fetch_ohlc(ticker)
        if df is None:
            continue

        latest = judge_trend_reversal(df)
        if latest is None:
            print(f"[SKIP] データ不足: {symbol}({ticker})")
            continue

        current_touched = bool(latest["is_touched"])
        was_touched = prev_state.get(symbol, False)

        if current_touched and not was_touched:
            # 新規タッチ: 通知対象 + DB更新
            print(f"[NEW TOUCH] {symbol}")
            client.table("trend_signal_state").update({
                "is_touched": True,
                "last_touched_at": now,
                "last_checked_at": now,
            }).eq("symbol", symbol).execute()

            newly_touched.append({
                "symbol": symbol,
                "ticker": ticker,
                "asset_class": item["asset_class"],
                "close": float(latest["close"]),
                "ema20": float(latest["ema20"]),
                "ema50": float(latest["ema50"]),
                "ema50_2m_ago": float(latest["ema50_2m_ago"]),
            })

        elif not current_touched and was_touched:
            # 条件から外れた: リセット(次回また通知できるようにする)
            print(f"[RESET] {symbol}")
            client.table("trend_signal_state").update({
                "is_touched": False,
                "last_checked_at": now,
            }).eq("symbol", symbol).execute()

        else:
            # 状態変化なし: last_checked_at だけ更新
            client.table("trend_signal_state").update({
                "last_checked_at": now,
            }).eq("symbol", symbol).execute()

    print(f"新規タッチ: {len(newly_touched)}件")
    return newly_touched


if __name__ == "__main__":
    touched = run_daily_scan()
    for t in touched:
        print(f"  - {t['symbol']} ({t['asset_class']}) close={t['close']:.4f}")
