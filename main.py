"""
トレンド転換シグナルbot メインエントリポイント。

daily_scan.py で新規タッチ銘柄を検出し、あれば line_notify.py 経由で
LINEに通知する。GitHub Actions からはこのファイルを実行する。

実行:
  python3 main.py
"""

from daily_scan import run_daily_scan
from line_notify import format_touch_message, send_line_message


def main():
    touched = run_daily_scan()

    if not touched:
        print("新規タッチなし。通知はスキップします。")
        return

    message = format_touch_message(touched)
    send_line_message(message)


if __name__ == "__main__":
    main()
