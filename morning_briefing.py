#!/usr/bin/env python3
"""
Morning Briefing System
Generates a daily digest of material news and earnings for stock holdings.
Email-only delivery via Apple Mail; iMessage path was removed in v2.6 (2026-05-19)
and is blocked at import time by `_v2_6_guard()` below.

Five workflow modes dispatched from main():
    morning           — 5:00 AM PT Mon–Fri, full AI editorial brief
    premarket         — 6:20 AM PT Mon–Fri, AI delta brief + bell plan
    recap             — 1:15 PM PT Mon–Fri, post-close editorial
    lunarcrush        — 5:30 PM PT Sunday, social/sentiment prep-for-the-week
    weekend_preview   — 6:00 PM PT Sunday, weekly setup

Usage:
    python3 morning_briefing.py [mode]   # mode defaults to "morning"

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
    format_market_recap_html,
    generate_ai_recap_brief,
    format_recap_text,
    generate_ai_premarket_brief,
    format_premarket_html,
    format_premarket_text,
    generate_ai_weekend_brief,
    format_weekend_html,
    format_weekend_text,
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

# === v2.6 safeguard: anti-regression guard ===
# Refuses to run if any iMessage symbol reappears.  This blocks the
# May-2026 deploy-drift regression at its source: if a future edit
# reintroduces send_imessage, IMESSAGE_RECIPIENT, _chunk_message, or
# format_morning_text-sent-via-imessage, the script exits 99 before
# any data fetch or email send.
def _v2_6_guard() -> None:
    import os, re, sys
    me = os.path.abspath(__file__)
    here = os.path.dirname(me)
    suspects = [
        os.path.join(here, "morning_briefing.py"),
        os.path.join(here, "morning_briefing_redesign.py"),
        os.path.join(here, "briefing_monitor.py"),
    ]
    forbidden = re.compile(r"\b(send_imessage|IMESSAGE_RECIPIENT|_chunk_message)\b")
    block_re = re.compile(
        r"# === v2\.6 safeguard.*?# === end v2\.6 safeguard ===",
        re.DOTALL,
    )
    for path in suspects:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            txt = fh.read()
        clean = block_re.sub("", txt)
        m = forbidden.search(clean)
        if m:
            sys.stderr.write(
                "\n[v2.6 GUARD] iMessage symbol '%s' reappeared in %s.\n"
                "Refusing to run.  See migrations/v2_6_imessage_removal_and_safeguards.py.\n\n"
                % (m.group(0), path)
            )
            sys.exit(99)


_v2_6_guard()
# === end v2.6 safeguard ===



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
    "EMAIL_RECIPIENT": os.getenv("EMAIL_RECIPIENT", ""),

    # Holdings — combined personal (JVS) ∪ firm-master top-30 stocks
    # Updated 2026-06-06 from SummPosn_Grp_JVS_Portfolio_060626.csv (full personal book, as of 06/05 close)
    #   + SummPosn_Mast_8000075_060526.csv (firm MASTER account, top 30 stock holdings by market value only, per Jeff)
    # Firm contribution capped at the 30 largest equity positions; firm ETFs and sub-top-30 names intentionally excluded.
    # Zero-quantity personal rows (FDXF, VBIL) excluded.
    # Personal: 63 stocks + 6 ETFs | Firm top-30 stocks | Combined: 70 stocks + 6 ETFs = 76 total
    "INDIVIDUAL_STOCKS": [
        # --- Held in both personal & firm-top30 ---
        "AAPL", "AMAT", "AMZN", "ARCC", "BAC", "BRKB", "C", "CMCSA", "CNH", "COF",
        "FCX", "FDX", "FISV", "GOOG", "META", "MSFT", "MU", "NVDA", "RIO", "SCHW",
        "UBER", "WFC", "WY",
        # --- Personal only ---
        "ABCL", "ABNB", "ADDYY", "AFRM", "AMD", "ASML", "AVAV", "CHTR", "CHWY", "DE",
        "DVN", "ELV", "EQT", "FSLR", "GILD", "GLXY", "HIMS", "IPWR", "ISRG", "LPKFF",
        "MDT", "MSGS", "MTN", "NBIS", "NFG", "ODD", "OUST", "PEYUF", "PLTR", "POWI",
        "RIG", "SOFI", "SOLS", "SU", "TDW", "TMUS", "TSLA", "VGZ", "ZBH", "ZETA",
        # --- Firm top-30 only (not in personal book) ---
        "BKR", "DIS", "GOOGL", "GS", "JNJ", "JPM", "PFE",
    ],
    "ETFS": [
        # --- Personal ETFs (firm master is equity-only / out of scope per top-30-stocks instruction) ---
        "CSRE", "DFEM", "DFEV", "GDX", "GDXJ", "URNM",
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

    # Strategy reads (Stratechery + Asianometry, recap only) — paid Passport RSS, tokens in URL
    "STRATECHERY_RSS_URL": os.getenv("STRATECHERY_RSS_URL", ""),
    "ASIANOMETRY_RSS_URL": os.getenv("ASIANOMETRY_RSS_URL", ""),
    "STRATEGY_READS_LOOKBACK_HOURS": 48,
    "STRATEGY_READS_SEEN_FILE": os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_reads_seen.json"),
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
                    "hour": item.get("hour", ""),  # bmo / amc / dmh
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


def fetch_todays_after_hours_earnings(api_key: str, tickers: set[str]) -> list[dict]:
    """Fetch today's after-market-close (AMC) earnings for our holdings.

    Returns BOTH reported and not-yet-reported AMC companies. If the recap runs
    shortly after market close, most reporters haven't published yet — we still
    surface them as 'pending' so the brief has forward-looking context.

    Each dict includes:
        reported (bool)  : True if Finnhub has actual EPS
        beat     (bool|None)
        eps_actual, eps_estimate, surprise_pct, rev_actual, rev_estimate, rev_beat
    """
    today = datetime.now().strftime("%Y-%m-%d")

    url = "https://finnhub.io/api/v1/calendar/earnings"
    params = {"from": today, "to": today, "token": api_key}

    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("earningsCalendar", []):
            symbol = item.get("symbol", "")
            hour = (item.get("hour") or "").lower()

            # Only today's after-market-close reporters among our holdings
            if symbol not in tickers or hour != "amc":
                continue

            eps_actual = item.get("epsActual")
            eps_estimate = item.get("epsEstimate")
            rev_actual = item.get("revenueActual")
            rev_estimate = item.get("revenueEstimate")

            reported = eps_actual is not None
            beat = None
            surprise_pct = None
            if reported and eps_estimate is not None:
                beat = eps_actual >= eps_estimate
                if eps_estimate != 0:
                    surprise_pct = ((eps_actual - eps_estimate) / abs(eps_estimate)) * 100

            rev_beat = None
            if rev_actual is not None and rev_estimate is not None:
                rev_beat = rev_actual >= rev_estimate

            results.append({
                "symbol": symbol,
                "date": item.get("date", today),
                "hour": "amc",
                "reported": reported,
                "eps_actual": eps_actual,
                "eps_estimate": eps_estimate,
                "beat": beat,
                "surprise_pct": surprise_pct,
                "rev_actual": rev_actual,
                "rev_estimate": rev_estimate,
                "rev_beat": rev_beat,
                "quarter": item.get("quarter"),
                "year": item.get("year"),
            })

        # Reported first (most interesting), then pending, alphabetical within
        results.sort(key=lambda x: (not x["reported"], x["symbol"]))
        return results
    except Exception as e:
        print(f"Error fetching today's after-hours earnings: {e}")
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

                # Coerce numpy scalars from pandas rows to Python-native types
                # BEFORE any arithmetic or comparison, otherwise `beat` becomes
                # numpy.bool_ which is not JSON serializable and breaks
                # save_earnings_history.
                eps_actual = float(eps_actual)
                eps_estimate = float(eps_estimate)
                surprise = eps_actual - eps_estimate
                surprise_pct = (surprise / abs(eps_estimate) * 100) if eps_estimate != 0 else 0

                scorecard.append({
                    "symbol": ticker,
                    "date": date_str,
                    "eps_actual": round(eps_actual, 2),
                    "eps_estimate": round(eps_estimate, 2),
                    "surprise": round(surprise, 4),
                    "surprise_pct": round(surprise_pct, 1),
                    "beat": bool(eps_actual >= eps_estimate),
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

            # fetch_premarket_movers is called from PRE-market flows (5 AM morning, 6:20 AM
            # premarket). If it somehow runs during POST (manual invocation), fall through to
            # Phase 2/3 — don't conflate after-hours movement with the day's move like the
            # 2026-04-23 recap bug did.
            if market_state in ("PRE", "PREPRE"):
                for symbol in tickers:
                    try:
                        info = yf.Ticker(symbol).info
                        price = info.get("preMarketPrice")
                        # During PRE, regularMarketPrice is yesterday's settlement close —
                        # the correct baseline for pre-market % moves. regularMarketPreviousClose
                        # can be 2 days stale early in pre-market.
                        prev_close = info.get("regularMarketPrice")
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
                    print(f"    yfinance: got pre-market prices for {len(found_symbols)} tickers")

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


# Priority/anchor holdings whose CURRENT price must always reach the AI brief,
# even when they are not moving enough to qualify as "movers." The editorial
# prompts repeatedly ask for tactical price levels on these names (PLTR above
# all, the ~30% anchor). fetch_premarket_movers only surfaces a price once a
# name clears the mover threshold, so on quiet days the model received NO PLTR
# price at all and invented a stale level — the 2026-06-15 "PLTR reclaiming $70"
# hallucination while it actually traded in the $130s. fetch_anchor_prices feeds
# a real price anchor so the "never invent a level" rule has data behind it.
ANCHOR_HOLDINGS = [
    "PLTR", "NVDA", "TSLA", "META", "AMZN", "GOOG", "GOOGL", "AMD", "SOFI",
    "UBER", "MSFT", "AAPL", "JPM", "ABNB", "AFRM", "HIMS", "ASML",
]


def fetch_anchor_prices(tickers: list[str]) -> dict[str, dict]:
    """Fetch current reference prices for anchor holdings regardless of move size.

    Returns {symbol: {"price": float, "prev_close": float|None, "change_pct": float|None}}.
    Uses the same yfinance market-state logic as fetch_premarket_movers: during PRE
    the baseline is regularMarketPrice (yesterday's settlement close); during POST/CLOSED
    the baseline is regularMarketPreviousClose. Failures are swallowed per-ticker so a
    single bad symbol never drops the whole anchor set.
    """
    wanted = [t for t in ANCHOR_HOLDINGS if t in set(tickers)]
    prices: dict[str, dict] = {}
    if not (YFINANCE_AVAILABLE and wanted):
        return prices
    try:
        import warnings
        warnings.filterwarnings("ignore", category=FutureWarning)
        for symbol in wanted:
            try:
                info = yf.Ticker(symbol).info
                state = info.get("marketState", "REGULAR")
                if state in ("PRE", "PREPRE"):
                    price = info.get("preMarketPrice") or info.get("regularMarketPrice")
                    prev_close = info.get("regularMarketPrice")
                elif state in ("POST", "POSTPOST", "CLOSED"):
                    price = info.get("postMarketPrice") or info.get("regularMarketPrice")
                    prev_close = (info.get("regularMarketPreviousClose")
                                  or info.get("regularMarketPrice"))
                else:
                    price = info.get("regularMarketPrice")
                    prev_close = info.get("regularMarketPreviousClose")
                if price:
                    change_pct = None
                    if prev_close and prev_close != 0 and price != prev_close:
                        change_pct = ((price - prev_close) / prev_close) * 100
                    prices[symbol] = {
                        "price": price,
                        "prev_close": prev_close,
                        "change_pct": change_pct,
                    }
            except Exception:
                continue
    except Exception as e:
        print(f"    Warning: anchor price fetch error: {e}")
    if prices:
        print(f"    Anchor reference prices: got {len(prices)}/{len(wanted)} priority names")
    return prices


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

            # PRE-market: price = preMarketPrice, baseline = regularMarketPrice (yesterday's close,
            #   since today's regular session hasn't opened yet).
            # POST-market: we want the DAY's move, not the after-hours move. So price = today's
            #   settlement close (regularMarketPrice during POST), baseline = yesterday's close
            #   (regularMarketPreviousClose). postMarketPrice is AFTER-HOURS noise and must NOT
            #   be used for the day's % change. Using it here caused the 2026-04-23 DIS bug where
            #   a thin after-hours print showed up as a +3.42% "day move" in the recap.
            if market_state in ("PRE", "PREPRE"):
                for symbol in tickers:
                    try:
                        info = yf.Ticker(symbol).info
                        price = info.get("preMarketPrice")
                        prev_close = info.get("regularMarketPrice")
                        if price and prev_close and prev_close != 0:
                            change_pct = ((price - prev_close) / prev_close) * 100
                            found_symbols.add(symbol)
                            performance.append({
                                "symbol": symbol, "price": price, "change_pct": change_pct,
                                "volume": 0, "day_high": None, "day_low": None,
                                "year_high": None, "year_low": None,
                                "at_52w_high": False, "at_52w_low": False,
                            })
                    except Exception:
                        continue
                if found_symbols:
                    print(f"  yfinance: got pre-market prices for {len(found_symbols)} tickers")
            elif market_state in ("POST", "POSTPOST", "CLOSED"):
                # Single batch yf.download covers both today/yesterday close AND the
                # 52-week window — replaces 84 sequential .info calls with one request.
                # Phase 1.5 enrichment below skips any ticker we already filled here.
                try:
                    df_post = yf.download(" ".join(tickers), period="1y",
                                          progress=False, threads=True)
                except Exception as e:
                    print(f"  Warning: yfinance batch error: {e}")
                    df_post = None

                if df_post is not None and not df_post.empty:
                    multi = len(tickers) > 1
                    for symbol in tickers:
                        try:
                            close = df_post["Close"][symbol] if multi else df_post["Close"]
                            close = close.dropna()
                            if len(close) < 2:
                                continue
                            price = float(close.iloc[-1])
                            prev_close = float(close.iloc[-2])
                            if not price or not prev_close:
                                continue
                            high = (df_post["High"][symbol] if multi else df_post["High"]).dropna()
                            low = (df_post["Low"][symbol] if multi else df_post["Low"]).dropna()
                            vol = (df_post["Volume"][symbol] if multi else df_post["Volume"]).dropna()
                            year_high = float(high.max()) if len(high) else None
                            year_low = float(low.min()) if len(low) else None
                            volume = int(vol.iloc[-1]) if len(vol) else 0
                            change_pct = ((price - prev_close) / prev_close) * 100
                            found_symbols.add(symbol)
                            performance.append({
                                "symbol": symbol, "price": price, "change_pct": change_pct,
                                "volume": volume,
                                "day_high": None, "day_low": None,
                                "year_high": year_high, "year_low": year_low,
                                "at_52w_high": bool(year_high and price >= year_high * 0.99),
                                "at_52w_low":  bool(year_low  and price <= year_low  * 1.01),
                            })
                        except Exception:
                            continue
                if found_symbols:
                    print(f"  yfinance batch: got post-close prices for {len(found_symbols)} tickers")
        except Exception as e:
            print(f"  Warning: yfinance portfolio error: {e}")

    # Phase 2: Yahoo spark fallback (batch, fast).
    # REGULAR hours: intraday bars with includePrePost=true (last bar is current price).
    # POST hours: range=5d&interval=1d gives two settlement closes; last bar is today, prior is
    #   yesterday — used to cover any holdings Phase 1 missed during POST.
    # PRE hours: do NOT run spark — chart range=1d returns yesterday's regular candles, which
    #   would give a flat 0% change. Phase 1 or Phase 3 (FMP) handle pre-market.
    spark_tickers = [t for t in tickers if t not in found_symbols]
    if spark_tickers and detected_market_state in ("REGULAR", "POST", "POSTPOST", "CLOSED"):
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
            is_post = detected_market_state != "REGULAR"
            spark_params = ("range=5d&interval=1d&includePrePost=false"
                            if is_post else "range=1d&interval=5m&includePrePost=true")
            for i in range(0, len(spark_tickers), 20):
                batch = spark_tickers[i:i+20]
                symbols = ",".join(batch)
                url = (f"https://query2.finance.yahoo.com/v8/finance/spark?symbols={symbols}"
                       f"&{spark_params}")
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    for symbol, info in data.items():
                        close_prices = [c for c in (info.get("close") or []) if c is not None]
                        # REGULAR-hours path: chartPreviousClose is yesterday's close — use it.
                        # POST-hours path (range=5d&interval=1d): chartPreviousClose is 5-6 days
                        #   ago; we need closes[-2] as yesterday's settlement close. Confirmed
                        #   empirically — using chartPreviousClose would give a multi-day % change.
                        if is_post:
                            prev_close = close_prices[-2] if len(close_prices) >= 2 else None
                        else:
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

    # Phase 2: Enrich with 52-week data via yfinance for tickers that came in
    # without it (PRE-market path or spark/FMP fallbacks). The POST batch above
    # already fills year_high/year_low, so those rows are skipped here.
    if YFINANCE_AVAILABLE and performance:
        unenriched = [p for p in performance if p.get("year_high") is None]
        if unenriched:
            try:
                import warnings
                warnings.filterwarnings("ignore", category=FutureWarning)
                syms = [p["symbol"] for p in unenriched]
                ticker_str = " ".join(syms)
                df = yf.download(ticker_str, period="1y", progress=False, threads=True)
                if not df.empty:
                    perf_map = {p["symbol"]: p for p in unenriched}
                    for sym in syms:
                        try:
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


# ============================================================================
# DUAL-SOURCE PRICE VERIFICATION (for Market Recap accuracy)
# ============================================================================
#
# The recap relies on accurate closing prices and daily % change. Primary source
# is yfinance (already fetched in portfolio_perf). Verification cross-checks
# each holding against Finnhub's /quote endpoint and flags material drift so
# we surface data-quality issues in the brief rather than silently reporting
# incorrect numbers.
#
# Thresholds (DRIFT_TOLERANCE_PCT / MATERIAL_DRIFT_PCT) are tuned for post-close
# regular-hours comparison — intra-day ticks between sources are expected, but
# after the close both sources should agree on the official settlement price
# within ~0.10%.

DRIFT_TOLERANCE_PCT = 0.10      # Anything within this is "consensus"
MATERIAL_DRIFT_PCT = 0.50       # Anything beyond this surfaces in the brief
CHANGE_PCT_DRIFT_TOLERANCE = 0.50  # Absolute difference in day %-change (percentage points);
                                    # >0.50pp between yfinance's change_pct and Finnhub's dp means
                                    # the two sources disagree on the size of the day's move and
                                    # we should prefer Finnhub (primary settlement feed).

def verify_portfolio_closes(portfolio_perf: list[dict], finnhub_key: str) -> dict:
    """
    Cross-check each holding's close price against Finnhub as a second source.

    Enriches each entry in `portfolio_perf` in-place with:
      - verified_source: "consensus" | "drift" | "yfinance_only"
      - drift_pct: float | None  (|yf - fh| / fh * 100, absolute value)
      - drift_direction: "yf_high" | "yf_low" | None
      - finnhub_close: float | None
      - finnhub_change_pct: float | None  (Finnhub's own % change for the day)

    Also returns a summary counts dict for footer reporting:
      {checked, consensus, drift, material_drift, missing, flagged_symbols}

    Behavior:
      - No-op if `finnhub_key` is empty (returns zeroed counts).
      - Rate-limited to ~55 calls/min (Finnhub free tier is 60/min) via 1.1s sleep.
      - Finnhub free tier does NOT cover many ETFs/foreign ADRs — those rows
        quietly fall back to "yfinance_only" without being counted as drift.
      - Prefers yfinance price for display (already in the perf dict), but the
        drift flag is what drives the "Data Quality" note in the HTML email.
    """
    counts = {
        "checked": 0,
        "consensus": 0,
        "drift": 0,
        "material_drift": 0,
        "missing": 0,
        "flagged_symbols": [],  # list of (symbol, drift_pct, yf_price, fh_price)
    }

    if not finnhub_key:
        for p in portfolio_perf:
            p.setdefault("verified_source", "yfinance_only")
            p.setdefault("drift_pct", None)
            p.setdefault("drift_direction", None)
            p.setdefault("finnhub_close", None)
            p.setdefault("finnhub_change_pct", None)
        return counts

    session = requests.Session()
    for p in portfolio_perf:
        symbol = p.get("symbol")
        yf_price = p.get("price")
        if not symbol or not isinstance(yf_price, (int, float)) or yf_price <= 0:
            p["verified_source"] = "yfinance_only"
            p["drift_pct"] = None
            p["drift_direction"] = None
            p["finnhub_close"] = None
            p["finnhub_change_pct"] = None
            counts["missing"] += 1
            continue

        counts["checked"] += 1
        fh_close = None
        fh_change_pct = None
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={finnhub_key}"
            resp = session.get(url, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                fh_close = data.get("c")
                fh_change_pct = data.get("dp")
                # Finnhub returns c=0 for symbols it doesn't cover
                if not fh_close or fh_close <= 0:
                    fh_close = None
                    fh_change_pct = None
        except Exception:
            pass

        if fh_close is None:
            p["verified_source"] = "yfinance_only"
            p["drift_pct"] = None
            p["drift_direction"] = None
            p["finnhub_close"] = None
            p["finnhub_change_pct"] = None
            counts["missing"] += 1
        else:
            drift = abs(fh_close - yf_price) / fh_close * 100
            direction = "yf_high" if yf_price > fh_close else ("yf_low" if yf_price < fh_close else None)
            p["finnhub_close"] = float(fh_close)
            p["finnhub_change_pct"] = float(fh_change_pct) if isinstance(fh_change_pct, (int, float)) else None
            p["drift_pct"] = float(drift)
            p["drift_direction"] = direction

            # % change drift — catches the 2026-04-23 DIS case where yf's change_pct was built
            # from an after-hours baseline while Finnhub's dp reflected the true day move.
            yf_change = p.get("change_pct")
            fh_dp = p["finnhub_change_pct"]
            change_pct_drift = (abs(yf_change - fh_dp)
                                if isinstance(yf_change, (int, float)) and isinstance(fh_dp, (int, float))
                                else None)
            p["change_pct_drift"] = change_pct_drift

            price_drift_material = drift >= MATERIAL_DRIFT_PCT
            pct_drift_material = (change_pct_drift is not None
                                   and change_pct_drift >= CHANGE_PCT_DRIFT_TOLERANCE)

            if price_drift_material or pct_drift_material:
                # Prefer Finnhub's settlement close + dp; yfinance is having a bad print.
                # We trust Finnhub here because /quote `c` is the official close and `dp` is
                # computed by Finnhub against its own `pc`, so both fields are internally
                # consistent. Keep the original yfinance values for audit/drift reporting.
                p["yfinance_price"] = float(yf_price)
                p["yfinance_change_pct"] = float(yf_change) if isinstance(yf_change, (int, float)) else None
                p["price"] = float(fh_close)
                if isinstance(fh_dp, (int, float)):
                    p["change_pct"] = float(fh_dp)
                p["verified_source"] = "finnhub_preferred"
                counts["drift"] += 1
                counts["material_drift"] += 1
                counts["flagged_symbols"].append(
                    (symbol, float(drift), float(yf_price), float(fh_close))
                )
            elif drift <= DRIFT_TOLERANCE_PCT:
                p["verified_source"] = "consensus"
                counts["consensus"] += 1
            else:
                p["verified_source"] = "drift"
                counts["drift"] += 1

        # Respect Finnhub free-tier rate limit (60/min)
        time.sleep(1.1)

    return counts


def verify_market_close_indices(market_close: dict, finnhub_key: str) -> dict:
    """
    Cross-check the major indices in `market_close` using ETF proxies on Finnhub.
    Finnhub free tier doesn't cover ^GSPC / ^IXIC / ^DJI directly, so we use
    SPY / QQQ / DIA as proxies — price levels differ, but daily % change should
    track the underlying index within ~0.05% on a normal session.

    Enriches market_close in-place:
      - {key}_verified_source  ("consensus" | "drift" | "yfinance_only")
      - {key}_drift_pct        (float | None)
      - {key}_finnhub_change   (float | None)

    Returns: {"checked": N, "drift": M, "flagged": [(key, drift_pct), ...]}
    """
    counts = {"checked": 0, "drift": 0, "flagged": []}
    if not finnhub_key:
        return counts

    proxies = [
        ("sp500", "SPY"),
        ("nasdaq", "QQQ"),
        ("dow", "DIA"),
    ]
    session = requests.Session()
    for key, proxy_symbol in proxies:
        yahoo_change = market_close.get(f"{key}_change")
        if yahoo_change is None:
            market_close[f"{key}_verified_source"] = "yfinance_only"
            market_close[f"{key}_drift_pct"] = None
            continue
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={proxy_symbol}&token={finnhub_key}"
            resp = session.get(url, timeout=8)
            if resp.status_code == 200:
                fh_change = resp.json().get("dp")
                if isinstance(fh_change, (int, float)):
                    counts["checked"] += 1
                    drift = abs(yahoo_change - fh_change)
                    market_close[f"{key}_drift_pct"] = float(drift)
                    market_close[f"{key}_finnhub_change"] = float(fh_change)
                    if drift <= DRIFT_TOLERANCE_PCT:
                        market_close[f"{key}_verified_source"] = "consensus"
                    else:
                        market_close[f"{key}_verified_source"] = "drift"
                        counts["drift"] += 1
                        counts["flagged"].append((key, float(drift)))
                else:
                    market_close[f"{key}_verified_source"] = "yfinance_only"
                    market_close[f"{key}_drift_pct"] = None
            else:
                market_close[f"{key}_verified_source"] = "yfinance_only"
                market_close[f"{key}_drift_pct"] = None
        except Exception:
            market_close[f"{key}_verified_source"] = "yfinance_only"
            market_close[f"{key}_drift_pct"] = None
        time.sleep(1.1)

    return counts


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
# STRATEGY READS (Stratechery + Asianometry RSS — recap only)
# ============================================================================
#
# Both feeds are paid Passport RSS — the URL itself contains a personal bearer
# token, so URLs come from .env and are never logged. Article links also embed
# a JWT (~30-day expiry) for paywall passthrough; same handling. We surface a
# clean excerpt + link in the recap email; we do not store article bodies.

def _load_strategy_seen(filepath: str) -> set:
    """Load the set of GUIDs already surfaced. Empty set if file missing/corrupt."""
    if not os.path.exists(filepath):
        return set()
    try:
        with open(filepath) as f:
            data = json.load(f)
        return set(data.get("seen_guids", []))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_strategy_seen(filepath: str, seen: set) -> None:
    """Persist the GUID set. Cap at 500 entries (FIFO via sorted) to keep file small."""
    seen_list = sorted(seen)
    if len(seen_list) > 500:
        seen_list = seen_list[-500:]
    try:
        with open(filepath, "w") as f:
            json.dump({"seen_guids": seen_list}, f, indent=2)
    except OSError as e:
        print(f"  ⚠ Could not save strategy_reads_seen: {e}")


def fetch_strategy_reads(stratechery_url: str, asianometry_url: str,
                         seen_file: str, lookback_hours: int = 48) -> list[dict]:
    """
    Fetch new posts from Stratechery + Asianometry RSS, deduped against seen_file.

    Returns list of dicts with: source, title, link, published_iso, excerpt.
    Posts older than lookback_hours OR already in seen_file are skipped.
    Newly surfaced GUIDs are added to seen_file before return.
    """
    sources = [
        ("Stratechery", stratechery_url),
        ("Asianometry", asianometry_url),
    ]
    seen = _load_strategy_seen(seen_file)
    cutoff = datetime.now().astimezone() - timedelta(hours=lookback_hours)
    posts = []
    new_guids = set()

    for source_name, url in sources:
        if not url:
            continue
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"  ⚠ {source_name} feed parse failed: {type(e).__name__}")
            continue
        if parsed.bozo and not parsed.entries:
            print(f"  ⚠ {source_name} feed returned no entries (bozo={parsed.bozo_exception.__class__.__name__ if parsed.bozo_exception else '?'})")
            continue

        for entry in parsed.entries:
            guid = entry.get("id") or entry.get("guid") or entry.get("link", "")
            if not guid or guid in seen:
                continue

            # Parse pub date
            published_dt = None
            if entry.get("published_parsed"):
                try:
                    published_dt = datetime(*entry.published_parsed[:6]).astimezone()
                except (TypeError, ValueError):
                    pass
            elif entry.get("published"):
                try:
                    published_dt = parsedate_to_datetime(entry.published)
                except (TypeError, ValueError):
                    pass
            if published_dt is None or published_dt < cutoff:
                continue

            # Excerpt: prefer the clean <description> over <content:encoded> HTML
            excerpt_raw = entry.get("summary", "") or entry.get("description", "")
            excerpt = re.sub(r"<[^>]+>", "", excerpt_raw).strip()
            excerpt = re.sub(r"\s+", " ", excerpt)
            if len(excerpt) > 320:
                excerpt = excerpt[:317].rsplit(" ", 1)[0] + "…"

            posts.append({
                "source": source_name,
                "title": entry.get("title", "(untitled)").strip(),
                "link": entry.get("link", ""),
                "published_iso": published_dt.isoformat(),
                "excerpt": excerpt,
            })
            new_guids.add(guid)

    # Persist before return so a failed render doesn't re-surface posts tomorrow
    if new_guids:
        _save_strategy_seen(seen_file, seen | new_guids)

    # Newest first
    posts.sort(key=lambda p: p["published_iso"], reverse=True)
    return posts


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


def _json_safe(value):
    """Coerce any numpy/pandas scalar to a JSON-native Python type.

    Belt-and-suspenders against numpy.bool_ / numpy.float64 / numpy.int64
    leaking in from yfinance or pandas-backed fetchers. Returns value
    unchanged if already native. Handles NaN by returning None.
    """
    if value is None:
        return None
    # Native bool must be checked before int (bool is a subclass of int in Python)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        # NaN check for floats (math.isnan only accepts real numbers)
        if isinstance(value, float) and value != value:
            return None
        return value
    # numpy / pandas scalar — cast via .item() if available, else best-effort
    if hasattr(value, "item"):
        try:
            v = value.item()
            if isinstance(v, float) and v != v:
                return None
            return v
        except (ValueError, TypeError):
            pass
    # Last-resort fallback — stringify rather than crash serialization
    try:
        return float(value)
    except (ValueError, TypeError):
        return str(value)


def save_earnings_history(filepath: str, scorecard: list, history: dict) -> None:
    """Merge fresh scorecard into history and persist to JSON."""
    entries = history.get("entries", {})

    # Fresh data wins for any symbol present in both
    for item in scorecard:
        sym = item["symbol"]
        entry = {
            "symbol": sym,
            "date": item.get("date", ""),
            "eps_actual": _json_safe(item.get("eps_actual")),
            "eps_estimate": _json_safe(item.get("eps_estimate")),
            "surprise_pct": _json_safe(item.get("surprise_pct")),
            "beat": _json_safe(item.get("beat")),
            "rev_actual": _json_safe(item.get("rev_actual")),
            "rev_estimate": _json_safe(item.get("rev_estimate")),
            "rev_beat": _json_safe(item.get("rev_beat")),
            "rev_surprise_pct": _json_safe(item.get("rev_surprise_pct")),
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
    """Merge fresh scorecard with historical entries.

    Fresh API data wins UNLESS the history entry was manually corrected
    (source='manual_correction'), in which case the correction is preserved.
    """
    # Build lookup of fresh results
    fresh = {item["symbol"]: item for item in scorecard}

    # Merge with historical entries
    for sym, entry in history.get("entries", {}).items():
        if sym not in fresh:
            # Historical entry not in fresh — add it
            fresh[sym] = entry
        elif entry.get("source") == "manual_correction":
            # Manual correction in history takes priority over stale API data
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
                rpt_date = item.get("date", "")
                date_tag = f"  ({rpt_date})" if rpt_date else ""
                lines.append(f"  🟢 {symbol:<6} EPS ${actual:.2f} vs ${estimate:.2f} (+{surprise_pct:.1f}%){date_tag}")
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
                rpt_date = item.get("date", "")
                date_tag = f"  ({rpt_date})" if rpt_date else ""
                lines.append(f"  🔴 {symbol:<6} EPS ${actual:.2f} vs ${estimate:.2f} ({surprise_pct:.1f}%){date_tag}")
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
    # Only show material actions (rating changes or PT moves >10% or new coverage)
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
            for symbol, a in material[:15]:  # Cap at 15 to keep the section scannable
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
                        rsi_alerts: list[dict] = None,
                        ah_earnings: list[dict] = None) -> str:
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
        
        gainers = [p for p in sorted_perf if p["change_pct"] > 0][:10]
        losers = [p for p in sorted_perf if p["change_pct"] < 0][-10:]
        losers.reverse()  # Most negative first

        # Top Gainers
        if gainers:
            lines.append("▸ TOP 10 GAINERS")
            lines.append("")
            for p in gainers:
                symbol = p["symbol"]
                price = p["price"]
                change = p["change_pct"]
                lines.append(f"  ▲ {symbol:<6} ${price:>8.2f}  +{change:.1f}%")
            lines.append("")

        # Top Losers
        if losers:
            lines.append("▸ TOP 10 LOSERS")
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

    # After-Hours Earnings (today's AMC reporters — reported and pending)
    if ah_earnings:
        reported = [e for e in ah_earnings if e.get("reported")]
        pending = [e for e in ah_earnings if not e.get("reported")]

        lines.append("▸ AFTER-HOURS EARNINGS")
        lines.append("")

        if reported:
            for e in reported:
                symbol = e["symbol"]
                status = "BEAT" if e.get("beat") else "MISS"
                marker = "✓" if e.get("beat") else "✗"
                eps_a = e.get("eps_actual")
                eps_e = e.get("eps_estimate")
                surp = e.get("surprise_pct")

                eps_str = ""
                if isinstance(eps_a, (int, float)) and isinstance(eps_e, (int, float)):
                    eps_str = f"EPS ${eps_a:.2f} / est ${eps_e:.2f}"
                surp_str = f"  ({'+' if surp and surp >= 0 else ''}{surp:.1f}%)" if isinstance(surp, (int, float)) else ""
                lines.append(f"  {marker} {symbol:<6} {status:<4}  {eps_str}{surp_str}")
            lines.append("")

        if pending:
            lines.append("  Pending (not yet reported):")
            for e in pending:
                symbol = e["symbol"]
                eps_e = e.get("eps_estimate")
                est_str = f"est EPS ${eps_e:.2f}" if isinstance(eps_e, (int, float)) else "est EPS n/a"
                lines.append(f"  ⋯ {symbol:<6}  {est_str}")
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

    # Send via Email
    print(f"Sending email to {CONFIG['EMAIL_RECIPIENT']}...")
    today = datetime.now().strftime("%B %d, %Y")
    email_subject = f"LunarCrush Brief - {today}"
    email_success = send_email(CONFIG["EMAIL_RECIPIENT"], email_subject, brief)

    if email_success:
        print("\n✓ LunarCrush brief delivered via Email!")
    else:
        print("\n✗ Delivery failed - check Mail configuration")


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

    # Always supply current prices for anchor names (PLTR etc.) so the AI brief
    # has a real price reference even when they are not movers — prevents the
    # model fabricating stale levels (the 2026-06-15 "PLTR $70" hallucination).
    anchor_prices = fetch_anchor_prices(all_tickers)

    print("\n[7b/10] Fetching analyst actions (yfinance)...")
    analyst_actions = fetch_analyst_actions(None, ticker_set)
    total_actions = sum(len(v) for v in analyst_actions.values())
    print(f"  Found {total_actions} analyst actions across {len(analyst_actions)} tickers")

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
# === v2.6 days_since enrichment ===
    from datetime import datetime as _dt_v26, date as _date_v26
    _today_v26 = _dt_v26.now().date()
    def _enrich(rec):
        d = rec.get('date') or rec.get('report_date')
        if isinstance(d, str):
            try:
                d = _dt_v26.strptime(d[:10], '%Y-%m-%d').date()
            except Exception:
                d = None
        if isinstance(d, _date_v26):
            rec['days_since'] = (_today_v26 - d).days
        return rec
    try:
        scorecard = [_enrich(dict(r)) for r in (scorecard or [])]
    except Exception:
        pass
    try:
        earnings = [_enrich(dict(r)) for r in (earnings or [])]
    except Exception:
        pass
    # === end v2.6 days_since enrichment ===

    briefing_data = {
        "market_snapshot": market_snapshot,
        "premarket_movers": premarket_movers,
        "anchor_prices": anchor_prices,
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

    # Narrow scope: only AI generation failures should trigger the legacy
    # fallback. Downstream formatting errors must not discard a working AI brief.
    try:
        ai_brief = generate_ai_morning_brief(briefing_data, CONFIG["ANTHROPIC_API_KEY"])
        print("  ✓ AI brief generated")
    except Exception as e:
        print(f"  ✗ AI brief failed: {e}")
        print("  Falling back to legacy formatter...")
        text_message = format_briefing(filtered_news, earnings, scorecard, [], miss_explanations,
                                       len(all_tickers), market_snapshot, premarket_movers, rsi_alerts, vk_highlights,
                                       analyst_actions=analyst_actions)
        html_email = None
    else:
        # Format HTML email (no plain-text twin — iMessage path removed in v2.6)
        html_email = format_morning_html(ai_brief, briefing_data)
        text_message = None
        print(f"  ✓ HTML email: {len(html_email):,} bytes")

    # Print to console (HTML is too large to dump; show plain-text fallback if used)
    print("\n" + "=" * 50)
    if text_message:
        print(text_message)
    else:
        print(f"HTML brief built ({len(html_email):,} bytes) — see Mail for rendered output.")
    print("=" * 50)

    # Send via Email (HTML if available, plain text fallback)
    print(f"Sending email to {CONFIG['EMAIL_RECIPIENT']}...")
    today = datetime.now().strftime("%B %d, %Y")
    if html_email:
        email_subject = f"Morning Brief \u2013 {today}"
        email_success = send_html_email(CONFIG["EMAIL_RECIPIENT"], email_subject, html_email)
    else:
        email_subject = f"Morning Briefing - {today}"
        email_success = send_email(CONFIG["EMAIL_RECIPIENT"], email_subject, text_message)

    if email_success:
        print("\n✓ Morning briefing delivered via Email!")
    else:
        print("\n✗ Delivery failed - check Mail configuration")


def run_market_recap():
    """Run the afternoon market recap workflow (v2 — AI editorial + verified prices)."""
    print("\n" + "=" * 50)
    print("Market Recap v2 (editorial + dual-source price verification)")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 50)

    # Combine all tickers
    all_tickers = CONFIG["INDIVIDUAL_STOCKS"] + CONFIG["ETFS"]
    ticker_set = set(all_tickers)

    print(f"\nAnalyzing {len(all_tickers)} holdings...")

    # Fetch data
    print("\n[1/8] Fetching market close data (Yahoo)...")
    market_close = fetch_market_close(CONFIG["FINNHUB_API_KEY"])
    sp = market_close.get("sp500")
    sp_chg = market_close.get("sp500_change")
    print(f"  S&P 500: {sp:,.2f} ({'+' if sp_chg >= 0 else ''}{sp_chg:.2f}%)" if sp else "  S&P 500: N/A")

    print("\n[2/8] Fetching portfolio performance (incl. 52-week data)...")
    portfolio_perf = fetch_portfolio_performance(CONFIG["FMP_API_KEY"], all_tickers)
    highs_52w = [p for p in portfolio_perf if p.get("at_52w_high")]
    lows_52w = [p for p in portfolio_perf if p.get("at_52w_low")]
    print(f"  Got quotes for {len(portfolio_perf)} holdings")
    print(f"  52-week highs: {len(highs_52w)} · 52-week lows: {len(lows_52w)}")

    # --- NEW: dual-source price verification (Finnhub as second source) ---
    print(f"\n[3/8] Cross-checking prices with Finnhub (~{len(portfolio_perf)}s rate-limited)...")
    dq_counts = verify_portfolio_closes(portfolio_perf, CONFIG["FINNHUB_API_KEY"])
    idx_dq = verify_market_close_indices(market_close, CONFIG["FINNHUB_API_KEY"])
    print(f"  Holdings: {dq_counts['checked']} checked · "
          f"{dq_counts['consensus']} consensus · "
          f"{dq_counts['drift']} drift>{DRIFT_TOLERANCE_PCT:.2f}% · "
          f"{dq_counts['material_drift']} material>{MATERIAL_DRIFT_PCT:.2f}% · "
          f"{dq_counts['missing']} Finnhub-unavailable")
    if dq_counts.get("flagged_symbols"):
        print("  Materially drifted holdings:")
        for sym, d, yf_p, fh_p in dq_counts["flagged_symbols"][:8]:
            print(f"    {sym:<6}  yfinance ${yf_p:.2f}  vs  Finnhub ${fh_p:.2f}  ({d:.2f}% drift)")
    print(f"  Indices:  {idx_dq['checked']} checked · {idx_dq['drift']} drift")

    print("\n[4/8] Fetching RSI alerts (Alpha Vantage)...")
    rsi_alerts = fetch_rsi_alerts(CONFIG["ALPHA_VANTAGE_API_KEY"], CONFIG["INDIVIDUAL_STOCKS"])
    print(f"  Found {len(rsi_alerts)} stocks with RSI alerts")

    print("\n[5/8] Fetching afternoon news...")
    news = fetch_yahoo_news(all_tickers)
    filtered_news = filter_news_with_ai(news, CONFIG["ANTHROPIC_API_KEY"]) if news else []
    print(f"  {len(filtered_news)} material news items")

    print("\n[6/8] Fetching today's after-hours earnings (Finnhub)...")
    ah_earnings = fetch_todays_after_hours_earnings(CONFIG["FINNHUB_API_KEY"], ticker_set)
    reported_count = len([e for e in ah_earnings if e.get("reported")])
    pending_count = len(ah_earnings) - reported_count
    print(f"  {len(ah_earnings)} AMC reporters (holdings): {reported_count} reported · {pending_count} pending")

    # Strategy reads (Stratechery + Asianometry, 48h lookback, GUID-deduped)
    print("\n[6.5/8] Fetching strategy reads (Stratechery + Asianometry RSS)...")
    strategy_reads = fetch_strategy_reads(
        CONFIG["STRATECHERY_RSS_URL"],
        CONFIG["ASIANOMETRY_RSS_URL"],
        CONFIG["STRATEGY_READS_SEEN_FILE"],
        lookback_hours=CONFIG["STRATEGY_READS_LOOKBACK_HOURS"],
    )
    if strategy_reads:
        by_source = {}
        for p in strategy_reads:
            by_source.setdefault(p["source"], 0)
            by_source[p["source"]] += 1
        print("  " + " · ".join(f"{src}: {n}" for src, n in by_source.items()))
    else:
        print("  No new posts in lookback window")

    # Bundle data for AI + formatters
    recap_data = {
        "market_close": market_close,
        "portfolio_perf": portfolio_perf,
        "filtered_news": filtered_news,
        "ah_earnings": ah_earnings,
        "rsi_alerts": rsi_alerts,
        "data_quality": dq_counts,
        "holdings_count": len(all_tickers),
        "strategy_reads": strategy_reads,
    }

    # --- NEW: AI editorial brief ---
    print("\n[7/8] Generating AI editorial recap brief...")
    ai_brief = None
    try:
        ai_brief = generate_ai_recap_brief(recap_data, CONFIG["ANTHROPIC_API_KEY"])
        print("  ✓ AI brief generated")
    except Exception as e:
        print(f"  ✗ AI brief failed: {e}")
        print("  Continuing with data-only rendering (legacy text fallback)")

    print("\n[8/8] Formatting recap (text + HTML)...")
    if ai_brief:
        try:
            recap_text = format_recap_text(ai_brief, recap_data)
            print(f"  ✓ Plain text (v2): {len(recap_text):,} chars")
        except Exception as e:
            print(f"  ✗ v2 text failed: {e} — falling back to legacy text")
            recap_text = format_market_recap(
                market_close, portfolio_perf, filtered_news, len(all_tickers),
                rsi_alerts, ah_earnings=ah_earnings,
            )
    else:
        recap_text = format_market_recap(
            market_close, portfolio_perf, filtered_news, len(all_tickers),
            rsi_alerts, ah_earnings=ah_earnings,
        )

    try:
        recap_html = format_market_recap_html(recap_data, ai_brief=ai_brief)
        print(f"  ✓ HTML recap: {len(recap_html):,} bytes")
    except Exception as e:
        print(f"  ✗ HTML recap failed: {e}")
        recap_html = None

    # Print recap to console
    print("\n" + "=" * 50)
    print(recap_text)
    print("=" * 50)

    # Send via Email (HTML if available, plain text fallback)
    print(f"Sending email to {CONFIG['EMAIL_RECIPIENT']}...")
    today = datetime.now().strftime("%B %d, %Y")
    email_subject = f"Market Recap \u2013 {today}"
    if recap_html:
        email_success = send_html_email(CONFIG["EMAIL_RECIPIENT"], email_subject, recap_html)
    else:
        email_success = send_email(CONFIG["EMAIL_RECIPIENT"], email_subject, recap_text)

    if email_success:
        print("\n✓ Market recap delivered via Email!")
    else:
        print("\n✗ Delivery failed - check Mail configuration")


def run_premarket_update():
    """Run the 6:20 AM pre-market update — AI editorial pipeline matching morning brief."""
    print("\n" + "=" * 50)
    print("Pre-Market Update (v2)")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 50)

    all_tickers = CONFIG["INDIVIDUAL_STOCKS"] + CONFIG["ETFS"]
    ticker_set = set(all_tickers)

    print(f"\nChecking {len(all_tickers)} holdings...")

    print("\n[1/5] Fetching market snapshot...")
    market_snapshot = fetch_market_snapshot(CONFIG["FINNHUB_API_KEY"])
    sp = market_snapshot.get("sp500_futures")
    nq = market_snapshot.get("nasdaq_futures")
    print(f"  S&P Futures: {sp:,.0f}" if sp else "  S&P Futures: N/A")
    print(f"  NASDAQ Futures: {nq:,.0f}" if nq else "  NASDAQ Futures: N/A")

    print("\n[2/5] Fetching pre-market movers...")
    premarket_movers = fetch_premarket_movers(CONFIG["FMP_API_KEY"], all_tickers, threshold=2.0)
    print(f"  Found {len(premarket_movers)} holdings moving >2%")

    # Always supply current prices for anchor names (PLTR etc.) so the AI brief
    # has a real price reference even when they are not movers — prevents the
    # model fabricating stale levels (the 2026-06-15 "PLTR $70" hallucination).
    anchor_prices = fetch_anchor_prices(all_tickers)

    print("\n[3/5] Fetching today's earnings...")
    finnhub_upcoming = fetch_finnhub_earnings(CONFIG["FINNHUB_API_KEY"], ticker_set)
    print(f"  Found {len(finnhub_upcoming)} earnings events")

    # Grade BMO prints that already dropped (e.g. UNP ~7:45 AM ET, well before 6:20 AM PT brief)
    today_str = datetime.now().strftime("%Y-%m-%d")
    bmo_today = {e["symbol"] for e in finnhub_upcoming
                 if e.get("date") == today_str and e.get("hour") == "bmo"}
    just_reported: list[dict] = []
    if bmo_today:
        print(f"\n[3b/5] Checking BMO actuals for {len(bmo_today)} reporters...")
        fh_actuals = fetch_earnings_scorecard(CONFIG["FINNHUB_API_KEY"], bmo_today)
        fh_found = {r["symbol"] for r in fh_actuals if r.get("date") == today_str}
        yf_actuals = fetch_yfinance_earnings(bmo_today, fh_found) if (bmo_today - fh_found) else []
        yf_today = [r for r in yf_actuals if r.get("date") == today_str]
        all_found = fh_found | {r["symbol"] for r in yf_today}
        still_missing = bmo_today - all_found
        av_actuals = (fetch_alpha_vantage_earnings(CONFIG["ALPHA_VANTAGE_API_KEY"], still_missing)
                      if still_missing else [])
        av_today = [r for r in av_actuals if r.get("date") == today_str]
        merged = merge_earnings_data(fh_actuals, [], None, yf_today, None, av_today)
        just_reported = [r for r in merged if r.get("date") == today_str]
        print(f"  Graded {len(just_reported)}/{len(bmo_today)} BMO prints")

    # Drop graded tickers from the upcoming list — they're printed, not pending
    graded_symbols = {r["symbol"] for r in just_reported}
    if graded_symbols:
        finnhub_upcoming = [e for e in finnhub_upcoming if e["symbol"] not in graded_symbols]

    # Load earnings history for scorecard context
    print("\n[4/5] Loading earnings history...")
    earnings_history = load_earnings_history(CONFIG["EARNINGS_HISTORY_FILE"])

    # Persist today's BMO prints so the 2 PM recap + tomorrow's 5 AM brief see them
    if just_reported:
        just_reported = merge_with_history(just_reported, earnings_history)
        # merge_with_history adds all historical entries; keep only today's prints for the briefing data
        just_reported = [r for r in just_reported if r.get("date") == today_str
                         and r.get("symbol") in graded_symbols]
        save_earnings_history(CONFIG["EARNINGS_HISTORY_FILE"], just_reported, earnings_history)
        earnings_history = load_earnings_history(CONFIG["EARNINGS_HISTORY_FILE"])

    scorecard = list(earnings_history.get("entries", {}).values())
    scorecard.sort(key=lambda x: x.get("date", ""), reverse=True)
    print(f"  {len(scorecard)} recent earnings in history")

    # Bundle data for AI
    briefing_data = {
        "market_snapshot": market_snapshot,
        "premarket_movers": premarket_movers,
        "anchor_prices": anchor_prices,
        "earnings": finnhub_upcoming,
        "scorecard": scorecard,
        "just_reported": just_reported,
        "holdings_count": len(all_tickers),
    }

    # Generate AI editorial brief.
    # v2.7.4 (2026-05-23): the previous version wrapped AI gen + HTML format + text
    # format in a single try/except.  A NameError or other failure in the text-format
    # step (e.g. a missing import) would erroneously print "AI brief failed",
    # clobber the already-built html_email to None, and discard the AI work — the
    # premarket would silently degrade to the legacy text formatter.  Narrow scope:
    # only AI generation failures should trigger the legacy fallback.  Downstream
    # formatting errors must not throw away a working AI brief.
    print("\n[5/5] Generating AI pre-market brief...")
    ai_brief = None
    html_email = None
    text_message = None
    try:
        ai_brief = generate_ai_premarket_brief(briefing_data, CONFIG["ANTHROPIC_API_KEY"])
        print("  ✓ AI brief generated")
    except Exception as e:
        print(f"  ✗ AI brief failed: {e}")
        print("  Falling back to legacy formatter...")
        text_message = format_premarket_update(
            market_snapshot, premarket_movers, finnhub_upcoming,
            [],  # vk_highlights — legacy fallback does not use VK
            len(all_tickers)
        )

    if ai_brief is not None:
        # Format HTML; on failure, surface clearly and keep ai_brief for the text path.
        try:
            html_email = format_premarket_html(ai_brief, briefing_data)
            print(f"  ✓ HTML email: {len(html_email):,} bytes")
        except Exception as e:
            print(f"  ✗ HTML formatting failed (keeping AI brief for text path): {e}")
            html_email = None

        # Format plain text; on failure, log and continue — we still have HTML.
        try:
            text_message = format_premarket_text(ai_brief, briefing_data)
            print(f"  ✓ Plain text: {len(text_message):,} chars")
        except Exception as e:
            print(f"  ✗ Plain-text formatting failed (HTML email will still send): {e}")
            text_message = None

    # Console output (HTML is too large to dump; show text if we have it)
    print("\n" + "=" * 50)
    if text_message:
        print(text_message)
    elif html_email:
        print(f"HTML brief built ({len(html_email):,} bytes) — see Mail for rendered output.")
    print("=" * 50)

    # Send HTML email (preferred); fall back to text, fail loudly if we have neither.
    print(f"Sending email to {CONFIG['EMAIL_RECIPIENT']}...")
    today = datetime.now().strftime("%B %d, %Y")
    email_subject = f"Pre-Market Update – {today}"
    if html_email:
        email_success = send_html_email(CONFIG["EMAIL_RECIPIENT"], email_subject, html_email)
    elif text_message:
        email_success = send_email(CONFIG["EMAIL_RECIPIENT"], email_subject, text_message)
    else:
        print("✗ No email body available (AI + HTML + text all failed). Skipping send.")
        email_success = False

    if email_success:
        print("\n✓ Pre-market update delivered via Email!")
    else:
        print("\n✗ Delivery failed - check Mail configuration")


def run_weekend_preview():
    """Sunday-evening preview — Sunday futures + weekend headlines + strategy reads + AI synthesis for Monday."""
    print("\n" + "=" * 50)
    print("Weekend Preview (Sunday-night setup for Monday)")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 50)

    all_tickers = CONFIG["INDIVIDUAL_STOCKS"] + CONFIG["ETFS"]
    print(f"\nAnalyzing {len(all_tickers)} holdings...")

    print("\n[1/4] Fetching Sunday futures snapshot...")
    market_snapshot = fetch_market_snapshot(CONFIG["FINNHUB_API_KEY"])
    sp = market_snapshot.get("sp500_futures")
    nq = market_snapshot.get("nasdaq_futures")
    print(f"  S&P Futures: {sp:,.0f}" if sp else "  S&P Futures: N/A")
    print(f"  NASDAQ Futures: {nq:,.0f}" if nq else "  NASDAQ Futures: N/A")

    print("\n[2/4] Fetching weekend portfolio news...")
    news = fetch_yahoo_news(all_tickers)
    filtered_news = filter_news_with_ai(news, CONFIG["ANTHROPIC_API_KEY"]) if news else []
    print(f"  {len(filtered_news)} material news items (from {len(news)} raw)")

    print("\n[3/4] Fetching strategy reads (Stratechery + Asianometry)...")
    strategy_reads = fetch_strategy_reads(
        CONFIG["STRATECHERY_RSS_URL"],
        CONFIG["ASIANOMETRY_RSS_URL"],
        CONFIG["STRATEGY_READS_SEEN_FILE"],
        lookback_hours=CONFIG["STRATEGY_READS_LOOKBACK_HOURS"],
    )
    if strategy_reads:
        by_source = {}
        for p in strategy_reads:
            by_source.setdefault(p["source"], 0)
            by_source[p["source"]] += 1
        print("  " + " · ".join(f"{src}: {n}" for src, n in by_source.items()))
    else:
        print("  No new posts in lookback window")

    weekend_data = {
        "market_snapshot": market_snapshot,
        "filtered_news": filtered_news,
        "strategy_reads": strategy_reads,
        "holdings_count": len(all_tickers),
    }

    print("\n[4/4] Generating AI weekend brief...")
    try:
        ai_brief = generate_ai_weekend_brief(weekend_data, CONFIG["ANTHROPIC_API_KEY"])
        print("  ✓ AI brief generated")
        html_email = format_weekend_html(ai_brief, weekend_data)
        text_message = format_weekend_text(ai_brief, weekend_data)
        print(f"  ✓ HTML: {len(html_email):,} bytes · Text: {len(text_message):,} chars")
    except Exception as e:
        print(f"  ✗ AI brief failed: {e}")
        return

    print("\n" + "=" * 50)
    print(text_message)
    print("=" * 50)

    print(f"Sending email to {CONFIG['EMAIL_RECIPIENT']}...")
    today = datetime.now().strftime("%B %d, %Y")
    email_subject = f"Weekend Preview – {today}"
    email_success = send_html_email(CONFIG["EMAIL_RECIPIENT"], email_subject, html_email)

    if email_success:
        print("\n✓ Weekend preview delivered via Email!")
    else:
        print("\n✗ Delivery failed - check Mail configuration")


def main():
    """Main entry point - dispatch based on command line argument."""
    # Support both "python3 script.py premarket" and "python3 script.py --mode premarket"
    if len(sys.argv) > 2 and sys.argv[1] == "--mode":
        mode = sys.argv[2]
    elif len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        mode = sys.argv[1]
    elif len(sys.argv) > 1:
        mode = sys.argv[1]  # handles --setup-gmail etc.
    else:
        mode = "morning"

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
        elif mode == "weekend_preview":
            run_weekend_preview()
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
