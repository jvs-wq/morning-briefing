# Morning Briefing — Project Context

## What This Is
Automated daily stock market intelligence brief for ~85 holdings. Delivers AI-generated editorial analysis via HTML email + plain text iMessage at scheduled times via macOS launchd.

## Architecture
- **Main script**: `morning_briefing.py` — data collection, all modes (morning, premarket, recap, lunarcrush)
- **v2 Redesign module**: `morning_briefing_redesign.py` — AI brief generation, HTML email formatting, editorial pipeline
- **v2 Pipeline**: collect data → bundle into dict → Claude Sonnet generates editorial analysis → format as HTML email + plain text iMessage → send both
- **Fallback**: if AI generation fails, falls back to legacy `format_briefing()` in main script
- **Data cascade for earnings**: Finnhub → yfinance → Alpha Vantage (FMP and Yahoo v10 are dead, code retained but skipped)
- **Delivery**: AppleScript via subprocess for iMessage (Messages.app) and HTML email (Mail.app)
- **Scheduling**: LaunchAgent plists in `~/Library/LaunchAgents/com.briefing.*.plist`
- **Secrets**: `.env` file in repo root (gitignored), loaded by `_load_dotenv()` at startup

## Key Files
| File | Purpose |
|------|---------|
| `morning_briefing.py` | Main script, all modes, data collection |
| `morning_briefing_redesign.py` | v2 module: AI brief generation, HTML email, editorial formatting |
| `.env` | API keys and recipient config (NOT in repo) |
| `briefing_monitor.py` | Health monitoring script |
| `~/Library/LaunchAgents/com.briefing.*.plist` | launchd schedules |

## v2 Redesign (2026-04-06)
The morning briefing was redesigned from a plain-text data dump to an AI-powered editorial intelligence brief.

### Design Aesthetic
"MoMA Penguin Books" — black (#1a1a1a) header, red (#c0392b) top rule, Georgia serif body, Arial sans-serif headers, table-based HTML layout at 640px max width.

### AI Brief Structure (JSON keys from Claude Sonnet)
- `what_matters` — thesis-driven lead connecting market events to portfolio positions
- `market_context` — macro interpretation
- `premarket_analysis` — pre-market movers with thesis implications
- `earnings_intelligence` — scorecard analysis with forward-looking calls
- `news_signal` — filtered news with portfolio relevance
- `watchlist` — specific levels and events to monitor

### Key Functions in morning_briefing_redesign.py
- `generate_ai_morning_brief(data, api_key)` — calls Claude Sonnet, returns structured JSON
- `format_morning_html(ai_brief, data)` — full HTML email with editorial aesthetic
- `format_morning_text(ai_brief, data)` — plain text iMessage with box-drawing chars
- `send_html_email(recipient, subject, html_body)` — HTML email via Apple Mail AppleScript

## Schedules (PT)
- `morning` — 5:00 AM (full briefing with news, earnings, social, AI analysis)
- `premarket` — 6:20 AM (movers + earnings only)
- `recap` — 1:15 PM (midday recap)

## API Dependencies & Status (as of 2026-04-06)
| API | Status | Used For |
|-----|--------|----------|
| yfinance | Working — **primary for pre/post market prices** | Earnings fallback, upcoming dates, pre-market quotes via Ticker.info |
| Yahoo spark | Working (regular hours only) | Batch stock prices during market hours |
| Yahoo chart | Working | Futures (ES=F, NQ=F), treasury yield, market close data |
| Finnhub | Working (60s timeout) | Earnings dates + scorecard |
| Alpha Vantage | Working (data quality varies) | Last-resort earnings, RSI alerts |
| FMP | Working (stable endpoint) | Fallback for missing tickers |
| LunarCrush | Working | Social buzz + creator signals |
| Anthropic Claude | Working | AI brief generation (Sonnet), news filtering, earnings analysis |
| Yahoo RSS | Working | News headlines |
| Gmail API | Not authorized | Vital Knowledge newsletter (deferred) |

## Known Issues
- Gmail OAuth needs setup: `python morning_briefing.py --setup-gmail` (Vital Knowledge feed deferred)
- Market snapshot only fetches S&P/NASDAQ/10Y — VIX, oil, gold, BTC, DXY show N/A
- Python 3.9 is EOL — deprecation warnings in stderr (cosmetic); `from __future__ import annotations` used for compatibility
- ETFs (DFAS, GDX, etc.) log "no earnings dates found" — expected, not a bug

## Testing
- Manual test: `cd ~/Claude/morning-briefing && /usr/bin/python3 morning_briefing.py morning`
- Remove lockfile first if needed: `rm -f /tmp/briefing-morning.lock`
- Syntax check: `python3 -c "import py_compile; py_compile.compile('morning_briefing.py', doraise=True)"`

## Common Pitfalls
- The plists use `osascript -e 'do shell script ...'` wrapper — required for GUI access (Messages.app) from launchd
- iMessage has a ~1600 char limit per message; script auto-chunks
- Python stdout buffers when redirected to file — stderr flushes immediately, so test logs may appear empty while running
- EPS sanity check rejects entries where actual=0.0 but estimate>$0.50 (garbage data from Alpha Vantage)
- Yahoo spark `close` field can be `null` (not an empty list) — always use `(info.get("close") or [])`
- Apple Mail AppleScript needs `html content` property for HTML email; timeout should be 320s for App Nap wake
