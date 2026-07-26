"""
LINE Messaging API でトレンド転換シグナルをpush通知するモジュール。

前提:
  - .env に LINE_CHANNEL_ACCESS_TOKEN と LINE_USER_ID を設定しておくこと
  - 対象ユーザー(LINE_USER_ID)がこのMessaging APIチャネルの
    公式アカウントを友だち追加済みであること

実行:
  pip install requests python-dotenv
  python3 line_notify.py   # 単体テスト実行(ダミーメッセージ送信)
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

LINE_PUSH_API = "https://api.line.me/v2/bot/message/push"


def send_line_message(text: str) -> bool:
    """LINEにテキストメッセージをpush送信する。成功時True。"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": text}],
    }

    r = requests.post(LINE_PUSH_API, headers=headers, json=payload, timeout=15)

    if r.status_code == 200:
        print("[OK] LINE通知を送信しました")
        return True
    else:
        print(f"[ERROR] LINE通知失敗: {r.status_code} {r.text}")
        return False


def format_touch_message(touched: list[dict]) -> str:
    """新規タッチ銘柄のリストをLINE通知用テキストに整形する。"""
    if not touched:
        return ""

    lines = [f"📈 トレンド転換シグナル検出 ({len(touched)}件)", ""]
    for t in touched:
        lines.append(
            f"■ {t['symbol']} ({t['asset_class']})\n"
            f"  終値: {t['close']:.4f}\n"
            f"  20EMA: {t['ema20']:.4f} / 50EMA: {t['ema50']:.4f}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    # 単体テスト: ダミーメッセージ送信
    send_line_message("トレンド転換Bot: 通知テストです。このメッセージが届けば連携成功です。")
