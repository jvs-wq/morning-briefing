# Morning Briefing

Automated daily stock market intelligence brief for a concentrated investment portfolio. Monitors 89 holdings and delivers an AI-generated editorial analysis via HTML email and plain text iMessage on weekday mornings.

## v3 — Earnings Season Enrichment (2026-04-14)

Major earnings data upgrade for Q1 2026 earnings season:

- **4-week persistent lookback** — `earnings_history.json` accumulates results across runs, auto-prunes entries older than 28 days. Manual corrections (via `source: manual_correction`) survive API overwrites.
- **Revenue estimates vs actuals** — shown in scorecard and upcoming earnings calendar (from Finnhub)
- **AI guidance analysis** — Claude infers raised/lowered/in-line from news headlines after each report
- **Sell-side analyst actions** — upgrades, downgrades, and price target changes via yfinance (7-day window). iMessage shows material changes only (rating changes, PT >10%, new coverage); full list in HTML email.
- **BCM holdings update** — 74 stocks + 15 ETFs = 89 total
- **dotenv fix** — `_load_dotenv()` uses direct assignment instead of `setdefault` to avoid empty shell env var masking

## v2 — AI Editorial Intelligence (2026-04-06)

Redesigned from plain-text data dump to AI-powered editorial brief. Claude Sonnet analyzes all collected market data and generates a thesis-driven intelligence brief.

## Features

- **AI intelligence brief** — Claude Sonnet generates thesis-driven analysis connecting market events to portfolio positions
- **Market snapshot** — S&P/NASDAQ futures, 10Y Treasury yield
- **Pre-market movers** — actual extended-hours prices via yfinance (not stale closes)
- **Earnings scorecard** — beat/miss with EPS + revenue actual vs estimate, AI guidance signals, miss explanations
- **Earnings calendar** — upcoming reports with EPS and revenue estimates
- **Analyst actions** — sell-side upgrades/downgrades/PT changes (7-day window)
- **AI-filtered news** — relevant headlines selected and interpreted by Claude API
- **Social intelligence** — LunarCrush social buzz and creator signals with color-coded interpretive signals
- **Strategy reads (recap only)** — long-form analyst posts (Stratechery, Asianometry) from the last 48h surfaced in a "Strategy & Analysis" section of the recap email, with GUID-deduped state so each post appears once
- **HTML email** — professional typography with data appendix tables
- **Plain text iMessage** — formatted for mobile, auto-chunks at ~1600 chars

## Architecture

```
morning_briefing.py          — Main script: data collection, all modes (3,464 lines)
morning_briefing_redesign.py — v2 module: AI brief, HTML email, text format (1,048 lines)
briefing_monitor.py          — Health monitoring and alerting
earnings_history.json        — Persistent 4-week earnings lookback (gitignored, runtime)
.env                         — API keys (gitignored)
```

## Modes

| Mode | Schedule | Content |
|------|----------|---------|
| `morning` | 5:00 AM PT | Full AI editorial brief (news, earnings, movers, analyst actions, social) |
| `premarket` | 6:20 AM PT | Movers + earnings only |
| `recap` | 1:15 PM PT | Midday performance recap |

## Setup

1. Clone the repo
2. Install dependencies:
   ```bash
   pip3 install requests feedparser anthropic yfinance
   ```
3. Create a `.env` file with API keys:
   ```
   FINNHUB_API_KEY=your_key
   ANTHROPIC_API_KEY=your_key
   LUNARCRUSH_API_KEY=your_key
   FMP_API_KEY=your_key
   ALPHA_VANTAGE_API_KEY=your_key
   IMESSAGE_RECIPIENT=+1234567890
   EMAIL_RECIPIENT=you@example.com
   # Optional — recap "Strategy & Analysis" section. Paid Passport RSS URLs;
   # leave blank to disable that section entirely.
   STRATECHERY_RSS_URL=
   ASIANOMETRY_RSS_URL=
   ```
4. Edit the holdings lists in `morning_briefing.py` CONFIG section
5. Run manually:
   ```bash
   python3 morning_briefing.py --mode morning
   ```

## Scheduling (macOS)

Uses LaunchAgent plists in `~/Library/LaunchAgents/` for automated scheduling.

## Data Sources

| Source | Auth | Used For |
|--------|------|----------|
| Anthropic Claude | API key | AI brief, news filter, earnings miss/guidance analysis |
| yfinance | None | Pre/post market prices, earnings fallback, analyst actions |
| Yahoo Finance spark/chart | None | Batch prices, futures, treasury yield |
| Yahoo Finance RSS | None | News headlines |
| Finnhub | API key | Earnings calendar + scorecard (with revenue), market snapshot |
| Alpha Vantage | API key | RSI alerts, last-resort earnings |
| FMP | API key | Pre-market movers fallback, portfolio performance |
| LunarCrush | API key | Social buzz, creator signals |
| Stratechery (Passport RSS) | Personal feed URL | Long-form tech-strategy posts in recap "Strategy & Analysis" section |
| Asianometry (Passport RSS) | Personal feed URL | Long-form semiconductor / East Asia analysis in recap "Strategy & Analysis" section |

## Data Quality Notes

- Finnhub earnings data can be stale on report day — the script supports manual corrections in `earnings_history.json` that persist across runs
- Yahoo free endpoints do NOT return pre-market prices — only yfinance (authenticated) provides them
- FMP `/stable/analyst-estimates` and `/stable/upgrades-downgrades` require paid tier (402/404)
- ETF tickers generate expected "no earnings dates found" warnings
