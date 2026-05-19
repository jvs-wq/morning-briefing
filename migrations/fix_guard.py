#!/usr/bin/env python3
"""Fix the v2.6 guard in morning_briefing.py — block-aware filter."""
from __future__ import annotations
import re
from pathlib import Path

P = Path.home() / "Claude" / "morning-briefing" / "morning_briefing.py"
src = P.read_text(encoding="utf-8")

# Remove the existing safeguard block entirely
src = re.sub(
    r"\n# === v2\.6 safeguard: anti-regression guard ===\n.*?# === end v2\.6 safeguard ===\n",
    "\n",
    src,
    flags=re.DOTALL,
)

# Cleanly written replacement using triple-quoted helpers
GUARD = '''
# === v2.6 safeguard: anti-regression guard ===
# Refuses to run if any iMessage symbol reappears.  This blocks the
# May-2026 deploy-drift regression at its source: if a future edit
# reintroduces send_imessage, IMESSAGE_RECIPIENT, _chunk_message, or
# format_morning_text-sent-via-imessage, the script exits 99 before
# any data fetch or email send.
def _v2_6_guard() -> None:
    import os, re, sys
    me = os.path.abspath(__file__)
    here = os.path.dirname(me)
    suspects = [
        os.path.join(here, "morning_briefing.py"),
        os.path.join(here, "morning_briefing_redesign.py"),
        os.path.join(here, "briefing_monitor.py"),
    ]
    forbidden = re.compile(r"\\b(send_imessage|IMESSAGE_RECIPIENT|_chunk_message)\\b")
    block_re = re.compile(
        r"# === v2\\.6 safeguard.*?# === end v2\\.6 safeguard ===",
        re.DOTALL,
    )
    for path in suspects:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            txt = fh.read()
        clean = block_re.sub("", txt)
        m = forbidden.search(clean)
        if m:
            sys.stderr.write(
                "\\n[v2.6 GUARD] iMessage symbol '%s' reappeared in %s.\\n"
                "Refusing to run.  See migrations/v2_6_imessage_removal_and_safeguards.py.\\n\\n"
                % (m.group(0), path)
            )
            sys.exit(99)


_v2_6_guard()
# === end v2.6 safeguard ===
'''

# Find a good insertion point: right after the last top-level import.
lines = src.splitlines(keepends=True)
last_import_idx = -1
for i, ln in enumerate(lines):
    if ln.startswith(("import ", "from ")):
        last_import_idx = i
if last_import_idx < 0:
    raise SystemExit("No imports found — refusing to inject guard blindly")

new_src = "".join(lines[: last_import_idx + 1]) + GUARD + "".join(lines[last_import_idx + 1 :])
P.write_text(new_src, encoding="utf-8")
print(f"Reinjected v2.6 guard after line {last_import_idx + 1}")
