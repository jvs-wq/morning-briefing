# Morning Briefing System — Cold Rebuild Guide

**Purpose:** Everything needed to rebuild the Morning Briefing system from scratch on a clean Mac. If this file plus the other files in this Drive folder exist, a new Claude session (or a human) can fully reconstruct the running system.

**Last Updated:** June 23, 2026 (v2.7.5 model-currency fix + retired-model guard — see PROJECT_STATE.md changelog)
**Owner:** Jeff Vessler | jvs@blumecapital.com | Blume Capital

## v2.7.5 Quick Reference (2026-06-23)

1. **AI model ID is `claude-sonnet-4-6`** (set in `morning_briefing.py` ×3 and `morning_briefing_redesign.py` ×4). The prior pin `claude-sonnet-4-20250514` retired 2026-06-15 and 404'd every AI call, silently degrading the briefing (FILTERED NEWS showed `[???]`/`FYI` everywhere). **When a model retires, update all 7 occurrences** — `grep -rn 'model="claude' *.py`.
2. **Retired-model guard.** `warn_if_model_retired()` / `is_model_retired_error()` in `morning_briefing.py` print a loud `!!!! MODEL RETIRED OR INVALID` banner (naming the fix) from every AI `except` block on a 404 model error. The news fallback now leads with a visible `SYSTEM`/`URGENT` "AI categorization unavailable — update the model ID" banner instead of cryptic `[???]` rows. **If you ever see that banner in a brief or log, swap the model ID per item 1.**
3. **Model currency is a standing maintenance item** — a pinned model ID works until it retires, then fails. Check the catalog at https://platform.claude.com/docs/en/about-claude/models when refreshing.

## v2.7.4 Quick Reference (2026-05-23)

1. **All 7 plists now live in `launchd/`** as the canonical source. `deploy.sh` mirrors them into `~/Library/LaunchAgents/` at the 4:50 AM auto-sync so schedule edits made via Cowork in Drive propagate to whichever machine runs the briefing.
2. **`requirements.txt`** created in Drive (was referenced by README but missing). Use it as the canonical dependency list across all three machines.
3. **Premarket exception handling narrowed.** Formatting errors no longer get reported as "AI brief failed" and no longer discard a working `html_email`. Long-standing silent regression closed.
4. **Software currency:** see `outputs/software_currency_audit_2026-05-23.md` for the Python 3.9 EOL recommendation and dependency-version notes.

## v2.7.2 Quick Reference (2026-05-23)

1. **LunarCrush moved to Sunday 5:30 PM PT** (was weekday 6:20 AM). Edit surface: `com.briefing.lunarcrush.plist` in this Drive folder. Reaches production via the 4:50 AM Monday `com.briefing.deploy` auto-sync.
2. **Monitor mode-per-time dispatch.** `briefing_monitor.py` exposes `_modes_for_current_time()` and a `--by-time` CLI flag. `com.briefing.monitor.plist` now passes `--by-time` and includes a Sunday 6:00 PM slot. Each scheduled run only validates the workflow that just fired.
3. **BRKB-style Yahoo "possibly delisted" pattern added to `KNOWN_NOISE_PATTERNS`** in `briefing_monitor.py`. Berkshire Class B is not delisted; Yahoo's quote endpoint flakes intermittently.
4. **No iMessage path anywhere.** The `_v2_6_guard()` import-time check in `morning_briefing.py` refuses to run if any iMessage symbol reappears. `run_lunarcrush_brief()` (line 3437) uses `send_email`, not iMessage.



## v2.7 Quick Reference (2026-05-22)

Layered on top of v2.6's anti-drift hardening. The brief no longer leads with stale earnings prints even when fresh ambient signal (analyst actions, downgrades) provides plausible cover, and the voice rules now constrain bearish hyperbole symmetrically with bullish.

1. **Hard payload tag for stale prints** — `_build_ai_payload` in `morning_briefing_redesign.py` prefixes every scorecard row with `days_since > 1` as `[STALE: Nd ago — CONTEXT ONLY, DO NOT LEAD]`. String label — harder to ignore than the numeric `days_since` field alone.
2. **Sign-flip suppression** — when EPS estimate and actual have opposite signs, OR `|surprise_pct| > 200`, the percentage is replaced in the payload with `(sign flip — % surprise not meaningful)`. Absolute EPS values still print.
3. **Fresh-hook-on-stale-print rule** in `BRIEFING_SYSTEM_PROMPT`: a fresh analyst action referencing a stale print does NOT make the print fresh. Lead with the rating change and the tape reaction, not the print. Includes an explicit quiet-morning escape valve.
4. **Sign-flip precision rule** in `BRIEFING_SYSTEM_PROMPT`: do not cite percentages from near-zero denominators; quote absolute EPS instead.
5. **Symmetric forbidden-words list** across all four prompts (morning, recap, premarket, weekend): added bearish hyperbole — "catastrophic," "catastrophe," "collapse(d/ing)," "breakdown," "disaster(ous)," "carnage," "bloodbath," "implosion," "death spiral," "annihilated," "decimated."

## v2.6 Quick Reference (2026-05-19)

If you are reading this after a fresh rebuild, the system now expects **seven** LaunchAgents (as of v2.7.2 — LunarCrush moved to its own Sunday agent; see the Section 4 inventory table) and a Drive↔production auto-sync. The full rebuild path below is updated; the additions over v2.5 are:

1. **`com.briefing.deploy`** (4:50 AM weekdays) is now required. It runs `scripts/deploy.sh --reload` to mirror Drive → production, commit + push to GitHub, and reload all briefing agents before the 5:00 AM morning run.
2. **`scripts/deploy.sh`** is the only correct way to push code from Drive to production. Manual `cp` works in a pinch but skips the py_compile validation and the v2.6 anti-regression guard.
3. **`_v2_6_guard()` in `morning_briefing.py`** runs on import and exits 99 if any iMessage symbol (`send_imessage`, `IMESSAGE_RECIPIENT`, `_chunk_message`) reappears. This is intentional: the entire iMessage send path was removed in v2.6 and the guard prevents accidental re-introduction.
4. **Deploy-drift alarm in `briefing_monitor.py`** SHA-compares production against Drive every monitor run and emails an alert if they drift.
5. **AI freshness rule** in `BRIEFING_SYSTEM_PROMPT` requires `days_since == 0` (or scheduled today) for an earnings event to qualify for the WHAT MATTERS lead. `morning_briefing.py` enriches the payload with `days_since` automatically. Strengthened by v2.7 with a hard payload tag and a fresh-hook-on-stale-print rule.

Email-only delivery — there is no iMessage path anywhere in v2.6+.

---

## 1. Prerequisites

### Hardware & OS
- macOS (tested on iMac, Ventura/Sonoma)
- Python 3.9+ (system Python at `/usr/bin/python3` is fine; tested with 3.9.6 on macOS)
- Mail.app must be running for delivery. Messages.app is not used; v2.6 guard exits 99 if iMessage symbols reappear.

### Python Dependencies
```
pip3 install --user requests feedparser anthropic google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client yfinance
```

Note: Use `--user` flag for system Python installs. If pip still complains about externally-managed environment, add `--break-system-packages` flag. The `yfinance` library (v1.2.0+) is required for 52-week high/low enrichment data.

---

## 2. File Placement

### Production Script (local Mac only — launchd cannot run from Google Drive)
```
~/Claude/morning-briefing/morning_briefing.py    ← the script launchd executes
```

### LaunchAgent Plists (must be in this exact location)
```
~/Library/LaunchAgents/com.briefing.morning.plist
~/Library/LaunchAgents/com.briefing.premarket.plist
~/Library/LaunchAgents/com.briefing.recap.plist
```

### Gmail OAuth Credentials
```
~/Documents/Claude-Workspace/credentials/client_secret_942007569615-qa9bggt8p0rlkno9r0mmv138j31m0m60.apps.googleusercontent.com.json
~/Documents/Claude-Workspace/credentials/gmail_token.json
```
The client_secret file is the OAuth2 client credential from Google Cloud Console.
The gmail_token.json is generated by running `python3 morning_briefing.py setup_gmail` (one-time browser-based authorization).

### Google Cloud Console Project (for Gmail API)
- Console: https://console.cloud.google.com
- API enabled: Gmail API
- OAuth consent screen: External (or Internal if using Workspace)
- OAuth 2.0 Client: Desktop application type
- Scopes: `https://www.googleapis.com/auth/gmail.readonly`
- The Vital Knowledge email is forwarded from Outlook to the Gmail account, and the script searches for it by sender name containing "vitalknowledge" (case-insensitive)

---

## 3. API Keys & Provider Portals

All keys are embedded in the CONFIG dict at the top of `morning_briefing.py` (with env var override support). If a key expires or gets rotated, update it in the script AND in the `api_keys.txt` reference copy.

| Provider | Portal URL | Tier | Rate Limits | Used For |
|----------|-----------|------|-------------|----------|
| **Anthropic** | https://console.anthropic.com | Pay-per-token | Token-based | News filtering (AI classification), earnings miss explanations |
| **Finnhub** | https://finnhub.io/dashboard | Free | 60 calls/min | Earnings calendar, company profiles (primary source) |
| **FMP** | https://site.financialmodelingprep.com/developer/docs | Free | 250 calls/day | **Only `/stable/` endpoints work on free plan:** single-symbol quote (`/stable/quote?symbol=X`), earning-calendar (`/stable/earning-calendar`), earnings-surprises (`/stable/earnings-surprises`). Legacy `/api/v3/` fallback code paths removed (Feb 26, 2026). Batch quote is premium-only. |
| **Alpha Vantage** | https://www.alphavantage.co/support/#api-key | Free | 25 calls/day, 5/min | RSI technical data, earnings calendar last-resort fallback. Free tier: 25 calls/min, 500/day. Script enforces 3s between all Alpha Vantage calls (shared across RSI + earnings). |
| **LunarCrush** | https://lunarcrush.com/developers | Public API | Reasonable use, 2-3s between calls | Social intelligence. Uses THREE v4 endpoints: `/public/topic/{ticker}/v1` (engagements, sentiment, trend), `/public/topic/{ticker}/time-series/v2` (hourly data), `/public/creator/x/{handle}/v1` (creator signals). Bearer auth. [API docs](https://github.com/lunarcrush/api) |
| **Yahoo Finance spark** | No auth needed | Public | Batch limit: 20 symbols per request (HTTP 400 if exceeded) | **PRIMARY** for portfolio quotes and premarket movers. Endpoint: `https://query2.finance.yahoo.com/v8/finance/spark?symbols={csv}&range=1d&interval=1d`. Returns close, chartPreviousClose. No 52-week data (use yfinance for that). |
| **yfinance** | pip library (no key) | Public | Rate-limited by Yahoo | 52-week high/low enrichment. Downloads 1 year of daily OHLCV data in batch. Multi-ticker DataFrame has `Price/Ticker` MultiIndex columns. |

### Current Keys
Stored in `~/Claude/morning-briefing/.env` on the iMac (gitignored). Also mirrored in `api_keys.txt` in this Drive folder for reference. **Do NOT commit live keys to this file or any tracked file** — GitHub secret scanning will reject the push, and any keys that briefly land in tracked history must be rotated. The full key set is:

```
ANTHROPIC, FINNHUB, FMP, ALPHA_VANTAGE, LUNARCRUSH
```

Pull live values from `.env` or `api_keys.txt`. To rotate: log into the provider portal (Section 3 table), generate a new key, update `.env` on the iMac.

---

## 4. LaunchAgent Plist Files

**Source of truth:** the seven canonical plists live in `launchd/` inside this Drive folder. They are mirrored to `~/Library/LaunchAgents/` by `scripts/deploy.sh` at 4:50 AM weekdays (or whenever you run it manually with `--reload`). Edit them in Drive, not in `~/Library/LaunchAgents/` — anything done in the LaunchAgents folder directly will be overwritten on the next sync.

**osascript wrapper pattern.** All Python-invoking plists wrap their command in `/usr/bin/osascript -e 'do shell script "..."'` rather than calling `/usr/bin/python3` directly. Required because a launchd-spawned python3 lacks macOS Automation (TCC) permission to drive Mail.app — direct invocation fails with `error -1743`. The osascript wrapper inherits the needed permissions. Python stdout/stderr is redirected inside the `do shell script` string; the plist-level `StandardOutPath` / `StandardErrorPath` only capture osascript-level output. (The deploy plist is an exception — it invokes `/bin/bash scripts/deploy.sh` directly because deploy.sh doesn't touch Mail.app.)

### Inventory and timing

| Plist | Schedule | Mode | Source |
|---|---|---|---|
| `com.briefing.deploy.plist` | Mon–Fri 4:50 AM PT | (runs `scripts/deploy.sh --reload`) | `launchd/com.briefing.deploy.plist` |
| `com.briefing.morning.plist` | Mon–Fri 5:00 AM PT | `morning_briefing.py morning` | `launchd/com.briefing.morning.plist` |
| `com.briefing.premarket.plist` | Mon–Fri 6:20 AM PT | `morning_briefing.py premarket` | `launchd/com.briefing.premarket.plist` |
| `com.briefing.recap.plist` | Mon–Fri 1:15 PM PT | `morning_briefing.py recap` | `launchd/com.briefing.recap.plist` |
| `com.briefing.lunarcrush.plist` | Sun 5:30 PM PT | `morning_briefing.py lunarcrush` | `launchd/com.briefing.lunarcrush.plist` |
| `com.briefing.weekend_preview.plist` | Sun 6:00 PM PT | `morning_briefing.py weekend_preview` | `launchd/com.briefing.weekend_preview.plist` |
| `com.briefing.monitor.plist` | Mon–Fri 5:10/6:30 AM + 1:25 PM + Sun 6:00 PM | `briefing_monitor.py --by-time` | `launchd/com.briefing.monitor.plist` |

### Editing a schedule

1. Open the relevant plist in `launchd/` via Cowork or your editor of choice (on any of your three machines — they sync via Drive).
2. Edit the `StartCalendarInterval` block. Weekday values: `0` or `7` = Sunday, `1` = Monday, …, `5` = Friday, `6` = Saturday.
3. If you change the time of a workflow, also update the dispatch window in `briefing_monitor.py._modes_for_current_time()` and the schedule table in `CLAUDE.md` — they must stay aligned or the monitor produces false positives.
4. Wait for the next 4:50 AM auto-sync, or run `~/Claude/morning-briefing/scripts/deploy.sh --reload` from Terminal for immediate effect.

---

## 5. Deploy From Scratch Checklist (cold rebuild on a fresh Mac)

This walks through the full rebuild path. Assumes you have the Drive folder synced and the GitHub repo accessible on the target Mac.

### Step 1: Install Python and dependencies
```bash
# Use the new requirements.txt (created v2.7.4); was previously a list embedded in this doc.
cd ~/Claude/morning-briefing  # placeholder — you'll create this folder in Step 2
# After Step 2 you can run:
pip3 install --user --break-system-packages -r requirements.txt
```
Or, if you're following the v2.7.4 software-currency recommendation and installing Python 3.12 from Homebrew:
```bash
brew install python@3.12
/opt/homebrew/bin/python3.12 -m venv ~/Claude/morning-briefing/.venv
~/Claude/morning-briefing/.venv/bin/pip install -r ~/Claude/morning-briefing/requirements.txt
# If you take this path, update the plists in launchd/ to point at .venv/bin/python3 instead of /usr/bin/python3.
```

### Step 2: Clone the repo into production location
```bash
mkdir -p ~/Claude
cd ~/Claude
git clone git@github.com:jvs-wq/morning-briefing.git
# OR if SSH isn't set up:
# git clone https://github.com/jvs-wq/morning-briefing.git
```

### Step 3: Restore secrets
The `.env` file is gitignored. Copy from a backup or recreate manually:
```bash
# At minimum, the .env needs:
#   ANTHROPIC_API_KEY
#   FINNHUB_API_KEY
#   FMP_API_KEY
#   ALPHA_VANTAGE_API_KEY
#   LUNARCRUSH_API_KEY
#   EMAIL_RECIPIENT (your jvs@blumecapital.com address)
#   STRATECHERY_RSS_URL (optional)
#   ASIANOMETRY_RSS_URL (optional)
cp /path/to/backup/.env ~/Claude/morning-briefing/.env
```

### Step 4: Smoke-test each workflow before scheduling
```bash
cd ~/Claude/morning-briefing
python3 morning_briefing.py morning           # full morning brief
python3 morning_briefing.py premarket         # 6:20 AM delta
python3 morning_briefing.py recap             # 1:15 PM post-close
python3 morning_briefing.py lunarcrush        # Sunday social brief
python3 morning_briefing.py weekend_preview   # Sunday weekly setup
```
First run prompts for Mail.app Automation permission — accept it. Subsequent runs are silent.

### Step 5: Install the LaunchAgents
The canonical install is one `scripts/deploy.sh --reload` invocation — it mirrors `launchd/*.plist` from Drive into `~/Library/LaunchAgents/` and `launchctl load`s them. Idempotent.
```bash
cd ~/Claude/morning-briefing
scripts/deploy.sh --reload
```
Verify:
```bash
launchctl list | grep briefing
# Should show 7 lines:
#   com.briefing.deploy
#   com.briefing.morning
#   com.briefing.premarket
#   com.briefing.recap
#   com.briefing.lunarcrush
#   com.briefing.weekend_preview
#   com.briefing.monitor
```

### Step 6: (Optional) Set up the Vital Knowledge Gmail OAuth
Only needed if you want the VK news section in the morning brief.
```bash
python3 ~/Claude/morning-briefing/morning_briefing.py --setup-gmail
# Opens a browser; authorize with the Gmail account that receives the VK forward.
```

### Step 7: (Optional) Restore runtime state from backup
- `earnings_history.json` (4-week earnings lookback) — gitignored, rebuilds over ~3 weeks if missing.
- `strategy_reads_seen.json` (article-GUID dedup) — gitignored, rebuilds itself.

---

## 6. Multi-machine sync (Jeff's three Macs)

Google Drive is the bridge. Every machine should have:

- The Drive folder synced locally (this folder you're reading).
- A production checkout at `~/Claude/morning-briefing/` (clone of `github.com:jvs-wq/morning-briefing`).
- `scripts/deploy.sh` runs nightly via `com.briefing.deploy.plist` to mirror Drive → production → GitHub, AND mirror Drive's `launchd/*.plist` → `~/Library/LaunchAgents/`.

**Which machine actually runs the briefs?** Only the iMac currently. The MacBook and third Mac sync the code via Drive + Git so any of them can be the active machine if needed, but only the active machine should have the LaunchAgents loaded. Don't load them on multiple Macs — you'd get duplicate emails.

**Editing schedules from a non-active machine:** edit the plist in Drive → wait for the iMac's 4:50 AM auto-sync → reloaded automatically. Or SSH to the iMac and run `~/Claude/morning-briefing/scripts/deploy.sh --reload` for immediate effect.

### Step 7: Verify
```bash
launchctl list | grep briefing
# Should show three entries with PID 0 (waiting for schedule) or a running PID
```

### Step 8: Test Each Workflow Manually
```bash
# Delete lockfiles to allow immediate re-runs
rm -f /tmp/briefing-morning.lock /tmp/briefing-premarket.lock /tmp/briefing-recap.lock

python3 ~/Claude/morning-briefing/morning_briefing.py morning
python3 ~/Claude/morning-briefing/morning_briefing.py premarket
python3 ~/Claude/morning-briefing/morning_briefing.py recap
```

---

## 6. Important Path Note

The plists reference `/Users/jeffreystclaire/Claude/morning-briefing/morning_briefing.py`. If the Mac username is different (e.g., a different machine), update the path in all three plists. The Gmail credentials path in the script CONFIG also contains a hardcoded home directory path — update `GMAIL_CREDENTIALS_FILE` and `GMAIL_TOKEN_FILE` if needed.

---

## 7. Periodic Maintenance

- **Earnings scorecard**: Now uses rolling 3-week lookback (`today - timedelta(days=21)`). No quarterly date update needed.
- **Update holdings**: Edit `INDIVIDUAL_STOCKS` and `ETFS` lists in the CONFIG dict if portfolio changes.
- **Update CREATOR_WATCHLIST**: Edit the list in CONFIG to add/remove creator handles. Current: CathieDWood, jimcramer, chamath, elonmusk, DavidSacks, altcap (Gerstner), GavinSBaker (Baker — not yet indexed by LunarCrush), bgurley (Gurley).
- **Verify API keys**: Log into each provider portal and confirm the key is active.
- **Check Gmail token**: If Vital Knowledge stops appearing, re-run `setup_gmail` to refresh the OAuth token.
- **Review LunarCrush response format**: Check `/tmp/briefing-morning.log` for debug lines. Three endpoints used: topic (for `interactions_24h`, `types_sentiment`, `num_posts`, `trend`), time-series/v2 (hourly data), creator (for `creator_followers`, `interactions_24h`, `topic_influence`). Sentiment comes from `types_sentiment["tweet"]`, NOT top-level `sentiment` field. If API format changes, check [official docs](https://github.com/lunarcrush/api).

---

## 8. Files in This Google Drive Folder

| File | Purpose | Authoritative? |
|------|---------|---------------|
| `morning_briefing.py` | Reference copy of production script | Backup (production copy is on iMac at ~/Claude/morning-briefing/) |
| `Morning_Briefing_Documentation.docx` | Full technical documentation (v2.3) | Yes — canonical documentation |
| `SETUP.md` | This file — cold rebuild instructions | Yes — canonical rebuild guide |
| `ORIGINAL_SPEC_2026-02-06.md` | Original requirements (historical) | Archive only |
| `README.md` | Quick-reference operations guide | Yes |
| `com.briefing.premarket.plist` | LaunchAgent template for pre-market | Reference (installed copy is at ~/Library/LaunchAgents/) |
| `api_keys.txt` | API key reference with provider portals | Yes — update when keys rotate |
