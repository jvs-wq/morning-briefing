#!/usr/bin/env python3
"""
Morning Briefing System
Generates a daily digest of material news and earnings for stock holdings.
Sends via iMessage at 5:30 AM PT on weekdays.

Usage:
    python3 morning_briefing.py

Requirements:
    pip3 install requests feedparser anthropic

Configuration:
    Set environment variables or edit the CONFIG section below.
"""

from __future__ import annotations

import os
import time
import fcntl
import sys
import json
import subprocess
import base64
import re
import feedparser

# v2 redesign: AI-generated editorial brief with HTML email
from morning_briefing_redesign import (
    generate_ai_morning_brief,
    format_morning_html,
    format_morning_text,
    send_html_email,
)

# Load .env file if present (no external dependency needed)
def _load_dotenv(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    # Use direct assignment — setdefault won't overwrite empty
                    # shell env vars (e.g., ANTHROPIC_API_KEY="" from Claude Code)
                    os.environ[key] = value

_load_dotenv()
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
import requests
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from anthropic import Anthropic

# Gmail API imports (for Vital Knowledge)
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    GMAIL_AVAILABLE = True
except ImportError:
    GMAIL_AVAILABLE = False

# ============================================================================
# CONFIGURATION - Edit these or set as environment variables
# ============================================================================

EARNINGS_LOOKBACK_DAYS = 28  # 4 weeks to cover full earnings season

CONFIG = {
    # API Keys
    "FINNHUB_API_KEY": os.getenv("FINNHUB_API_KEY", ""),
    "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
    "CREATOR_WATCHLIST": [
        "CathieDWood",   # ARK Invest - PLTR/TSLA holder
        "jimcramer",     # CNBC - market mover
        "chamath",       # Chamath - tech/SPAC influence
        "elonmusk",      # Elon Musk - TSLA/xAI/policy
        "DavidSacks",    # White House AI czar
        "altcap",        # Brad Gerstner - Altimeter Capital
        "GavinSBaker",   # Gavin Baker - Atreides Management
        "bgurley",       # Bill Gurley - Benchmark
    ],
    "LUNARCRUSH_API_KEY": os.getenv("LUNARCRUSH_API_KEY", ""),
    "FMP_API_KEY": os.getenv("FMP_API_KEY", ""),
    "ALPHA_VANTAGE_API_KEY": os.getenv("ALPHA_VANTAGE_API_KEY", ""),

    # Delivery
    "IMESSAGE_RECIPIENT": os.getenv("IMESSAGE_RECIPIENT", ""),
    "EMAIL_RECIPIENT": os.getenv("EMAIL_RECIPIENT", ""),

    # Holdings — combined personal (JVS) ∪ BCM portfolios
    # Updated 2026-04-14 from SummPosn_Grp_JVS_Portfolio_031626.csv + BCM Top holdings 041326.xlsx
    # Personal: 58 stocks + 10 ETFs | BCM-only additions: 16 stocks + 5 ETFs/funds | Combined: 74 stocks + 15 ETFs = 89 total
    "INDIVIDUAL_STOCKS": [
        # --- Both personal & BCM ---
        "AAPL", "ABNB", "AMAT", "AMZN", "BAC", "C", "CMCSA", "COF", "DE", "ELV",
        "EQT", "FDX", "FISV", "FSLR", "GOOG", "META", "MSGS", "MSFT", "MTN", "MU",
        "NVDA", "SCHW", "UBER", "VSNT", "WFC",
        # --- Personal only ---
        "ABCL", "ADDYY", "AFRM", "AMD", "ARCC", "ASML", "AVAV", "BMNR", "BRKB",
        "CNH", "FCX", "GILD", "GLXY", "HIMS", "ISRG", "NBIS", "NFG", "NTR", "NU",
        "ODD", "OUST", "PEYUF", "PLTR", "RIG", "RIO", "SNY", "SOFI", "TDW", "TSLA",
        "VGZ", "VWAPY", "WY", "ZETA",
        # --- BCM only (not in personal, but top holdings) ---
        "BKR", "CHWY", "COST", "CTRA", "CVS", "DIS", "GOOGL", "GS", "IFF", "INVH",
        "JNJ", "JPM", "PFE", "SLB", "TROW", "UNP",
    ],
    "ETFS": [
        # --- Personal ETFs ---
        "CSRE", "DFAS", "DFCF", "DFEM", "DFEV", "DVYE", "GDX", "GDXJ", "URNM", "VCRB",
        # --- BCM ETFs/funds ---
        "AKRE", "IBB", "VDE", "VGHAX", "XLE",
    ],

    # Social buzz threshold (% week-over-week engagement increase to flag)
    "SOCIAL_BUZZ_THRESHOLD": 100,  # Flag if engagements up >100% week-over-week

    # Gmail API (for Vital Knowledge integration)
    # Set up: forward VK from Outlook to this Gmail, then run with --setup-gmail
    "GMAIL_CREDENTIALS_FILE": os.path.expanduser("~/Documents/Claude-Workspace/credentials/client_secret_942007569615-qa9bggt8p0rlkno9r0mmv138j31m0m60.apps.googleusercontent.com.json"),
    "GMAIL_TOKEN_FILE": os.path.expanduser("~/Documents/Claude-Workspace/credentials/gmail_token.json"),
    "VITAL_KNOWLEDGE_SENDER": "vitalknowledge",  # Partial match on sender (case-insensitive)

    # Earnings history persistence (4-week rolling lookback)
    "EARNINGS_HISTORY_FILE": os.path.join(os.path.dirname(os.path.abspath(__file__)), "earnings_history.json"),
}

# ============================================================================
# DATA FETCHING
# ============================================================================
#
# API EFFICIENCY NOTES:
# - Batch endpoints used wherever possible (FMP quotes, news RSS)
# - Cascading lookups: only query secondary sources for tickers missing from primary
# - Yahoo endpoints don't support batching, so we minimize by checking only gaps
#
# Current API call count (approx) — ordered to space out rate-limited APIs:
#   1 call  - Market snapshot (S&P futures)
#   1 call  - Market snapshot (NASDAQ futures)
#   1 call  - Market snapshot (10Y Treasury)
#   1 call  - Yahoo news RSS (all tickers)
#   1 call  - Finnhub upcoming earnings
#   N calls - yfinance upcoming earnings (only for ~83 missing tickers)
#   15 calls - Alpha Vantage RSI (priority tickers, 3s spacing)    ← rate-limited
#   1 call  - Finnhub scorecard                                     ← cooldown gap
#   N calls - yfinance earnings history (only still-missing tickers)
#   N calls - Alpha Vantage earnings (still-missing, max 20, 3s)   ← rate-limited
#   2 calls - FMP batch quotes (pre-market movers, 50 tickers each) ← cooldown gap
#   5 calls - LunarCrush topics (priority tickers, 3s spacing)     ← rate-limited
#   8 calls - LunarCrush creators (watchlist, 4s spacing)          ← rate-limited
#   1 call  - Anthropic AI filter
#   2 calls - Gmail API (list + get message for Vital Knowledge)
#   N calls - Anthropic AI miss explanations (up to 10 misses)
#
# MARKET RECAP API calls (1:15 PM):
#   5 calls - Yahoo Finance (market indices: S&P, NASDAQ, Dow, VIX, 10Y)
#   2 calls - FMP batch quotes (portfolio performance + 52w high/low, 50 tickers each)
#   15 calls - Alpha Vantage RSI (priority tickers only)
#   1 call  - Yahoo news RSS
#   1 call  - Anthropic AI filter
#

def fetch_market_snapshot(finnhub_key: str) -> dict:
    """Fetch S&P 500 futures, NASDAQ futures, and 10-year Treasury yield."""
    snapshot = {
        "sp500_futures": None,
        "sp500_change": None,
        "nasdaq_futures": None,
        "nasdaq_change": None,
        "treasury_10y": None
    }
    
    try:
        # S&P 500 futures (ES=F on Yahoo)
        sp_url = "https://query1.finance.yahoo.com/v8/finance/chart/ES=F?interval=1d&range=1d&includePrePost=true"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(sp_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            result = data.get("chart", {}).get("result", [{}])[0]
            meta = result.get("meta", {})
            snapshot["sp500_futures"] = meta.get("regularMarketPrice")
            prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
            if snapshot["sp500_futures"] and prev_close:
                snapshot["sp500_change"] = ((snapshot["sp500_futures"] - prev_close) / prev_close) * 100
    except Exception as e:
        print(f"  Warning: Could not fetch S&P futures: {e}")
    
    try:
        # NASDAQ futures (NQ=F on Yahoo)
        nq_url = "https://query1.finance.yahoo.com/v8/finance/chart/NQ=F?interval=1d&range=1d&includePrePost=true"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(nq_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            result = data.get("chart", {}).get("result", [{}])[0]
            meta = result.get("meta", {})
            snapshot["nasdaq_futures"] = meta.get("regularMarketPrice")
            prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
            if snapshot["nasdaq_futures"] and prev_close:
                snapshot["nasdaq_change"] = ((snapshot["nasdaq_futures"] - prev_close) / prev_close) * 100
    except Exception as e:
        print(f"  Warning: Could not fetch NASDAQ futures: {e}")
    
    try:
        # 10-Year Treasury Yield (^TNX on Yahoo)
        tnx_url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?interval=1d&range=1d&includePrePost=true"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(tnx_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            result = data.get("chart", {}).get("result", [{}])[0]
            meta = result.get("meta", {})
            snapshot["treasury_10y"] = meta.get("regularMarketPrice")
    except Exception as e:
        print(f"  Warning: Could not fetch Treasury yield: {e}")
    
    return snapshot


def fetch_yahoo_news(tickers: list[str]) -> list[dict]:
    """Fetch news from Yahoo Finance RSS feed."""
    ticker_string = ",".join(tickers)
    url = f"https://finance.yahoo.com/rss/headline?s={ticker_string}"

    try:
        feed = feedparser.parse(url)
        news_items = []

        for entry in feed.entries:
            news_items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", ""),
                "source": "Yahoo Finance"
            })

        return news_items
    except Exception as e:
        print(f"Error fetching Yahoo news: {e}")
        return []


def fetch_ticker_news(ticker: str) -> list[dict]:
    """Fetch news for a specific ticker."""
    url = f"https://finance.yahoo.com/rss/headline?s={ticker}"

    try:
        feed = feedparser.parse(url)
        news_items = []

        for entry in feed.entries[:5]:  # Limit to 5 most recent
            news_items.append({
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
            })

        return news_items
    except Exception as e:
        return []


def fetch_finnhub_earnings(api_key: str, tickers: set[str]) -> list[dict]:
    """Fetch upcoming earnings from Finnhub API."""
    today = datetime.now()
    end_date = today + timedelta(days=7)

    url = "https://finnhub.io/api/v1/calendar/earnings"
    params = {
        "from": today.strftime("%Y-%m-%d"),
        "to": end_date.strftime("%Y-%m-%d"),
        "token": api_key
    }

    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()

        # Filter to only our holdings
        earnings = []
        for item in data.get("earningsCalendar", []):
            symbol = item.get("symbol", "")
            if symbol in tickers:
                earnings.append({
                    "symbol": symbol,
                    "date": item.get("date", ""),
                    "hour": item.get("hour", ""),  # bmo = before market open, amc = after market close
                    "eps_estimate": item.get("epsEstimate"),
                    "eps_actual": item.get("epsActual"),
                    "revenue_estimate": item.get("revenueEstimate"),
                    "quarter": item.get("quarter"),
                    "year": item.get("year")
                })

        return sorted(earnings, key=lambda x: x["date"])
    except Exception as e:
        print(f"Error fetching Finnhub earnings: {e}")
        return []


def fetch_earnings_scorecard(api_key: str, tickers: set[str]) -> list[dict]:
    """Fetch past earnings (last 4 weeks) to show beat/miss status."""
    today = datetime.now()

    # Look back 4 weeks for recent earnings results
    lookback_start = today - timedelta(days=EARNINGS_LOOKBACK_DAYS)

    url = "https://finnhub.io/api/v1/calendar/earnings"
    params = {
        "from": lookback_start.strftime("%Y-%m-%d"),
        "to": today.strftime("%Y-%m-%d"),
        "token": api_key
    }

    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()

        # Filter to our holdings with actual results
        scorecard = []
        for item in data.get("earningsCalendar", []):
            symbol = item.get("symbol", "")
            eps_actual = item.get("epsActual")
            eps_estimate = item.get("epsEstimate")
            rev_actual = item.get("revenueActual")
            rev_estimate = item.get("revenueEstimate")

            # Only include if it's our holding AND has actual results
            if symbol in tickers and eps_actual is not None and eps_estimate is not None:
                surprise = eps_actual - eps_estimate
                surprise_pct = (surprise / abs(eps_estimate) * 100) if eps_estimate != 0 else 0

                # Calculate revenue beat/miss
                rev_beat = None
                rev_surprise_pct = None
                if rev_actual is not None and rev_estimate is not None and rev_estimate != 0:
                    rev_surprise = rev_actual - rev_estimate
                    rev_surprise_pct = (rev_surprise / abs(rev_estimate) * 100)
                    rev_beat = rev_actual >= rev_estimate

                scorecard.append({
                    "symbol": symbol,
                    "date": item.get("date", ""),
                    "eps_actual": eps_actual,
                    "eps_estimate": eps_estimate,
                    "surprise": surprise,
                    "surprise_pct": surprise_pct,
                    "beat": eps_actual >= eps_estimate,
                    "rev_actual": rev_actual,
                    "rev_estimate": rev_estimate,
                    "rev_beat": rev_beat,
                    "rev_surprise_pct": rev_surprise_pct
                })

        # Sort by date descending (most recent first)
        return sorted(scorecard, key=lambda x: x["date"], reverse=True)
    except Exception as e:
        print(f"Error fetching earnings scorecard: {e}")
        return []


def fetch_social_buzz(tickers: list, api_key: str = "", threshold: int = 100) -> list:
    """Check LunarCrush for social engagement data on priority holdings.

    Uses the LunarCrush API v4 topic endpoint:
      /public/topic/{ticker}/v1 -- returns interactions_24h, sentiment, num_posts, trend

    Note: The time-series/v2 endpoint requires a paid plan (HTTP 402),
    so we use the free topic endpoint and always report the social snapshot
    for top holdings. The 'trend' field (up/down/flat) serves as LunarCrush's
    own directional signal.

    Returns a list of dicts for ALL successfully queried tickers (not just spikes),
    so the briefing always shows a social buzz section.
    """
    results = []

    # Cap at 5 tickers -- LunarCrush rate-limits aggressively (HTTP 429)
    priority_tickers = ["PLTR", "NVDA", "TSLA", "META", "AMZN", "GOOG", "AMD", "SOFI", "UBER", "MSFT"]
    tickers_to_check = [t for t in priority_tickers if t in tickers][:5]

    lc_backoff = 3  # Start with 3s between calls, increase on 429

    for i, ticker in enumerate(tickers_to_check):
        try:
            if i > 0:
                time.sleep(lc_backoff)
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

            topic_url = f"https://lunarcrush.com/api4/public/topic/{ticker}/v1"
            topic_resp = requests.get(topic_url, headers=headers, timeout=10)

            if topic_resp.status_code == 429:
                # Rate limited — back off exponentially
                lc_backoff = min(lc_backoff * 2, 30)
                print(f"    LunarCrush topic {ticker}: HTTP 429 (rate limited, backoff now {lc_backoff}s)")
                time.sleep(lc_backoff)
                # Retry once after backoff
                topic_resp = requests.get(topic_url, headers=headers, timeout=10)

            if topic_resp.status_code != 200:
                print(f"    LunarCrush topic {ticker}: HTTP {topic_resp.status_code}")
                continue
            else:
                # Successful call — reset backoff
                lc_backoff = max(lc_backoff - 1, 3)

            topic_json = topic_resp.json()
            topic_data = topic_json.get("data", topic_json)

            interactions_24h = topic_data.get("interactions_24h", 0)
            num_posts = topic_data.get("num_posts", 0)
            trend = topic_data.get("trend", "flat")

            # Sentiment: use tweet sentiment (most relevant for stocks),
            # fall back to weighted average across platforms
            types_sent = topic_data.get("types_sentiment", {})
            if "tweet" in types_sent:
                sentiment = types_sent["tweet"]
            elif types_sent:
                sentiment = round(sum(types_sent.values()) / len(types_sent))
            else:
                sentiment = 50

            if i == 0:
                top_keys = list(topic_json.keys())[:10]
                print(f"    LunarCrush response keys: {top_keys}")
                if "data" in topic_json and isinstance(topic_json["data"], dict):
                    inner_keys = list(topic_json["data"].keys())[:15]
                    print(f"    LunarCrush data keys: {inner_keys}")
            print(f"    LunarCrush {ticker}: interactions_24h={interactions_24h:,}, sentiment={sentiment}, trend={trend}")

            # Format interactions for display
            if interactions_24h >= 1_000_000_000:
                interactions_display = f"{interactions_24h / 1_000_000_000:.1f}B"
            elif interactions_24h >= 1_000_000:
                interactions_display = f"{interactions_24h / 1_000_000:.1f}M"
            elif interactions_24h >= 1_000:
                interactions_display = f"{interactions_24h / 1_000:.0f}K"
            else:
                interactions_display = str(interactions_24h)

            results.append({
                "symbol": ticker,
                "interactions_24h": interactions_24h,
                "interactions_display": interactions_display,
                "sentiment": sentiment,
                "num_posts": num_posts,
                "trend": trend,
                "alert_type": "social_snapshot"
            })

        except Exception as e:
            print(f"    LunarCrush error for {ticker}: {e}")
            continue

    return results



def fetch_creator_signals(watchlist: list, api_key: str = "", holdings: list = None) -> list:
    """Fetch social activity from high-signal creators via LunarCrush Creator endpoint.

    For each creator in the watchlist, checks which topics they're discussing
    and cross-references with the user's holdings to surface relevant signals.

    Returns a list of dicts with creator info and their holding-relevant topics.
    """
    results = []
    if not watchlist:
        return results

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    holdings_lower = set()
    if holdings:
        for h in holdings:
            holdings_lower.add(h.lower())
            holdings_lower.add("$" + h.lower())

    cr_backoff = 4  # Start with 4s between calls, increase on 429

    for i, handle in enumerate(watchlist[:10]):
        try:
            if i > 0:
                time.sleep(cr_backoff)
            url = f"https://lunarcrush.com/api4/public/creator/x/{handle}/v1"
            resp = requests.get(url, headers=headers, timeout=10)

            if resp.status_code == 429:
                cr_backoff = min(cr_backoff * 2, 30)
                print(f"    Creator {handle}: HTTP 429 (rate limited, backoff now {cr_backoff}s)")
                time.sleep(cr_backoff)
                resp = requests.get(url, headers=headers, timeout=10)

            if resp.status_code != 200:
                print(f"    Creator {handle}: HTTP {resp.status_code}")
                continue
            else:
                cr_backoff = max(cr_backoff - 1, 4)

            data = resp.json().get("data", {})
            name = data.get("creator_display_name", handle)
            followers = data.get("creator_followers", 0)
            engagements = data.get("interactions_24h", 0)
            topics = data.get("topic_influence", [])

            if not followers and not engagements:
                print(f"    Creator {handle}: no data")
                continue

            # Cross-reference topics with holdings
            holding_topics = []
            other_topics = []
            for t in topics[:15]:
                topic = t.get("topic", "")
                count = t.get("count", 0)
                rank = t.get("rank", 0)
                pct = t.get("percent", 0)
                # Check if topic matches any holding
                topic_clean = topic.lower().strip("$")
                is_holding = topic_clean in holdings_lower or ("$" + topic_clean) in holdings_lower
                entry = {"topic": topic, "count": count, "rank": rank, "percent": pct}
                if is_holding:
                    holding_topics.append(entry)
                else:
                    other_topics.append(entry)

            # Format followers
            if followers >= 1_000_000:
                fol_str = f"{followers / 1_000_000:.1f}M"
            elif followers >= 1_000:
                fol_str = f"{followers / 1_000:.0f}K"
            else:
                fol_str = str(followers)

            # Format engagements
            if engagements >= 1_000_000:
                eng_str = f"{engagements / 1_000_000:.1f}M"
            elif engagements >= 1_000:
                eng_str = f"{engagements / 1_000:.1f}K"
            else:
                eng_str = str(engagements)

            print(f"    Creator {handle}: {fol_str} followers, {eng_str} eng, {len(holding_topics)} holding matches")

            results.append({
                "handle": handle,
                "name": name,
                "followers": followers,
                "followers_display": fol_str,
                "engagements_24h": engagements,
                "engagements_display": eng_str,
                "holding_topics": holding_topics,
                "top_topics": (other_topics[:3] if not holding_topics else []),
            })

        except Exception as e:
            print(f"    Creator {handle} error: {e}")
            continue

    return results


def fetch_fmp_earnings_scorecard(api_key: str, tickers: set[str]) -> list[dict]:
    """Fetch earnings data from Financial Modeling Prep (stable API)."""
    scorecard = []
    today = datetime.now()
    lookback_start = today - timedelta(days=EARNINGS_LOOKBACK_DAYS)

    try:
        # Try new stable endpoint
        url = f"https://financialmodelingprep.com/stable/earning-calendar"
        params = {
            "from": lookback_start.strftime("%Y-%m-%d"),
            "to": today.strftime("%Y-%m-%d"),
            "apikey": api_key
        }
        response = requests.get(url, params=params, timeout=30)

        if response.status_code != 200:
            print(f"    FMP stable earning-calendar returned HTTP {response.status_code}")
            return scorecard

        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                for item in data:
                    symbol = item.get("symbol", "")
                    eps_actual = item.get("eps")
                    eps_estimate = item.get("epsEstimated")
                    rev_actual = item.get("revenue")
                    rev_estimate = item.get("revenueEstimated")

                    if symbol in tickers and eps_actual is not None and eps_estimate is not None:
                        surprise = eps_actual - eps_estimate
                        surprise_pct = (surprise / abs(eps_estimate) * 100) if eps_estimate != 0 else 0

                        rev_beat = None
                        rev_surprise_pct = None
                        if rev_actual is not None and rev_estimate is not None and rev_estimate != 0:
                            rev_surprise = rev_actual - rev_estimate
                            rev_surprise_pct = (rev_surprise / abs(rev_estimate) * 100)
                            rev_beat = rev_actual >= rev_estimate

                        scorecard.append({
                            "symbol": symbol,
                            "date": item.get("date", ""),
                            "eps_actual": eps_actual,
                            "eps_estimate": eps_estimate,
                            "surprise": surprise,
                            "surprise_pct": surprise_pct,
                            "beat": eps_actual >= eps_estimate,
                            "rev_actual": rev_actual,
                            "rev_estimate": rev_estimate,
                            "rev_beat": rev_beat,
                            "rev_surprise_pct": rev_surprise_pct,
                            "source": "FMP"
                        })

        return sorted(scorecard, key=lambda x: x["date"], reverse=True)
    except Exception as e:
        print(f"Error fetching FMP earnings: {e}")
        return []


def fetch_yfinance_earnings(tickers: set[str], existing_symbols: set[str]) -> list[dict]:
    """Fetch earnings data from yfinance for tickers not found in other sources.

    Uses yf.Ticker(symbol).earnings_dates which returns a DataFrame with:
    EPS Estimate, Reported EPS, Surprise(%).
    This catches many earnings that Finnhub/FMP miss.
    Requires: pip3 install --user yfinance lxml
    """
    scorecard = []
    today = datetime.now()
    lookback_start = today - timedelta(days=EARNINGS_LOOKBACK_DAYS)
    missing = tickers - existing_symbols

    if not missing:
        return scorecard

    try:
        import yfinance as yf
    except ImportError:
        print("    yfinance not installed, skipping")
        return scorecard

    for ticker in missing:
        try:
            t = yf.Ticker(ticker)
            dates = t.earnings_dates
            if dates is None or dates.empty:
                continue

            for idx, row in dates.iterrows():
                date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, 'strftime') else str(idx)[:10]
                if date_str < lookback_start.strftime("%Y-%m-%d") or date_str > today.strftime("%Y-%m-%d"):
                    continue

                eps_actual = row.get("Reported EPS")
                eps_estimate = row.get("EPS Estimate")

                # Skip if no actual (upcoming earnings)
                if eps_actual is None or (hasattr(eps_actual, '__class__') and eps_actual.__class__.__name__ == 'float' and str(eps_actual) == 'nan'):
                    continue
                if eps_estimate is None or (hasattr(eps_estimate, '__class__') and eps_estimate.__class__.__name__ == 'float' and str(eps_estimate) == 'nan'):
                    continue

                import math
                if math.isnan(eps_actual) or math.isnan(eps_estimate):
                    continue

                surprise = eps_actual - eps_estimate
                surprise_pct = (surprise / abs(eps_estimate) * 100) if eps_estimate != 0 else 0

                scorecard.append({
                    "symbol": ticker,
                    "date": date_str,
                    "eps_actual": round(eps_actual, 2),
                    "eps_estimate": round(eps_estimate, 2),
                    "surprise": round(surprise, 4),
                    "surprise_pct": round(surprise_pct, 1),
                    "beat": eps_actual >= eps_estimate,
                    "source": "yfinance"
                })
                print(f"    Found {ticker} via yfinance: eps={eps_actual:.2f} vs {eps_estimate:.2f}")
                break  # Only most recent
        except Exception as e:
            print(f"    yfinance error for {ticker}: {e}")
            continue

    return sorted(scorecard, key=lambda x: x["date"], reverse=True)


def fetch_yfinance_upcoming_earnings(tickers: set[str], existing_symbols: set[str]) -> list[dict]:
    """Fetch upcoming earnings dates from yfinance for tickers not found in Finnhub.

    Replaces fetch_yahoo_upcoming_earnings (Yahoo v10 quoteSummary returns 401).
    """
    upcoming = []
    missing = tickers - existing_symbols
    if not missing:
        return upcoming

    try:
        import yfinance as yf
    except ImportError:
        print("    yfinance not installed, skipping upcoming earnings")
        return upcoming

    today = datetime.now()
    week_ahead = today + timedelta(days=7)

    for ticker in missing:
        try:
            t = yf.Ticker(ticker)
            dates = t.earnings_dates
            if dates is None or dates.empty:
                continue

            for idx, row in dates.iterrows():
                d = idx.to_pydatetime().replace(tzinfo=None)
                if today <= d <= week_ahead:
                    eps_estimate = row.get("EPS Estimate")
                    import math
                    if eps_estimate is not None and not math.isnan(eps_estimate):
                        eps_estimate = round(eps_estimate, 2)
                    else:
                        eps_estimate = None

                    # Determine timing from hour
                    hour = d.hour
                    if hour < 12:
                        timing = "bmo"
                    elif hour >= 16:
                        timing = "amc"
                    else:
                        timing = ""

                    upcoming.append({
                        "symbol": ticker,
                        "date": d.strftime("%Y-%m-%d"),
                        "hour": timing,
                        "eps_estimate": eps_estimate,
                        "source": "yfinance"
                    })
                    break  # Only need the next upcoming date
        except Exception:
            continue

    return upcoming


def fetch_premarket_movers(api_key: str, tickers: list[str], threshold: float = 3.0) -> list[dict]:
    """Fetch pre-market movers using yfinance (pre/post market) → Yahoo spark → FMP fallback."""
    movers = []
    found_symbols = set()
    detected_market_state = "REGULAR"  # track state for Phase 2 decision

    # Phase 1: yfinance — provides actual pre-market / post-market prices via
    # authenticated Yahoo endpoint. During PRE/POST states, Ticker.info returns
    # preMarketPrice/postMarketPrice which the unauthenticated spark endpoint lacks.
    if YFINANCE_AVAILABLE:
        try:
            import warnings
            warnings.filterwarnings("ignore", category=FutureWarning)

            # Check market state from a liquid ticker
            probe = yf.Ticker("AAPL").info
            market_state = probe.get("marketState", "REGULAR")
            detected_market_state = market_state
            print(f"    Market state: {market_state}")

            if market_state in ("PRE", "POST", "PREPRE", "POSTPOST"):
                price_field = "preMarketPrice" if "PRE" in market_state else "postMarketPrice"
                change_field = "preMarketChangePercent" if "PRE" in market_state else "postMarketChangePercent"

                for symbol in tickers:
                    try:
                        info = yf.Ticker(symbol).info
                        price = info.get(price_field)
                        prev_close = info.get("regularMarketPreviousClose")
                        # No fallback: if ticker lacks pre/post price, skip it.
                        # regularMarketPrice is yesterday's close for OTC/foreign
                        # tickers and would show yesterday's move, not premarket.
                        if price and prev_close and prev_close != 0:
                            change_pct = ((price - prev_close) / prev_close) * 100
                            found_symbols.add(symbol)
                            if abs(change_pct) >= threshold:
                                movers.append({
                                    "symbol": symbol,
                                    "price": price,
                                    "prev_close": prev_close,
                                    "change_pct": change_pct,
                                    "volume": 0
                                })
                    except Exception:
                        continue

                if found_symbols:
                    print(f"    yfinance: got {market_state.lower()} prices for {len(found_symbols)} tickers")

        except Exception as e:
            print(f"    Warning: yfinance premarket error: {e}")

    # Phase 2: Yahoo Finance spark endpoint (batch) — ONLY during regular hours.
    # During PRE/POST, spark range=1d returns yesterday's candles, not today's premarket.
    spark_tickers = [t for t in tickers if t not in found_symbols]
    if spark_tickers and detected_market_state == "REGULAR":
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
            for i in range(0, len(spark_tickers), 20):
                batch = spark_tickers[i:i+20]
                symbols = ",".join(batch)
                url = (f"https://query2.finance.yahoo.com/v8/finance/spark?symbols={symbols}"
                       f"&range=1d&interval=5m&includePrePost=true")
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    for symbol, info in data.items():
                        close_prices = [c for c in (info.get("close") or []) if c is not None]
                        prev_close = info.get("chartPreviousClose")
                        if close_prices and prev_close and prev_close != 0:
                            price = close_prices[-1]
                            change_pct = ((price - prev_close) / prev_close) * 100
                            found_symbols.add(symbol)
                            if abs(change_pct) >= threshold:
                                movers.append({
                                    "symbol": symbol,
                                    "price": price,
                                    "prev_close": prev_close,
                                    "change_pct": change_pct,
                                    "volume": 0
                                })
                time.sleep(0.3)
        except Exception as e:
            print(f"    Warning: Yahoo spark error for premarket: {e}")

    # Phase 3: FMP stable single-symbol for missing tickers
    missing = [t for t in tickers if t not in found_symbols]
    if missing and api_key:
        for ticker in missing[:15]:
            try:
                url = f"https://financialmodelingprep.com/stable/quote?symbol={ticker}&apikey={api_key}"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        item = data[0]
                        change_pct = item.get("changePercentage", 0)
                        if abs(change_pct) >= threshold:
                            movers.append({
                                "symbol": item.get("symbol", ticker),
                                "price": item.get("price", 0),
                                "prev_close": item.get("previousClose", 0),
                                "change_pct": change_pct,
                                "volume": item.get("volume", 0)
                            })
                time.sleep(0.3)
            except Exception:
                continue

    # Sort by absolute change percentage
    return sorted(movers, key=lambda x: abs(x["change_pct"]), reverse=True)[:10]


def fetch_market_close(finnhub_key: str) -> dict:
    """Fetch market close data for S&P 500, NASDAQ, and other indices."""
    close_data = {
        "sp500": None, "sp500_change": None,
        "nasdaq": None, "nasdaq_change": None,
        "dow": None, "dow_change": None,
        "vix": None,
        "treasury_10y": None
    }
    
    indices = [
        ("^GSPC", "sp500"),  # S&P 500
        ("^IXIC", "nasdaq"),  # NASDAQ
        ("^DJI", "dow"),      # Dow Jones
        ("^VIX", "vix"),      # VIX
        ("^TNX", "treasury_10y")  # 10-Year Treasury
    ]
    
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for symbol, key in indices:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d&includePrePost=true"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("chart", {}).get("result", [{}])[0]
                meta = result.get("meta", {})
                price = meta.get("regularMarketPrice")
                prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")

                close_data[key] = price
                if price and prev_close and key != "vix" and key != "treasury_10y":
                    close_data[f"{key}_change"] = ((price - prev_close) / prev_close) * 100
        except Exception as e:
            print(f"    Market close error for {symbol}: {e}")
            continue
    
    return close_data


def fetch_portfolio_performance(api_key: str, tickers: list[str]) -> list[dict]:
    """Fetch today's performance for all holdings using yfinance (pre/post) → Yahoo spark."""
    performance = []
    found_symbols = set()
    detected_market_state = "REGULAR"

    # Phase 1: yfinance — actual pre/post market prices when outside regular hours
    if YFINANCE_AVAILABLE:
        try:
            import warnings
            warnings.filterwarnings("ignore", category=FutureWarning)
            probe = yf.Ticker("AAPL").info
            market_state = probe.get("marketState", "REGULAR")
            detected_market_state = market_state

            if market_state in ("PRE", "POST", "PREPRE", "POSTPOST"):
                price_field = "preMarketPrice" if "PRE" in market_state else "postMarketPrice"
                for symbol in tickers:
                    try:
                        info = yf.Ticker(symbol).info
                        price = info.get(price_field)
                        # No fallback: skip tickers without actual pre/post price
                        prev_close = info.get("regularMarketPreviousClose")
                        if price and prev_close and prev_close != 0:
                            change_pct = ((price - prev_close) / prev_close) * 100
                            found_symbols.add(symbol)
                            performance.append({
                                "symbol": symbol,
                                "price": price,
                                "change_pct": change_pct,
                                "volume": 0,
                                "day_high": None,
                                "day_low": None,
                                "year_high": None,
                                "year_low": None,
                                "at_52w_high": False,
                                "at_52w_low": False,
                            })
                    except Exception:
                        continue
                if found_symbols:
                    print(f"  yfinance: got {market_state.lower()} prices for {len(found_symbols)} tickers")
        except Exception as e:
            print(f"  Warning: yfinance portfolio error: {e}")

    # Phase 2: Yahoo spark fallback (batch, fast) — ONLY during regular hours.
    # During PRE/POST, spark range=1d returns yesterday's candles, not today's premarket.
    spark_tickers = [t for t in tickers if t not in found_symbols]
    if spark_tickers and detected_market_state == "REGULAR":
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
            for i in range(0, len(spark_tickers), 20):
                batch = spark_tickers[i:i+20]
                symbols = ",".join(batch)
                url = (f"https://query2.finance.yahoo.com/v8/finance/spark?symbols={symbols}"
                       f"&range=1d&interval=5m&includePrePost=true")
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    for symbol, info in data.items():
                        close_prices = [c for c in (info.get("close") or []) if c is not None]
                        prev_close = info.get("chartPreviousClose")
                        if close_prices and prev_close and prev_close != 0:
                            price = close_prices[-1]
                            change_pct = ((price - prev_close) / prev_close) * 100
                            performance.append({
                                "symbol": symbol,
                                "price": price,
                                "change_pct": change_pct,
                                "volume": 0,
                                "day_high": None,
                                "day_low": None,
                                "year_high": None,
                                "year_low": None,
                                "at_52w_high": False,
                                "at_52w_low": False,
                            })
                time.sleep(0.3)
        except Exception as e:
            print(f"  Warning: Yahoo spark error: {e}")

    # Phase 2: Enrich with 52-week data via yfinance if available
    if YFINANCE_AVAILABLE and performance:
        try:
            import warnings
            warnings.filterwarnings("ignore", category=FutureWarning)
            syms = [p["symbol"] for p in performance]
            ticker_str = " ".join(syms)
            df = yf.download(ticker_str, period="1y", progress=False, threads=True)
            if not df.empty:
                perf_map = {p["symbol"]: p for p in performance}
                for sym in syms:
                    try:
                        # Handle both single-ticker and multi-ticker DataFrame structures
                        if len(syms) == 1:
                            high_col = df['High']
                            low_col = df['Low']
                            vol_col = df['Volume']
                        else:
                            if sym not in df['High'].columns:
                                continue
                            high_col = df['High'][sym]
                            low_col = df['Low'][sym]
                            vol_col = df['Volume'][sym]

                        year_high = float(high_col.dropna().max())
                        year_low = float(low_col.dropna().min())
                        latest_vol = vol_col.dropna()
                        volume = int(latest_vol.iloc[-1]) if len(latest_vol) > 0 else 0

                        p = perf_map.get(sym)
                        if p:
                            p["year_high"] = year_high
                            p["year_low"] = year_low
                            p["volume"] = volume
                            p["at_52w_high"] = p["price"] >= year_high * 0.99 if year_high else False
                            p["at_52w_low"] = p["price"] <= year_low * 1.01 if year_low else False
                    except Exception:
                        continue
        except Exception as e:
            print(f"  Warning: yfinance 52-week data error: {e}")

    # Phase 3: FMP single-symbol fallback for any tickers we missed
    found_symbols = {p["symbol"] for p in performance}
    missing = [t for t in tickers if t not in found_symbols]
    if missing and api_key:
        for ticker in missing[:10]:  # Cap at 10 to avoid rate limits
            try:
                url = f"https://financialmodelingprep.com/stable/quote?symbol={ticker}&apikey={api_key}"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        item = data[0]
                        performance.append({
                            "symbol": item.get("symbol", ticker),
                            "price": item.get("price", 0),
                            "change_pct": item.get("changePercentage", 0),
                            "volume": item.get("volume", 0),
                            "day_high": item.get("dayHigh"),
                            "day_low": item.get("dayLow"),
                            "year_high": item.get("yearHigh"),
                            "year_low": item.get("yearLow"),
                            "at_52w_high": item.get("price", 0) >= item.get("yearHigh", 999999) * 0.99 if item.get("yearHigh") else False,
                            "at_52w_low": item.get("price", 0) <= item.get("yearLow", 0) * 1.01 if item.get("yearLow") else False,
                        })
                time.sleep(0.5)
            except Exception:
                continue

    return performance


def fetch_yahoo_earnings(tickers: set[str]) -> list[dict]:
    """Fetch earnings data from Yahoo Finance as additional source."""
    scorecard = []
    today = datetime.now()
    lookback_start = today - timedelta(days=EARNINGS_LOOKBACK_DAYS)
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for ticker in tickers:
        try:
            # Yahoo Finance quote summary with earnings data
            url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
            params = {"modules": "earningsHistory,earnings"}
            
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("quoteSummary", {}).get("result", [])
                
                if result:
                    # Check earningsHistory for recent quarters
                    earnings_history = result[0].get("earningsHistory", {}).get("history", [])
                    
                    for quarter in earnings_history:
                        report_date = quarter.get("quarterDate", {}).get("fmt", "")
                        
                        # Only include if reported this quarter
                        if report_date and report_date >= lookback_start.strftime("%Y-%m-%d"):
                            eps_actual = quarter.get("epsActual", {}).get("raw")
                            eps_estimate = quarter.get("epsEstimate", {}).get("raw")
                            
                            if eps_actual is not None and eps_estimate is not None:
                                surprise = eps_actual - eps_estimate
                                surprise_pct = (surprise / abs(eps_estimate) * 100) if eps_estimate != 0 else 0
                                
                                scorecard.append({
                                    "symbol": ticker,
                                    "date": report_date,
                                    "eps_actual": eps_actual,
                                    "eps_estimate": eps_estimate,
                                    "surprise": surprise,
                                    "surprise_pct": surprise_pct,
                                    "beat": eps_actual >= eps_estimate,
                                    "source": "Yahoo"
                                })
                                break  # Only need most recent
        except Exception as e:
            print(f"    Yahoo earnings error for {ticker}: {e}")
            continue

    return scorecard


def fetch_yahoo_upcoming_earnings(tickers: set[str]) -> list[dict]:
    """Fetch upcoming earnings dates from Yahoo Finance."""
    upcoming = []
    today = datetime.now()
    week_ahead = today + timedelta(days=7)
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for ticker in tickers:
        try:
            url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
            params = {"modules": "calendarEvents,earnings"}
            
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("quoteSummary", {}).get("result", [])
                
                if result:
                    calendar = result[0].get("calendarEvents", {})
                    earnings_info = calendar.get("earnings", {})
                    
                    # Get earnings date
                    earnings_date_raw = earnings_info.get("earningsDate", [])
                    if earnings_date_raw:
                        # Can be a range or single date
                        date_obj = earnings_date_raw[0] if isinstance(earnings_date_raw, list) else earnings_date_raw
                        earnings_date = date_obj.get("fmt", "")
                        
                        # Only include if within next 7 days
                        if earnings_date:
                            try:
                                ed = datetime.strptime(earnings_date, "%Y-%m-%d")
                                if today <= ed <= week_ahead:
                                    eps_estimate = earnings_info.get("earningsAverage", {}).get("raw")
                                    
                                    upcoming.append({
                                        "symbol": ticker,
                                        "date": earnings_date,
                                        "hour": "",  # Yahoo doesn't reliably provide timing
                                        "eps_estimate": eps_estimate,
                                        "source": "Yahoo"
                                    })
                            except (ValueError, KeyError):
                                pass
        except Exception as e:
            print(f"    Yahoo upcoming earnings error for {ticker}: {e}")
            continue

    return upcoming


def merge_upcoming_earnings(finnhub_data: list[dict], yahoo_data: list[dict]) -> list[dict]:
    """Merge upcoming earnings from multiple sources."""
    merged = {}
    
    # Add Finnhub data first (has timing info)
    for item in finnhub_data:
        symbol = item["symbol"]
        merged[symbol] = item
    
    # Add Yahoo data for any missing tickers
    for item in yahoo_data:
        symbol = item["symbol"]
        if symbol not in merged:
            merged[symbol] = item
    
    # Sort by date, then timing
    def sort_key(e):
        hour = e.get("hour", "")
        timing_order = 0 if hour == "bmo" else 1 if hour == "amc" else 2
        return (e.get("date", ""), timing_order)
    
    return sorted(merged.values(), key=sort_key)


# Alpha Vantage rate limiter — free tier allows 25 calls/min, 500/day
# Shared across RSI + earnings to avoid exceeding limits
_ALPHA_VANTAGE_LAST_CALL = 0

def _alpha_vantage_rate_limit(min_interval: float = 3.0):
    """Enforce minimum interval between Alpha Vantage API calls."""
    global _ALPHA_VANTAGE_LAST_CALL
    elapsed = time.time() - _ALPHA_VANTAGE_LAST_CALL
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _ALPHA_VANTAGE_LAST_CALL = time.time()


def fetch_rsi_alerts(api_key: str, tickers: list[str], oversold_threshold: int = 30) -> list[dict]:
    """Fetch RSI data and flag oversold or 52-week low RSI stocks."""
    alerts = []

    # Check priority tickers only (limit API calls)
    priority_tickers = [
        "PLTR", "NVDA", "TSLA", "META", "AMZN", "GOOG", "AMD", "SOFI", "UBER",
        "MSFT", "AAPL", "JPM", "COST", "ABNB", "AFRM", "HIMS", "NU", "ASML", "AVAV", "ARCC"
    ]
    tickers_to_check = [t for t in priority_tickers if t in tickers][:15]

    for ticker in tickers_to_check:
        try:
            _alpha_vantage_rate_limit()
            url = "https://www.alphavantage.co/query"
            params = {
                "function": "RSI",
                "symbol": ticker,
                "interval": "daily",
                "time_period": 14,
                "series_type": "close",
                "apikey": api_key
            }
            
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                
                rsi_data = data.get("Technical Analysis: RSI", {})
                if rsi_data:
                    # Get dates sorted (most recent first)
                    dates = sorted(rsi_data.keys(), reverse=True)
                    
                    if len(dates) >= 252:  # ~52 weeks of trading days
                        current_rsi = float(rsi_data[dates[0]]["RSI"])
                        
                        # Get 52-week RSI values
                        year_rsi_values = [float(rsi_data[d]["RSI"]) for d in dates[:252]]
                        min_rsi_52w = min(year_rsi_values)
                        
                        # Flag if oversold or at 52-week low
                        is_oversold = current_rsi < oversold_threshold
                        is_52w_low = current_rsi <= min_rsi_52w * 1.05  # Within 5% of 52-week low
                        
                        if is_oversold or is_52w_low:
                            alerts.append({
                                "symbol": ticker,
                                "current_rsi": current_rsi,
                                "min_rsi_52w": min_rsi_52w,
                                "is_oversold": is_oversold,
                                "is_52w_low": is_52w_low
                            })
                            print(f"    RSI alert: {ticker} RSI={current_rsi:.1f}")
        except Exception as e:
            print(f"    RSI error for {ticker}: {e}")
            continue
    
    # Sort by RSI (lowest first)
    return sorted(alerts, key=lambda x: x["current_rsi"])


def fetch_alpha_vantage_earnings(api_key: str, tickers: set[str]) -> list[dict]:
    """Fetch earnings data from Alpha Vantage (use sparingly - 25 calls/day limit)."""
    scorecard = []
    today = datetime.now()
    lookback_start = today - timedelta(days=EARNINGS_LOOKBACK_DAYS)
    
    # Limit to avoid hitting daily cap (500 calls/day on free tier, 25/min)
    tickers_to_check = list(tickers)[:20]

    for ticker in tickers_to_check:
        try:
            _alpha_vantage_rate_limit()
            url = "https://www.alphavantage.co/query"
            params = {
                "function": "EARNINGS",
                "symbol": ticker,
                "apikey": api_key
            }

            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                
                # Check quarterly earnings
                quarterly = data.get("quarterlyEarnings", [])
                if quarterly:
                    # Get most recent quarter
                    latest = quarterly[0]
                    report_date = latest.get("reportedDate", "")
                    
                    # Only include if reported this quarter
                    if report_date and report_date >= lookback_start.strftime("%Y-%m-%d"):
                        eps_actual = latest.get("reportedEPS")
                        eps_estimate = latest.get("estimatedEPS")
                        
                        # Convert to float if string
                        if eps_actual and eps_estimate:
                            try:
                                eps_actual = float(eps_actual)
                                eps_estimate = float(eps_estimate)
                                
                                surprise = eps_actual - eps_estimate
                                surprise_pct = (surprise / abs(eps_estimate) * 100) if eps_estimate != 0 else 0
                                
                                scorecard.append({
                                    "symbol": ticker,
                                    "date": report_date,
                                    "eps_actual": eps_actual,
                                    "eps_estimate": eps_estimate,
                                    "surprise": surprise,
                                    "surprise_pct": surprise_pct,
                                    "beat": eps_actual >= eps_estimate,
                                    "source": "AlphaVantage"
                                })
                                print(f"    Found {ticker} via Alpha Vantage")
                            except ValueError:
                                pass
        except Exception as e:
            print(f"    Alpha Vantage error for {ticker}: {e}")
            continue

    return scorecard


def fetch_individual_earnings(api_key: str, tickers: set[str], existing_symbols: set[str]) -> list[dict]:
    """Fetch earnings for specific tickers not found in calendar data."""
    scorecard = []
    today = datetime.now()
    lookback_start = today - timedelta(days=EARNINGS_LOOKBACK_DAYS)

    missing_tickers = tickers - existing_symbols

    for ticker in missing_tickers:
        try:
            # Try new FMP stable endpoint
            url = f"https://financialmodelingprep.com/stable/earnings-surprises"
            params = {"symbol": ticker, "apikey": api_key}
            resp = requests.get(url, params=params, timeout=10)

            if resp.status_code != 200:
                print(f"    FMP stable earnings-surprises for {ticker}: HTTP {resp.status_code}")
                continue

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    report_date = item.get("date", "")

                    if report_date >= lookback_start.strftime("%Y-%m-%d"):
                        eps_actual = item.get("actualEarningResult") or item.get("eps")
                        eps_estimate = item.get("estimatedEarning") or item.get("epsEstimated")
                        rev_actual = item.get("actualRevenue") or item.get("revenue")
                        rev_estimate = item.get("estimatedRevenue") or item.get("revenueEstimated")

                        if eps_actual is not None and eps_estimate is not None:
                            surprise = eps_actual - eps_estimate
                            surprise_pct = (surprise / abs(eps_estimate) * 100) if eps_estimate != 0 else 0

                            rev_beat = None
                            rev_surprise_pct = None
                            if rev_actual is not None and rev_estimate is not None and rev_estimate != 0:
                                rev_surprise = rev_actual - rev_estimate
                                rev_surprise_pct = (rev_surprise / abs(rev_estimate) * 100)
                                rev_beat = rev_actual >= rev_estimate

                            scorecard.append({
                                "symbol": ticker,
                                "date": report_date,
                                "eps_actual": eps_actual,
                                "eps_estimate": eps_estimate,
                                "surprise": surprise,
                                "surprise_pct": surprise_pct,
                                "beat": eps_actual >= eps_estimate,
                                "rev_actual": rev_actual,
                                "rev_estimate": rev_estimate,
                                "rev_beat": rev_beat,
                                "rev_surprise_pct": rev_surprise_pct,
                                "source": "FMP-Direct"
                            })
                            print(f"    Found {ticker} via direct lookup")
            time.sleep(0.3)
        except Exception as e:
            print(f"    FMP direct lookup error for {ticker}: {e}")
            continue

    return scorecard


def fetch_vital_knowledge(tickers: list[str], credentials_file: str, token_file: str,
                          sender_filter: str = "vitalknowledge") -> list[dict]:
    """
    Fetch today's Vital Knowledge email from Gmail and extract ticker-relevant items.

    Prerequisites:
    1. Create Google Cloud project and enable Gmail API
    2. Create OAuth credentials (Desktop app type)
    3. Download credentials.json to ~/Claude/credentials/gmail_credentials.json
    4. Run: python morning_briefing.py --setup-gmail (one-time auth flow)
    5. Set up Outlook rule to forward Vital Knowledge to your Gmail
    """
    if not GMAIL_AVAILABLE:
        print("  Gmail API not installed. Run: pip install google-api-python-client google-auth-oauthlib")
        return []

    highlights = []
    ticker_set = set(t.upper() for t in tickers)

    # Add common variations (e.g., GOOGL/GOOG, BRK.B/BRKB)
    ticker_patterns = ticker_set.copy()
    if "GOOGL" in ticker_set:
        ticker_patterns.add("GOOG")
    if "BRKB" in ticker_set:
        ticker_patterns.add("BRK.B")
        ticker_patterns.add("BERKSHIRE")

    try:
        creds = None

        # Load existing token
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, ['https://www.googleapis.com/auth/gmail.readonly'])

        # Refresh or re-auth if needed
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                print("  Gmail not authorized. Run: python morning_briefing.py --setup-gmail")
                return []

            # Save refreshed token
            with open(token_file, 'w') as token:
                token.write(creds.to_json())

        # Build Gmail service
        service = build('gmail', 'v1', credentials=creds)

        # Search for today's Vital Knowledge email (by subject, since it's forwarded)
        today = datetime.now().strftime("%Y/%m/%d")
        query = f'subject:"{sender_filter}" after:{today}'

        results = service.users().messages().list(userId='me', q=query, maxResults=1).execute()
        messages = results.get('messages', [])

        if not messages:
            print("  No Vital Knowledge email found for today")
            return []

        # Get the full message
        msg = service.users().messages().get(userId='me', id=messages[0]['id'], format='full').execute()

        # Extract body
        body_text = ""
        payload = msg.get('payload', {})

        def extract_text(part):
            """Recursively extract text from message parts."""
            text = ""
            mime_type = part.get('mimeType', '')

            if mime_type == 'text/plain':
                data = part.get('body', {}).get('data', '')
                if data:
                    text = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            elif mime_type == 'text/html':
                data = part.get('body', {}).get('data', '')
                if data:
                    html = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    # Strip HTML tags for plain text extraction
                    text = re.sub(r'<[^>]+>', ' ', html)
                    text = re.sub(r'\s+', ' ', text)
            elif 'parts' in part:
                for subpart in part.get('parts', []):
                    text += extract_text(subpart)

            return text

        body_text = extract_text(payload)

        if not body_text:
            print("  Could not extract text from Vital Knowledge email")
            return []

        # Split into paragraphs/sentences for analysis
        # Vital Knowledge typically has bullet points or short paragraphs
        paragraphs = re.split(r'\n\n+|\r\n\r\n+|•|●|▪|►', body_text)

        for para in paragraphs:
            para = para.strip()
            if len(para) < 20:  # Skip very short fragments
                continue

            # Check if any of our tickers are mentioned
            para_upper = para.upper()
            matched_tickers = []

            for ticker in ticker_patterns:
                # Match whole word ticker (avoid matching COST in COSTCO, etc.)
                pattern = r'\b' + re.escape(ticker) + r'\b'
                if re.search(pattern, para_upper):
                    # Map back to canonical ticker
                    canonical = ticker
                    if ticker == "GOOG":
                        canonical = "GOOGL"
                    elif ticker in ["BRK.B", "BERKSHIRE"]:
                        canonical = "BRKB"
                    matched_tickers.append(canonical)

            if matched_tickers:
                # Clean up the paragraph
                clean_para = re.sub(r'\s+', ' ', para).strip()
                if len(clean_para) > 150:
                    clean_para = clean_para[:147] + "..."

                highlights.append({
                    "tickers": list(set(matched_tickers)),
                    "text": clean_para,
                    "source": "Vital Knowledge"
                })

        print(f"  Found {len(highlights)} items mentioning your holdings")
        return highlights

    except Exception as e:
        print(f"  Error fetching Vital Knowledge: {e}")
        return []


def setup_gmail_auth(credentials_file: str, token_file: str):
    """One-time setup to authorize Gmail API access."""
    if not GMAIL_AVAILABLE:
        print("Gmail API not installed. Run:")
        print("  pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
        return False

    if not os.path.exists(credentials_file):
        print(f"Credentials file not found: {credentials_file}")
        print("\nSetup instructions:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a new project (or select existing)")
        print("3. Enable Gmail API: APIs & Services > Enable APIs > Gmail API")
        print("4. Create credentials: APIs & Services > Credentials > Create Credentials > OAuth client ID")
        print("   - Application type: Desktop app")
        print("   - Download the JSON file")
        print(f"5. Save as: {credentials_file}")
        print("6. Re-run: python morning_briefing.py --setup-gmail")
        return False

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            credentials_file,
            ['https://www.googleapis.com/auth/gmail.readonly']
        )
        creds = flow.run_local_server(port=0)

        # Ensure directory exists
        os.makedirs(os.path.dirname(token_file), exist_ok=True)

        # Save the token
        with open(token_file, 'w') as token:
            token.write(creds.to_json())

        print(f"✓ Gmail authorization successful!")
        print(f"  Token saved to: {token_file}")
        print("\nNow set up Outlook forwarding:")
        print("1. In Outlook, create a rule for Vital Knowledge emails")
        print("2. Forward them to your Gmail address")
        print("3. The morning briefing will automatically include relevant items")
        return True

    except Exception as e:
        print(f"Error during Gmail setup: {e}")
        return False


def merge_earnings_data(finnhub_data: list[dict], fmp_data: list[dict],
                        direct_data: list[dict] = None, yf_data: list[dict] = None,
                        yahoo_data: list[dict] = None,
                        alpha_vantage_data: list[dict] = None) -> list[dict]:
    """Merge earnings data from multiple sources, preferring more complete data.

    Priority: Finnhub > FMP calendar > FMP direct > yfinance > Yahoo quoteSummary > Alpha Vantage
    """
    # Create a dict keyed by symbol to deduplicate
    merged = {}

    # Add Finnhub data first (highest priority)
    for item in finnhub_data:
        symbol = item["symbol"]
        merged[symbol] = item

    # Add FMP data, only if symbol not already present or FMP has more recent data
    for item in fmp_data:
        symbol = item["symbol"]
        if symbol not in merged:
            merged[symbol] = item
        else:
            # If FMP has more recent date, use it
            if item["date"] > merged[symbol]["date"]:
                merged[symbol] = item

    # Add direct lookup data for any remaining missing tickers
    if direct_data:
        for item in direct_data:
            symbol = item["symbol"]
            if symbol not in merged:
                merged[symbol] = item

    # Add yfinance data for any remaining missing tickers
    if yf_data:
        for item in yf_data:
            symbol = item["symbol"]
            if symbol not in merged:
                merged[symbol] = item

    # Add Yahoo quoteSummary data for any remaining missing tickers
    if yahoo_data:
        for item in yahoo_data:
            symbol = item["symbol"]
            if symbol not in merged:
                merged[symbol] = item

    # Add Alpha Vantage data for any remaining missing tickers
    if alpha_vantage_data:
        for item in alpha_vantage_data:
            symbol = item["symbol"]
            if symbol not in merged:
                merged[symbol] = item

    # Sanity check: reject garbage data
    # e.g., Alpha Vantage returning $0.00 actual when estimate is $4.54
    cleaned = {}
    for symbol, item in merged.items():
        eps_actual = item.get("eps_actual", 0)
        eps_estimate = item.get("eps_estimate", 0)
        surprise_pct = item.get("surprise_pct", 0)

        # Reject if actual is exactly 0 but estimate is significant (>$0.50)
        if eps_actual == 0.0 and abs(eps_estimate) > 0.50:
            print(f"    Rejected {symbol}: eps_actual=0.00 vs est={eps_estimate:.2f} (likely bad data)")
            continue

        # Reject if surprise is absurdly large (>500%) unless estimate is near zero
        if abs(surprise_pct) > 500 and abs(eps_estimate) > 0.05:
            print(f"    Rejected {symbol}: surprise {surprise_pct:.0f}% too extreme (likely bad data)")
            continue

        cleaned[symbol] = item

    # Sort by date descending
    return sorted(cleaned.values(), key=lambda x: x["date"], reverse=True)


# ============================================================================
# EARNINGS HISTORY PERSISTENCE (4-week rolling lookback)
# ============================================================================


def load_earnings_history(filepath: str) -> dict:
    """Load persistent earnings history from JSON file, pruning stale entries."""
    try:
        with open(filepath, "r") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return {"last_updated": None, "entries": {}}

    # Prune entries older than lookback window
    cutoff = (datetime.now() - timedelta(days=EARNINGS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    entries = history.get("entries", {})
    pruned = {sym: e for sym, e in entries.items() if e.get("date", "") >= cutoff}
    history["entries"] = pruned
    return history


def save_earnings_history(filepath: str, scorecard: list, history: dict) -> None:
    """Merge fresh scorecard into history and persist to JSON."""
    entries = history.get("entries", {})

    # Fresh data wins for any symbol present in both
    for item in scorecard:
        sym = item["symbol"]
        entry = {
            "symbol": sym,
            "date": item.get("date", ""),
            "eps_actual": item.get("eps_actual"),
            "eps_estimate": item.get("eps_estimate"),
            "surprise_pct": item.get("surprise_pct"),
            "beat": item.get("beat"),
            "rev_actual": item.get("rev_actual"),
            "rev_estimate": item.get("rev_estimate"),
            "rev_beat": item.get("rev_beat"),
            "rev_surprise_pct": item.get("rev_surprise_pct"),
            "guidance_signal": item.get("guidance_signal", ""),
            "source": item.get("source", "unknown"),
        }
        # Preserve first_seen from history if it exists
        if sym in entries and "first_seen" in entries[sym]:
            entry["first_seen"] = entries[sym]["first_seen"]
        else:
            entry["first_seen"] = datetime.now().strftime("%Y-%m-%d")
        entries[sym] = entry

    # Prune anything outside the lookback window
    cutoff = (datetime.now() - timedelta(days=EARNINGS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    entries = {sym: e for sym, e in entries.items() if e.get("date", "") >= cutoff}

    output = {
        "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "lookback_start": cutoff,
        "entries": entries,
    }

    try:
        with open(filepath, "w") as f:
            json.dump(output, f, indent=2)
    except IOError as e:
        print(f"  Warning: could not save earnings history: {e}")


def merge_with_history(scorecard: list, history: dict) -> list:
    """Merge fresh scorecard with historical entries (history fills gaps, fresh wins)."""
    # Build lookup of fresh results
    fresh = {item["symbol"]: item for item in scorecard}

    # Add historical entries not in fresh results
    for sym, entry in history.get("entries", {}).items():
        if sym not in fresh:
            fresh[sym] = entry

    # Sort by date descending
    return sorted(fresh.values(), key=lambda x: x.get("date", ""), reverse=True)


def fetch_forward_estimates(api_key: str, symbols: list) -> dict:
    """Fetch next-quarter consensus estimates from FMP for companies that just reported."""
    estimates = {}
    if not api_key or not symbols:
        return estimates

    for symbol in symbols[:15]:
        try:
            url = "https://financialmodelingprep.com/stable/analyst-estimates"
            params = {
                "symbol": symbol,
                "period": "quarter",
                "limit": 2,
                "apikey": api_key,
            }
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                continue

            data = resp.json()
            if not data or not isinstance(data, list):
                continue

            # First entry is the next quarter's consensus
            est = data[0]
            estimates[symbol] = {
                "next_q_eps_est": est.get("estimatedEpsAvg"),
                "next_q_rev_est": est.get("estimatedRevenueAvg"),
                "num_analysts": est.get("numberAnalystEstimatedEps", est.get("numberAnalystsEstimatedEps")),
            }

            time.sleep(0.3)  # Rate limiting

        except Exception as e:
            print(f"    Forward estimates error for {symbol}: {e}")
            continue

    return estimates


def fetch_analyst_actions(api_key: str, tickers: set) -> dict:
    """Fetch recent analyst upgrades/downgrades/price target changes via yfinance.

    Returns dict keyed by symbol with list of recent actions (last 7 days).
    Each action: {analyst, action, rating, price_target, prior_target, date}
    """
    actions = {}
    today = datetime.now()
    week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")

    for symbol in sorted(tickers):
        try:
            t = yf.Ticker(symbol)
            ud = t.upgrades_downgrades
            if ud is None or ud.empty:
                continue

            # Filter to last 7 days
            for grade_date, row in ud.iterrows():
                date_str = str(grade_date)[:10]
                if date_str < week_ago:
                    break  # sorted newest first, so stop when older

                action_entry = {
                    "analyst": row.get("Firm", "Unknown"),
                    "action": row.get("ToGrade", ""),
                    "prior_rating": row.get("FromGrade", ""),
                    "price_target": row.get("currentPriceTarget") if row.get("currentPriceTarget") and row.get("currentPriceTarget") > 0 else None,
                    "prior_target": row.get("priorPriceTarget") if row.get("priorPriceTarget") and row.get("priorPriceTarget") > 0 else None,
                    "date": date_str,
                    "pt_action": row.get("priceTargetAction", ""),
                }

                if symbol not in actions:
                    actions[symbol] = []
                actions[symbol].append(action_entry)

        except Exception:
            continue

    return actions


# ============================================================================
# AI ANALYSIS
# ============================================================================

FILTER_PROMPT = """You are a news filter for a 60-year-old CEO of a $900M RIA firm. Your job is to separate signal from noise.

HOLDINGS CONTEXT:
- PLTR is the largest personal holding (~30% of portfolio)
- Investment style: concentrated positions, long-term holds, monopolistic businesses
- Goal: Never be surprised by material events

INCLUDE (HIGH PRIORITY):
- Earnings releases or guidance changes
- Executive changes (CEO, CFO, Board)
- Major contracts (>$10M or strategic)
- M&A activity (acquisitions, mergers, divestitures, spin-offs)
- Regulatory actions or legal developments
- Material 8-K filings
- Significant insider transactions (>$1M)
- Credit rating changes
- Dividend changes
- Stock splits or buybacks
- FDA approvals/rejections (pharma)
- Major partnerships

EXCLUDE (NOISE):
- Analyst rating changes or price targets
- Routine product launches
- Options activity commentary
- Technical analysis
- General market commentary
- Conference attendance
- Minor executive hires
- Sponsored content

Given the following news items, categorize each as:
- URGENT: Critical, time-sensitive (earnings miss, CEO departure, major legal issue)
- IMPORTANT: Material but not urgent (guidance change, acquisition, contract win)
- FYI: Worth noting but minor (partnership, product news)
- SKIP: Noise, exclude entirely

Return JSON array with format:
[
  {"title": "...", "ticker": "...", "category": "URGENT|IMPORTANT|FYI|SKIP", "summary": "one-line summary"}
]

NEWS ITEMS:
"""


def filter_news_with_ai(news_items: list[dict], api_key: str) -> list[dict]:
    """Use Claude to filter and categorize news."""
    if not news_items:
        return []

    # Prepare news for filtering
    news_text = "\n".join([
        f"- {item['title']}" for item in news_items[:50]  # Limit to avoid token overflow
    ])

    try:
        client = Anthropic(api_key=api_key)

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": FILTER_PROMPT + news_text
                }
            ]
        )

        # Parse response
        response_text = message.content[0].text

        # Extract JSON from response
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        if start != -1 and end > start:
            filtered = json.loads(response_text[start:end])
            # Remove SKIP items
            filtered = [item for item in filtered if item.get("category") != "SKIP"]

            # Re-attach original links by matching on title
            title_to_link = {item["title"]: item.get("link", "") for item in news_items}
            for item in filtered:
                title = item.get("title", "")
                item["link"] = title_to_link.get(title, "")
                # Also add a Yahoo Finance link for the ticker
                ticker = item.get("ticker", "")
                if ticker and ticker != "GENERAL":
                    item["ticker_link"] = f"https://finance.yahoo.com/quote/{ticker}"

            return filtered

        return []
    except Exception as e:
        print(f"Error filtering with AI: {e}")
        # Fallback: return all news as FYI
        return [{"title": item["title"], "ticker": "???", "category": "FYI", "summary": item["title"]}
                for item in news_items[:10]]


def explain_earnings_misses(misses: list[dict], api_key: str) -> dict:
    """Generate brief explanations for why companies missed earnings."""
    explanations = {}

    if not misses:
        return explanations

    try:
        client = Anthropic(api_key=api_key)

        for miss in misses[:10]:  # Process up to 10 misses
            symbol = miss["symbol"]
            eps_actual = miss["eps_actual"]
            eps_estimate = miss["eps_estimate"]
            surprise_pct = miss["surprise_pct"]

            # Fetch recent news for this ticker
            news = fetch_ticker_news(symbol)
            news_text = "\n".join([f"- {n['title']}" for n in news]) if news else "No recent news available."

            prompt = f"""A company ({symbol}) missed earnings estimates this quarter.
Actual EPS: ${eps_actual:.2f}
Expected EPS: ${eps_estimate:.2f}
Miss: {surprise_pct:.1f}%

Recent news headlines:
{news_text}

Based ONLY on facts clearly stated in the news headlines, in ONE brief sentence (max 15 words), explain the reason for the miss. Be specific about the business driver (e.g., "Weak advertising revenue" or "Higher R&D spending"). IMPORTANT: Only state what is clearly supported by the headlines. If the headlines don't clearly explain the miss, respond with "Miss reason not specified in recent coverage."
"""

            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}]
            )

            explanation = message.content[0].text.strip()
            # Clean up the explanation
            explanation = explanation.replace('"', '').replace("'", "")
            if len(explanation) > 80:
                explanation = explanation[:77] + "..."

            explanations[symbol] = explanation

    except Exception as e:
        print(f"Error generating miss explanations: {e}")

    return explanations


def analyze_earnings_guidance(scorecard: list, forward_estimates: dict, api_key: str) -> dict:
    """Analyze whether companies raised/lowered/maintained guidance after reporting.

    Uses news headlines + forward estimate context to infer guidance direction.
    Same pattern as explain_earnings_misses().
    """
    signals = {}
    if not scorecard or not api_key:
        return signals

    try:
        client = Anthropic(api_key=api_key)

        for item in scorecard[:10]:
            symbol = item["symbol"]
            eps_actual = item.get("eps_actual", 0)
            eps_estimate = item.get("eps_estimate", 0)
            beat = item.get("beat", False)

            # Get forward estimate context if available
            fwd = forward_estimates.get(symbol, {})
            fwd_eps = fwd.get("next_q_eps_est")
            fwd_rev = fwd.get("next_q_rev_est")
            fwd_context = ""
            if fwd_eps:
                fwd_context = f"\nNext quarter consensus: EPS ${fwd_eps:.2f}"
                if fwd_rev:
                    fwd_context += f", Revenue ${fwd_rev/1e9:.1f}B"

            # Fetch recent news
            news = fetch_ticker_news(symbol)
            news_text = "\n".join([f"- {n['title']}" for n in news]) if news else "No recent news."

            prompt = f"""{symbol} just reported earnings. EPS: ${eps_actual:.2f} vs ${eps_estimate:.2f} est ({'beat' if beat else 'miss'}).
{fwd_context}

Recent news headlines:
{news_text}

Based ONLY on the headlines, answer in 2-3 words max: did management RAISE guidance, LOWER guidance, or is guidance IN-LINE with expectations? If unclear from headlines, say UNCLEAR. Respond with ONLY one of: raised guidance / lowered outlook / guidance in-line / unclear"""

            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=30,
                messages=[{"role": "user", "content": prompt}]
            )

            signal = message.content[0].text.strip().lower()
            # Normalize to standard labels
            if "raise" in signal:
                signals[symbol] = "raised guidance"
            elif "lower" in signal:
                signals[symbol] = "lowered outlook"
            elif "in-line" in signal or "inline" in signal:
                signals[symbol] = "guidance in-line"
            # Skip 'unclear' — don't add noise

    except Exception as e:
        print(f"Error analyzing guidance: {e}")

    return signals


# ============================================================================
# FORMATTING
# ============================================================================


def _format_revenue(value) -> str:
    """Format revenue as human-readable: $98.2B, $4.3B, $450M, etc."""
    if value is None:
        return "N/A"
    if not isinstance(value, (int, float)):
        return str(value)
    abs_val = abs(value)
    if abs_val >= 1e9:
        return f"${value / 1e9:.1f}B"
    elif abs_val >= 1e6:
        return f"${value / 1e6:.0f}M"
    else:
        return f"${value:,.0f}"


def _lunarcrush_signals(sentiment: int, trend: str, interactions_raw: int,
                        num_posts: int) -> list[str]:
    """Generate tiered LunarCrush signals. Returns only actionable/watch items.

    ⚡ = high-confidence, historically predictive (ACTION)
    ⚠️ = notable but not yet actionable (WATCH)
    Normal-range activity is suppressed (no noise).
    """
    signals = []

    # ── Engagement level ──
    if interactions_raw > 100000:
        signals.append("⚡ BUZZ SPIKE (>100K eng): sharp move likely within 24h")
    elif interactions_raw > 50000:
        signals.append("⚠️ ELEVATED (>50K eng): above-avg volatility likely within 48h")
    elif interactions_raw < 1000 and num_posts > 0:
        signals.append("⚠️ APATHY: posts with no engagement — drift until next catalyst")
    # 1K-50K = normal range → suppress

    # ── Sentiment-trend divergence (most predictive LunarCrush signals) ──
    if sentiment > 65 and trend == "down":
        signals.append("⚡ FADING: bullish crowd + falling momentum → 2-5 day pullback pattern")
    elif sentiment < 35 and trend == "up":
        signals.append("⚡ CONTRARIAN: bearish crowd + rising momentum → reliable bottom indicator")
    elif sentiment > 70 and trend == "up":
        signals.append("⚠️ CROWDED LONG: consensus bullish — reversal risk rising")
    elif sentiment < 30 and trend == "down":
        signals.append("⚠️ WASHOUT: deep negativity — bounce likely 1-2 wks but can overshoot")

    # ── Extreme sentiment ──
    if sentiment > 80:
        signals.append("⚡ EUPHORIA (sent >80): reliable fade signal within 3-5 sessions")
    elif sentiment < 20:
        signals.append("⚡ FEAR (sent <20): historically marks local bottoms")

    # ── Signal quality (posts-to-engagement ratio) ──
    if num_posts > 0 and interactions_raw > 0:
        eng_per_post = interactions_raw / num_posts
        if eng_per_post > 500:
            signals.append("⚠️ HIGH SIGNAL: few posts, massive engagement — institutional/influencer catalyst")
        # Low eng/post with many posts = noise about noise → suppress

    return signals


def _format_lunarcrush_ticker(item: dict) -> list[str]:
    """Format a single ticker's LunarCrush data + signals into display lines."""
    symbol = item["symbol"]
    interactions_raw = item.get("interactions_24h", 0)
    sentiment = item.get("sentiment", 50)
    num_posts = item.get("num_posts", 0)
    trend = item.get("trend", "flat")

    # Trend arrow (only place 🟢/🔴 appear)
    if trend == "up":
        trend_icon = "🟢▲"
    elif trend == "down":
        trend_icon = "🔴▼"
    else:
        trend_icon = "⚪→"

    # Compact engagement display
    if interactions_raw >= 1_000_000:
        eng_str = f"{interactions_raw / 1_000_000:.1f}M"
    elif interactions_raw >= 1000:
        eng_str = f"{interactions_raw / 1000:.1f}K"
    else:
        eng_str = str(interactions_raw)

    # Sentiment label (no emoji — trend arrow already has color)
    if sentiment > 70:
        sent_label = "strong bull"
    elif sentiment > 60:
        sent_label = "bullish"
    elif sentiment < 30:
        sent_label = "strong bear"
    elif sentiment < 40:
        sent_label = "bearish"
    else:
        sent_label = "neutral"

    # Compact posts display
    if num_posts >= 1000:
        posts_str = f"{num_posts / 1000:.1f}K"
    else:
        posts_str = str(num_posts)

    lines = []
    lines.append(f"  {symbol:<6} {trend_icon}  {eng_str} eng · {sentiment}% {sent_label} · {posts_str} posts")

    # Signals — one line each, indented
    signals = _lunarcrush_signals(sentiment, trend, interactions_raw, num_posts)
    for sig in signals:
        lines.append(f"         {sig}")

    return lines


def format_briefing(filtered_news: list[dict], earnings: list[dict], scorecard: list[dict],
                    social_alerts: list[dict], miss_explanations: dict, holdings_count: int,
                    market_snapshot: dict = None, premarket_movers: list[dict] = None,
                    rsi_alerts: list[dict] = None, vk_highlights: list[dict] = None,
                    creator_signals: list[dict] = None,
                    analyst_actions: dict = None) -> str:
    """Format the morning briefing with refined aesthetics."""
    now = datetime.now()

    # Elegant header
    lines = [
        "",
        "────────────────────────────────────",
        "       M O R N I N G   B R I E F I N G",
        f"       {now.strftime('%A, %B %d, %Y')}",
        "────────────────────────────────────",
        ""
    ]

    # Vital Knowledge Highlights (place first - professional curated news)
    if vk_highlights:
        lines.append("▸ VITAL KNOWLEDGE")
        lines.append("")
        for item in vk_highlights[:8]:  # Show up to 8 items
            tickers = item.get("tickers", [])
            ticker_str = ", ".join(tickers[:3])
            text = item.get("text", "")[:120]  # More context
            lines.append(f"  [{ticker_str}]")
            lines.append(f"    {text}")
            lines.append("")

    # Market Snapshot
    if market_snapshot:
        lines.append("▸ MARKET SNAPSHOT")
        lines.append("")
        
        sp = market_snapshot.get("sp500_futures")
        sp_chg = market_snapshot.get("sp500_change")
        nq = market_snapshot.get("nasdaq_futures")
        nq_chg = market_snapshot.get("nasdaq_change")
        tnx = market_snapshot.get("treasury_10y")
        
        if sp is not None:
            arrow = "▲" if sp_chg and sp_chg >= 0 else "▼"
            chg_str = f"{'+' if sp_chg >= 0 else ''}{sp_chg:.2f}%" if sp_chg else ""
            lines.append(f"  S&P Futures    {sp:>8,.0f}  {arrow} {chg_str}")
        
        if nq is not None:
            arrow = "▲" if nq_chg and nq_chg >= 0 else "▼"
            chg_str = f"{'+' if nq_chg >= 0 else ''}{nq_chg:.2f}%" if nq_chg else ""
            lines.append(f"  NASDAQ Futures {nq:>8,.0f}  {arrow} {chg_str}")
        
        if tnx is not None:
            lines.append(f"  10Y Treasury   {tnx:>8.2f}%")
        
        lines.append("")

    # Pre-Market Movers
    if premarket_movers:
        lines.append("▸ PRE-MARKET MOVERS")
        lines.append("")
        for mover in premarket_movers:
            symbol = mover["symbol"]
            change = mover["change_pct"]
            price = mover["price"]
            arrow = "▲" if change >= 0 else "▼"
            sign = "+" if change >= 0 else ""
            lines.append(f"  {symbol:<6} ${price:>8.2f}  {arrow} {sign}{change:.1f}%")
        lines.append("")

    # RSI Alerts (oversold or 52-week low)
    if rsi_alerts:
        lines.append("▸ RSI WATCH (Oversold / 52-Week Low)")
        lines.append("")
        for alert in rsi_alerts:
            symbol = alert["symbol"]
            rsi = alert["current_rsi"]
            min_rsi = alert["min_rsi_52w"]
            flags = []
            if alert["is_oversold"]:
                flags.append("oversold")
            if alert["is_52w_low"]:
                flags.append("52w low")
            flag_str = " · ".join(flags)
            lines.append(f"  {symbol:<6} RSI {rsi:>5.1f}  (52w min: {min_rsi:.1f})  {flag_str}")
        lines.append("")

    # Categorize news
    urgent = [n for n in filtered_news if n.get("category") == "URGENT"]
    important = [n for n in filtered_news if n.get("category") == "IMPORTANT"]
    fyi = [n for n in filtered_news if n.get("category") == "FYI"]

    has_content = urgent or important or earnings or fyi or scorecard

    if not has_content:
        lines.append("▸ All clear. No material events today.")
        lines.append("")

    # Urgent - show full detail
    if urgent:
        lines.append("▸ URGENT")
        lines.append("")
        for item in urgent:
            ticker = item.get("ticker", "???")
            title = item.get("title", "")[:100]
            summary = item.get("summary", "")
            link = item.get("link", "")
            lines.append(f"  🚨 [{ticker}] {title}")
            if summary and summary != title:
                lines.append(f"      {summary[:120]}")
            if link:
                lines.append(f"      {link}")
            lines.append("")

    # Important - show full detail
    if important:
        lines.append("▸ IMPORTANT")
        lines.append("")
        for item in important:
            ticker = item.get("ticker", "???")
            title = item.get("title", "")[:100]
            summary = item.get("summary", "")
            link = item.get("link", "")
            lines.append(f"  • [{ticker}] {title}")
            if summary and summary != title:
                lines.append(f"      {summary[:120]}")
            if link:
                lines.append(f"      {link}")
            lines.append("")

    # Earnings Scorecard - Beats first (green), then Misses (red)
    if scorecard:
        beats = [s for s in scorecard if s.get("beat")]
        misses = [s for s in scorecard if not s.get("beat")]
        lines.append(f"▸ EARNINGS SCORECARD  ({len(beats)} beat · {len(misses)} miss · 4-wk)")
        lines.append("")

        # Show beats first with green indicator
        if beats:
            lines.append("  BEATS")
            for item in beats[:8]:
                symbol = item["symbol"]
                actual = item.get("eps_actual", 0)
                estimate = item.get("eps_estimate", 0)
                surprise_pct = item.get("surprise_pct", 0)
                lines.append(f"  🟢 {symbol:<6} EPS ${actual:.2f} vs ${estimate:.2f} (+{surprise_pct:.1f}%)")
                # Revenue sub-line
                rev_actual = item.get("rev_actual")
                rev_estimate = item.get("rev_estimate")
                guidance = item.get("guidance_signal", "")
                if rev_actual and rev_estimate:
                    rev_mark = "✓" if item.get("rev_beat") else "✗"
                    guidance_tag = f"  {guidance}" if guidance else ""
                    lines.append(f"           Rev {_format_revenue(rev_actual)} vs {_format_revenue(rev_estimate)} {rev_mark}{guidance_tag}")
                elif guidance:
                    lines.append(f"           {guidance}")
            lines.append("")

        # Show misses with red indicator
        if misses:
            lines.append("  MISSES")
            for item in misses[:8]:
                symbol = item["symbol"]
                actual = item.get("eps_actual", 0)
                estimate = item.get("eps_estimate", 0)
                surprise_pct = item.get("surprise_pct", 0)
                lines.append(f"  🔴 {symbol:<6} EPS ${actual:.2f} vs ${estimate:.2f} ({surprise_pct:.1f}%)")
                # Revenue sub-line
                rev_actual = item.get("rev_actual")
                rev_estimate = item.get("rev_estimate")
                guidance = item.get("guidance_signal", "")
                if rev_actual and rev_estimate:
                    rev_mark = "✓" if item.get("rev_beat") else "✗"
                    guidance_tag = f"  {guidance}" if guidance else ""
                    lines.append(f"           Rev {_format_revenue(rev_actual)} vs {_format_revenue(rev_estimate)} {rev_mark}{guidance_tag}")
                elif guidance:
                    lines.append(f"           {guidance}")
                if symbol in miss_explanations:
                    lines.append(f"      └─ {miss_explanations[symbol]}")
            lines.append("")

    # Analyst upgrades/downgrades/price target changes
    # iMessage: only show material actions (rating changes or PT moves >5%)
    if analyst_actions:
        material = []
        for symbol in sorted(analyst_actions.keys()):
            for a in analyst_actions[symbol][:2]:
                action = a.get("action", "")
                prior_rating = a.get("prior_rating", "")
                pt = a.get("price_target")
                prior_pt = a.get("prior_target")
                # Material = actual rating change, or PT move >10%, or new coverage
                is_rating_change = prior_rating and action and prior_rating != action
                is_big_pt_move = (pt and prior_pt and abs(pt - prior_pt) / prior_pt > 0.10)
                is_new_coverage = not prior_rating and action
                if is_rating_change or is_big_pt_move or is_new_coverage:
                    material.append((symbol, a))
        if material:
            lines.append("▸ ANALYST ACTIONS (7d)")
            lines.append("")
            for symbol, a in material[:15]:  # Cap at 15 for iMessage
                analyst = a.get("analyst", "?")
                action = a.get("action", "")
                pt = a.get("price_target")
                prior_pt = a.get("prior_target")
                prior_rating = a.get("prior_rating", "")
                if pt and prior_pt:
                    direction = "↑" if pt > prior_pt else "↓"
                    lines.append(f"  {symbol:<6} {analyst}: {prior_rating}→{action}  PT ${prior_pt:.0f}→${pt:.0f} {direction}")
                elif pt:
                    lines.append(f"  {symbol:<6} {analyst}: {action}  PT ${pt:.0f}")
                else:
                    rating_change = f"{prior_rating}→{action}" if prior_rating else action
                    lines.append(f"  {symbol:<6} {analyst}: {rating_change}")
            if len(material) > 15:
                lines.append(f"  ... +{len(material) - 15} more (see email)")
            lines.append("")

    # Upcoming Earnings (sorted: date, then pre-market before post-market)
    if earnings:
        lines.append("▸ EARNINGS THIS WEEK")
        lines.append("")
        
        # Sort by date, then by timing (bmo=0, amc=1, other=2)
        def earnings_sort_key(e):
            hour = e.get("hour", "")
            timing_order = 0 if hour == "bmo" else 1 if hour == "amc" else 2
            return (e.get("date", ""), timing_order)
        
        sorted_earnings = sorted(earnings, key=earnings_sort_key)
        
        for e in sorted_earnings:
            symbol = e["symbol"]
            date = e["date"]
            hour = e.get("hour", "")
            timing = "pre" if hour == "bmo" else "post" if hour == "amc" else ""
            eps = e.get("eps_estimate")
            eps_str = f"EPS ${eps:.2f}" if eps else ""
            rev_est = e.get("revenue_estimate")
            rev_str = f"  Rev {_format_revenue(rev_est)}" if rev_est else ""
            lines.append(f"  {symbol:<6} {date}  {timing:<4} {eps_str}{rev_str}")
        lines.append("")

    # FYI - show more items with full text
    if fyi:
        lines.append("▸ FYI")
        lines.append("")
        for item in fyi[:7]:  # Show up to 7 FYI items
            ticker = item.get("ticker", "???")
            title = item.get("title", "")[:100]
            summary = item.get("summary", "")
            link = item.get("link", "")
            lines.append(f"  • [{ticker}] {title}")
            if summary and summary != title and len(summary) > 20:
                lines.append(f"      {summary[:120]}")
            if link:
                lines.append(f"      {link}")
            lines.append("")

    # LunarCrush Social Intelligence (last content section)
    if social_alerts:
        lines.append("┌─────────────────────────────────────┐")
        lines.append("│   LUNARCRUSH · SOCIAL INTELLIGENCE  │")
        lines.append("└─────────────────────────────────────┘")
        lines.append("")

        for item in social_alerts:
            lines.extend(_format_lunarcrush_ticker(item))
            lines.append("")

        lines.append("  ⚡ = actionable signal  ⚠️ = watch")
        lines.append("  src: lunarcrush.com")
        lines.append("")

    # Creator Signals
    if creator_signals:
        lines.append("┌─────────────────────────────────────┐")
        lines.append("│   KEY VOICES · CREATOR SIGNALS      │")
        lines.append("└─────────────────────────────────────┘")
        lines.append("")

        for creator in creator_signals:
            handle = creator["handle"]
            name = creator["name"]
            fol = creator["followers_display"]
            eng = creator["engagements_display"]
            holding_topics = creator.get("holding_topics", [])
            top_topics = creator.get("top_topics", [])
            eng_raw = creator.get("engagements_24h", 0)

            # Color-code creator engagement level
            if eng_raw > 500000:
                eng_flag = " 🔥"
            elif eng_raw > 100000:
                eng_flag = " 🟢"
            else:
                eng_flag = ""

            lines.append(f"  {name} (@{handle}) · {fol} followers · {eng} eng/24h{eng_flag}")

            if holding_topics:
                parts = []
                for ht in holding_topics[:4]:
                    topic = ht["topic"].upper()
                    count = ht["count"]
                    parts.append(f"{topic}({count})")
                lines.append(f"    🟢 YOUR HOLDINGS: {', '.join(parts)}")
                lines.append(f"    key-voice overlap with your book — monitor for position sizing signals")
            elif top_topics:
                parts = []
                for tt in top_topics[:3]:
                    topic = tt["topic"]
                    count = tt["count"]
                    parts.append(f"{topic}({count})")
                lines.append(f"    talking: {', '.join(parts)}")

            lines.append("")

        lines.append("")

    # Footer
    lines.append("────────────────────────────────────")
    lines.append(f"  {holdings_count} holdings · {now.strftime('%I:%M %p')} PT")
    lines.append("")

    return "\n".join(lines)


def format_premarket_update(market_snapshot: dict, premarket_movers: list[dict],
                             today_earnings: list[dict], vk_highlights: list[dict],
                             holdings_count: int) -> str:
    """Format the 6:20 AM pre-market update - concise check before the bell."""
    now = datetime.now()

    lines = [
        "",
        "────────────────────────────",
        "     P R E - M A R K E T",
        f"     {now.strftime('%A %I:%M %p')}",
        "────────────────────────────",
        ""
    ]

    # Futures (final check before open)
    if market_snapshot:
        sp = market_snapshot.get("sp500_futures")
        sp_chg = market_snapshot.get("sp500_change")
        nq = market_snapshot.get("nasdaq_futures")
        nq_chg = market_snapshot.get("nasdaq_change")
        tnx = market_snapshot.get("treasury_10y")

        lines.append("▸ FUTURES")
        lines.append("")

        if sp is not None:
            arrow = "▲" if sp_chg and sp_chg >= 0 else "▼"
            chg_str = f"{'+' if sp_chg >= 0 else ''}{sp_chg:.2f}%" if sp_chg else ""
            lines.append(f"  S&P      {sp:>8,.0f}  {arrow} {chg_str}")

        if nq is not None:
            arrow = "▲" if nq_chg and nq_chg >= 0 else "▼"
            chg_str = f"{'+' if nq_chg >= 0 else ''}{nq_chg:.2f}%" if nq_chg else ""
            lines.append(f"  NASDAQ   {nq:>8,.0f}  {arrow} {chg_str}")

        if tnx is not None:
            lines.append(f"  10Y      {tnx:>8.2f}%")

        lines.append("")

    # LunarCrush social intelligence moved to separate LunarCrush Brief workflow

    # Pre-Market Movers - show more detail
    if premarket_movers:
        lines.append("▸ YOUR MOVERS")
        lines.append("")
        for mover in premarket_movers[:8]:
            symbol = mover["symbol"]
            change = mover["change_pct"]
            price = mover["price"]
            arrow = "▲" if change >= 0 else "▼"
            sign = "+" if change >= 0 else ""
            lines.append(f"  {arrow} {symbol:<6} ${price:>7.2f}  {sign}{change:.1f}%")
        lines.append("")

    # Today's Earnings (if any)
    today_str = datetime.now().strftime("%Y-%m-%d")
    todays_reports = [e for e in today_earnings if e.get("date") == today_str]

    if todays_reports:
        lines.append("▸ REPORTING TODAY")
        lines.append("")

        # Sort: pre-market first
        def sort_key(e):
            hour = e.get("hour", "")
            return 0 if hour == "bmo" else 1 if hour == "amc" else 2

        for e in sorted(todays_reports, key=sort_key):
            symbol = e["symbol"]
            hour = e.get("hour", "")
            timing = "pre" if hour == "bmo" else "post" if hour == "amc" else ""
            eps = e.get("eps_estimate")
            eps_str = f"  est ${eps:.2f}" if eps else ""
            lines.append(f"  {symbol:<6} {timing:<4}{eps_str}")
        lines.append("")

    # Vital Knowledge Highlights (fresh items)
    if vk_highlights:
        lines.append("▸ VITAL KNOWLEDGE")
        lines.append("")
        for item in vk_highlights[:5]:  # Fewer for pre-market
            tickers = item.get("tickers", [])
            ticker_str = ", ".join(tickers[:2])
            text = item.get("text", "")[:100]
            lines.append(f"  [{ticker_str}]")
            lines.append(f"    {text}")
            lines.append("")

    # If nothing notable
    if not premarket_movers and not todays_reports and not vk_highlights:
        lines.append("  Quiet morning. No significant moves.")
        lines.append("")

    # Compact footer
    lines.append("────────────────────────────")
    lines.append(f"  {holdings_count} holdings · bell in 40 min")
    lines.append("")

    return "\n".join(lines)


def format_market_recap(market_close: dict, portfolio_perf: list[dict],
                        filtered_news: list[dict], holdings_count: int,
                        rsi_alerts: list[dict] = None) -> str:
    """Format the afternoon market recap with refined aesthetics."""
    now = datetime.now()
    
    # Elegant header
    lines = [
        "",
        "────────────────────────────────────",
        "         M A R K E T   R E C A P",
        f"         {now.strftime('%A, %B %d, %Y')}",
        "────────────────────────────────────",
        ""
    ]

    # Market Close
    lines.append("▸ MARKET CLOSE")
    lines.append("")
    
    sp = market_close.get("sp500")
    sp_chg = market_close.get("sp500_change")
    nq = market_close.get("nasdaq")
    nq_chg = market_close.get("nasdaq_change")
    dow = market_close.get("dow")
    dow_chg = market_close.get("dow_change")
    vix = market_close.get("vix")
    tnx = market_close.get("treasury_10y")
    
    if sp is not None:
        arrow = "▲" if sp_chg and sp_chg >= 0 else "▼"
        chg_str = f"{'+' if sp_chg >= 0 else ''}{sp_chg:.2f}%" if sp_chg else ""
        lines.append(f"  S&P 500     {sp:>10,.2f}  {arrow} {chg_str}")
    
    if nq is not None:
        arrow = "▲" if nq_chg and nq_chg >= 0 else "▼"
        chg_str = f"{'+' if nq_chg >= 0 else ''}{nq_chg:.2f}%" if nq_chg else ""
        lines.append(f"  NASDAQ      {nq:>10,.2f}  {arrow} {chg_str}")
    
    if dow is not None:
        arrow = "▲" if dow_chg and dow_chg >= 0 else "▼"
        chg_str = f"{'+' if dow_chg >= 0 else ''}{dow_chg:.2f}%" if dow_chg else ""
        lines.append(f"  Dow Jones   {dow:>10,.2f}  {arrow} {chg_str}")
    
    lines.append("")
    
    if vix is not None:
        lines.append(f"  VIX         {vix:>10.2f}")
    if tnx is not None:
        lines.append(f"  10Y Yield   {tnx:>10.2f}%")
    
    lines.append("")

    # Portfolio Performance
    if portfolio_perf:
        # Sort by change percentage
        sorted_perf = sorted(portfolio_perf, key=lambda x: x["change_pct"], reverse=True)
        
        gainers = [p for p in sorted_perf if p["change_pct"] > 0][:5]
        losers = [p for p in sorted_perf if p["change_pct"] < 0][-5:]
        losers.reverse()  # Most negative first
        
        # Top Gainers
        if gainers:
            lines.append("▸ TOP GAINERS")
            lines.append("")
            for p in gainers:
                symbol = p["symbol"]
                price = p["price"]
                change = p["change_pct"]
                lines.append(f"  ▲ {symbol:<6} ${price:>8.2f}  +{change:.1f}%")
            lines.append("")
        
        # Top Losers
        if losers:
            lines.append("▸ TOP LOSERS")
            lines.append("")
            for p in losers:
                symbol = p["symbol"]
                price = p["price"]
                change = p["change_pct"]
                lines.append(f"  ▼ {symbol:<6} ${price:>8.2f}  {change:.1f}%")
            lines.append("")
        
        # Portfolio Summary
        avg_change = sum(p["change_pct"] for p in portfolio_perf) / len(portfolio_perf)
        up_count = len([p for p in portfolio_perf if p["change_pct"] > 0])
        down_count = len([p for p in portfolio_perf if p["change_pct"] < 0])
        
        lines.append("▸ PORTFOLIO SUMMARY")
        lines.append("")
        arrow = "▲" if avg_change >= 0 else "▼"
        sign = "+" if avg_change >= 0 else ""
        lines.append(f"  Average Move   {arrow} {sign}{avg_change:.2f}%")
        lines.append(f"  Advancers      {up_count}")
        lines.append(f"  Decliners      {down_count}")
        lines.append("")

        # 52-Week Highs
        highs_52w = [p for p in portfolio_perf if p.get("at_52w_high")]
        if highs_52w:
            lines.append("▸ 52-WEEK HIGHS")
            lines.append("")
            for p in highs_52w:
                symbol = p["symbol"]
                price = p["price"]
                year_high = p.get("year_high", price)
                lines.append(f"  ★ {symbol:<6} ${price:>8.2f}  (52w: ${year_high:.2f})")
            lines.append("")

        # 52-Week Lows
        lows_52w = [p for p in portfolio_perf if p.get("at_52w_low")]
        if lows_52w:
            lines.append("▸ 52-WEEK LOWS")
            lines.append("")
            for p in lows_52w:
                symbol = p["symbol"]
                price = p["price"]
                year_low = p.get("year_low", price)
                lines.append(f"  ⚠ {symbol:<6} ${price:>8.2f}  (52w: ${year_low:.2f})")
            lines.append("")

    # RSI Alerts (oversold stocks)
    if rsi_alerts:
        lines.append("▸ RSI WATCH (Oversold)")
        lines.append("")
        for alert in rsi_alerts:
            symbol = alert["symbol"]
            rsi = alert["current_rsi"]
            min_rsi = alert["min_rsi_52w"]
            flags = []
            if alert["is_oversold"]:
                flags.append("oversold")
            if alert["is_52w_low"]:
                flags.append("52w RSI low")
            flag_str = " · ".join(flags)
            lines.append(f"  {symbol:<6} RSI {rsi:>5.1f}  (52w min: {min_rsi:.1f})  {flag_str}")
        lines.append("")

    # Afternoon News Highlights
    important = [n for n in filtered_news if n.get("category") in ["URGENT", "IMPORTANT"]]
    if important:
        lines.append("▸ NEWS HIGHLIGHTS")
        lines.append("")
        for item in important[:5]:
            ticker = item.get("ticker", "???")
            summary = item.get("summary", item.get("title", ""))[:65]
            link = item.get("link", "")
            lines.append(f"  • [{ticker}] {summary}")
            if link:
                lines.append(f"    {link}")
        lines.append("")

    # Footer
    lines.append("────────────────────────────────────")
    lines.append(f"  {holdings_count} holdings · {now.strftime('%I:%M %p')} PT")
    lines.append("")

    return "\n".join(lines)


def format_lunarcrush_brief(social_alerts: list[dict], creator_signals: list[dict],
                             holdings_count: int) -> str:
    """Format the standalone LunarCrush social intelligence brief.

    Runs at 6:20 AM as a separate message from the premarket update.
    Holdings-focused dashboard: always shows top holdings' social metrics,
    with interpretive overlay flagging divergences and anomalies.
    Creator signals follow with cross-references to holdings.
    """
    now = datetime.now()

    lines = [
        "",
        "┌─────────────────────────────────────┐",
        "│   LUNARCRUSH · SOCIAL INTELLIGENCE  │",
        f"│   {now.strftime('%A, %B %d')}                    │",
        "└─────────────────────────────────────┘",
        ""
    ]

    # ── Holdings Social Dashboard ──
    if social_alerts:
        lines.append("▸ YOUR HOLDINGS — SOCIAL PULSE")
        lines.append("")

        for item in social_alerts:
            lines.extend(_format_lunarcrush_ticker(item))
            lines.append(f"         https://lunarcrush.com/topic/{item['symbol'].lower()}")
            lines.append("")

        lines.append("  ⚡ = actionable signal  ⚠️ = watch")
        lines.append("")
    else:
        lines.append("  No social data available for holdings today.")
        lines.append("")

    # ── Creator Signals ──
    if creator_signals:
        lines.append("▸ KEY VOICES — CREATOR SIGNALS")
        lines.append("")

        for creator in creator_signals:
            handle = creator["handle"]
            name = creator["name"]
            fol = creator["followers_display"]
            eng = creator["engagements_display"]
            holding_topics = creator.get("holding_topics", [])
            top_topics = creator.get("top_topics", [])
            eng_raw = creator.get("engagements_24h", 0)

            # Color-code creator engagement level
            if eng_raw > 500000:
                eng_flag = " 🔥 viral reach"
            elif eng_raw > 100000:
                eng_flag = " 🟢 high engagement"
            else:
                eng_flag = ""

            lines.append(f"  {name} (@{handle}) · {fol} followers · {eng} eng/24h{eng_flag}")

            if holding_topics:
                parts = []
                for ht in holding_topics[:4]:
                    topic = ht["topic"].upper()
                    count = ht["count"]
                    parts.append(f"{topic}({count})")
                lines.append(f"    🟢 YOUR HOLDINGS: {', '.join(parts)}")
                lines.append(f"    key-voice overlap with your book — historically, sustained creator attention precedes 1-3 week trends")
            elif top_topics:
                parts = []
                for tt in top_topics[:3]:
                    topic = tt["topic"]
                    count = tt["count"]
                    parts.append(f"{topic}({count})")
                lines.append(f"    talking: {', '.join(parts)}")

            lines.append(f"    https://lunarcrush.com/creator/x/{handle}")
            lines.append("")

    # Footer
    lines.append("─────────────────────────────────────")
    lines.append(f"  {holdings_count} holdings tracked · {now.strftime('%I:%M %p')} PT")
    lines.append("")

    return "\n".join(lines)


def run_lunarcrush_brief():
    """Run the 6:20 AM LunarCrush social intelligence brief.

    Separate from the premarket update — arrives as its own message
    with holdings-focused social dashboard and creator signals.
    """
    print("\n" + "=" * 50)
    print("LunarCrush Social Intelligence Brief")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 50)

    all_tickers = CONFIG["INDIVIDUAL_STOCKS"] + CONFIG["ETFS"]

    print(f"\nChecking social data for {len(CONFIG['INDIVIDUAL_STOCKS'])} individual holdings...")

    print("\n[1/2] Fetching social buzz (LunarCrush topics)...")
    social_alerts = fetch_social_buzz(
        CONFIG["INDIVIDUAL_STOCKS"],
        CONFIG["LUNARCRUSH_API_KEY"],
        CONFIG["SOCIAL_BUZZ_THRESHOLD"]
    )
    print(f"  Found social data for {len(social_alerts)} tickers")

    print("\n[2/2] Fetching creator signals (LunarCrush creators)...")
    creator_signals = fetch_creator_signals(
        CONFIG["CREATOR_WATCHLIST"],
        CONFIG["LUNARCRUSH_API_KEY"],
        CONFIG["INDIVIDUAL_STOCKS"]
    )
    print(f"  Got data for {len(creator_signals)} creators")

    print("\nGenerating LunarCrush brief...")
    brief = format_lunarcrush_brief(social_alerts, creator_signals, len(all_tickers))

    # Print to console
    print("\n" + "=" * 50)
    print(brief)
    print("=" * 50)

    # Send via iMessage
    print(f"\nSending iMessage to {CONFIG['IMESSAGE_RECIPIENT']}...")
    imessage_success = send_imessage(CONFIG["IMESSAGE_RECIPIENT"], brief)

    # Send via Email
    print(f"Sending email to {CONFIG['EMAIL_RECIPIENT']}...")
    today = datetime.now().strftime("%B %d, %Y")
    email_subject = f"LunarCrush Brief - {today}"
    email_success = send_email(CONFIG["EMAIL_RECIPIENT"], email_subject, brief)

    if imessage_success and email_success:
        print("\n✓ LunarCrush brief delivered via iMessage and Email!")
    elif imessage_success:
        print("\n⚠ Brief sent via iMessage only (email failed)")
    elif email_success:
        print("\n⚠ Brief sent via Email only (iMessage failed)")
    else:
        print("\n✗ Delivery failed - check iMessage and Mail configuration")


# ============================================================================
# DELIVERY
# ============================================================================

def _wake_app(app_name: str) -> None:
    """Activate an app to wake it from App Nap before sending Apple Events."""
    try:
        subprocess.run(
            ["osascript", "-e", f'tell application "{app_name}" to activate'],
            capture_output=True, text=True, timeout=30
        )
        time.sleep(2)  # Give app time to fully wake
    except Exception:
        pass  # Best effort — continue even if activate fails


def _chunk_message(message: str, max_chars: int = 4000) -> list:
    """Split a long message into chunks at section boundaries."""
    if len(message) <= max_chars:
        return [message]

    chunks = []
    remaining = message
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        # Try to split at a section boundary (double newline or ═/─ line)
        split_at = -1
        for marker in ["\n\n▸ ", "\n\n┌", "\n\n────", "\n══", "\n\n"]:
            idx = remaining.rfind(marker, 0, max_chars)
            if idx > max_chars // 4:  # Don't split too early
                split_at = idx
                break
        if split_at == -1:
            # Fallback: split at last newline before limit
            split_at = remaining.rfind("\n", 0, max_chars)
        if split_at <= 0:
            split_at = max_chars
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    return chunks


def send_imessage(recipient: str, message: str, max_retries: int = 3) -> bool:
    """Send message via iMessage using AppleScript.

    Wakes Messages.app from App Nap before sending, chunks long messages,
    and retries on timeout (-1712) errors.
    """
    chunks = _chunk_message(message)
    print(f"  iMessage: {len(message)} chars in {len(chunks)} chunk(s)")

    # Wake Messages.app from App Nap (critical for 5 AM launchd runs)
    _wake_app("Messages")

    for i, chunk in enumerate(chunks):
        escaped_chunk = chunk.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

        applescript = f'''
        with timeout of 300 seconds
            tell application "Messages"
                set targetService to 1st account whose service type = iMessage
                set targetBuddy to participant "{recipient}" of targetService
                send "{escaped_chunk}" to targetBuddy
            end tell
        end timeout
        '''

        sent = False
        for attempt in range(1, max_retries + 1):
            try:
                subprocess.run(
                    ["osascript", "-e", applescript],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=320  # Python timeout slightly longer than AppleScript timeout
                )
                sent = True
                if len(chunks) > 1:
                    print(f"  ✓ Chunk {i+1}/{len(chunks)} sent")
                    time.sleep(1)  # Inter-chunk delay
                break
            except subprocess.CalledProcessError as e:
                print(f"  ✗ iMessage attempt {attempt}/{max_retries}: {e.stderr.strip()}")
                if attempt < max_retries:
                    print(f"    Retrying in 5s (re-activating Messages.app)...")
                    _wake_app("Messages")
                    time.sleep(3)
            except subprocess.TimeoutExpired:
                print(f"  ✗ iMessage attempt {attempt}/{max_retries}: Python subprocess timeout (320s)")
                if attempt < max_retries:
                    _wake_app("Messages")
                    time.sleep(3)

        if not sent:
            print(f"✗ Failed to send iMessage after {max_retries} attempts")
            return False

    print(f"✓ iMessage sent to {recipient}")
    return True


def send_email(recipient: str, subject: str, body: str, max_retries: int = 3) -> bool:
    """Send email via Apple Mail using AppleScript.

    Wakes Mail.app from App Nap before sending, with retry on timeout.
    """
    escaped_body = body.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\r")
    escaped_subject = subject.replace('"', '\\"')

    # Wake Mail.app from App Nap (critical for 5 AM launchd runs)
    _wake_app("Mail")

    applescript = f'''
    with timeout of 300 seconds
        tell application "Mail"
            set newMessage to make new outgoing message with properties {{subject:"{escaped_subject}", content:"{escaped_body}", visible:false}}
            tell newMessage
                make new to recipient at end of to recipients with properties {{address:"{recipient}"}}
                send
            end tell
        end tell
    end timeout
    '''

    for attempt in range(1, max_retries + 1):
        try:
            subprocess.run(
                ["osascript", "-e", applescript],
                check=True,
                capture_output=True,
                text=True,
                timeout=320
            )
            print(f"✓ Email sent to {recipient}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"  ✗ Email attempt {attempt}/{max_retries}: {e.stderr.strip()}")
            if attempt < max_retries:
                print(f"    Retrying in 5s (re-activating Mail.app)...")
                _wake_app("Mail")
                time.sleep(3)
        except subprocess.TimeoutExpired:
            print(f"  ✗ Email attempt {attempt}/{max_retries}: Python subprocess timeout (320s)")
            if attempt < max_retries:
                _wake_app("Mail")
                time.sleep(3)

    print(f"✗ Failed to send email after {max_retries} attempts")
    return False


# ============================================================================
# MAIN
# ============================================================================

def run_morning_briefing():
    """Run the morning briefing workflow."""
    print("\n" + "=" * 50)
    print("Morning Briefing")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 50)

    # Validate configuration
    if CONFIG["ANTHROPIC_API_KEY"] == "YOUR_ANTHROPIC_API_KEY_HERE":
        print("ERROR: Please set your Anthropic API key")
        print("  Edit this file or set ANTHROPIC_API_KEY environment variable")
        return

    if CONFIG["IMESSAGE_RECIPIENT"] == "YOUR_PHONE_OR_EMAIL_HERE":
        print("ERROR: Please set your iMessage recipient")
        print("  Edit this file or set IMESSAGE_RECIPIENT environment variable")
        return

    # Combine all tickers
    all_tickers = CONFIG["INDIVIDUAL_STOCKS"] + CONFIG["ETFS"]
    ticker_set = set(all_tickers)

    print(f"\nMonitoring {len(all_tickers)} holdings...")

    # Fetch data
    print("\n[1/10] Fetching market snapshot...")
    market_snapshot = fetch_market_snapshot(CONFIG["FINNHUB_API_KEY"])
    sp = market_snapshot.get("sp500_futures")
    nq = market_snapshot.get("nasdaq_futures")
    tnx = market_snapshot.get("treasury_10y")
    print(f"  S&P Futures: {sp:,.0f}" if sp else "  S&P Futures: N/A")
    print(f"  NASDAQ Futures: {nq:,.0f}" if nq else "  NASDAQ Futures: N/A")
    print(f"  10Y Treasury: {tnx:.2f}%" if tnx else "  10Y Treasury: N/A")

    print("\n[2/10] Fetching Yahoo Finance news...")
    news = fetch_yahoo_news(all_tickers)
    print(f"  Found {len(news)} news items")

    print("\n[3/10] Fetching upcoming earnings (Finnhub)...")
    finnhub_upcoming = fetch_finnhub_earnings(CONFIG["FINNHUB_API_KEY"], ticker_set)
    print(f"  Found {len(finnhub_upcoming)} from Finnhub")
    
    # Check yfinance for tickers NOT found in Finnhub (Yahoo v10 quoteSummary returns 401)
    finnhub_symbols = {e["symbol"] for e in finnhub_upcoming}
    missing_upcoming = ticker_set - finnhub_symbols

    print(f"\n[3b/10] Fetching upcoming earnings (yfinance) for {len(missing_upcoming)} missing tickers...")
    yf_upcoming = fetch_yfinance_upcoming_earnings(ticker_set, finnhub_symbols)
    print(f"  Found {len(yf_upcoming)} additional from yfinance")

    # Merge upcoming earnings
    earnings = merge_upcoming_earnings(finnhub_upcoming, yf_upcoming)
    print(f"  Combined: {len(earnings)} upcoming earnings this week")

    # RSI moved early — Alpha Vantage calls get natural cooldown before AV earnings lookup
    print("\n[4/10] Fetching RSI alerts (Alpha Vantage)...")
    rsi_alerts = fetch_rsi_alerts(CONFIG["ALPHA_VANTAGE_API_KEY"], CONFIG["INDIVIDUAL_STOCKS"])
    print(f"  Found {len(rsi_alerts)} stocks with RSI alerts")

    print("\n[5/10] Fetching earnings scorecard (last 4 weeks) (Finnhub)...")
    finnhub_scorecard = fetch_earnings_scorecard(CONFIG["FINNHUB_API_KEY"], ticker_set)
    print(f"  Found {len(finnhub_scorecard)} from Finnhub")

    # Check which symbols we already have
    found_symbols = {item["symbol"] for item in finnhub_scorecard}

    # yfinance is the most reliable secondary source (FMP endpoints are dead, Yahoo v10 returns 401)
    still_missing = len(ticker_set - found_symbols)
    print(f"\n[6/10] yfinance earnings lookup for {still_missing} remaining tickers...")
    yf_scorecard = fetch_yfinance_earnings(ticker_set, found_symbols)
    print(f"  Found {len(yf_scorecard)} additional via yfinance")

    # Update found symbols
    found_symbols.update({item["symbol"] for item in yf_scorecard})
    still_missing = len(ticker_set - found_symbols)

    # Alpha Vantage earnings — naturally spaced from RSI calls above by Finnhub + yfinance work
    print(f"\n[6b/10] Alpha Vantage lookup for {still_missing} remaining tickers...")
    alpha_scorecard = fetch_alpha_vantage_earnings(CONFIG["ALPHA_VANTAGE_API_KEY"], ticker_set - found_symbols) if still_missing > 0 else []
    print(f"  Found {len(alpha_scorecard)} additional via Alpha Vantage")

    # Merge earnings data from all sources (FMP and Yahoo v10 skipped — endpoints dead)
    scorecard = merge_earnings_data(finnhub_scorecard, [], None, yf_scorecard, None, alpha_scorecard)
    print(f"  Combined: {len(scorecard)} unique earnings results (4-week lookback)")

    # 4-week earnings history: load previous, merge, save
    print("\n[6c/10] Loading/saving 4-week earnings history...")
    earnings_history = load_earnings_history(CONFIG["EARNINGS_HISTORY_FILE"])
    scorecard = merge_with_history(scorecard, earnings_history)
    print(f"  {len(scorecard)} total earnings results (with history)")

    # Forward estimates — FMP analyst-estimates requires paid tier (402)
    # Keeping the function for future use; skipping the call for now
    forward_estimates = {}
    # Uncomment when FMP plan supports it:
    # print("\n[6d/10] Fetching forward estimates (FMP)...")
    # reported_symbols = [s["symbol"] for s in scorecard]
    # forward_estimates = fetch_forward_estimates(CONFIG["FMP_API_KEY"], reported_symbols)
    # for entry in scorecard:
    #     if entry["symbol"] in forward_estimates:
    #         entry.update(forward_estimates[entry["symbol"]])
    # print(f"  Forward estimates for {len(forward_estimates)} companies")

    print("\n[7/10] Fetching pre-market movers...")
    premarket_movers = fetch_premarket_movers(CONFIG["FMP_API_KEY"], all_tickers, threshold=3.0)
    print(f"  Found {len(premarket_movers)} holdings moving >3%")

    print("\n[7b/10] Fetching analyst actions (yfinance)...")
    analyst_actions = fetch_analyst_actions(None, ticker_set)
    total_actions = sum(len(v) for v in analyst_actions.values())
    print(f"  Found {total_actions} analyst actions across {len(analyst_actions)} tickers")

    # LunarCrush calls — now separated from Alpha Vantage by FMP/Finnhub/yfinance work
    print("\n[8/10] Checking social buzz (LunarCrush)...")
    social_alerts = fetch_social_buzz(CONFIG["INDIVIDUAL_STOCKS"], CONFIG["LUNARCRUSH_API_KEY"], CONFIG["SOCIAL_BUZZ_THRESHOLD"])
    print(f"  Found social data for {len(social_alerts)} tickers")

    print("\n[8b/10] Checking creator signals (LunarCrush)...")
    creator_signals = fetch_creator_signals(
        CONFIG["CREATOR_WATCHLIST"],
        CONFIG["LUNARCRUSH_API_KEY"],
        CONFIG["INDIVIDUAL_STOCKS"]
    )
    print(f"  Got data for {len(creator_signals)} creators")

    print("\n[9/10] Filtering news with AI...")
    filtered_news = filter_news_with_ai(news, CONFIG["ANTHROPIC_API_KEY"])
    print(f"  {len(filtered_news)} items after filtering")

    print("\n[10/10] Fetching Vital Knowledge highlights...")
    vk_highlights = fetch_vital_knowledge(
        all_tickers,
        CONFIG["GMAIL_CREDENTIALS_FILE"],
        CONFIG["GMAIL_TOKEN_FILE"],
        CONFIG["VITAL_KNOWLEDGE_SENDER"]
    )

    print("\nAnalyzing earnings misses...")
    misses = [s for s in scorecard if not s.get("beat")]
    miss_explanations = explain_earnings_misses(misses, CONFIG["ANTHROPIC_API_KEY"])
    print(f"  Generated explanations for {len(miss_explanations)} misses")

    print("Analyzing earnings guidance signals...")
    guidance_signals = analyze_earnings_guidance(scorecard, forward_estimates, CONFIG["ANTHROPIC_API_KEY"])
    for entry in scorecard:
        if entry["symbol"] in guidance_signals:
            entry["guidance_signal"] = guidance_signals[entry["symbol"]]
    print(f"  Guidance signals for {len(guidance_signals)} companies")

    # Save enriched scorecard to history
    save_earnings_history(CONFIG["EARNINGS_HISTORY_FILE"], scorecard, earnings_history)

    # ── v2 REDESIGN: AI-powered editorial brief ──────────────────────────
    print("\n[10/10] Generating AI intelligence brief...")

    # Bundle all data for the AI
    briefing_data = {
        "market_snapshot": market_snapshot,
        "premarket_movers": premarket_movers,
        "filtered_news": filtered_news,
        "scorecard": scorecard,
        "earnings": earnings,
        "rsi_alerts": rsi_alerts,
        "vk_highlights": vk_highlights if vk_highlights else [],
        "miss_explanations": miss_explanations,
        "social_alerts": [],       # Social is in separate 6:20 AM brief
        "creator_signals": [],
        "analyst_actions": analyst_actions,
    }

    try:
        ai_brief = generate_ai_morning_brief(briefing_data, CONFIG["ANTHROPIC_API_KEY"])
        print("  ✓ AI brief generated")

        # Format HTML email
        html_email = format_morning_html(ai_brief, briefing_data)
        print(f"  ✓ HTML email: {len(html_email):,} bytes")

        # Format plain text iMessage
        text_message = format_morning_text(ai_brief, briefing_data)
        print(f"  ✓ Plain text: {len(text_message):,} chars")

    except Exception as e:
        print(f"  ✗ AI brief failed: {e}")
        print("  Falling back to legacy formatter...")
        text_message = format_briefing(filtered_news, earnings, scorecard, [], miss_explanations,
                                       len(all_tickers), market_snapshot, premarket_movers, rsi_alerts, vk_highlights,
                                       analyst_actions=analyst_actions)
        html_email = None

    # Print to console
    print("\n" + "=" * 50)
    print(text_message)
    print("=" * 50)

    # Send via iMessage (plain text)
    print(f"\nSending iMessage to {CONFIG['IMESSAGE_RECIPIENT']}...")
    imessage_success = send_imessage(CONFIG["IMESSAGE_RECIPIENT"], text_message)

    # Send via Email (HTML if available, plain text fallback)
    print(f"Sending email to {CONFIG['EMAIL_RECIPIENT']}...")
    today = datetime.now().strftime("%B %d, %Y")
    if html_email:
        email_subject = f"Morning Brief \u2013 {today}"
        email_success = send_html_email(CONFIG["EMAIL_RECIPIENT"], email_subject, html_email)
    else:
        email_subject = f"Morning Briefing - {today}"
        email_success = send_email(CONFIG["EMAIL_RECIPIENT"], email_subject, text_message)

    if imessage_success and email_success:
        print("\n✓ Morning briefing delivered via iMessage and Email!")
    elif imessage_success:
        print("\n⚠ Briefing sent via iMessage only (email failed)")
    elif email_success:
        print("\n⚠ Briefing sent via Email only (iMessage failed)")
    else:
        print("\n✗ Delivery failed - check iMessage and Mail configuration")


def run_market_recap():
    """Run the afternoon market recap workflow."""
    print("\n" + "=" * 50)
    print("Market Recap")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 50)

    # Combine all tickers
    all_tickers = CONFIG["INDIVIDUAL_STOCKS"] + CONFIG["ETFS"]
    ticker_set = set(all_tickers)

    print(f"\nAnalyzing {len(all_tickers)} holdings...")

    # Fetch data
    print("\n[1/5] Fetching market close data...")
    market_close = fetch_market_close(CONFIG["FINNHUB_API_KEY"])
    sp = market_close.get("sp500")
    sp_chg = market_close.get("sp500_change")
    print(f"  S&P 500: {sp:,.2f} ({'+' if sp_chg >= 0 else ''}{sp_chg:.2f}%)" if sp else "  S&P 500: N/A")

    print("\n[2/5] Fetching portfolio performance (incl. 52-week data)...")
    portfolio_perf = fetch_portfolio_performance(CONFIG["FMP_API_KEY"], all_tickers)
    highs_52w = [p for p in portfolio_perf if p.get("at_52w_high")]
    lows_52w = [p for p in portfolio_perf if p.get("at_52w_low")]
    print(f"  Got quotes for {len(portfolio_perf)} holdings")
    print(f"  52-week highs: {len(highs_52w)} · 52-week lows: {len(lows_52w)}")

    print("\n[3/5] Fetching RSI alerts (Alpha Vantage)...")
    rsi_alerts = fetch_rsi_alerts(CONFIG["ALPHA_VANTAGE_API_KEY"], CONFIG["INDIVIDUAL_STOCKS"])
    print(f"  Found {len(rsi_alerts)} stocks with RSI alerts")

    print("\n[4/5] Fetching afternoon news...")
    news = fetch_yahoo_news(all_tickers)
    filtered_news = filter_news_with_ai(news, CONFIG["ANTHROPIC_API_KEY"]) if news else []
    print(f"  {len(filtered_news)} material news items")

    print("\n[5/5] Generating recap...")
    recap = format_market_recap(market_close, portfolio_perf, filtered_news, len(all_tickers), rsi_alerts)

    # Print recap to console
    print("\n" + "=" * 50)
    print(recap)
    print("=" * 50)

    # Send via iMessage
    print(f"\nSending iMessage to {CONFIG['IMESSAGE_RECIPIENT']}...")
    imessage_success = send_imessage(CONFIG["IMESSAGE_RECIPIENT"], recap)

    # Send via Email
    print(f"Sending email to {CONFIG['EMAIL_RECIPIENT']}...")
    today = datetime.now().strftime("%B %d, %Y")
    email_subject = f"Market Recap - {today}"
    email_success = send_email(CONFIG["EMAIL_RECIPIENT"], email_subject, recap)

    if imessage_success and email_success:
        print("\n✓ Market recap delivered via iMessage and Email!")
    elif imessage_success:
        print("\n⚠ Recap sent via iMessage only (email failed)")
    elif email_success:
        print("\n⚠ Recap sent via Email only (iMessage failed)")
    else:
        print("\n✗ Delivery failed - check iMessage and Mail configuration")


def run_premarket_update():
    """Run the 6:20 AM pre-market update - quick check before the bell."""
    print("\n" + "=" * 50)
    print("Pre-Market Update")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 50)

    # Combine all tickers
    all_tickers = CONFIG["INDIVIDUAL_STOCKS"] + CONFIG["ETFS"]
    ticker_set = set(all_tickers)

    print(f"\nChecking {len(all_tickers)} holdings...")

    # Fetch data (lightweight - no AI filtering)
    print("\n[1/4] Fetching market snapshot...")
    market_snapshot = fetch_market_snapshot(CONFIG["FINNHUB_API_KEY"])
    sp = market_snapshot.get("sp500_futures")
    nq = market_snapshot.get("nasdaq_futures")
    print(f"  S&P Futures: {sp:,.0f}" if sp else "  S&P Futures: N/A")
    print(f"  NASDAQ Futures: {nq:,.0f}" if nq else "  NASDAQ Futures: N/A")

    print("\n[2/4] Fetching pre-market movers...")
    premarket_movers = fetch_premarket_movers(CONFIG["FMP_API_KEY"], all_tickers, threshold=2.0)
    print(f"  Found {len(premarket_movers)} holdings moving >2%")

    print("\n[3/4] Fetching today's earnings...")
    finnhub_upcoming = fetch_finnhub_earnings(CONFIG["FINNHUB_API_KEY"], ticker_set)
    print(f"  Found {len(finnhub_upcoming)} earnings events")

    print("\n[4/4] Fetching Vital Knowledge highlights...")
    vk_highlights = fetch_vital_knowledge(
        all_tickers,
        CONFIG["GMAIL_CREDENTIALS_FILE"],
        CONFIG["GMAIL_TOKEN_FILE"],
        CONFIG["VITAL_KNOWLEDGE_SENDER"]
    )

    print("\nGenerating pre-market update...")
    update = format_premarket_update(
        market_snapshot, premarket_movers, finnhub_upcoming,
        vk_highlights, len(all_tickers)
    )

    # Print update to console
    print("\n" + "=" * 50)
    print(update)
    print("=" * 50)

    # Send via iMessage
    print(f"\nSending iMessage to {CONFIG['IMESSAGE_RECIPIENT']}...")
    imessage_success = send_imessage(CONFIG["IMESSAGE_RECIPIENT"], update)

    # Send via Email
    print(f"Sending email to {CONFIG['EMAIL_RECIPIENT']}...")
    today = datetime.now().strftime("%B %d, %Y")
    email_subject = f"Pre-Market Update - {today}"
    email_success = send_email(CONFIG["EMAIL_RECIPIENT"], email_subject, update)

    if imessage_success and email_success:
        print("\n✓ Pre-market update delivered!")
    elif imessage_success:
        print("\n⚠ Update sent via iMessage only (email failed)")
    elif email_success:
        print("\n⚠ Update sent via Email only (iMessage failed)")
    else:
        print("\n✗ Delivery failed - check iMessage and Mail configuration")


def main():
    """Main entry point - dispatch based on command line argument."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"

    if mode == "--setup-gmail":
        print("\n" + "=" * 50)
        print("Gmail API Setup for Vital Knowledge Integration")
        print("=" * 50)
        setup_gmail_auth(CONFIG["GMAIL_CREDENTIALS_FILE"], CONFIG["GMAIL_TOKEN_FILE"])
        return

    # Lockfile guard: prevent duplicate runs of the same mode
    lock_path = f"/tmp/briefing-{mode}.lock"
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        print(f"Another {mode} briefing is already running (lockfile: {lock_path}). Exiting.")
        return

    try:
        if mode == "premarket":
            run_premarket_update()
        elif mode == "recap":
            run_market_recap()
        elif mode == "lunarcrush":
            run_lunarcrush_brief()
        else:
            run_morning_briefing()
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
        try:
            os.remove(lock_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
