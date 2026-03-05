# Morning Briefing — Project Context

## What This Is
Automated daily stock market digest for ~85 holdings. Sends via iMessage + email at scheduled times via macOS launchd.

## Architecture
- **Single file**: `morning_briefing.py` — all modes (morning, premarket, recap, lunarcrush)
- **Data cascade for earnings**: Finnhub → yfinance → Alpha Vantage (FMP and Yahoo v10 are dead, code retained but skipped)
- **Delivery**: AppleScript via subprocess for iMessage (Messages.app) and email (Mail.app)
- **Scheduling**: LaunchAgent plists in `~/Library/LaunchAgents/com.briefing.*.plist`
- **Secrets**: `.env` file in repo root (gitignored), loaded by `_load_dotenv()` at startup

## Key Files
| File | Purpose |
|------|---------|
| `morning_briefing.py` | Main script, all modes |
| `.env` | API keys and recipient config (NOT in repo) |
| `briefing_monitor.py` | Health monitoring script |
| `~/Library/LaunchAgents/com.briefing.*.plist` | launchd schedules |

## Schedules (PT)
- `morning` — 5:00 AM (full briefing with news, earnings, social)
- `premarket` — 6:20 AM (movers + earnings only)
- `recap` — 1:15 PM (midday recap)

## API Dependencies & Status (as of 2026-03-05)
| API | Status | Used For |
|-----|--------|----------|
| Finnhub | Working (60s timeout) | Earnings dates + scorecard |
| yfinance | Working | Earnings fallback, upcoming dates |
| Alpha Vantage | Working (data quality varies) | Last-resort earnings |
| FMP | Dead (404) | Skipped in cascade |
| Yahoo v10 | Dead (401) | Replaced by yfinance |
| LunarCrush | Working | Social buzz + creator signals |
| Anthropic Claude | Working | News filtering, earnings analysis |
| Yahoo RSS | Working | News headlines |
| Gmail API | Not authorized | Vital Knowledge newsletter |

## Known Issues
- Gmail OAuth needs setup: `python morning_briefing.py --setup-gmail`
- Python 3.9 is EOL — deprecation warnings in stderr (cosmetic)
- ETFs (DFAS, GDX, etc.) log "no earnings dates found" — expected, not a bug

## Testing
- Dry run (no send): not currently supported; test by running a mode and checking `/tmp/briefing-*.log`
- Syntax check: `python3 -c "import py_compile; py_compile.compile('morning_briefing.py', doraise=True)"`

## Common Pitfalls
- The plists use `osascript -e 'do shell script ...'` wrapper — required for GUI access (Messages.app) from launchd
- iMessage has a ~1600 char limit per message; script auto-chunks
- EPS sanity check rejects entries where actual=0.0 but estimate>$0.50 (garbage data pattern from Alpha Vantage)
