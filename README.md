# Morning Briefing

Automated daily stock market intelligence brief for a personal portfolio. Monitors ~85 holdings and delivers an AI-generated editorial analysis via HTML email and plain text iMessage on weekday mornings.

## v2 — AI Editorial Intelligence (2026-04-06)

The briefing was redesigned from a plain-text data dump to an AI-powered editorial brief. Claude Sonnet analyzes all collected market data and generates a thesis-driven intelligence brief with a "MoMA Penguin Books" visual aesthetic.

**What changed:**
- AI-generated editorial analysis replaces mechanical data formatting
- HTML email delivery with professional typography (Georgia/Arial, table-based layout)
- Structured intelligence sections: What Matters, Market Context, Pre-Market Analysis, Earnings Intelligence, News Signal, Watchlist
- Plain text iMessage with box-drawing characters for mobile readability
- Automatic fallback to legacy formatting if AI generation fails

## Features

- **AI intelligence brief** — Claude Sonnet generates thesis-driven analysis connecting market events to portfolio positions
- **Market snapshot** — S&P/NASDAQ futures, 10Y Treasury yield
- **Pre-market movers** — actual extended-hours prices via yfinance (not stale closes)
- **Earnings scorecard** — beat/miss tracking with EPS surprise data and AI-generated miss analysis
- **AI-filtered news** — relevant headlines selected and interpreted by Claude API
- **Social intelligence** — LunarCrush social buzz and creator signals with color-coded interpretive signals (divergences, capitulation, extreme sentiment, signal quality)
- **HTML email** — MoMA Penguin Books aesthetic with data appendix
- **Plain text iMessage** — formatted for mobile with box-drawing characters

## Architecture

```
morning_briefing.py          — Main script: data collection, all modes
morning_briefing_redesign.py — v2 module: AI brief, HTML email, editorial pipeline
briefing_monitor.py          — Health monitoring and alerting
.env                         — API keys (gitignored)
```

## Modes

| Mode | Schedule | Content |
|------|----------|---------|
| `morning` | 5:00 AM PT | Full AI editorial brief (news, earnings, movers, social) |
| `premarket` | 6:20 AM PT | Movers + earnings only |
| `recap` | 1:15 PM PT | Midday performance recap |
| `lunarcrush` | 6:20 AM PT | Standalone social intelligence report |

## Setup

1. Clone the repo
2. Install dependencies:
   ```bash
   pip3 install requests feedparser anthropic yfinance
   ```
3. Create a `.env` file in the repo root with your API keys:
   ```
   FINNHUB_API_KEY=your_key
   ANTHROPIC_API_KEY=your_key
   LUNARCRUSH_API_KEY=your_key
   ALPHA_VANTAGE_API_KEY=your_key
   IMESSAGE_RECIPIENT=+1234567890
   EMAIL_RECIPIENT=you@example.com
   ```
4. Edit the `HOLDINGS` list in `morning_briefing.py` to match your portfolio
5. Run manually:
   ```bash
   python3 morning_briefing.py morning
   ```

## Scheduling (macOS)

The system uses LaunchAgent plists for automated scheduling. See `.claude/CLAUDE.md` for details on the launchd configuration.

## Data Sources

- **Anthropic Claude** — AI brief generation (Sonnet), news filtering, earnings analysis
- **yfinance** — pre/post market prices (primary for extended hours), earnings fallback, 52-week data
- **Yahoo Finance spark** — batch stock prices during regular hours
- **Yahoo Finance chart** — futures, treasury yield, market close data
- **Finnhub** — earnings calendar and scorecard
- **Alpha Vantage** — last-resort earnings data, RSI alerts
- **FMP** — fallback for tickers missing from Yahoo
- **Yahoo Finance RSS** — news headlines
- **LunarCrush** — social media engagement metrics and creator signals
