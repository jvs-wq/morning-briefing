# Morning Briefing

Automated stock-market intelligence brief for a concentrated investment portfolio. Monitors 84 holdings (70 stocks + 14 ETFs) and delivers AI-generated editorial analysis via HTML email and a slim iMessage teaser on a weekday + weekend-aware schedule.

## v3 — Earnings Season Enrichment (2026-04-14)

Major earnings data upgrade for Q1 2026 earnings season:

- **4-week persistent lookback** — `earnings_history.json` accumulates results across runs, auto-prunes entries older than 28 days. Manual corrections (via `source: manual_correction`) survive API overwrites.
- **Revenue estimates vs actuals** — shown in scorecard and upcoming earnings calendar (from Finnhub)
- **AI guidance analysis** — Claude infers raised/lowered/in-line from news headlines after each report
- **Sell-side analyst actions** — upgrades, downgrades, and price target changes via yfinance (7-day window). iMessage shows material changes only (rating changes, PT >10%, new coverage); full list in HTML email.
- **BCM holdings update** — at the time, 74 stocks + 15 ETFs = 89 total. *Has since been refreshed 2026-04-23 to 70 stocks + 14 ETFs = 84 total — see `PROJECT_STATE.md` and the heading line at the top of this README.*
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
- **Strategy reads (recap + weekend_preview)** — long-form analyst posts (Stratechery, Asianometry) from the last 48h surfaced in a "Strategy & Analysis" section, with GUID-deduped state shared across recap and weekend_preview so each post appears once
- **HTML email** — professional typography with data appendix tables
- **Slim iMessage teaser** — single chunk, ~750–900 chars, lead paragraph + market snapshot + pointer to email. (Old multi-chunk text dump was retired 2026-04-22.)
- **Social intelligence** — *the morning brief no longer calls LunarCrush as of 2026-04-26.* Daily LunarCrush coverage lives in the sibling [`lunarcrush-brief`](https://github.com/jvs-wq/lunarcrush-brief) repo (evening 5 PM PT, Saturday weekly digest, Monday review).

## Architecture

```
morning_briefing.py          — Main script: data collection + all four modes (~4,225 lines)
morning_briefing_redesign.py — AI briefs, HTML email, iMessage text for all four modes (~2,501 lines)
briefing_monitor.py          — Health monitoring and alerting
launchd/                     — Launchd plists + idempotent install.sh (source of truth for the schedule)
scripts/verify_schedule.sh   — Schedule health smoke-test (also runs as a one-shot check)
requirements.txt             — Python dependencies
earnings_history.json        — Persistent 4-week earnings lookback (gitignored, runtime)
strategy_reads_seen.json     — Stratechery + Asianometry GUID dedup state (gitignored, runtime)
.env                         — API keys (gitignored)
```

## Modes

| Mode | Schedule | Content |
|------|----------|---------|
| `morning` | **Mon–Fri** 5:00 AM PT | Full AI editorial brief (news, earnings, movers, analyst actions) |
| `premarket` | **Mon–Fri** 6:20 AM PT | AI delta brief — what changed since 5 AM, BMO actuals, bell plan |
| `recap` | **Mon–Fri** 2:00 PM PT | Post-close editorial — grades the day, frames tomorrow, includes Stratechery + Asianometry strategy reads |
| `weekend_preview` | **Sun** 6:00 PM PT | Sunday futures + AI-filtered weekend headlines + strategy reads + AI synthesis ("setup for Monday") |

The four briefing modes are weekday- vs Sunday-gated at the launchd layer (see `launchd/`). Saturday is reserved for the LunarCrush weekly digest, which lives in the sibling [`lunarcrush-brief`](https://github.com/jvs-wq/lunarcrush-brief) repo.

## Setup

1. Clone the repo to `~/Claude/morning-briefing/` (the launchd plists hardcode this path — see Disaster Recovery below if you want to put it somewhere else).
2. Install dependencies:
   ```bash
   pip3 install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your API keys. `STRATECHERY_RSS_URL` and `ASIANOMETRY_RSS_URL` are optional — leave blank to disable the recap "Strategy & Analysis" section.
4. Edit the holdings lists in `morning_briefing.py` CONFIG section if your portfolio differs.
5. Run manually:
   ```bash
   python3 morning_briefing.py morning          # full morning brief
   python3 morning_briefing.py premarket        # 6:20 AM delta
   python3 morning_briefing.py recap            # 2 PM post-close
   python3 morning_briefing.py weekend_preview  # Sunday-night setup
   ```

## Scheduling (macOS launchd)

The five plists in `launchd/` are the source of truth for the schedule. Install them with:

```bash
bash launchd/install.sh
```

The script copies every `*.plist` in `launchd/` to `~/Library/LaunchAgents/` and `launchctl load`s them. It's idempotent — safe to re-run. You should see five agents loaded: `com.briefing.morning`, `com.briefing.premarket`, `com.briefing.recap`, `com.briefing.weekend_preview`, `com.briefing.monitor`.

Schedule details:
- `morning` / `premarket` / `recap` use an array of five `StartCalendarInterval` dicts (Weekday 1–5) so they only fire on weekdays.
- `weekend_preview` uses a single dict with `Weekday=0` (Sunday) at 6:00 PM PT.
- `monitor` is a long-running watchdog (no schedule).

## Disaster Recovery

If this iMac dies, here's the full rebuild path on a fresh macOS box:

1. **Install Python 3.9+** (system Python at `/usr/bin/python3` works on macOS).
2. **Clone the repo** to `~/Claude/morning-briefing/`. If you put it somewhere else or your username isn't `jeffreystclaire`, edit the absolute paths in `launchd/*.plist` (they reference `/Users/jeffreystclaire/Claude/morning-briefing/morning_briefing.py`).
3. **Install Python deps**: `pip3 install -r requirements.txt`. The Google packages are only needed if you use the Vital Knowledge Gmail integration; you can skip them otherwise.
4. **Restore secrets**: copy your `.env` from a backup (it's gitignored — never committed). API keys you'll need: `FINNHUB_API_KEY`, `ANTHROPIC_API_KEY`, `FMP_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `LUNARCRUSH_API_KEY` (LunarCrush usage is via the `lunarcrush-brief` repo now, but a key may still be referenced). Plus the recipient phone/email and (optional) the paid Stratechery + Asianometry Passport RSS URLs.
5. **Install the schedule**: `bash launchd/install.sh`.
6. **Smoke-test each mode** before relying on the schedule:
   ```bash
   python3 morning_briefing.py morning
   python3 morning_briefing.py weekend_preview
   ```
   Both should produce console output, an HTML email, and an iMessage. iMessage uses AppleScript — macOS will prompt for Messages.app automation permission the first time.
7. **(Optional) Restore runtime state**: `earnings_history.json` (4-week earnings lookback) and `strategy_reads_seen.json` (article-GUID dedup) are gitignored runtime files. They rebuild themselves over time, but copying them from backup avoids a re-grading window after recovery.
8. **Vital Knowledge / Gmail**: if you use it, run `python3 morning_briefing.py --setup-gmail` to re-authorize the Gmail OAuth flow. The OAuth token is machine-local and gitignored.

The sibling [`lunarcrush-brief`](https://github.com/jvs-wq/lunarcrush-brief) repo has its own `launchd/` directory and install script — recover that separately if you use the LunarCrush evening / Saturday weekly / Monday review jobs.

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
| Stratechery (Passport RSS) | Personal feed URL | Long-form tech-strategy posts in recap + weekend_preview "Strategy & Analysis" sections |
| Asianometry (Passport RSS) | Personal feed URL | Long-form semiconductor / East Asia analysis in recap + weekend_preview "Strategy & Analysis" sections |

LunarCrush is **not** a data source for this repo as of 2026-04-26 — see the sibling [`lunarcrush-brief`](https://github.com/jvs-wq/lunarcrush-brief) repo for daily evening / Saturday weekly / Monday review LunarCrush coverage.

## Data Quality Notes

- Finnhub earnings data can be stale on report day — the script supports manual corrections in `earnings_history.json` that persist across runs
- Yahoo free endpoints do NOT return pre-market prices — only yfinance (authenticated) provides them
- FMP `/stable/analyst-estimates` and `/stable/upgrades-downgrades` require paid tier (402/404)
- ETF tickers generate expected "no earnings dates found" warnings
