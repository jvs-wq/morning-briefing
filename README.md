# Morning Briefing

Automated daily stock market digest for a personal portfolio. Monitors ~85 holdings and delivers a formatted briefing via iMessage and email on weekday mornings.

## Features

- **Market snapshot** — S&P/NASDAQ futures, 10Y Treasury yield
- **Pre-market movers** — holdings moving >3% before open
- **Earnings scorecard** — beat/miss tracking with EPS surprise data
- **AI-filtered news** — relevant headlines selected by Claude API
- **Social intelligence** — LunarCrush social buzz and creator signals
- **Earnings miss analysis** — AI-generated explanations for misses

## Modes

| Mode | Schedule | Content |
|------|----------|---------|
| `morning` | 5:00 AM PT | Full briefing (news, earnings, movers, social) |
| `premarket` | 6:20 AM PT | Movers + earnings only |
| `recap` | 1:15 PM PT | Midday performance recap |
| `lunarcrush` | Manual | Standalone social intelligence report |

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

- **Finnhub** — earnings calendar and scorecard
- **yfinance** — earnings fallback and upcoming dates
- **Alpha Vantage** — last-resort earnings data
- **Yahoo Finance RSS** — news headlines
- **LunarCrush** — social media engagement metrics
- **Anthropic Claude** — AI news filtering and analysis
