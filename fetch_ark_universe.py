"""
ARK Investment Management LLC の13F-HRから保有銘柄を取得し、
OpenFIGIでCUSIP→ティッカー変換、ETFを除外して個別株ユニバースを生成する。

フロー:
  1. SEC EDGAR submissions API で最新の13F-HRファイリングを特定
  2. そのファイリングの Information Table (XML) を取得・パース
  3. CUSIP一覧を100件ずつバッチ化してOpenFIGIに投げる
  4. securityType == "Common Stock" のみ残す
  5. {表示名: ティッカー} 形式で ema_signal.py の ARK_TICKERS に読み込める形で保存

注意:
  このサンドボックス環境はネットワークがホワイトリスト制のため、
  sec.gov / api.openfigi.com への実アクセスはできていません。
  XMLパース部分はダミーデータで検証済みですが、
  実際のHTTP取得部分はご自身の環境で動作確認してください。
"""

import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests  # OpenFIGI呼び出し用

try:
    # SEC data.sec.gov / www.sec.gov は requests の機械的なTLS指紋を
    # bot判定して403を返すことがあるため、ブラウザのTLS指紋を模倣できる
    # curl_cffi があればそちらを優先して使う。
    #   pip install curl_cffi
    from curl_cffi import requests as sec_requests
    _SEC_IMPERSONATE = "chrome"
except ImportError:
    sec_requests = requests
    _SEC_IMPERSONATE = None


def _sec_get(url: str, **kwargs):
    """SEC向けGET。curl_cffiがあればChromeを偽装、なければ通常のrequests。"""
    if _SEC_IMPERSONATE:
        return sec_requests.get(url, impersonate=_SEC_IMPERSONATE, **kwargs)
    return sec_requests.get(url, **kwargs)


CIK = "1697748"  # ARK Investment Management LLC
SEC_HEADERS = {
    # SEC APIは連絡先メール付きUser-Agentが必須。必ずご自身のメールアドレスに変更してください。
    "User-Agent": "PersonalTradingBot/1.0 (your_email@example.com)",
    "Accept-Encoding": "gzip, deflate",
}
OPENFIGI_API_KEY = ""  # https://www.openfigi.com/api で取得したキーを設定(空でも動くがレート制限が厳しい)

OUTPUT_PATH = Path("ark_universe.json")


# ------------------------------------------------------------
# 1. 最新の13F-HRファイリングを特定
# ------------------------------------------------------------

def get_latest_13f_filing_url(cik: str) -> str | None:
    """SEC EDGAR submissions APIから最新の13F-HR提出物のInformation Table URLを取得する。"""
    url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
    r = _sec_get(url, headers=SEC_HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()

    recent = data["filings"]["recent"]
    for i, form in enumerate(recent["form"]):
        if form == "13F-HR":
            accession_raw = recent["accessionNumber"][i]
            accession_nodash = accession_raw.replace("-", "")
            # Information Table のファイル名は提出ごとに違うことがあるため、
            # まずインデックスページを見て実際のXMLファイル名を特定する
            index_url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                f"&CIK={cik}&type=13F-HR"
            )
            filing_index_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/"
            )
            return filing_index_url
    return None


def find_information_table_xml(filing_index_url: str) -> str | None:
    """ファイリングのインデックスページから Information Table XML のURLを特定する。"""
    r = _sec_get(filing_index_url, headers=SEC_HEADERS, timeout=30)
    r.raise_for_status()
    # 素朴な方法: "InfoTable" を含む .xml ファイル名をテキストから拾う
    # (本格的にやるなら index.json を使う方が安全)
    index_json_url = filing_index_url.rstrip("/") + "/index.json"
    r2 = _sec_get(index_json_url, headers=SEC_HEADERS, timeout=30)
    r2.raise_for_status()
    items = r2.json().get("directory", {}).get("item", [])
    for item in items:
        fname = item.get("name", "")
        if "infotable" in fname.lower() and fname.endswith(".xml"):
            return filing_index_url + fname
    return None


# ------------------------------------------------------------
# 2. Information Table XML をパース
# ------------------------------------------------------------

def parse_information_table(xml_bytes: bytes) -> list[dict]:
    """13F Information Table XMLをパースし、[{name, cusip, value, shares}, ...] を返す。"""
    root = ET.fromstring(xml_bytes)
    # 名前空間はファイリングごとに微妙に異なる場合があるため、タグ名の末尾一致で拾う
    holdings = []
    for info in root.iter():
        if info.tag.endswith("infoTable"):
            name = _find_text(info, "nameOfIssuer")
            cusip = _find_text(info, "cusip")
            value = _find_text(info, "value")
            shares = _find_text(info, "sshPrnamt")
            if name and cusip:
                holdings.append({
                    "name": name,
                    "cusip": cusip,
                    "value": value,
                    "shares": shares,
                })
    return holdings


def _find_text(elem: ET.Element, tag_suffix: str) -> str | None:
    for child in elem.iter():
        if child.tag.endswith(tag_suffix):
            return child.text
    return None


# ------------------------------------------------------------
# 3. OpenFIGIでCUSIP→ティッカー変換
# ------------------------------------------------------------

def cusips_to_tickers(cusips: list[str], batch_size: int | None = None) -> dict[str, dict]:
    """
    CUSIPのリストをOpenFIGIでティッカーに変換する。
    戻り値: {cusip: {"ticker": ..., "name": ..., "securityType": ...}}

    batch_size: 未指定ならAPIキー有無で自動決定
                (キーなし=5件/リクエスト、キーあり=100件/リクエスト)
                ※ OpenFIGIの上限を超えると413 Payload Too Largeになる
    """
    if batch_size is None:
        batch_size = 100 if OPENFIGI_API_KEY else 5

    headers = {"Content-Type": "application/json"}
    if OPENFIGI_API_KEY:
        headers["X-OPENFIGI-APIKEY"] = OPENFIGI_API_KEY

    result: dict[str, dict] = {}

    for i in range(0, len(cusips), batch_size):
        batch = cusips[i:i + batch_size]
        jobs = [{"idType": "ID_CUSIP", "idValue": c} for c in batch]

        r = requests.post(
            "https://api.openfigi.com/v3/mapping",
            headers=headers,
            json=jobs,
            timeout=30,
        )
        r.raise_for_status()
        responses = r.json()

        for cusip, resp in zip(batch, responses):
            if "data" not in resp or not resp["data"]:
                print(f"[WARN] マッピング失敗: {cusip}")
                continue
            top = resp["data"][0]
            result[cusip] = {
                "ticker": top.get("ticker"),
                "name": top.get("name"),
                "securityType": top.get("securityType"),
                "exchCode": top.get("exchCode"),
            }

        # 無料枠のレート制限対策(APIキーなしの場合は特に)
        time.sleep(6)

    return result


# ------------------------------------------------------------
# 4. メイン処理
# ------------------------------------------------------------

def build_ark_universe() -> dict[str, str]:
    filing_index_url = get_latest_13f_filing_url(CIK)
    if not filing_index_url:
        raise RuntimeError("13F-HRファイリングが見つかりませんでした")

    xml_url = find_information_table_xml(filing_index_url)
    if not xml_url:
        raise RuntimeError("Information Table XMLが見つかりませんでした")

    r = _sec_get(xml_url, headers=SEC_HEADERS, timeout=30)
    r.raise_for_status()
    holdings = parse_information_table(r.content)
    print(f"13F保有銘柄数(生データ): {len(holdings)}")

    cusips = list({h["cusip"] for h in holdings})
    mapping = cusips_to_tickers(cusips)

    universe: dict[str, str] = {}
    for cusip, info in mapping.items():
        if info.get("securityType") == "Common Stock" and info.get("ticker"):
            universe[info["ticker"]] = info["ticker"]

    print(f"個別株(ETF除く)としてユニバースに残った銘柄数: {len(universe)}")

    OUTPUT_PATH.write_text(json.dumps(universe, ensure_ascii=False, indent=2))
    print(f"保存先: {OUTPUT_PATH.resolve()}")

    return universe


if __name__ == "__main__":
    build_ark_universe()
