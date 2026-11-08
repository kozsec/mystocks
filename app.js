const yen = value => value == null || !Number.isFinite(value)
  ? "—"
  : new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY", maximumFractionDigits: 0 }).format(value);

const number = value => value == null || !Number.isFinite(value)
  ? "—"
  : new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 0 }).format(value);

const signedYen = value => {
  if (value == null || !Number.isFinite(value)) return "—";
  const prefix = value > 0 ? "+" : "";
  return prefix + yen(value);
};

const byId = id => document.getElementById(id);
const chartInstances = [];

function makeLineChart(canvas, labels, values, color, fill = false, averageCost = null) {
  if (!window.Chart) return;
  const chart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          data: values,
          borderColor: color,
          backgroundColor: fill ? "rgba(59, 130, 246, 0.10)" : "transparent",
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          fill,
          tension: 0.25,
          spanGaps: true
        },
        ...(averageCost != null && Number.isFinite(averageCost) ? [{
          data: labels.map(() => averageCost),
          borderColor: "#dc2626",
          borderWidth: 1.5,
          borderDash: [5, 4],
          pointRadius: 0,
          pointHoverRadius: 0,
          fill: false
        }] : [])
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "index" },
      plugins: { legend: { display: false } },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: "#8293aa", maxTicksLimit: 6, maxRotation: 0, font: { size: 9 } },
          border: { display: false }
        },
        y: {
          grid: { color: "rgba(145, 161, 183, 0.10)" },
          ticks: {
            color: "#8293aa",
            maxTicksLimit: 5,
            font: { size: 9 },
            callback: value => new Intl.NumberFormat("ja-JP", { notation: "compact" }).format(value)
          },
          border: { display: false }
        }
      }
    }
  });
  chartInstances.push(chart);
  return chart;
}

function renderSummary(holdings, prices, cashAssets) {
  let stockValue = 0;
  let totalCost = 0;
  let valuedCount = 0;
  let missingCount = 0;
  for (const stock of holdings) {
    const shares = Number(stock.shares);
    const price = prices[stock.ticker];
    if (!price) missingCount++;
    if (!Number.isFinite(shares) || shares <= 0 || !price) continue;
    const averageCost = Number(stock.average_cost);
    stockValue += Number(price.close) * shares;
    if (Number.isFinite(averageCost) && averageCost > 0) totalCost += averageCost * shares;
    valuedCount++;
  }
  const cashValue = cashAssets.reduce((sum, asset) => sum + Number(asset.amount || 0), 0);
  const totalValue = stockValue + cashValue;
  const profit = stockValue - totalCost;
  const rate = totalCost > 0 ? profit / totalCost * 100 : null;
  byId("totalValue").textContent = yen(totalValue);
  byId("stockValue").textContent = yen(stockValue);
  byId("cashValue").textContent = yen(cashValue);
  byId("totalCost").textContent = yen(totalCost);
  byId("totalProfit").textContent = signedYen(profit);
  byId("totalProfit").className = "summary-value " + (profit >= 0 ? "positive" : "negative");
  byId("profitRate").textContent = rate == null ? "—" : `${rate >= 0 ? "+" : ""}${rate.toFixed(2)}%`;
  byId("valuedCount").textContent = `評価対象 ${valuedCount} 銘柄 / 株価未取得 ${missingCount}`;
}

function renderCashBreakdown(cashAssets) {
  const container = byId("cashBreakdown");
  container.replaceChildren();
  for (const asset of cashAssets) {
    const row = document.createElement("div");
    row.className = "cash-breakdown-row";
    const name = document.createElement("span");
    name.textContent = asset.name;
    const amount = document.createElement("strong");
    amount.textContent = yen(Number(asset.amount));
    row.append(name, amount);
    container.append(row);
  }
}
function renderStockCharts(holdings, prices, histories) {
  const container = byId("stockCharts");
  container.replaceChildren();
  for (const stock of holdings) {
    const price = prices[stock.ticker];
    const rows = histories[stock.ticker] || [];
    const card = document.createElement("article");
    card.className = "stock-card";

    const head = document.createElement("div");
    head.className = "stock-card-head";
    const nameBlock = document.createElement("div");
    nameBlock.innerHTML = `<div class="stock-name"></div><div class="stock-ticker"></div>`;
    nameBlock.querySelector(".stock-name").textContent = stock.name;
    nameBlock.querySelector(".stock-ticker").textContent = stock.ticker;
    const priceBlock = document.createElement("div");
    priceBlock.className = "stock-price";
    priceBlock.innerHTML = `<span></span><small></small>`;
    priceBlock.querySelector("span").textContent = price ? yen(Number(price.close)) : "株価なし";
    priceBlock.querySelector("small").textContent = price ? `終値 ${price.date}` : "データ未取得";
    head.append(nameBlock, priceBlock);

    const chartWrap = document.createElement("div");
    chartWrap.className = "stock-chart";
    const canvas = document.createElement("canvas");
    canvas.setAttribute("aria-label", `${stock.name}の株価推移`);
    chartWrap.append(canvas);

    const meta = document.createElement("div");
    meta.className = "stock-meta";
    const latestClose = price ? Number(price.close) : null;
    const averageCost = Number(stock.average_cost);
    const shares = Number(stock.shares);
    let profitText = "取得単価 —";
    if (Number.isFinite(averageCost) && averageCost > 0 && latestClose != null) {
      const diff = (latestClose - averageCost) * (Number.isFinite(shares) ? shares : 0);
      profitText = `取得単価 ${yen(averageCost)}`;
      if (Number.isFinite(shares) && shares > 0) {
        profitText += ` / 損益 ${signedYen(diff)}`;
      }
    }
    meta.innerHTML = `<span></span><span></span>`;
    meta.children[0].textContent = "";
    meta.children[1].textContent = profitText;

    card.append(head, chartWrap, meta);
    container.append(card);
    if (rows.length) {
      const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));
      makeLineChart(canvas, sorted.map(row => row.date), sorted.map(row => Number(row.close)), "#2563eb", false, Number(stock.average_cost));
    } else {
      chartWrap.innerHTML = '<div class="empty-state">履歴データなし</div>';
    }
  }
}

function renderTable(holdings, prices) {
  const body = byId("holdingsTable");
  body.replaceChildren();
  const rows = holdings.map(stock => {
    const price = prices[stock.ticker];
    const shares = stock.shares == null ? null : Number(stock.shares);
    const averageCost = stock.average_cost == null ? null : Number(stock.average_cost);
    const close = price ? Number(price.close) : null;
    const validShares = Number.isFinite(shares) && shares > 0;
    const value = validShares && close != null ? shares * close : null;
    const cost = validShares && Number.isFinite(averageCost) ? shares * averageCost : null;
    const profit = value != null && cost != null ? value - cost : null;
    return {stock, shares, averageCost, close, validShares, value, profit};
  }).sort((a,b) => (b.profit ?? -Infinity) - (a.profit ?? -Infinity));
  for (const row of rows) {
    const {stock, shares, averageCost, close, validShares, value, profit} = row;
    const tr = document.createElement("tr");
    const name = document.createElement("td");
    name.innerHTML = `<div class="stock-cell-name"></div><div class="stock-cell-ticker"></div>`;
    name.querySelector(".stock-cell-name").textContent = stock.name;
    name.querySelector(".stock-cell-ticker").textContent = stock.ticker;
    tr.append(name);
    const purposeCell = document.createElement("td");
    purposeCell.textContent = stock.purpose || "未設定";
    tr.append(purposeCell);
    const cells = [
      shares == null ? "未入力" : validShares ? number(shares) + "株" : "—",
      averageCost == null ? "—" : yen(averageCost),
      close == null ? "—" : yen(close),
      value == null ? "—" : yen(value),
      profit == null ? "—" : signedYen(profit)
    ];
    cells.forEach((valueText,index) => {
      const td = document.createElement("td");
      td.textContent = valueText;
      if(index===4 && profit!=null) td.className = profit>=0 ? "positive" : "negative";
      if(valueText==="—" || valueText==="未入力") td.classList.add("na");
      tr.append(td);
    });
    body.append(tr);
  }
  byId("tableCount").textContent = holdings.length + " 銘柄";
}
async function init() {
  try {
    const [holdingsResponse, pricesResponse, historyResponse, portfolioHistoryResponse] = await Promise.all([
      fetch("data/holdings.json"),
      fetch("data/prices.json"),
      fetch("data/history.json"),
      fetch("data/portfolio_history.json")
    ]);
    if (!holdingsResponse.ok) throw new Error("holdings.json を読み込めません。");
    const holdingsData = await holdingsResponse.json();
    const pricesData = pricesResponse.ok ? await pricesResponse.json() : { prices: {} };
    const historyData = historyResponse.ok ? await historyResponse.json() : { stocks: {} };
    const portfolioHistoryData = portfolioHistoryResponse.ok ? await portfolioHistoryResponse.json() : { daily: [] };
    const holdings = holdingsData.stocks || [];
    const cashAssets = holdingsData.cash_assets || [];
    const cashValue = cashAssets.reduce((sum, asset) => sum + Number(asset.amount || 0), 0);
    const prices = pricesData.prices || {};
    const histories = historyData.stocks || {};

    byId("updatedAt").textContent = pricesData.updated_at
      ? `最終更新 ${new Date(pricesData.updated_at).toLocaleString("ja-JP")}`
      : "株価データ未更新";

    renderSummary(holdings, prices, cashAssets);
    renderCashBreakdown(cashAssets);
    renderTable(holdings, prices);
    renderStockCharts(holdings, prices, histories);

    const daily = portfolioHistoryData.daily || [];
    if (daily.length) {
      makeLineChart(byId("portfolioChart"), daily.map(row => row.date), daily.map(row => Number(row.total_value)), "#66a7ff", true);
    } else {
      byId("portfolioChart").hidden = true;
      byId("portfolioEmpty").hidden = false;
      byId("portfolioEmpty").textContent = "履歴データが未取得です。GitHub Actionsの更新完了後に再読み込みしてください。";
    }
    if (!pricesResponse.ok || !historyResponse.ok || !portfolioHistoryResponse.ok) {
      byId("updatedAt").textContent = "株価データ未検出：先に更新スクリプトを実行してください";
    }
  } catch (error) {
    byId("updatedAt").textContent = "読み込みエラー";
    byId("holdingsTable").innerHTML = `<tr><td colspan="7" class="loading-cell">${error.message}</td></tr>`;
    byId("portfolioEmpty").hidden = false;
    byId("portfolioEmpty").textContent = "履歴データを読み込めません。GitHub Actionsの実行結果と data/portfolio_history.json を確認してください。";
  }
}

init();
