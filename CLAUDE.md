# Morning Briefing — Read This First

**What this is.** Email-only AI editorial market brief, runs on Jeff's iMac via launchd. Six LaunchAgents fire weekday mornings (4:50 deploy / 5:00 morning / 6:20 premarket), midday (1:15 recap), evening on Sundays (6:00 weekend_preview), plus a monitor watchdog. v2.6 hardened against deploy-drift on 2026-05-19; no iMessage path anywhere.

**Canonical files.**
- `morning_briefing.py` — main script. Hosts `_v2_6_guard()` (import-time anti-regression) and `days_since` enrichment.
- `morning_briefing_redesign.py` — AI editorial briefs + HTML email + plain-text email fallback. `BRIEFING_SYSTEM_PROMPT` carries the v2.6 freshness rule.
- `briefing_monitor.py` — log health monitor with `check_deploy_freshness()` drift alarm.
- `scripts/deploy.sh` — the only correct way to push code Drive → production.
- `launchd/*.plist` — six agents. Source of truth for the schedule.
- `PROJECT_STATE.md` — current state, changelog, deferred items.
- `README.md` — quick operations reference.
- `SETUP.md` — cold-rebuild guide for a new Mac.

**Where things actually live (this catches people).**
- Production tree: `~/Claude/morning-briefing/` on `Jeffs-iMac`. This IS the git working tree for `github.com:jvs-wq/morning-briefing` `main` branch.
- Drive edit surface: `~/My Drive/Claude-Workspace/Claude Projects/Morning Briefing/` — local-only, NOT Google Drive sync.
- Real Drive sync (stale): `~/Library/CloudStorage/GoogleDrive-jeffstclaire@gmail.com/My Drive/.../Morning Briefing/` — flagged for separate follow-up.

**Deploy mechanic.** Edit in Drive. `com.briefing.deploy` LaunchAgent at 4:50 AM Mon–Fri runs `scripts/deploy.sh --reload`: SHA-diffs Drive vs production → `py_compile` validation → copies if drift → runs the v2.6 guard → `git add -A`, commit, `git push origin main` → unloads + loads all six LaunchAgents. For emergency same-day deploys, run `~/Claude/morning-briefing/scripts/deploy.sh --reload` from Terminal.

**Smoke test before claiming 'work is done'.**
```
osascript -e 'do shell script "cd ~/Claude/morning-briefing && /usr/bin/python3 -c \"import morning_briefing\" && launchctl list | grep briefing"'
```
Expect: zero errors, six `com.briefing.*` lines. If the guard fires, fix the regression before doing anything else.

**Safety rails.**
- `_v2_6_guard()` exits 99 on import if `send_imessage`, `IMESSAGE_RECIPIENT`, or `_chunk_message` reappears. Never bypass — re-run `migrations/v2_6_imessage_removal_and_safeguards.py` to re-strip.
- `check_deploy_freshness()` in monitor emails an alert if production SHAs diverge from Drive. If you see that alert twice running, the 4:50 AM auto-sync is broken — check `/tmp/briefing-deploy.log`.
- Pre-v2.6 backup at git tag `pre-imessage-removal-20260519-0553` and branch `backup/pre-imessage-removal`.

**Recent changelog.** See `PROJECT_STATE.md` for full history. Last three commits on main: `cf4b189` (v2.6.2 monitor reorder), `e1a8fbe` (v2.6.1 dangling imessage_success fix), `05c4653` (v2.6 anti-drift hardening).
