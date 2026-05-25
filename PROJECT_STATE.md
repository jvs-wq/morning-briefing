# Morning Briefing — Project State

**Last updated:** 2026-05-23
**Status:** Production — v2.7.4 plist consolidation + multi-machine Drive bridge unblocked (Drive-side; reaches prod via Monday 4:50 AM auto-sync, or `scripts/deploy.sh --reload` for immediate effect)

---

## Current State

The morning briefing system runs on Jeff's iMac (`Jeffs-iMac`) via launchd. **Seven LaunchAgents** — `deploy` (4:50 AM weekdays), `morning` (5:00 AM weekdays), `premarket` (6:20 AM weekdays), `recap` (1:15 PM weekdays), `lunarcrush` (5:30 PM Sunday — moved from weekday morning in v2.7.2), `weekend_preview` (Sunday 6:00 PM), `monitor` (5:10 AM, 6:30 AM, 1:25 PM weekdays + 6:00 PM Sunday). Email-only delivery via Apple Mail. The production tree (`~/Claude/morning-briefing/`) is the git working tree for `github.com/jvs-wq/morning-briefing` `main` branch; the Drive folder is a synced mirror reconciled by `scripts/deploy.sh` at 4:50 AM each weekday.

**Macro frame.** Everything in this system serves two goals: (1) keep Jeff fully informed about his and his firm's portfolios; (2) preemptively flag signal from noise. Features that create noise — false-positive monitor alerts, stale-earnings led briefs, hype words — are regressions even if they "work."

### What's Working (2026-05-19)
- Full data collection pipeline: market snapshot, pre-market movers, earnings scorecard with revenue, AI-filtered news, analyst actions, RSI alerts.
- Four AI editorial briefs: morning, premarket, recap, weekend_preview.
- HTML email delivery via Apple Mail (plain-text fallback when HTML rendering fails).
- Health monitor with deploy-drift detection: emails an alert if production code SHAs diverge from Drive.
- Anti-regression guard: `_v2_6_guard()` in `morning_briefing.py` exits 99 on import if any iMessage symbol reappears.
- Drive→production auto-sync via `com.briefing.deploy` LaunchAgent at 4:50 AM weekdays — runs `scripts/deploy.sh --reload` which SHA-diffs, py_compile-validates, copies, commits, pushes, and reloads all LaunchAgents.
- AI freshness rule: `BRIEFING_SYSTEM_PROMPT` carries an explicit "days_since" rule; payload enrichment adds `days_since` to each scorecard/earnings record before the AI sees them.

### Known Gaps (Deferred)
- **Vital Knowledge feed:** Gmail OAuth still not authorized — VK highlights section empty. `python morning_briefing.py --setup-gmail` when ready (requires Jeff at the keyboard for browser OAuth).
- **Market snapshot incomplete:** VIX / oil / gold / BTC / DXY still N/A — need data-fetch expansion.
- **Python 3.9 EOL upgrade pending:** iMac on 3.9.6 (EOL Oct 2025). Recommended target 3.11+ via Homebrew. Plan documented in `outputs/software_currency_audit_2026-05-23.md` — non-urgent, maintenance window.
- **Drive sync surface verified informally only.** Earlier PROJECT_STATE note said `~/My Drive/` on the iMac was local-only (with the real sync at `~/Library/CloudStorage/GoogleDrive-jeffstclaire@gmail.com/My Drive/`). Jeff confirmed 2026-05-23 that Drive IS the bridge across his three machines, so the multi-machine flow now relies on this being true. If a future change made on the MacBook doesn't appear on the iMac after a sync cycle, this assumption needs revisiting.

### Resolved in v2.7.4 (no longer deferred)
- **~~Only 3 of 7 plists in Drive~~** — All 7 now in `launchd/`. `deploy.sh` mirrors them to `~/Library/LaunchAgents/` as part of the auto-sync.
- **~~Schedule changes from a non-iMac machine~~** — Now possible: edit plist in Drive (any machine) → propagates via Drive → next 4:50 AM sync picks it up.
- **~~No requirements.txt in Drive~~** — Created.

## Recent Changes (2026-05-23 — v2.7.4 plist consolidation + Drive-bridge unblock + software currency)

**Trigger.** Jeff confirmed Google Drive is the bridge across his three Macs and asked me to fix all the open items I'd flagged plus a new standing rule: keep software up to date proactively. The biggest structural item: only 3 of 7 plists lived in Drive, so editing schedules from any non-iMac machine was effectively impossible.

**Changes.**

1. **All 7 plists consolidated into `launchd/` in Drive.** Previously: `launchd/com.briefing.deploy.plist` (already there), `com.briefing.monitor.plist` + `com.briefing.lunarcrush.plist` at root, and `com.briefing.morning/premarket/recap/weekend_preview` only on the iMac in `~/Library/LaunchAgents/`. Now: all seven in `launchd/` as the single canonical location. The four missing plists were written fresh using the canonical osascript-wrapper pattern (matching the existing lunarcrush plist's style). The two root-level duplicates were moved into `launchd/` and the root copies deleted.

2. **`scripts/deploy.sh` extended to mirror plists.** New step 4b after the v2.6 guard: `cp launchd/*.plist ~/Library/LaunchAgents/`, with SHA drift detection and the same dry-run support as the Python sync. Reload loop now covers all 6 non-deploy agents (`morning premarket recap lunarcrush weekend_preview monitor`); the deploy plist itself is deliberately NOT reloaded by deploy.sh to avoid the script killing its own scheduler mid-run.

3. **Premarket exception handling narrowed.** The previous `try/except Exception` block wrapped AI generation + HTML formatting + text formatting together. A NameError in text formatting (the v2.7.3 bug) was reported as "AI brief failed", clobbered the AI-generated `html_email` to None, and silently degraded the premarket to legacy text-only. New structure: AI gen is its own try-block (legacy fallback only fires on AI failure); HTML formatting and text formatting are their own try-blocks (each preserves whatever upstream succeeded). Plus an explicit guard at the send step: if all three paths failed, log loudly and skip the send rather than passing `None` to the email client.

4. **`requirements.txt` created in Drive.** Was referenced by README but never existed in Drive (presumably lived only on the iMac, if at all). Pinned with lower bounds, not exact versions, so a `pip install -U -r requirements.txt` can safely bump patch and minor versions on routine refresh.

5. **Software currency audit** in `outputs/software_currency_audit_2026-05-23.md`. Headline: production iMac is on Python 3.9.6 (EOL since Oct 2025). Recommended target 3.11+ via Homebrew, in a maintenance window. yfinance has a major version available (0.2.x → 1.x) that needs deliberate review before bumping. Anthropic SDK is also worth bumping for Claude 4.x model strings.

6. **Docs updated comprehensively.** CLAUDE.md (agent inventory now reflects `launchd/` location and `requirements.txt`), SETUP.md (Sections 4–6 rewritten — the v2.5-era three-plist XMLs replaced with a single inventory table, a proper fresh-Mac install checklist using `scripts/deploy.sh --reload`, and a new Section 6 explaining multi-machine sync), README.md (existing).

**Why this matters (macro overlay).** The structural gap I'd been flagging for two sessions — plists only on the iMac — was actively blocking Jeff's three-machine workflow. He confirmed Drive is the bridge, which made this a goal (1) "keep informed" issue: he was relying on a multi-machine sync that wasn't actually multi-machine for schedule changes. Now it is. The premarket exception narrowing is a goal (2) "signal from noise" cleanup: a misleading "AI brief failed" error was masking a missing import, which is exactly the noise that erodes alert trust over time.

**Deferred (not blocking).** Vital Knowledge Gmail OAuth still not authorized (requires Jeff at the keyboard to authorize). Market snapshot N/A values (VIX/oil/gold/BTC/DXY) need a data-fetch expansion. Python 3.9 → 3.12 upgrade per the currency audit — scheduled for a maintenance window, not Monday morning.

**Deployment (important).** This is the first time `deploy.sh` will sync plists. To bring production into lockstep:
```bash
~/Claude/morning-briefing/scripts/deploy.sh --reload
```
That single command will: SHA-diff Python files, copy them if needed, run the v2.6 guard, mirror Drive `launchd/*.plist` → `~/Library/LaunchAgents/`, git commit + push, and reload all 6 non-deploy LaunchAgents. After it completes, all 7 plists in `~/Library/LaunchAgents/` will exactly match the ones in Drive — the single-source-of-truth state.

## Recent Changes (2026-05-23 — v2.7.3 dead-code cleanup + premarket import bug)

**Trigger.** v2.7.2 flagged `run_morning_briefing_v2()` in `morning_briefing_redesign.py` as deferred dead code with dangling `imessage_sent` NameError-bombs. Jeff asked for it cleaned up. While doing the cleanup I discovered a related live bug: `format_premarket_text` was called at `morning_briefing.py:4011` but never imported, so every weekday morning the premarket workflow has been silently NameError-ing into the legacy fallback path — clobbering the AI-generated HTML email and delivering a legacy text-only premarket instead. Goal (1) regression hiding in plain sight.

**Changes.**
1. **Deleted `run_morning_briefing_v2()`** (was `morning_briefing_redesign.py:1730-1809`) and its empty "5. MAIN ORCHESTRATION FUNCTION" section header. Zero callers — confirmed by grep before deletion.
2. **Deleted `format_morning_text()`** (was `morning_briefing_redesign.py:1596-1642`) and its stale "3. PLAIN TEXT FORMATTING FOR iMESSAGE" section header. Only caller was inside `run_morning_briefing_v2`, so orphaned by the deletion above. README's claim that it served as a "plain-text email fallback when HTML rendering fails" was incorrect — the real fallback for the live morning path is `format_briefing` and it's triggered on AI generation failure (not HTML rendering failure).
3. **Fixed premarket missing-import bug.** Added `format_premarket_text` to the `from morning_briefing_redesign import (...)` block at `morning_briefing.py:38`. After this, the premarket try-block at line 4004 no longer NameError-s, the `except` no longer fires erroneously, and `html_email` is no longer clobbered to None. Premarket now delivers the AI-editorial HTML brief as intended.
4. **Updated stale docstrings.** `morning_briefing.py` top-of-file docstring no longer says "Sends via iMessage at 5:30 AM PT" — replaced with email-only language and a full five-mode dispatcher inventory. Inline comments at lines 2906 and 2924 ("iMessage: only show material actions" / "Cap at 15 for iMessage") rewritten to reflect their actual purpose. `format_premarket_text` and `format_weekend_text` docstrings no longer call themselves "iMessage teasers" — they're identified as plain-text email fallbacks.

**Verification.** Both modules `py_compile` clean. Full module import passes — v2.6 guard does not fire. `format_morning_text` and `run_morning_briefing_v2` confirmed gone from both module namespaces. Live formatters (`format_premarket_text`, `format_weekend_text`, `format_recap_text`) still resolve. `format_premarket_text` confirmed present in `morning_briefing.py` namespace post-import — premarket NameError bug closed. Final iMessage residue check: `morning_briefing_redesign.py` and `briefing_monitor.py` now have **zero** iMessage references; `morning_briefing.py` retains only the v2.6 guard's own forbidden-symbol regex and a handful of intentional historical-context comments explaining why iMessage was removed.

**Why this matters (macro overlay).** The premarket bug is the cleaner illustration of why dead-code cleanup is a goal (1) discipline, not cosmetics: a half-deleted feature (iMessage send removed, but the parameter/structure scaffolding left behind) created a latent NameError that silently degraded the premarket brief from "AI-editorial HTML" to "legacy text-only" for an unknown number of weeks. If `run_morning_briefing_v2` had been fully removed in v2.6, the wiring confusion that left `format_premarket_text` unimported would never have happened. Lesson: when a feature gets removed, remove the scaffolding too, not just the call sites.

**Deployment.** Drive-side change. Reaches production via 4:50 AM Monday `com.briefing.deploy` auto-sync. For same-day effect: `~/Claude/morning-briefing/scripts/deploy.sh --reload` from Terminal. After this lands, expect Tuesday's premarket email to be the AI-editorial HTML brief (not the legacy text fallback) — that's the visible smoke test.

## Recent Changes (2026-05-23 — v2.7.2 LunarCrush → Sunday evening)

**Trigger.** Jeff flagged that LunarCrush had been firing weekday mornings (6:20 AM Mon–Fri) since launch, but the original intent was a Sunday-evening prep-for-the-week social/sentiment brief. The plist had drifted from intent; `CLAUDE.md` didn't mention LunarCrush at all (silently inflated the "six LaunchAgents" claim into seven without the doc catching up).

**Changes.**
1. **`com.briefing.lunarcrush.plist`** rewritten — single `StartCalendarInterval` at Sunday 5:30 PM PT (Weekday 0, Hour 17, Minute 30). Old five weekday-morning entries removed. Pairs with `weekend_preview` at 6:00 PM so the Sunday evening review lands as a complete two-part package: social/sentiment lens first, general weekly prep second.
2. **`briefing_monitor.py` → `_modes_for_current_time()`** updated. LunarCrush removed from the weekday 6–8 AM check. New rule: Sunday 17–20 → `["lunarcrush"]`; weekday 6–8 → `["premarket"]` only. Day-of-week awareness via `datetime.now().weekday() == 6`.
3. **`com.briefing.monitor.plist`** gained a Sunday 6:00 PM entry (Weekday 0, Hour 18, Minute 0) so the watchdog actually fires on Sunday evening to validate the LunarCrush brief delivered.
4. **`CLAUDE.md`** rewritten — corrected agent count (six → seven), added LunarCrush to the schedule table, added an explicit "macro frame" paragraph at the top, added v2.7.1/v2.7.2 to the safety rails, and flagged the structural gap that only 3 of 7 plists live in Drive.
5. **Sample outputs** generated in `outputs/`: `lunarcrush_sample_sunday_evening.html` shows what the new Sunday LC email will look like; `monitor_before_after_sample.html` shows the false-positive that landed Friday vs the silence that will now follow.

**Why this matters (macro overlay).** Two structural patterns this fix addresses: (1) intent drift — a feature ships, intent gets lost, no doc catches it; (2) silent feature growth — agents added without updating the inventory. Both work against goal (1) "stay fully informed" because they erode the user's mental model of what the system is doing on his behalf. Going forward, any schedule change requires a paired update to the plist AND `_modes_for_current_time()` AND the CLAUDE.md schedule table.

**Deferred items from v2.7.2 are now closed in v2.7.3** — see the v2.7.3 entry above. `run_morning_briefing_v2()` and `format_morning_text()` deleted; `format_premarket_text` / `format_weekend_text` docstrings corrected.

**Deployment.** Drive-side change; reaches production via 4:50 AM Monday `com.briefing.deploy` auto-sync. **Important:** `deploy.sh` only syncs the three plists currently mirrored in Drive (deploy, monitor, lunarcrush). For same-day effect, run `~/Claude/morning-briefing/scripts/deploy.sh --reload` from Terminal — that will reload all loaded LaunchAgents including the updated lunarcrush + monitor plists.

## Recent Changes (2026-05-23 — v2.7.1 monitor false-positive fix)

**Trigger.** User received a monitor email reading `MORNING: stale — Log is 7h 30m old (max 3h for this workflow)` alongside `RECAP: warning · stderr: ['BRKB']: possibly delisted; no price data found`. Both were false positives.

**Root causes.**
1. **One CLI invocation for three different watchdog times.** `com.briefing.monitor.plist` fires at 5:10 AM, 6:30 AM, and 1:25 PM, but all three invocations called `briefing_monitor.py all`, which validates every workflow's log against its `WORKFLOW_MAX_AGE_HOURS`. Morning's max is 3h — correct for the 5:10 AM check, but by 1:25 PM the morning log is ~8h old, so the recap-check run always flagged morning as stale. Recurring daily noise.
2. **Yahoo "possibly delisted" wording wasn't in the noise filter.** `KNOWN_NOISE_PATTERNS` caught `"Quote not found for symbol:"` but not `"possibly delisted; no price data found"`. BRKB (Berkshire B) is not delisted; Yahoo flakes on it intermittently.

**Changes.**
1. **`_modes_for_current_time()` in `briefing_monitor.py`.** Returns the workflow(s) the monitor should check based on local hour: 5-6 → morning; 6-8 → premarket + lunarcrush; 13-15 → recap; else all four. Single source of truth for the dispatch table.
2. **`--by-time` CLI flag in `briefing_monitor.py`.** `main()` calls `_modes_for_current_time()` when invoked with `--by-time`; `all` and explicit workflow names still work unchanged. `main()` also now accepts multiple workflow names as positional args.
3. **`com.briefing.monitor.plist` now passes `--by-time`** instead of `all`. Each scheduled run validates only the workflow that just fired.
4. **Added `"possibly delisted; no price data found"`** to `KNOWN_NOISE_PATTERNS` so the BRKB transient stops surfacing as a warning.

**Why this matters.** Monitor noise is corrosive — once alerts are routinely false, real alerts get ignored. This was firing every weekday at 1:25 PM (and on Fridays the email was sitting unread Saturday morning, which is when the user spotted it). The fix collapses the alert surface to "something actually went wrong with the workflow that just ran."

**Deployment.** Drive-side change; will reach production via the 4:50 AM Monday `com.briefing.deploy` auto-sync, which reloads all six LaunchAgents (picking up the new plist). For immediate effect, run `~/Claude/morning-briefing/scripts/deploy.sh --reload` from Terminal.

## Recent Changes (2026-05-22 — v2.7 stale-lead + bearish-hyperbole fix)

**Trigger.** 2026-05-22 morning brief led WHAT MATTERS with an 11-day-old HIMS earnings miss (date 2026-05-11, days_since=11), framed as "catastrophic" and citing a sign-flip-artifact `-1433.3%` surprise. Three failure modes stacked:

1. **Soft freshness rule.** v2.6 put `days_since` on each scorecard record as a numeric field. With a quiet tape (zero >3% pre-market movers) and a fresh BofA HIMS downgrade in `analyst_actions`, the AI used the rating change as a "current hook" to re-litigate the stale print as the lead. The numeric field was easy to overlook in a payload of dozens of rows.
2. **Asymmetric forbidden-words list.** Voice rules covered bullish hyperbole ("surge," "soar," "rocket") but not bearish ("catastrophic," "collapse," "breakdown"). "Catastrophic" walked right through.
3. **Sign-flip precision laundering.** When EPS goes from a positive estimate to a negative actual, `surprise_pct` from yfinance becomes a near-zero-denominator artifact (-1433.3% here). The AI quoted it as if it were a magnitude claim.

**Changes.**
1. **Payload-level stale tag** (`_build_ai_payload` in `morning_briefing_redesign.py`). For every scorecard row with `days_since > 1`, the row is now prefixed with `[STALE: Nd ago — CONTEXT ONLY, DO NOT LEAD]` before the BEAT/MISS tag. String-level label — harder to ignore than a numeric field.
2. **Payload-level sign-flip suppression.** When EPS estimate and actual have opposite signs, OR `|surprise_pct| > 200`, the % is replaced with `(sign flip — % surprise not meaningful)`. The absolute EPS values are still shown.
3. **Prompt: v2.7 fresh-hook-on-stale-print rule.** Explicit anti-pattern: a fresh analyst action referencing a stale print does NOT make the print fresh. Lead with the rating change and its tape reaction, not the underlying print. Quiet-morning escape valve: "no same-day name-specific catalyst" is a valid lead — naming the quiet beats manufacturing drama.
4. **Prompt: v2.7 sign-flip precision rule.** When estimate ≥ 0 and actual < 0 (or vice versa) or `|surprise_pct| > 200`, do not cite the percentage. Quote absolute EPS.
5. **Prompt: bearish-hyperbole forbidden words.** Added "catastrophic," "catastrophe," "collapse(d/ing)," "breakdown," "disaster(ous)," "carnage," "bloodbath," "implosion/implodes/imploded," "death spiral," "annihilated," "decimated" to the forbidden list — mirrored across all four prompts (morning, recap, premarket, weekend).

**Why this matters.** v2.6 was an anti-drift release (Drive ↔ prod sync). v2.7 is an anti-stale-lead release (don't elevate history into the lead even when fresh ambient signal makes it plausible). The two together: production code is current AND it can't dress up history as today's news.

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
