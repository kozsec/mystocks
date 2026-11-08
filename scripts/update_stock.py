import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf


ROOT = Path(__file__).resolve().parent.parent
HOLDINGS_FILE = ROOT / "data" / "holdings.json"
PRICES_FILE = ROOT / "data" / "prices.json"
HISTORY_FILE = ROOT / "data" / "history.json"
PORTFOLIO_HISTORY_FILE = ROOT / "data" / "portfolio_history.json"
HISTORY_PERIOD = "1y"


def load_holdings():
    with HOLDINGS_FILE.open("r", encoding="utf-8") as file:
        holdings = json.load(file)

    stocks = holdings.get("stocks", [])
    if not stocks:
        raise ValueError("data/holdings.json に銘柄が登録されていません。")

    return holdings


def fetch_stock(stock):
    ticker = stock["ticker"]
    name = stock.get("name", ticker)

    data = yf.Ticker(ticker).history(
        period=HISTORY_PERIOD,
        interval="1d",
        auto_adjust=False,
    )

    if data.empty:
        print(f"取得できませんでした: {name} ({ticker})")
        return None

    data = data.dropna(subset=["Close"])
    latest = data.iloc[-1]

    history = []
    for date, row in data.iterrows():
        history.append({
            "date": date.strftime("%Y-%m-%d"),
            "open": round(float(row["Open"]), 4),
            "high": round(float(row["High"]), 4),
            "low": round(float(row["Low"]), 4),
            "close": round(float(row["Close"]), 4),
            "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
        })

    latest_price = {
        "ticker": ticker,
        "name": name,
        "date": data.index[-1].strftime("%Y-%m-%d"),
        "open": round(float(latest["Open"]), 4),
        "high": round(float(latest["High"]), 4),
        "low": round(float(latest["Low"]), 4),
        "close": round(float(latest["Close"]), 4),
        "volume": int(latest["Volume"]) if latest["Volume"] == latest["Volume"] else 0,
    }

    return latest_price, history


def main():
    holdings = load_holdings()
    stocks = holdings.get("stocks", [])
    prices = {}
    histories = {}
    failures = []
    fetched_tickers = set()

    for stock in stocks:
        ticker = stock["ticker"]
        name = stock.get("name", ticker)
        if ticker in fetched_tickers:
            continue
        fetched_tickers.add(ticker)
        print(f"取得中: {name} ({ticker})")

        try:
            result = fetch_stock(stock)
            if result is None:
                failures.append(ticker)
                continue

            latest_price, history = result
            prices[ticker] = latest_price
            histories[ticker] = history
            print(f"  {latest_price['date']} 終値: {latest_price['close']:,.2f}")
        except Exception as error:
            failures.append(ticker)
            print(f"  エラー: {error}")

    if not prices:
        raise RuntimeError("株価を1件も取得できませんでした。JSONは更新していません。")

    fetched_at = datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")

    PRICES_FILE.parent.mkdir(parents=True, exist_ok=True)

    prices_output = {
        "updated_at": fetched_at,
        "prices": prices,
    }
    history_output = {
        "updated_at": fetched_at,
        "period": HISTORY_PERIOD,
        "stocks": histories,
    }

    PRICES_FILE.write_text(
        json.dumps(prices_output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    HISTORY_FILE.write_text(
        json.dumps(history_output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    portfolio_history = {"updated_at": None, "daily": []}
    if PORTFOLIO_HISTORY_FILE.exists():
        try:
            portfolio_history = json.loads(PORTFOLIO_HISTORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    required_tickers = {stock["ticker"] for stock in stocks}
    missing_tickers = required_tickers - prices.keys()

    if not missing_tickers:
        today = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
        stock_total = sum(
            float(prices[stock["ticker"]]["close"]) * float(stock.get("shares", 0) or 0)
            for stock in stocks
        )
        cash_total = sum(float(asset.get("amount", 0) or 0) for asset in holdings.get("cash_assets", []))
        snapshot = {
            "date": today,
            "stock_value": round(stock_total, 2),
            "cash_value": round(cash_total, 2),
            "total_value": round(stock_total + cash_total, 2),
        }
        daily = {row["date"]: row for row in portfolio_history.get("daily", []) if "date" in row}
        daily[today] = snapshot
        portfolio_history = {
            "updated_at": fetched_at,
            "daily": [daily[date] for date in sorted(daily)],
        }
        PORTFOLIO_HISTORY_FILE.write_text(
            json.dumps(portfolio_history, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"総資産の日次記録を保存しました: {today}")
        print(f"  株式評価額: {stock_total:,.0f}円")
        print(f"  現金・預金: {cash_total:,.0f}円")
        print(f"  総資産評価額: {stock_total + cash_total:,.0f}円")
    else:
        print("一部の株価を取得できなかったため、総資産の日次記録はスキップしました。")
        print("未取得銘柄: " + ", ".join(sorted(missing_tickers)))

    print(f"\n更新完了: {len(prices)}銘柄")
    print(f"保存先: {PRICES_FILE.relative_to(ROOT)}")
    print(f"保存先: {HISTORY_FILE.relative_to(ROOT)}")

    if failures:
        print("取得できなかった銘柄: " + ", ".join(failures))


if __name__ == "__main__":
    main()
