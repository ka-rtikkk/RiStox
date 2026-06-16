const state = {
  chart: null,
  latestData: null,
};

const els = {
  form: document.getElementById("searchForm"),
  landingForm: document.getElementById("landingSearchForm"),
  tickerInput: document.getElementById("tickerInput"),
  landingTickerInput: document.getElementById("landingTickerInput"),
  landingPage: document.getElementById("landingPage"),
  dashboard: document.getElementById("dashboard"),
  notification: document.getElementById("notification"),
  niftyCard: document.getElementById("niftyCard"),
  sensexCard: document.getElementById("sensexCard"),
  lastUpdated: document.getElementById("lastUpdated"),
  sentimentScore: document.getElementById("sentimentScore"),
  sentimentLabel: document.getElementById("sentimentLabel"),
  gaugeNeedle: document.getElementById("gaugeNeedle"),
  companyName: document.getElementById("companyName"),
  companySector: document.getElementById("companySector"),
  currentPrice: document.getElementById("currentPrice"),
  priceDelta: document.getElementById("priceDelta"),
  summaryText: document.getElementById("summaryText"),
  recommendationCard: document.getElementById("recommendationCard"),
  recommendationAction: document.getElementById("recommendationAction"),
  recommendationConfidence: document.getElementById("recommendationConfidence"),
  recommendationReason: document.getElementById("recommendationReason"),
  mapeScore: document.getElementById("mapeScore"),
  peRatio: document.getElementById("peRatio"),
  marketCap: document.getElementById("marketCap"),
  weekHigh: document.getElementById("weekHigh"),
  weekLow: document.getElementById("weekLow"),
  peerTableBody: document.getElementById("peerTableBody"),
  newsFeed: document.getElementById("newsFeed"),
  toggleSma50: document.getElementById("toggleSma50"),
  toggleSma200: document.getElementById("toggleSma200"),
};

function formatCurrency(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: value > 1000 ? 0 : 2,
  }).format(value);
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(value);
}

function formatMarketCap(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const abs = Math.abs(value);
  if (abs >= 1e7) return `${formatNumber(value / 1e7)} Cr`;
  if (abs >= 1e5) return `${formatNumber(value / 1e5)} L`;
  return formatNumber(value);
}

function sentimentLabel(score) {
  if (score <= 20) return "Extreme Fear";
  if (score <= 40) return "Fear";
  if (score < 60) return "Neutral";
  if (score < 80) return "Greed";
  return "Extreme Greed";
}

function setGauge(score) {
  const safeScore = Math.max(0, Math.min(100, Number(score) || 0));
  const angle = -90 + (safeScore / 100) * 180;
  els.gaugeNeedle.style.transform = `rotate(${angle}deg)`;
  els.sentimentScore.textContent = Math.round(safeScore);
  els.sentimentLabel.textContent = sentimentLabel(safeScore);
}

function setLoading(isLoading) {
  document.body.classList.toggle("loading", isLoading);
  els.form.querySelector("button").disabled = isLoading;
  els.landingForm.querySelector("button").disabled = isLoading;
  document.querySelectorAll(".quick-picks button").forEach((button) => {
    button.disabled = isLoading;
  });
}

function showNotification(message) {
  els.notification.textContent = message;
  els.notification.classList.add("show");
  window.clearTimeout(showNotification.timer);
  showNotification.timer = window.setTimeout(() => els.notification.classList.remove("show"), 5200);
}

async function apiGet(path) {
  const response = await fetch(path);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Unable to load market data");
  }
  return response.json();
}

function updateIndexCard(card, data) {
  const [label, value, delta] = card.children;
  value.textContent = formatNumber(data.price);
  const pct = data.change_percent ?? 0;
  delta.textContent = `${pct >= 0 ? "+" : ""}${formatNumber(data.change)} (${pct >= 0 ? "+" : ""}${formatNumber(pct)}%)`;
  delta.className = pct > 0 ? "positive" : pct < 0 ? "negative" : "neutral";
  label.textContent = data.name;
}

async function loadIndices() {
  try {
    const data = await apiGet("/api/indices");
    updateIndexCard(els.niftyCard, data.nifty);
    updateIndexCard(els.sensexCard, data.sensex);
    els.lastUpdated.textContent = new Date(data.updated_at).toLocaleTimeString("en-IN");
  } catch (error) {
    els.lastUpdated.textContent = "Index feed unavailable";
  }
}

function buildDatasets(data) {
  const labels = [...data.history.dates, ...data.prediction.dates];
  const blankForecastPad = Array(data.history.close.length - 1).fill(null);

  const datasets = [
    {
      label: "Close",
      data: [...data.history.close, ...Array(data.prediction.close.length).fill(null)],
      borderColor: "#38bdf8",
      backgroundColor: "rgba(56, 189, 248, 0.12)",
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.22,
    },
    {
      label: "7D Forecast",
      data: [...blankForecastPad, data.history.close.at(-1), ...data.prediction.close],
      borderColor: "#22c55e",
      borderDash: [6, 5],
      borderWidth: 2,
      pointRadius: 2,
      tension: 0.2,
    },
  ];

  if (els.toggleSma50.checked) {
    datasets.push({
      label: "50D SMA",
      data: [...data.history.sma50, ...Array(data.prediction.close.length).fill(null)],
      borderColor: "#facc15",
      borderWidth: 1.8,
      pointRadius: 0,
      tension: 0.2,
    });
  }

  if (els.toggleSma200.checked) {
    datasets.push({
      label: "200D SMA",
      data: [...data.history.sma200, ...Array(data.prediction.close.length).fill(null)],
      borderColor: "#a78bfa",
      borderWidth: 1.8,
      pointRadius: 0,
      tension: 0.2,
    });
  }

  return { labels, datasets };
}

function renderChart(data) {
  const ctx = document.getElementById("priceChart");
  const chartData = buildDatasets(data);

  if (state.chart) {
    state.chart.destroy();
  }

  state.chart = new Chart(ctx, {
    type: "line",
    data: chartData,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          labels: { color: "#cbd5e1", boxWidth: 12, usePointStyle: true },
        },
        tooltip: {
          backgroundColor: "#020617",
          borderColor: "#334155",
          borderWidth: 1,
          callbacks: {
            label: (item) => `${item.dataset.label}: ${formatCurrency(item.raw)}`,
          },
        },
      },
      scales: {
        x: {
          ticks: { color: "#94a3b8", maxTicksLimit: 8 },
          grid: { color: "rgba(148, 163, 184, 0.08)" },
        },
        y: {
          ticks: { color: "#94a3b8", callback: (value) => formatCurrency(value) },
          grid: { color: "rgba(148, 163, 184, 0.08)" },
        },
      },
    },
  });
}

function renderPeers(peers) {
  if (!peers.length) {
    els.peerTableBody.innerHTML = '<tr><td colspan="4">No peer data available</td></tr>';
    return;
  }

  els.peerTableBody.innerHTML = peers.map((peer) => `
    <tr>
      <td><strong>${peer.ticker}</strong></td>
      <td>${formatCurrency(peer.price)}</td>
      <td>${formatNumber(peer.pe_ratio)}</td>
      <td>${formatMarketCap(peer.market_cap)}</td>
    </tr>
  `).join("");
}

function renderNews(news) {
  if (!news.length) {
    els.newsFeed.innerHTML = '<p class="empty-state">No news headlines found for this ticker.</p>';
    return;
  }

  els.newsFeed.innerHTML = news.slice(0, 5).map((item) => {
    const cls = item.sentiment === "positive" ? "positive" : item.sentiment === "negative" ? "negative" : "neutral";
    const url = item.link || "#";
    return `
      <article class="news-item ${cls}">
        <a href="${url}" target="_blank" rel="noopener noreferrer">${item.title}</a>
        <span>${item.sentiment} ${Math.round((item.score || 0) * 100)}%</span>
      </article>
    `;
  }).join("");
}

function renderRecommendation(recommendation) {
  const signal = recommendation || {
    action: "HOLD",
    confidence: 0,
    rationale: "No recent yfinance headlines were available, so the news-only signal stays neutral.",
    counts: { positive: 0, neutral: 0, negative: 0 },
  };
  const action = String(signal.action || "HOLD").toUpperCase();
  const stateClass = action === "BUY" ? "buy" : action === "SELL" ? "sell" : "hold";
  const counts = signal.counts || { positive: 0, neutral: 0, negative: 0 };

  els.recommendationCard.className = `recommendation-card ${stateClass}`;
  els.recommendationAction.textContent = action;
  els.recommendationConfidence.textContent = `${formatNumber(signal.confidence || 0)}% confidence`;
  els.recommendationReason.textContent = `${signal.rationale} Headlines: ${counts.positive || 0} positive, ${counts.neutral || 0} neutral, ${counts.negative || 0} negative.`;
}

function renderDashboard(data) {
  state.latestData = data;
  els.companyName.textContent = data.company.name || data.ticker;
  els.companySector.textContent = `${data.ticker} / ${data.company.sector || "Sector unavailable"}`;
  els.currentPrice.textContent = formatCurrency(data.financials.current_price);

  const changePct = data.financials.day_change_percent ?? 0;
  els.priceDelta.textContent = `${changePct >= 0 ? "+" : ""}${formatNumber(data.financials.day_change)} (${changePct >= 0 ? "+" : ""}${formatNumber(changePct)}%)`;
  els.priceDelta.className = changePct > 0 ? "positive" : changePct < 0 ? "negative" : "neutral";

  els.summaryText.textContent = data.company.summary || "Live analytics generated from yfinance market, fundamentals, price history, and news data.";
  els.mapeScore.textContent = data.prediction.mape === null ? "N/A" : `${formatNumber(data.prediction.mape)}%`;
  els.peRatio.textContent = formatNumber(data.financials.pe_ratio);
  els.marketCap.textContent = formatMarketCap(data.financials.market_cap);
  els.weekHigh.textContent = formatCurrency(data.financials.fifty_two_week_high);
  els.weekLow.textContent = formatCurrency(data.financials.fifty_two_week_low);

  setGauge(data.sentiment.score);
  renderRecommendation(data.recommendation);
  renderChart(data);
  renderPeers(data.peers);
  renderNews(data.news);
}

async function analyzeTicker(ticker) {
  setLoading(true);
  els.notification.classList.remove("show");

  try {
    const data = await apiGet(`/api/stock/${encodeURIComponent(ticker)}`);
    renderDashboard(data);
    els.dashboard.classList.remove("hidden");
    els.landingPage.classList.add("searched");
    els.dashboard.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showNotification(error.message.includes("not found") ? "Stock Ticker Not Found" : error.message);
  } finally {
    setLoading(false);
  }
}

function handleSearchSubmit(event, input) {
  event.preventDefault();
  const ticker = input.value.trim();
  if (!ticker) {
    showNotification("Enter an NSE/BSE ticker such as TCS.NS or RELIANCE.NS.");
    return;
  }
  els.tickerInput.value = ticker;
  els.landingTickerInput.value = ticker;
  analyzeTicker(ticker);
}

els.form.addEventListener("submit", (event) => handleSearchSubmit(event, els.tickerInput));
els.landingForm.addEventListener("submit", (event) => handleSearchSubmit(event, els.landingTickerInput));

document.querySelectorAll(".quick-picks button").forEach((button) => {
  button.addEventListener("click", () => {
    const ticker = button.dataset.ticker;
    els.tickerInput.value = ticker;
    els.landingTickerInput.value = ticker;
    analyzeTicker(ticker);
  });
});

[els.toggleSma50, els.toggleSma200].forEach((checkbox) => {
  checkbox.addEventListener("change", () => {
    if (state.latestData) renderChart(state.latestData);
  });
});

setGauge(50);
loadIndices();
setInterval(loadIndices, 10000);
