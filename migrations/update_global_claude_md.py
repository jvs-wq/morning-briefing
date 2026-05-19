#!/usr/bin/env python3
"""Append the v2.6 anti-drift rules to Jeff's global CLAUDE.md.

Idempotent: refuses to re-append if the marker section is already present.
"""
from __future__ import annotations
from pathlib import Path

P = Path("/var/folders/f5/fccjlcmj5yl_q97g9y4db2940000gn/T/claude-hostloop-plugins/2186468faf5f1fbc/CLAUDE.md")

ADDITION = """

**Working on production projects (Morning Briefing, 13F Update, BCM Trading Platform, BCM Valuation, lunarcrush-brief, and anything that runs locally on the iMac)**

- Before proposing changes, running migrations, or claiming work is done: read `PROJECT_STATE.md`, `README.md`, `SETUP.md`, and any `CLAUDE.md` in the working folder. If the folder is a git repo, also run `git log --oneline -10`. Don't infer state from modification dates — read content. If sources disagree: most recent git commit beats Drive timestamps beats your memory.

- Drive folders and production trees are not the same filesystem. Any project that runs in production via launchd or cron has two filesystems that drift independently. Production lives at `~/Claude/<project>/` (git working trees). The Drive edit surface at `~/My Drive/Claude-Workspace/Claude Projects/<project>/` is local-only — it is NOT Google Drive sync. The real Drive sync at `~/Library/CloudStorage/GoogleDrive-jeffstclaire@gmail.com/My Drive/` is currently stale relative to `~/My Drive/`. SHA-compare both before any 'work is done' claim.

- On the iMac (`Jeffs-iMac`), reach for `mcp__Control_your_Mac__osascript` proactively to inspect production state — `launchctl list`, `git status` in `~/Claude/<project>/`, grep production source files. Don't rely on Drive-folder reads alone when production is reachable via shell. The same applies to `mcp__computer-use__*` when a native app needs driving.

- Before declaring 'work is done' on a production system: run the project's smoke test (defined in `PROJECT_STATE.md`, or end-to-end against real inputs if not defined). 'File edited' is not proof of work. For Morning Briefing the smoke test is `cd ~/Claude/morning-briefing && /usr/bin/python3 -c "import morning_briefing" && launchctl list | grep briefing` — expect zero errors and six `com.briefing.*` lines.

- When a deploy is needed, prefer automation over manual `cp`. Most production projects have a `scripts/deploy.sh` and a `com.<project>.deploy.plist` LaunchAgent that auto-syncs Drive→production. If a project lacks one, propose adding it before doing more manual sync work.
"""

src = P.read_text(encoding="utf-8")
marker = "Working on production projects"
if marker in src:
    print("Section already present — skipping append")
else:
    new_src = src.rstrip() + "\n" + ADDITION
    P.write_text(new_src, encoding="utf-8")
    print(f"Appended {len(ADDITION)} bytes to {P}")
    print(f"File now {P.stat().st_size} bytes")
