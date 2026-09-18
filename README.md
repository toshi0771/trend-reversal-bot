# trend-reversal-bot

トレンド転換シグナル検知bot。為替・先物・米国株(ARK 13F個別銘柄)・暗号通貨を対象に、
50EMAの反転を検知してLINEに通知する。

## 構成
- データ取得: yfinance
- 状態管理: Supabase (trend_watchlist, trend_signal_state)
- 通知: LINE Messaging API
- 定期実行: GitHub Actions (毎週平日 日本時間7:00)
