import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent.parent
HOLDINGS_FILE = ROOT / "data" / "holdings.json"
SOURCES_FILE = ROOT / "data" / "ir_sources.json"
NEWS_FILE = ROOT / "data" / "news.json"
PERIOD_DAYS = 7
JST = ZoneInfo("Asia/Tokyo")
USER_AGENT = "Mozilla/5.0 (compatible; koz-stock-news/1.0)"
DATE_PATTERN = re.compile(
    r"(20\d{2})\s*(?:年|[./-])\s*(\d{1,2})\s*(?:月|[./-])\s*(\d{1,2})\s*日?"
)
SKIP_TITLES = {
    "一覧", "一覧を見る", "もっと見る", "詳細はこちら", "IRニュース",
    "ニュース", "ニュースリリース", "PDF", "資料", "続きを読む",
    "IR情報", "株主・投資家情報", "お問い合わせ"
}


def load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def parse_date(value):
    if not value:
        return None
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=JST)
        return parsed.astimezone(JST).date()
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=JST)
        return parsed.astimezone(JST).date()
    except (TypeError, ValueError, OverflowError):
        pass
    match = DATE_PATTERN.search(value)
    if match:
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            return None
    return None


def date_from_text(value):
    match = DATE_PATTERN.search(value or "")
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def classify(title):
    value = title.lower()
    if any(word in value for word in ("決算", "業績", "financial results", "earnings")):
        return "決算・業績"
    if any(word in value for word in ("配当", "dividend")):
        return "配当"
    if any(word in value for word in ("自己株式", "自社株", "株式取得", "株式消却", "増資", "新株", "資本政策")):
        return "資本政策"
    if any(word in value for word in ("公開買付", "買収", "株式譲渡", "子会社", "合併", "事業譲渡", "業務提携", "資本業務提携", "m&a")):
        return "M&A・事業"
    if any(word in value for word in ("代表取締役", "役員", "人事異動", "組織変更", "社長")):
        return "人事・組織"
    if any(word in value for word in ("不正アクセス", "情報漏えい", "情報流出", "個人情報", "システム障害", "サイバー", "情報漏洩", "障害")):
        return "インシデント"
    return "その他"


def normalize_title(value):
    value = re.sub(r"\s+", " ", value or "").strip()
    value = re.sub(r"^(?:PDF|NEW|新着)\s*", "", value, flags=re.IGNORECASE)
    return value.strip(" |｜・-")


def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def entry_values(entry):
    values = []
    for element in entry.iter():
        if element.text and element.text.strip():
            values.append(element.text.strip())
        values.extend(str(value) for value in element.attrib.values())
    return " ".join(values)


def find_child_text(entry, names):
    for element in entry.iter():
        if local_name(element.tag) in names:
            value = " ".join(element.itertext()).strip()
            if value:
                return value
    return ""


def find_entry_link(entry):
    for element in entry.iter():
        if local_name(element.tag) == "link":
            href = element.attrib.get("href")
            if href:
                return href
            if element.text and element.text.strip():
                return element.text.strip()
    return ""


def fetch_tdnet(session, stocks, cutoff):
    codes = [stock["ticker"].replace(".T", "") for stock in stocks]
    stock_by_code = {stock["ticker"].replace(".T", ""): stock for stock in stocks}
    items = []
    successful_batches = 0

    for start in range(0, len(codes), 15):
        batch = codes[start:start + 15]
        endpoint = (
            "https://webapi.yanoshin.jp/webapi/tdnet/list/"
            + "-".join(batch)
            + ".atom?limit=300"
        )
        try:
            response = session.get(endpoint, timeout=20)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            successful_batches += 1
        except Exception as error:
            print(f"TDnet取得エラー ({','.join(batch)}): {error}")
            continue

        for entry in root.iter():
            if local_name(entry.tag) not in ("entry", "item"):
                continue

            raw = entry_values(entry)
            code = next(
                (
                    candidate for candidate in batch
                    if re.search(
                        rf"(?<![0-9A-Z]){re.escape(candidate)}(?![0-9A-Z])",
                        raw,
                        re.IGNORECASE
                    )
                ),
                None
            )
            if not code:
                code = next(
                    (
                        candidate for candidate, stock in stock_by_code.items()
                        if len(stock.get("name", "")) >= 3 and stock["name"] in raw
                    ),
                    None
                )
            if not code:
                continue

            published = (
                find_child_text(entry, {"published", "updated", "pubdate", "date", "issued"})
            )
            published_date = parse_date(published) or date_from_text(raw)
            if not published_date or published_date < cutoff:
                continue

            stock = stock_by_code[code]
            title = normalize_title(find_child_text(entry, {"title"}))
            summary = find_child_text(entry, {"summary", "description", "content"})
            if not title or len(title) < 5:
                title = normalize_title(BeautifulSoup(summary, "html.parser").get_text(" ", strip=True))
            if not title or title in SKIP_TITLES:
                continue

            link = find_entry_link(entry)
            if not link:
                urls = re.findall(r"https?://[^\s\"'<>]+", raw)
                link = urls[0] if urls else ""
            if not link:
                continue
            link = urljoin("https://webapi.yanoshin.jp/", link)

            items.append({
                "date": published_date.isoformat(),
                "ticker": stock["ticker"],
                "company": stock.get("name", stock["ticker"]),
                "title": title,
                "source": "TDnet",
                "category": classify(title),
                "url": link
            })

    print(f"TDnet: {len(items)}件 / {successful_batches}バッチ取得")
    return items, successful_batches


def fetch_official_rss(session, source, cutoff):
    response = session.get(source["url"], timeout=10)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    items = []

    for entry in root.iter():
        if local_name(entry.tag) not in ("item", "entry"):
            continue
        published = find_child_text(entry, {"pubdate", "published", "updated", "date", "issued"})
        published_date = parse_date(published) or date_from_text(entry_values(entry))
        if not published_date or published_date < cutoff:
            continue
        title = normalize_title(find_child_text(entry, {"title"}))
        link = find_entry_link(entry)
        if not title or len(title) < 5 or not link:
            continue
        items.append({
            "date": published_date.isoformat(),
            "ticker": source["ticker"],
            "company": source["name"],
            "title": title,
            "source": "公式IR",
            "category": classify(title),
            "url": urljoin(source["url"], link)
        })
    return items


def fetch_official_source(session, source, cutoff):
    if source.get("type") == "rss":
        return fetch_official_rss(session, source, cutoff)
    response = session.get(source["url"], timeout=10)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    items = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        anchor_title = normalize_title(
            anchor.get_text(" ", strip=True)
            or anchor.get("title", "")
            or anchor.get("aria-label", "")
        )
        ancestors = [anchor.parent, anchor.parent.parent if anchor.parent else None]
        if ancestors[-1] and ancestors[-1].parent:
            ancestors.append(ancestors[-1].parent)

        block = ""
        published_date = None
        for ancestor in ancestors:
            if ancestor is None:
                continue
            candidate = re.sub(r"\s+", " ", ancestor.get_text(" ", strip=True)).strip()
            candidate_date = date_from_text(candidate)
            if candidate_date:
                block = candidate
                published_date = candidate_date
                break

        if not published_date or published_date < cutoff:
            continue

        title = anchor_title
        if not title or title.lower() in SKIP_TITLES or len(title) < 5:
            title = DATE_PATTERN.sub("", block)
            title = re.sub(r"\b(?:適時開示|IR情報|IRニュース|決算情報|お知らせ|NEW|PDF)\b", "", title)
            title = re.sub(r"\s+", " ", title).strip(" |｜・-")
        if not title or title.lower() in SKIP_TITLES or len(title) < 5:
            continue

        href = anchor["href"].strip()
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        link = urljoin(source["url"], href)
        if link == source["url"]:
            continue

        key = (published_date.isoformat(), title, link)
        if key in seen:
            continue
        seen.add(key)

        items.append({
            "date": published_date.isoformat(),
            "ticker": source["ticker"],
            "company": source["name"],
            "title": title,
            "source": "公式IR",
            "category": classify(title),
            "url": link
        })

    return items


def deduplicate(items):
    unique = {}
    for item in items:
        url = item.get("url", "").split("#", 1)[0]
        key = (item["ticker"], url) if url else (
            item["ticker"], item["date"], item["title"]
        )
        if key not in unique:
            unique[key] = item
    return sorted(
        unique.values(),
        key=lambda item: (item["date"], item["company"], item["title"]),
        reverse=True
    )


def main():
    holdings = load_json(HOLDINGS_FILE)
    registry = load_json(SOURCES_FILE)
    stocks_by_ticker = {}
    for stock in holdings.get("stocks", []):
        stocks_by_ticker[stock["ticker"]] = {
            "ticker": stock["ticker"],
            "name": stock.get("name", stock["ticker"])
        }
    stocks = list(stocks_by_ticker.values())
    sources = [
        source for source in registry.get("sources", [])
        if source.get("enabled") and source.get("url")
        and source.get("ticker") in stocks_by_ticker
    ]

    now = datetime.now(JST)
    cutoff = now.date() - timedelta(days=PERIOD_DAYS)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    tdnet_items, tdnet_batches = fetch_tdnet(session, stocks, cutoff)
    official_items = []
    checked = 0
    failed = []

    for source in sources:
        try:
            found = fetch_official_source(session, source, cutoff)
            official_items.extend(found)
            checked += 1
            print(f"公式IR: {source['name']} {len(found)}件")
        except Exception as error:
            failed.append(source["ticker"])
            print(f"公式IR取得エラー ({source['name']}): {error}")
        time.sleep(0.35)

    items = deduplicate(tdnet_items + official_items)
    if tdnet_batches == 0 and checked == 0:
        raise RuntimeError("TDnetと公式IRのいずれからもデータを取得できませんでした。news.jsonは更新していません。")

    output = {
        "updated_at": now.isoformat(timespec="seconds"),
        "period_days": PERIOD_DAYS,
        "tdnet_provider": "Yanoshin TDnet WEB-API（非公式）",
        "official_sources_checked": checked,
        "official_sources_failed": failed,
        "news": items
    }
    NEWS_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print(f"\n更新完了: {len(items)}件")
    print(f"公式IR取得成功: {checked} / {len(sources)}社")
    print(f"取得失敗: {len(failed)}社")
    print(f"保存先: {NEWS_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
