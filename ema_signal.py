"""
トレンド転換シグナル判定モジュール

手法:
  50EMA(today) <= 50EMA(2ヶ月前)  かつ  Close(today) >= 20EMA(today)
を満たした銘柄を「タッチ」として検出する。

注意:
  - このスクリプトはサンドボックス環境のネットワーク制限により
    Yahoo Financeへの実アクセスをテストできていません。
    ロジック自体はダミーデータで検証済みです。
    ご自身の環境(ローカル/GitHub Actions)で実データ取得を確認してください。
"""

import pandas as pd
import yfinance as yf
from dataclasses import dataclass
from typing import Optional


# ------------------------------------------------------------
# 監視対象ティッカー定義
# ------------------------------------------------------------
# 各シンボルはYahoo Finance表記に準拠。実際に yfinance で取得できるか
# 事前に必ず動作確認してください(特に先物・BTCJPYは表記ゆれの可能性あり)。

FX_TICKERS = {
    "USDJPY": "USDJPY=X",
    "EURJPY": "EURJPY=X",
    "GBPJPY": "GBPJPY=X",   # 「ぽんど円」想定。違う通貨ペアなら要修正
}

FUTURES_TICKERS = {
    "SP500":     "ES=F",   # S&P500先物
    "NIKKEI225": "NIY=F",  # 日経225先物(取得できない場合は "^N225" を検討)
    "GOLD":      "GC=F",
    "SILVER":    "SI=F",
    "PLATINUM":  "PL=F",
    "CORN":      "ZC=F",
    "SOYBEANS":  "ZS=F",
    "WTI":       "CL=F",
}

CRYPTO_TICKERS = {
    "BTCJPY": "BTC-JPY",   # 取得できない場合は BTC-USD × USDJPY=X で合成が必要
}

# 米国株(ARK 13F由来)は動的に生成されるためここでは空。
# 別スクリプト(CUSIP→ティッカー変換の結果)から読み込んで統合する想定。
ARK_TICKERS: dict[str, str] = {}


# ------------------------------------------------------------
# EMA判定ロジック
# ------------------------------------------------------------

@dataclass
class SignalResult:
    symbol: str
    ticker: str
    close: float
    ema20: float
    ema50: float
    ema50_2m_ago: float
    is_touched: bool


def fetch_ohlc(ticker: str, period: str = "1y", interval: str = "1d") -> Optional[pd.DataFrame]:
    """yfinanceでOHLCを取得する。取得失敗時はNoneを返す。"""
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval)
        if df.empty:
            print(f"[WARN] データが空: {ticker}")
            return None
        return df
    except Exception as e:
        print(f"[ERROR] 取得失敗: {ticker} - {e}")
        return None


def judge_trend_reversal(df: pd.DataFrame, lookback_days: int = 42) -> Optional[pd.Series]:
    """
    EMAを計算し、直近行の判定結果を返す。

    lookback_days: 「2ヶ月前」を営業日換算した日数。
                   為替(土日以外毎日)と株式・先物(取引所カレンダー)で
                   厳密には営業日数が異なるため、資産クラスごとに
                   調整したい場合はここを可変にしてください。
    """
    if len(df) < 50 + lookback_days:
        # EMA50 + 2ヶ月前参照に必要な最低データ量に満たない
        return None

    close = df["Close"]
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema50_2m_ago = ema50.shift(lookback_days)

    latest = pd.Series({
        "close": close.iloc[-1],
        "ema20": ema20.iloc[-1],
        "ema50": ema50.iloc[-1],
        "ema50_2m_ago": ema50_2m_ago.iloc[-1],
    })

    if pd.isna(latest["ema50_2m_ago"]):
        return None

    latest["is_touched"] = bool(
        (latest["ema50"] <= latest["ema50_2m_ago"]) and (latest["close"] >= latest["ema20"])
    )
    return latest


def scan_universe(universe: dict[str, str], lookback_days: int = 42) -> list[SignalResult]:
    """銘柄辞書 {表示名: ティッカー} を全件スキャンし、結果一覧を返す。"""
    results: list[SignalResult] = []

    for symbol, ticker in universe.items():
        df = fetch_ohlc(ticker)
        if df is None:
            continue

        latest = judge_trend_reversal(df, lookback_days=lookback_days)
        if latest is None:
            print(f"[SKIP] データ不足のためスキップ: {symbol}({ticker})")
            continue

        results.append(SignalResult(
            symbol=symbol,
            ticker=ticker,
            close=latest["close"],
            ema20=latest["ema20"],
            ema50=latest["ema50"],
            ema50_2m_ago=latest["ema50_2m_ago"],
            is_touched=latest["is_touched"],
        ))

    return results


if __name__ == "__main__":
    # 動作確認用: 為替のみスキャン
    universe = {**FUTURES_TICKERS, **CRYPTO_TICKERS}
    results = scan_universe(universe)

    for r in results:
        flag = "★TOUCHED" if r.is_touched else ""
        print(f"{r.symbol:12s} close={r.close:.4f}  ema20={r.ema20:.4f}  "
              f"ema50={r.ema50:.4f}  ema50(2m前)={r.ema50_2m_ago:.4f}  {flag}")
