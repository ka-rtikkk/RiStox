from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sklearn.linear_model import LinearRegression


app = FastAPI(title="RiStox Indian Market Analytics", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


SECTOR_PEERS: dict[str, list[str]] = {
    "Technology": ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS"],
    "Information Technology": ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS"],
    "Financial Services": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS"],
    "Financial": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS"],
    "Energy": ["RELIANCE.NS", "ONGC.NS", "IOC.NS", "BPCL.NS"],
    "Consumer Defensive": ["HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS"],
    "Consumer Cyclical": ["TITAN.NS", "MARUTI.NS", "M&M.NS", "BAJAJ-AUTO.NS"],
    "Healthcare": ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS"],
    "Industrials": ["LT.NS", "SIEMENS.NS", "ABB.NS", "HAL.NS"],
    "Basic Materials": ["TATASTEEL.NS", "HINDALCO.NS", "JSWSTEEL.NS", "ULTRACEMCO.NS"],
    "Communication Services": ["BHARTIARTL.NS", "IDEA.NS", "TATACOMM.NS", "INDUSTOWER.NS"],
}

DEFAULT_PEERS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS"]


class NewsItem(BaseModel):
    title: str
    link: str | None = None
    publisher: str | None = None
    sentiment: str = "neutral"
    score: float = 0.0


def clean_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def normalize_ticker(ticker: str) -> str:
    symbol = ticker.strip().upper()
    if "." not in symbol and symbol not in {"^NSEI", "^BSESN"}:
        symbol = f"{symbol}.NS"
    return symbol


@lru_cache(maxsize=1)
def get_finbert_pipeline():
    from transformers import pipeline

    return pipeline("sentiment-analysis", model="ProsusAI/finbert", tokenizer="ProsusAI/finbert")


def safe_finbert(headlines: list[str]) -> list[dict[str, Any]]:
    if not headlines:
        return []
    try:
        return get_finbert_pipeline()(headlines[:10], truncation=True)
    except Exception:
        return [{"label": "neutral", "score": 0.0} for _ in headlines[:10]]


def extract_news(stock: yf.Ticker) -> list[dict[str, Any]]:
    try:
        news = stock.news or []
    except Exception:
        return []

    normalized = []
    for item in news[:10]:
        content = item.get("content", item) if isinstance(item, dict) else {}
        title = content.get("title")
        if not title and isinstance(item, dict):
            title = item.get("title")
        if not title:
            continue
        link = content.get("canonicalUrl", {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else None
        link = link or content.get("clickThroughUrl", {}).get("url") if isinstance(content.get("clickThroughUrl"), dict) else link
        if not link and isinstance(item, dict):
            link = item.get("link")
        publisher = content.get("provider", {}).get("displayName") if isinstance(content.get("provider"), dict) else None
        if not publisher and isinstance(item, dict):
            publisher = item.get("publisher")
        normalized.append({"title": title, "link": link, "publisher": publisher})
    return normalized


def sentiment_to_score(label: str, confidence: float) -> float:
    label = label.lower()
    if label == "positive":
        return 50 + confidence * 50
    if label == "negative":
        return 50 - confidence * 50
    return 50


def recommendation_from_news(news_score: float, scored_news: list[NewsItem]) -> dict[str, Any]:
    positive_count = sum(1 for item in scored_news if item.sentiment == "positive")
    negative_count = sum(1 for item in scored_news if item.sentiment == "negative")
    neutral_count = sum(1 for item in scored_news if item.sentiment == "neutral")
    headline_count = len(scored_news)

    if headline_count == 0:
        return {
            "action": "HOLD",
            "confidence": 0,
            "news_score": 50.0,
            "rationale": "No recent yfinance headlines were available, so the news-only signal stays neutral.",
            "counts": {"positive": 0, "neutral": 0, "negative": 0},
        }

    if news_score >= 62:
        action = "BUY"
        rationale = "Recent headlines skew positive based on FinBERT sentiment."
    elif news_score <= 38:
        action = "SELL"
        rationale = "Recent headlines skew negative based on FinBERT sentiment."
    else:
        action = "HOLD"
        rationale = "Recent headlines are mixed or close to neutral."

    confidence = min(100, round(abs(news_score - 50) * 2))
    if action == "HOLD":
        confidence = max(15, 100 - confidence)

    return {
        "action": action,
        "confidence": confidence,
        "news_score": round(news_score, 2),
        "rationale": rationale,
        "counts": {
            "positive": positive_count,
            "neutral": neutral_count,
            "negative": negative_count,
        },
    }


def calculate_sentiment(news_items: list[dict[str, Any]], hist: pd.DataFrame) -> dict[str, Any]:
    headlines = [item["title"] for item in news_items[:10]]
    finbert_results = safe_finbert(headlines)

    scored_news: list[NewsItem] = []
    headline_scores = []
    for item, result in zip(news_items, finbert_results):
        label = str(result.get("label", "neutral")).lower()
        confidence = float(result.get("score", 0.0) or 0.0)
        headline_scores.append(sentiment_to_score(label, confidence))
        scored_news.append(
            NewsItem(
                title=item["title"],
                link=item.get("link"),
                publisher=item.get("publisher"),
                sentiment=label,
                score=confidence,
            )
        )

    news_score = float(np.mean(headline_scores)) if headline_scores else 50.0

    close = hist["Close"].dropna()
    latest_close = clean_number(close.iloc[-1]) if not close.empty else None
    sma50 = clean_number(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else latest_close
    if latest_close and sma50:
        momentum_ratio = (latest_close - sma50) / sma50
        momentum_score = max(0.0, min(100.0, 50.0 + momentum_ratio * 500.0))
    else:
        momentum_score = 50.0

    returns = close.pct_change().dropna().tail(30)
    vol = float(returns.std() * math.sqrt(252)) if not returns.empty else 0.0
    volatility_score = max(0.0, min(100.0, 100.0 - vol * 220.0))

    composite = news_score * 0.5 + momentum_score * 0.3 + volatility_score * 0.2
    return {
        "score": round(max(0.0, min(100.0, composite)), 2),
        "components": {
            "news": round(news_score, 2),
            "momentum": round(momentum_score, 2),
            "volatility": round(volatility_score, 2),
        },
        "recommendation": recommendation_from_news(news_score, scored_news),
        "news": [item.model_dump() for item in scored_news],
    }


def history_payload(hist: pd.DataFrame) -> dict[str, list[Any]]:
    one_year = hist.tail(252).copy()
    close = one_year["Close"]
    return {
        "dates": [idx.strftime("%Y-%m-%d") for idx in one_year.index],
        "close": [clean_number(v) for v in close],
        "sma50": [clean_number(v) for v in close.rolling(50).mean()],
        "sma200": [clean_number(v) for v in close.rolling(200).mean()],
    }


def forecast_prices(hist: pd.DataFrame) -> dict[str, Any]:
    close = hist["Close"].dropna().reset_index(drop=True)
    if len(close) < 90:
        raise HTTPException(status_code=404, detail="Stock Ticker Not Found")

    values = close.to_numpy(dtype=float)
    indices = np.arange(len(values)).reshape(-1, 1)
    backtest_errors = []

    for target_idx in range(max(30, len(values) - 30), len(values)):
        train_x = indices[:target_idx]
        train_y = values[:target_idx]
        model = LinearRegression().fit(train_x, train_y)
        pred = float(model.predict([[target_idx]])[0])
        actual = float(values[target_idx])
        if actual:
            backtest_errors.append(abs((actual - pred) / actual))

    mape = float(np.mean(backtest_errors) * 100) if backtest_errors else None
    model = LinearRegression().fit(indices, values)
    future_x = np.arange(len(values), len(values) + 7).reshape(-1, 1)
    prediction = model.predict(future_x)

    last_date = hist.index[-1].date()
    future_dates = [(last_date + timedelta(days=offset)).isoformat() for offset in range(1, 8)]
    return {
        "dates": future_dates,
        "close": [round(max(0.0, float(v)), 2) for v in prediction],
        "mape": round(mape, 2) if mape is not None else None,
    }


def get_price_change(hist: pd.DataFrame) -> tuple[float | None, float | None]:
    close = hist["Close"].dropna()
    if len(close) < 2:
        return None, None
    current = float(close.iloc[-1])
    previous = float(close.iloc[-2])
    change = current - previous
    pct = (change / previous * 100) if previous else 0.0
    return round(change, 2), round(pct, 2)


def fetch_peer_data(ticker: str, sector: str | None) -> list[dict[str, Any]]:
    peer_symbols = SECTOR_PEERS.get(sector or "", DEFAULT_PEERS)
    peer_symbols = [symbol for symbol in peer_symbols if symbol != ticker][:3]
    peers = []
    for symbol in peer_symbols:
        try:
            peer = yf.Ticker(symbol)
            info = peer.info or {}
            hist = peer.history(period="5d", interval="1d", auto_adjust=False)
            price = clean_number(hist["Close"].dropna().iloc[-1]) if not hist.empty else clean_number(info.get("currentPrice"))
            peers.append(
                {
                    "ticker": symbol,
                    "price": price,
                    "pe_ratio": clean_number(info.get("trailingPE") or info.get("forwardPE")),
                    "market_cap": clean_number(info.get("marketCap")),
                }
            )
        except Exception:
            continue
    return peers


def company_summary(info: dict[str, Any]) -> str:
    summary = info.get("longBusinessSummary")
    if not summary:
        return "Live analytics generated from yfinance market, fundamentals, price history, and news data."
    return summary[:320] + ("..." if len(summary) > 320 else "")


@app.get("/")
def root() -> FileResponse:
    return FileResponse("index.html")


@app.get("/api/indices")
def indices() -> dict[str, Any]:
    def index_payload(symbol: str, name: str) -> dict[str, Any]:
        hist = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=False)
        close = hist["Close"].dropna()
        if close.empty:
            return {"name": name, "price": None, "change": None, "change_percent": None}
        price = float(close.iloc[-1])
        previous = float(close.iloc[-2]) if len(close) > 1 else price
        change = price - previous
        pct = (change / previous * 100) if previous else 0.0
        return {
            "name": name,
            "price": round(price, 2),
            "change": round(change, 2),
            "change_percent": round(pct, 2),
        }

    return {
        "nifty": index_payload("^NSEI", "NIFTY 50"),
        "sensex": index_payload("^BSESN", "SENSEX"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/sentiment")
def sentiment(ticker: str = "TCS.NS") -> dict[str, Any]:
    symbol = normalize_ticker(ticker)
    stock = yf.Ticker(symbol)
    hist = stock.history(period="1y", interval="1d", auto_adjust=False)
    if hist.empty:
        raise HTTPException(status_code=404, detail="Stock Ticker Not Found")
    news = extract_news(stock)
    return calculate_sentiment(news, hist)


@app.get("/api/stock/{ticker}")
def stock_dashboard(ticker: str) -> dict[str, Any]:
    symbol = normalize_ticker(ticker)
    stock = yf.Ticker(symbol)

    try:
        hist = stock.history(period="2y", interval="1d", auto_adjust=False)
        info = stock.info or {}
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Stock Ticker Not Found") from exc

    if hist.empty or "Close" not in hist or hist["Close"].dropna().empty:
        raise HTTPException(status_code=404, detail="Stock Ticker Not Found")

    current_price = clean_number(hist["Close"].dropna().iloc[-1])
    change, change_pct = get_price_change(hist)
    news = extract_news(stock)
    sentiment_data = calculate_sentiment(news, hist)
    sector = info.get("sector")

    return {
        "ticker": symbol,
        "company": {
            "name": info.get("longName") or info.get("shortName") or symbol,
            "sector": sector,
            "industry": info.get("industry"),
            "summary": company_summary(info),
        },
        "financials": {
            "current_price": current_price,
            "day_change": change,
            "day_change_percent": change_pct,
            "pe_ratio": clean_number(info.get("trailingPE") or info.get("forwardPE")),
            "market_cap": clean_number(info.get("marketCap")),
            "fifty_two_week_high": clean_number(info.get("fiftyTwoWeekHigh") or hist["High"].tail(252).max()),
            "fifty_two_week_low": clean_number(info.get("fiftyTwoWeekLow") or hist["Low"].tail(252).min()),
        },
        "history": history_payload(hist),
        "prediction": forecast_prices(hist),
        "sentiment": {
            "score": sentiment_data["score"],
            "components": sentiment_data["components"],
        },
        "recommendation": sentiment_data["recommendation"],
        "peers": fetch_peer_data(symbol, sector),
        "news": sentiment_data["news"][:5],
    }


app.mount("/", StaticFiles(directory=".", html=True), name="static")
