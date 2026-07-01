# Morning Briefing — Project State

**Last updated:** 2026-07-01
**Status:** Production. **v2.8.1 — Upcoming Earnings section now always visible (2026-07-01).** The morning HTML brief already fetched a 7-day upcoming-earnings calendar, but the structured "Upcoming Earnings Calendar" appendix block was gated `if earnings:` and the whole appendix table was only invoked `if scorecard or earnings` — so in a quiet week (e.g. the current early-July off-season) the section silently vanished. It now always renders as **"Upcoming Earnings Calendar (Next 7 Days)"** with an explicit *"No portfolio holdings report in the next 7 days."* note when the calendar is empty. Prior: **v2.8 readability + visual-identity pass (bullets, Charter typeface, black ticker boxes) was DEPLOYED to prod 2026-06-26 ~06:16** via `deploy.sh --reload` (SHA-diff → py_compile → v2.6 guard passed → committed + pushed to `origin/main` → all agents reloaded). A live morning brief was then run manually and **delivered from Apple Mail to jvs@blumecapital.com at 06:22** (exit 0, 41KB HTML, real market data); the 06:20 scheduled premarket agent also fired on the new code. v2.7.5 model-currency fix + retired-model guard remains LIVE. Two audits (news-source freshness, API efficiency) completed 2026-06-26 — findings below carry open recommendations still NOT implemented.

### Changelog — 2026-07-01 (v2.8.1 — Upcoming Earnings section always visible)
**Trigger.** Jeff asked to make sure the morning briefing has a section for upcoming earnings, roughly a week in advance.
**Finding.** The data plumbing already existed: `fetch_finnhub_earnings` uses a 7-day horizon and the result reaches the HTML email both as AI prose (Section 4, "Earnings Intelligence") and as a structured appendix table. The gap was visibility — the structured "Upcoming Earnings Calendar" block in `morning_briefing_redesign.py:_format_full_earnings_table` was gated `if earnings:`, and the appendix call site was gated `if scorecard or earnings`, so an off-season week with no reporters dropped the section entirely.
**Change** (`morning_briefing_redesign.py`, per Jeff's "keep in appendix, always show" choice):
- The "Upcoming Earnings Calendar" block now **always renders**, retitled **"Upcoming Earnings Calendar (Next 7 Days)"** to make the horizon explicit.
- Empty calendar prints *"No portfolio holdings report in the next 7 days."* instead of disappearing.
- Call site simplified to invoke `_format_full_earnings_table(scorecard, earnings)` unconditionally (dropped the "No earnings data available" fallback that suppressed the whole appendix block).
**Verified.** `py_compile` clean; unit-tested both branches (empty week → header + "none" note; populated week → header + ticker rows, no note). No horizon change (already 7 days); no new API calls.

### Changelog — 2026-06-26 (v2.8 — readability, Charter typeface, ticker-box restyle + two audits)
**Trigger.** Jeff asked to (1) make the briefs faster to visually digest, (2) move to a monospace "wire/telegraph" identity, (3) restyle the ticker boxes, and (4) double-check news-source freshness and API efficiency before a re-run.

**Changes (all in `morning_briefing_redesign.py`, Drive edit surface).**
1. **Hybrid bullet formatting across all four briefs (morning, premarket, recap, weekend).** Lead sections (`what_matters` / `closing_pulse` / `open_signal` / `weekend_takeaway`) now open with one `<strong>` takeaway sentence, then a `<ul>` of 2–4 bullets. The list-shaped sections (movers, earnings, news, watch/tomorrow) render as one `<li>` per item. The short macro/context sections stay prose. Each `<li>` is required to remain a complete buy-side thought (magnitude + mechanism + portfolio impact) — bullets replace paragraph breaks, not the reasoning. Implemented at the prompt level (an `OUTPUT FORMATTING` hard-rule block was appended to all four system prompts) plus two render helpers: `_style_bullets()` injects Outlook-safe inline styles into the AI-emitted `<ul>/<li>`, and `_html_to_text()` flattens those bullets to plain-text `•` lines for the text-email fallback so raw tags never leak.
2. **Font → Charter (single typeface).** All prose, headers, data tables, labels, and the masthead now use `font-family: Charter, Charter BT, Iowan Old Style, Palatino Linotype, Georgia, serif` (unquoted family names — deliberate, to avoid clashing with both Python single-quoted string literals and HTML double-quoted `style` attributes). Charter is **Apple-native**, so it renders with no embedding in Apple Mail (Jeff's reader); non-Apple clients fall back through Iowan Old Style → Palatino Linotype → Georgia — all readable serifs, so the editorial character holds across clients. No webfont `@import` needed. **Exploration note:** IBM Plex Mono (full-mono, wire/telegraph identity) was trialed first via an embedded Google-Fonts `@import`; Jeff moved to Charter for readability. If the mono direction is revisited, the swap is a single global replace of the font stack plus re-adding the `@import`.
3. **Ticker-box restyle — now applied to ALL data tables (conformed 2026-06-26 at Jeff's request).** Every table header that used the dark-tan fill (`#ebe7e1`) is now black (`#1a1a1a`) with white text plus a `border-top: 3px solid #c0392b` red accent, matching the masthead. This covers all 13 such tables across the four briefs: morning Market Snapshot + Pre-Market Movers + the appendix tables (full earnings, analyst actions); recap close/movers/after-hours-reported/after-hours-pending/52-week/RSI; and premarket "Still to Report"/"Just Printed"/movers. (Earlier hierarchy idea of keeping appendix tables tan was overridden — Jeff wanted uniform conformance.) The dark-tan header fill is fully retired; zero `#ebe7e1` remain. **This box-conform pass is in the Drive edit surface and NOT yet deployed** (the morning brief sent at 06:22 predates it) — push with `deploy.sh --reload` to make it live.

**Audit 1 — news-source freshness (findings; recommendations NOT yet implemented).**
- **Single, fragile source.** All four briefs get news from one place: the Yahoo Finance RSS headline feed (`finance.yahoo.com/rss/headline?s=...`, `fetch_yahoo_news` / `fetch_ticker_news`). This is an undocumented, unsupported endpoint; a live probe on 2026-06-26 (single-ticker and multi-ticker) returned empty. The code already documents that adjacent Yahoo endpoints are dead ("Yahoo v10 quoteSummary returns 401"); the news feed is the same class of dependency. The comma-joined ~80-ticker query is exactly the form Yahoo serves least reliably.
- **No recency filter anywhere.** `filter_news_with_ai` judges relevance/category only; the `published` date is fetched but never used. A multi-day-old headline can surface as today's NEWS SIGNAL — inconsistent with the earnings `days_since` freshness discipline invested in v2.6/v2.7.
- **Silent-degradation risk.** If Yahoo returns empty, the news section just goes quiet — there is no "source returned 0 items" alarm (unlike the loud model-retired guard). Same failure-mode class the model-currency guard was built to kill.
- **Recommendation.** Migrate news to **Finnhub company-news** (`/company-news?symbol=X&from=&to=`) — the Finnhub key is already configured and used for earnings — with a hard published-date window (e.g. trailing 48–72h), optionally add Finnhub `/news?category=general` for macro, and add an empty-source warning banner mirroring the retired-model guard. This fixes freshness, adds real recency filtering, and consolidates onto an API already paid for.

**Audit 2 — API efficiency (findings; recommendations NOT yet implemented).**
- **Biggest drag: full-book per-symbol verification.** `verify_portfolio_closes` (and `verify_market_close_indices`) loop the entire holdings universe (~74) calling Finnhub `/quote` one symbol at a time with `time.sleep(1.1)` between calls — ~80s of serial sleeping and ~74 calls every run, purely to cross-check prices already fetched in bulk from yfinance. Recommend scoping the Finnhub cross-check to the names that actually appear in the brief (top movers + gainers/losers shown + indices), not the whole book — cuts the call count and runtime by roughly an order of magnitude.
- **Redundant per-ticker news fetches.** `explain_earnings_misses` (and a second loop) call `fetch_ticker_news(symbol)` per name — separate Yahoo RSS round-trips that duplicate the bulk `fetch_yahoo_news`. Folding news onto Finnhub company-news (Audit 1) lets these reuse one fetched corpus.
- **What's already good.** The earnings cascade is well-built: Finnhub first, then only still-missing tickers fall through to yfinance, then only still-missing to Alpha Vantage — no redundant full-universe calls; dead endpoints (FMP analyst-estimates 402, Yahoo v10 401) are correctly skipped. yfinance pre/post-market pulls are batched. LunarCrush is rate-limited by design and Sunday-only.

**"Re-run a new batch" — what was and wasn't possible.** A true live-data batch cannot run from the Cowork sandbox: production API keys live only in `~/Claude/morning-briefing/.env` (not in Drive), and the send path is Apple Mail via `osascript` (macOS-only). What was produced instead: a faithful **sample render** of the morning brief with representative data (`outputs/sample_morning_brief_v2_8_charter_2026-06-26.html` + a copy at the project root; an earlier `…_plexmono_…` sample captures the trialed mono look) showing the new font, bullets, and black ticker boxes. For a real live batch, run `~/Claude/morning-briefing/scripts/deploy.sh --reload` on the iMac (syncs v2.8 to prod) then let the 5:00 AM agent fire, or run the morning workflow manually on the iMac. On 2026-06-26 an updated sample was also delivered as a **Gmail draft** (via the Gmail connector — no live-send capability, so a draft Jeff opens/sends himself) so the Charter rendering can be eyeballed in Apple Mail.

**Lesson — label sample renders.** A mock UBER "BEAT" line in an earlier sample was mistaken for a real report (Uber actually last reported 2026-05-06 Q1, ~51 days out — outside the 28-day scorecard window, so the live pipeline would never have surfaced it). Going forward, any sample/preview render carries a loud `DESIGN SAMPLE — not live market intelligence` banner and avoids asserting specific real-world earnings events. Better still, wire realistic in-window data into sample renders so previews can't mislead.

**Validated.** `morning_briefing.py`, `morning_briefing_redesign.py`, `briefing_monitor.py` all `py_compile` clean. Sample render asserts the unquoted Charter stack, the black header rows, the red top accent, styled `<ul>/<li>`, and zero leftover `IBM Plex Mono`/`Arial` references (`Georgia` remains intentionally, as the universal-fallback tail of the Charter stack). Model ID unchanged at `claude-sonnet-4-6`.

**Deploy.** Drive-side change; reaches prod via the 4:50 AM weekday `com.briefing.deploy` auto-sync, or immediately via `scripts/deploy.sh --reload` on the iMac.

### Changelog — 2026-06-23 (v2.7.5 — model-currency fix + retired-model guard)
- **Root cause.** The AI model was pinned to `claude-sonnet-4-20250514` (Sonnet 4) in 7 spots across `morning_briefing.py` (3) and `morning_briefing_redesign.py` (4). That model **retired on 2026-06-15**; from 6/15 onward every AI call returned HTTP 404 `not_found_error`, so all AI features silently fell back. The visible symptom was the FILTERED NEWS section rendering every item as `[???]` / `FYI` — the signature of `filter_news_with_ai`'s fallback path. The same 404 also degraded the brief narrative, miss explanations, and guidance analysis.
- **Fix 1 — model refresh.** All 7 occurrences swapped to `claude-sonnet-4-6` (current, same tier, official drop-in replacement). Verified with a live API call (`stop_reason: end_turn`) and a live `filter_news_with_ai` test returning real tickers/categories (`PLTR` / `URGENT`). Checked: no breaking 4.6 params in use (no `temperature`/`top_p`/`budget_tokens`/prefills).
- **Fix 2 — retired-model guard (so this never silently recurs).** Added `is_model_retired_error()` + `warn_if_model_retired()` to `morning_briefing.py`. Every AI `except` block (filter, misses, guidance, and the 4 redesign brief functions via a lazy `_warn_if_model_retired` wrapper that dodges the circular import) now prints an unmissable `!!!! MODEL RETIRED OR INVALID` banner naming the fix when it sees a 404 model error.
- **Fix 3 — visible degradation, no more cryptic `[???]`.** The `filter_news_with_ai` fallback now prepends a `SYSTEM` / `URGENT` banner item ("⚠️ AI news categorization unavailable — …; update the model ID") so the degraded state leads the briefing instead of hiding as `[???]`. Degraded rows now carry `—` instead of `???`, and the 4 render-time `item.get("ticker", "???")` defaults were changed to `—`. Zero `"???"` literals remain in either tree.
- **Why this matters.** A pinned model ID is a time bomb — it works until the model retires, then fails silently and looks like a rendering bug. The guard converts that failure mode into a loud, self-documenting alarm in the run log and the briefing itself. **The next time a model retires, the fix is named on screen.** Forward note: `claude-sonnet-4-6` will itself retire eventually; the guard will say so.
- **Validated.** Both modules `py_compile` clean (prod + Drive); simulated-404 test confirms the banner fires and the fallback returns the visible `SYSTEM` tag with no `[???]`; non-model errors correctly do *not* raise a false "retired" claim; redesign lazy wrapper imports without circular-import error. Drive == prod for both `.py` files.

### Changelog — 2026-06-20 (personal-book refresh)
- **Personal side re-ingested** from `SummPosn_Grp_JVS_Portfolio_062026.csv` (full personal book, as-of 06/19 close, 61 equities + 6 ETFs; mutual funds DODFX/SGOIX and options excluded per scope; no zero-qty rows).
- **Net personal diff vs 6/6:** +LBRDK (Liberty Broadband C, 495 sh). −CHTR, −MSGS, −SU (sold out of personal book; none were in the firm top-30, so they drop from the universe entirely).
- **Firm top-30 NOT refreshed.** Jeff supplied only the personal CSV this cycle. Firm contribution carried over unchanged from the 2026-06-05 `SummPosn_Mast_8000075_060526.csv` to avoid re-deriving the top-30 from a stale file. Re-run the full recipe when a fresh firm MASTER CSV is supplied.
- **New universe:** 68 stocks + 6 ETFs = 74 total (was 76).
- Validated: `py_compile` clean; AST check confirms 68/6 with zero duplicates, the three sells removed, LBRDK added, firm-only names intact. Source CSV copied into the project folder.

### Changelog — 2026-06-06 (holdings refresh)
- **CONFIG holdings re-ingested** using the established 6/4 recipe: full personal book (`SummPosn_Grp_JVS_Portfolio_060626.csv`, as-of 06/05 close) ∪ firm MASTER top-30 equities by market value (`SummPosn_Mast_8000075_060526.csv`). Firm ETFs and sub-top-30 firm names remain out of scope. New rule applied: zero-quantity personal rows excluded.
- **Net diff vs 6/4:** +TMUS (new personal position, 45 sh). −FDXF and −VBIL (both zero-quantity in the personal book; firm VBIL is an ETF and out of scope; firm FDXF ~$2.5M is sub-top-30). Now 70 stocks + 6 ETFs = 76 total (was 77).
- **Firm top-30 churn (no universe impact):** DE fell below the firm top-30 cutoff (#31, $4.48M vs JPM's $5.18M at #30) but stays in the universe via the personal book. The both/personal-only annotations in CONFIG reflect 6/4 overlap groupings; membership is what matters functionally.
- Validated: `py_compile` clean; AST check confirms 70/6 with zero duplicates and exact match to the computed union. Source CSVs copied into the project folder. **Deployed 2026-06-06** via `scripts/deploy.sh --reload` — Drive→prod synced, committed + pushed to `origin/main`, all five briefing LaunchAgents reloaded (no longer waiting on the Monday 6/8 auto-sync).

### Changelog — 2026-06-04 (holdings refresh)
- **CONFIG holdings re-ingested.** `INDIVIDUAL_STOCKS` + `ETFS` rebuilt from `SummPosn_Grp_JVS_Portfolio_060426.csv` (full personal book, 63 stocks + 7 ETFs) ∪ `SummPosn_Mast_8000075_06042026.csv` (firm MASTER account — **top 30 equity positions by market value only**, per Jeff's instruction). Firm contribution is now capped at the 30 largest stocks; firm ETFs (AKRE, IBB, VDE, VGHAX, XLE) and sub-top-30 firm names are intentionally out of scope.
- **Net:** 70 stocks (count unchanged, composition changed) + 7 ETFs = 77 total (was 84). Stocks added: CHTR, DVN, FDXF, IPWR, LPKFF, MDT, POWI, SOLS, SU, ZBH. Stocks dropped: BMNR, COST, CVS, IFF, NU, SLB, TROW, UNP, VSNT, VWAPY (none in fresh personal book or firm top-30). ETFs added: VBIL; dropped: AKRE, DFAS, DVYE, IBB, UVXY, VDE, VGHAX, XLE.
- Validated: `py_compile` clean; AST extract confirms 70/7 with no duplicates. **Not committed/pushed** from this session — left for the normal deploy mechanic. The two source CSVs live in the synced Google Drive project folder, not the local-only edit-surface mirror.
- Produced a same-day one-off brief from the new universe: `Morning_Brief_2026-06-04.html`.

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
| `com.briefing.*.plist` | `launchd/` (canonical, Drive) + `~/Library/LaunchAgents/` (mirrored by deploy.sh) | Seven LaunchAgents (see above) |

### Deploy workflow (going forward)
1. User edits files in Drive folder via Cowork (`~/My Drive/Claude-Workspace/Claude Projects/Morning Briefing/`).
2. `com.briefing.deploy` fires at 4:50 AM Mon–Fri: SHA-diffs Drive vs prod, copies Drive→prod if drift, py_compile validates, runs v2.6 guard, mirrors `launchd/*.plist` → `~/Library/LaunchAgents/` (v2.7.4), commits + pushes to `origin/main`, reloads the six non-deploy LaunchAgents (deploy never reloads itself).
3. `com.briefing.morning` fires at 5:00 AM running the fresh code.
4. `com.briefing.monitor` at 5:10 AM verifies success AND re-runs the drift check; emails alert on any failure or drift.
5. If a fix can't wait until tomorrow morning, run `~/Claude/morning-briefing/scripts/deploy.sh --reload` from Terminal — same flow, immediate.

## Open Questions
- Should the daily auto-sync also push notifications to the other two synced machines? (Jeff confirmed 2026-05-23 that `~/My Drive/` IS the bridge across the three machines, but sync has only been verified informally — see Known Gaps.)
- Is Python 3.9 → 3.12 upgrade worth the risk of breaking other scripts on the iMac?
- Worth expanding market snapshot to include VIX / oil / gold / BTC / DXY?

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-19 | v2.6: auto-sync Drive→prod + import-time guard + drift alarm | Recurring deploy-drift bug — solve structurally, not via discipline. |
| 2026-05-19 | Production is canonical git working tree; Drive is edit-surface mirror | Avoids the "Drive is canonical but lacks recent prod commits" trap. |
| 2026-05-19 | `format_morning_text()` survives as email plain-text fallback | Useful even without iMessage; HTML-render-failure backstop. **Reversed in v2.7.3 (2026-05-23): deleted — the real live fallback is `format_briefing` on AI-generation failure.** |
| 2026-05-18 | Email-only dispatch (no iMessage) | iMessage delivery flaky and noisy; HTML email proven reliable. |
| 2026-04-06 | v2 redesign: AI editorial brief | Old format was a data dump with gaps. |
| 2026-04-06 | Use Claude Sonnet for brief generation | Faster + cheaper for daily automation; quality sufficient. |
