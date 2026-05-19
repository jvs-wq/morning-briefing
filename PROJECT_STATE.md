# Morning Briefing — Project State

**Last updated:** 2026-05-19
**Status:** Production — v2.6 anti-drift hardening deployed

---

## Current State

The morning briefing system runs on Jeff's iMac (`Jeffs-iMac`) via launchd. Six LaunchAgents — `deploy` (4:50 AM weekdays), `morning` (5:00 AM weekdays), `premarket` (6:20 AM weekdays), `recap` (1:15 PM weekdays), `weekend_preview` (Sunday 6:00 PM), `monitor` (5:10 AM, 6:30 AM, 1:25 PM weekdays). Email-only delivery via Apple Mail. The production tree (`~/Claude/morning-briefing/`) is the git working tree for `github.com/jvs-wq/morning-briefing` `main` branch; the Drive folder is a synced mirror reconciled by `scripts/deploy.sh` at 4:50 AM each weekday.

### What's Working (2026-05-19)
- Full data collection pipeline: market snapshot, pre-market movers, earnings scorecard with revenue, AI-filtered news, analyst actions, RSI alerts.
- Four AI editorial briefs: morning, premarket, recap, weekend_preview.
- HTML email delivery via Apple Mail (plain-text fallback when HTML rendering fails).
- Health monitor with deploy-drift detection: emails an alert if production code SHAs diverge from Drive.
- Anti-regression guard: `_v2_6_guard()` in `morning_briefing.py` exits 99 on import if any iMessage symbol reappears.
- Drive→production auto-sync via `com.briefing.deploy` LaunchAgent at 4:50 AM weekdays — runs `scripts/deploy.sh --reload` which SHA-diffs, py_compile-validates, copies, commits, pushes, and reloads all LaunchAgents.
- AI freshness rule: `BRIEFING_SYSTEM_PROMPT` carries an explicit "days_since" rule; payload enrichment adds `days_since` to each scorecard/earnings record before the AI sees them.

### Known Gaps (Deferred)
- **Vital Knowledge feed:** Gmail OAuth still not authorized — VK highlights section empty. `python morning_briefing.py --setup-gmail` when ready.
- **Market snapshot incomplete:** VIX / oil / gold / BTC / DXY still N/A — need data-fetch expansion.
- **Python 3.9 EOL:** iMac on 3.9.6, deprecation warnings from `google-auth` / `google-api-core`. Upgrade deferred.
- **`~/My Drive/` is not actually synced.** The user's "My Drive" at `~/My Drive/` is a local directory, not a Google Drive mount. The real Google Drive sync points at `~/Library/CloudStorage/GoogleDrive-jeffstclaire@gmail.com/My Drive/` and has a stale May-12 copy. As far as the briefing system goes, this is fine — `deploy.sh` uses `~/My Drive/` (where Cowork edits land) as the source. But for the user's 3-machine sync goal, the other two machines aren't actually getting the latest. Flagged for separate follow-up.

## Recent Changes (2026-05-19 — v2.6 anti-drift hardening)

1. **iMessage fully removed.** Stripped `send_imessage()`, `_chunk_message()`, `IMESSAGE_RECIPIENT`, and all 5 send call-sites from `morning_briefing.py`; removed the iMessage send from `run_morning_briefing_v2()` in `morning_briefing_redesign.py`; updated docstrings; replaced production `briefing_monitor.py` with the Drive email-only version.
2. **Anti-regression guard.** Added `_v2_6_guard()` invocation at module import time. Self-aware: strips its own block from the scan via `# === v2.6 safeguard ... # === end v2.6 safeguard ===` markers so the guard's own forbidden-symbol regex doesn't trip it. Negative-control tested.
3. **Drive↔prod lockstep.** New `scripts/deploy.sh` (SHA-diff → py_compile → copy → guard → commit → push → optional reload). New `com.briefing.deploy.plist` (4:50 AM weekdays). Both mirrored to production tree.
4. **Deploy-drift monitor.** Added `check_deploy_freshness()` to `briefing_monitor.py`, wired into `main()` so every monitor run surfaces drift via email alert before the run-health summary.
5. **AI freshness rule.** Appended a `## v2.6 freshness rule` section to `BRIEFING_SYSTEM_PROMPT`. Injected a `days_since` enrichment pass into `morning_briefing.py` between scorecard build and AI payload. Kills the AFRM-as-today's-news bug (2-week-old earnings being presented as today's catalyst).
6. **Backup tag + branch.** `git tag pre-imessage-removal-20260519-0553` and `git branch backup/pre-imessage-removal` capture pre-migration state.

### Why this matters
Recurring class of bug: changes made in Drive (Cowork edit surface) never reached the iMac production tree. The user reported this on 2026-05-19 after an iMessage briefing fired at 5:05 AM despite a 2026-05-18 README entry declaring email-only dispatch. Root cause: the May-18 Drive edits were never committed/pushed to GitHub and the production directory (which is the git working tree) was never updated. The fix is structural: auto-sync at 4:50 AM weekdays + a fail-fast guard at the import boundary + a drift alarm in the monitor. Spec compliance no longer relies on human discipline.

## Architecture

```
Production tree:  ~/Claude/morning-briefing/   (iMac, git working tree)
GitHub:           github.com/jvs-wq/morning-briefing  (canonical history)
Drive mirror:     ~/My Drive/Claude-Workspace/Claude Projects/Morning Briefing/  (local edit surface used by Cowork)
```

### Key Files
| File | Location | Purpose |
|------|----------|---------|
| `morning_briefing.py` | Production + Drive + GitHub | Main script. Hosts `_v2_6_guard()` + `days_since` enrichment. |
| `morning_briefing_redesign.py` | Production + Drive + GitHub | AI briefs, HTML email, plain-text fallback. Hosts v2.6 freshness rule. |
| `briefing_monitor.py` | Production + Drive + GitHub | Log monitor + `check_deploy_freshness()` drift alarm. |
| `scripts/deploy.sh` | Production + Drive + GitHub | Drive→prod→GitHub deploy with py_compile, guard, reload. |
| `launchd/com.briefing.deploy.plist` | Production + Drive + GitHub + `~/Library/LaunchAgents/` | 4:50 AM weekday auto-sync. |
| `migrations/v2_6_*.py` | Production + Drive + GitHub | Idempotent migration scripts. Audit trail. |
| `.env` | Production only (gitignored) | API keys + recipient config |
| `com.briefing.*.plist` | `~/Library/LaunchAgents/` | Six LaunchAgents (see above) |

### Deploy workflow (going forward)
1. User edits files in Drive folder via Cowork (`~/My Drive/Claude-Workspace/Claude Projects/Morning Briefing/`).
2. `com.briefing.deploy` fires at 4:50 AM Mon–Fri: SHA-diffs Drive vs prod, copies Drive→prod if drift, py_compile validates, runs v2.6 guard, commits + pushes to `origin/main`, reloads all six LaunchAgents.
3. `com.briefing.morning` fires at 5:00 AM running the fresh code.
4. `com.briefing.monitor` at 5:10 AM verifies success AND re-runs the drift check; emails alert on any failure or drift.
5. If a fix can't wait until tomorrow morning, run `~/Claude/morning-briefing/scripts/deploy.sh --reload` from Terminal — same flow, immediate.

## Open Questions
- Should the daily auto-sync also push notifications to the other two synced machines? (Currently `~/My Drive/` is local-only on this machine.)
- Is Python 3.9 → 3.12 upgrade worth the risk of breaking other scripts on the iMac?
- Worth expanding market snapshot to include VIX / oil / gold / BTC / DXY?

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-19 | v2.6: auto-sync Drive→prod + import-time guard + drift alarm | Recurring deploy-drift bug — solve structurally, not via discipline. |
| 2026-05-19 | Production is canonical git working tree; Drive is edit-surface mirror | Avoids the "Drive is canonical but lacks recent prod commits" trap. |
| 2026-05-19 | `format_morning_text()` survives as email plain-text fallback | Useful even without iMessage; HTML-render-failure backstop. |
| 2026-05-18 | Email-only dispatch (no iMessage) | iMessage delivery flaky and noisy; HTML email proven reliable. |
| 2026-04-06 | v2 redesign: AI editorial brief | Old format was a data dump with gaps. |
| 2026-04-06 | Use Claude Sonnet for brief generation | Faster + cheaper for daily automation; quality sufficient. |
