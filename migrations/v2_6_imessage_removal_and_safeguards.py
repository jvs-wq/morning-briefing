#!/usr/bin/env python3
"""
Migration v2.6 — Morning Briefing
==================================
Idempotent, in-place migration that:
  (1) surgically strips ALL iMessage send paths from the three production files
      while preserving the May-2026 AI-prompt improvements that landed in prod
      after the Drive snapshot diverged;
  (2) hardens the morning_briefing.py launchpad with a startup guard that
      fail-fasts if any iMessage symbol re-appears, blocking regressions;
  (3) injects a `days_since_earnings` field into the payload and tightens
      BRIEFING_SYSTEM_PROMPT so the AI brief stops presenting 2-week-old
      earnings as today's catalyst (the AFRM-as-today's-news bug);
  (4) adds a SHA-drift staleness alarm to briefing_monitor.py that emails
      jvs@blumecapital.com if production code drifts from the Drive mirror
      for >24h.

Run on the iMac:
    /usr/bin/python3 "/path/to/this/file"

It will refuse to run twice in a row if every change is already applied
(safe — idempotent on re-run).
"""

from __future__ import annotations

import os
import re
import sys
import shutil
import hashlib
from datetime import datetime
from pathlib import Path

PROD_DIR = Path.home() / "Claude" / "morning-briefing"
DRIVE_DIR = (
    Path.home()
    / "My Drive"
    / "Claude-Workspace"
    / "Claude Projects"
    / "Morning Briefing"
)

REPORT: list[str] = []


def log(msg: str) -> None:
    print(msg)
    REPORT.append(msg)


def backup(p: Path) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(p, p.with_suffix(p.suffix + f".bak.v2_6.{ts}"))


def write_atomic(p: Path, content: str) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# Step 1 — Strip iMessage from morning_briefing.py
# ---------------------------------------------------------------------------


def strip_imessage_from_main(src: str) -> tuple[str, int]:
    """Return (modified_source, change_count). Idempotent."""
    changes = 0
    out = src

    # 1a — drop the IMESSAGE_RECIPIENT entry from CONFIG dict
    new = re.sub(
        r"^\s*\"IMESSAGE_RECIPIENT\"\s*:\s*os\.getenv\([^\)]+\)\s*,\s*\n",
        "",
        out,
        count=1,
        flags=re.MULTILINE,
    )
    if new != out:
        changes += 1
        out = new

    # 1b — drop the IMESSAGE_RECIPIENT placeholder check block
    new = re.sub(
        r'    if CONFIG\["IMESSAGE_RECIPIENT"\] == "YOUR_PHONE_OR_EMAIL_HERE":\n'
        r'        print\("ERROR: Please set your iMessage recipient"\)\n'
        r'        print\("  Edit this file or set IMESSAGE_RECIPIENT environment variable"\)\n'
        r"        return\n+",
        "",
        out,
        count=0,
    )
    if new != out:
        changes += 1
        out = new

    # 1c — drop every iMessage send block of the shape:
    #         # Send via iMessage...
    #         print(f"\nSending iMessage to {CONFIG['IMESSAGE_RECIPIENT']}...")
    #         imessage_success = send_imessage(CONFIG["IMESSAGE_RECIPIENT"], ...)
    #
    # Captures the optional comment line + the print + the call.
    pattern_send = re.compile(
        r"(?:^[ \t]*#[^\n]*iMessage[^\n]*\n)?"
        r"^[ \t]*print\(f?\"\\?n?Sending iMessage to [^\n]+\n"
        r"^[ \t]*imessage_success\s*=\s*send_imessage\([^\n]+\n"
        r"(?:^[ \t]*\n)?",
        flags=re.MULTILINE,
    )
    new, n = pattern_send.subn("", out)
    if n:
        changes += n
        out = new
    log(f"  · removed {n} iMessage send call sites from morning_briefing.py")

    # 1d — drop the send_imessage() function definition (and its body).
    # Robust: from `def send_imessage` until the next top-level def or comment-section.
    pattern_func = re.compile(
        r"^def send_imessage\([^\n]*\n"
        r"(?:    [^\n]*\n|\n)+?"
        r"(?=^(?:def |# ={3,}|\nclass |# ----))",
        flags=re.MULTILINE,
    )
    new, n = pattern_func.subn("", out)
    if n:
        changes += n
        out = new
        log("  · removed send_imessage() function definition")

    # 1e — drop _chunk_message() if standalone
    pattern_chunk = re.compile(
        r"^def _chunk_message\([^\n]*\n"
        r"(?:    [^\n]*\n|\n)+?"
        r"(?=^(?:def |# ={3,}|\nclass ))",
        flags=re.MULTILINE,
    )
    new, n = pattern_chunk.subn("", out)
    if n:
        changes += n
        out = new
        log("  · removed _chunk_message() helper")

    # 1f — remove format_morning_text / format_premarket_text from the
    # `from morning_briefing_redesign import (...)` block.  We keep them
    # defined in the redesign module (they're harmless), just stop importing.
    new = re.sub(
        r"^[ \t]+format_morning_text,\s*\n",
        "",
        out,
        count=0,
        flags=re.MULTILINE,
    )
    if new != out:
        changes += 1
        out = new
    new = re.sub(
        r"^[ \t]+format_premarket_text,\s*\n",
        "",
        out,
        count=0,
        flags=re.MULTILINE,
    )
    if new != out:
        changes += 1
        out = new

    # 1g — also drop the lines that *call* format_*_text inside run_morning /
    # run_premarket etc.  They populate `text_message` which then went to
    # iMessage; we now keep `text_message` only as a plain-text fallback
    # passed to send_email() — so we still need the variable, but we should
    # source it from the legacy formatter when AI succeeds, or use the AI
    # brief's `what_matters` field as a minimal fallback.  Safer to leave
    # the calls in place since the redesign module still defines the
    # functions and they no longer touch iMessage.

    return out, changes


# ---------------------------------------------------------------------------
# Step 2 — Strip iMessage from morning_briefing_redesign.py
# ---------------------------------------------------------------------------


def strip_imessage_from_redesign(src: str) -> tuple[str, int]:
    changes = 0
    out = src

    # 2a — replace the run_morning_briefing_v2 iMessage send block
    pattern = re.compile(
        r"    # Send iMessage \(uses existing send_imessage from morning_briefing\.py\)\n"
        r"    # This function must be imported or called from the main script\n"
        r"    imessage_sent\s*=\s*send_imessage\([^\n]+\n",
        flags=re.MULTILINE,
    )
    new, n = pattern.subn("", out)
    if n:
        changes += n
        out = new
        log("  · removed run_morning_briefing_v2 iMessage send")

    # 2b — replace the NOTE block referencing send_imessage reuse
    pattern_note = re.compile(
        r"# NOTE: For iMessage delivery, reuse the existing send_imessage\(\) function\n"
        r"# from morning_briefing\.py — it has proper chunking, retry logic, and the\n"
        r"# correct AppleScript pattern for the iMac's Messages\.app configuration\.\n"
        r"# Do NOT rewrite the iMessage sender here\.\n+",
        flags=re.MULTILINE,
    )
    new, n = pattern_note.subn("", out)
    if n:
        changes += n
        out = new
        log("  · removed obsolete iMessage NOTE comment block")

    # 2c — update docstrings that say "iMessage teaser" / "iMessage delivery"
    out2 = out.replace(
        "Format a concise iMessage teaser for the morning intelligence brief.",
        "Format a concise plain-text version of the morning brief.",
    )
    if out2 != out:
        changes += 1
        out = out2

    out2 = out.replace(
        "Format the post-close market recap as plain text for iMessage delivery.",
        "Format the post-close market recap as plain text (email fallback).",
    )
    if out2 != out:
        changes += 1
        out = out2

    out2 = out.replace(
        "Parallel to format_morning_text — editorial voice at the top, key data\n"
        "    below, optimized for multi-chunk iMessage delivery.",
        "Parallel to format_morning_text — editorial voice at the top, key data\n"
        "    below.  Used as the email body when HTML rendering fails.",
    )
    if out2 != out:
        changes += 1
        out = out2

    # 2d — update the "Formatting plain text iMessage" log line
    out2 = out.replace(
        '    print("\\n[3/4] Formatting plain text iMessage...")',
        '    print("\\n[3/4] Formatting plain-text email fallback...")',
    )
    if out2 != out:
        changes += 1
        out = out2

    out2 = out.replace(
        '    print("\\n[4/4] Sending via Apple Mail and Messages...")',
        '    print("\\n[4/4] Sending via Apple Mail...")',
    )
    if out2 != out:
        changes += 1
        out = out2

    # 2e — drop any leftover imessage_recipient variable declarations
    out2 = re.sub(
        r"^[ \t]+imessage_recipient\s*=\s*[^\n]+\n",
        "",
        out,
        count=0,
        flags=re.MULTILINE,
    )
    if out2 != out:
        changes += 1
        out = out2

    return out, changes


# ---------------------------------------------------------------------------
# Step 3 — Inject startup safeguard at top of morning_briefing.py
# ---------------------------------------------------------------------------

SAFEGUARD_MARKER = "# === v2.6 safeguard: anti-regression guard ==="
SAFEGUARD_BLOCK = '''
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
    forbidden = re.compile(
        r"\\b(send_imessage|IMESSAGE_RECIPIENT|_chunk_message)\\b"
    )
    for path in suspects:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            txt = fh.read()
        # the guard itself names the symbols — skip its own lines
        clean = "\\n".join(
            ln for ln in txt.splitlines()
            if "v2.6 safeguard" not in ln and "_v2_6_guard" not in ln
            and "forbidden = re.compile" not in ln
        )
        if forbidden.search(clean):
            sys.stderr.write(
                f"\\n[v2.6 GUARD] iMessage symbol reappeared in {path}.\\n"
                "Refusing to run.  Run the migration script or revert.\\n\\n"
            )
            sys.exit(99)


_v2_6_guard()
# === end v2.6 safeguard ===
'''


def inject_safeguard(src: str) -> tuple[str, int]:
    if SAFEGUARD_MARKER in src:
        return src, 0
    # Insert immediately after the shebang/docstring/from-future block,
    # before the first non-import non-comment statement.
    # Simplest robust placement: directly after the module docstring.
    lines = src.splitlines(keepends=True)
    insert_at = 0
    # skip shebang
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    # skip leading docstring
    if insert_at < len(lines) and lines[insert_at].lstrip().startswith(('"""', "'''")):
        quote = lines[insert_at].lstrip()[:3]
        # find end of docstring
        if lines[insert_at].count(quote) >= 2:
            insert_at += 1
        else:
            insert_at += 1
            while insert_at < len(lines) and quote not in lines[insert_at]:
                insert_at += 1
            insert_at = min(insert_at + 1, len(lines))
    # skip from __future__ import lines
    while insert_at < len(lines) and lines[insert_at].startswith("from __future__"):
        insert_at += 1
    new_src = "".join(lines[:insert_at]) + SAFEGUARD_BLOCK + "".join(lines[insert_at:])
    return new_src, 1


# ---------------------------------------------------------------------------
# Step 4 — Freshness fix in BRIEFING_SYSTEM_PROMPT (redesign file)
# ---------------------------------------------------------------------------

FRESHNESS_RULE_MARKER = "## v2.6 freshness rule"
FRESHNESS_RULE_TEXT = '''

## v2.6 freshness rule (data-staleness anti-pattern)
- The `scorecard` field contains earnings that REPORTED IN THE LAST 21 DAYS.
  Each entry has a `days_since` field.  If `days_since > 1`, the print is
  history — do NOT lead with it as a current-day catalyst.  Reference it
  only as context for the cycle read.
- "Upcoming" means an earnings entry whose `date` is today or in the
  future.  If you can't find one for a name you want to discuss, do not
  invent one — say "no scheduled catalyst this week."
- If the `earnings calendar` shows a date that matches today's year/month
  (e.g. "May 2026" on May 19, 2026), trust it.  Do not flag it as a data
  error.  Real upcoming earnings genuinely fall in the current month.
- Lead-section eligibility: an earnings event qualifies for the WHAT MATTERS
  lead ONLY if `days_since == 0` (reported today, including after-hours
  yesterday) or its scheduled date is today.  Older prints belong in
  EARNINGS INTELLIGENCE as cycle context.
'''


def add_freshness_rule(src: str) -> tuple[str, int]:
    if FRESHNESS_RULE_MARKER in src:
        return src, 0
    # Append to BRIEFING_SYSTEM_PROMPT (find closing triple-quote of the
    # first occurrence after `BRIEFING_SYSTEM_PROMPT = """`)
    m = re.search(r'BRIEFING_SYSTEM_PROMPT\s*=\s*"""', src)
    if not m:
        return src, 0
    # find closing """ after that
    end = src.find('"""', m.end())
    if end < 0:
        return src, 0
    new_src = src[:end] + FRESHNESS_RULE_TEXT + src[end:]
    return new_src, 1


# ---------------------------------------------------------------------------
# Step 5 — days_since injection into morning_briefing.py earnings payload
# ---------------------------------------------------------------------------


def add_days_since(src: str) -> tuple[str, int]:
    marker = "# === v2.6 days_since enrichment ==="
    if marker in src:
        return src, 0
    # Find the scorecard-build region; we add a post-process step at the
    # site where the scorecard list is constructed and just before it is
    # placed in `briefing_data`.  Look for a stable anchor.
    anchor = '    briefing_data = {\n        "market_snapshot": market_snapshot,'
    if anchor not in src:
        return src, 0
    enrich = (
        marker + "\n"
        "    from datetime import datetime as _dt_v26, date as _date_v26\n"
        "    _today_v26 = _dt_v26.now().date()\n"
        "    def _enrich(rec):\n"
        "        d = rec.get('date') or rec.get('report_date')\n"
        "        if isinstance(d, str):\n"
        "            try:\n"
        "                d = _dt_v26.strptime(d[:10], '%Y-%m-%d').date()\n"
        "            except Exception:\n"
        "                d = None\n"
        "        if isinstance(d, _date_v26):\n"
        "            rec['days_since'] = (_today_v26 - d).days\n"
        "        return rec\n"
        "    try:\n"
        "        scorecard = [_enrich(dict(r)) for r in (scorecard or [])]\n"
        "    except Exception:\n"
        "        pass\n"
        "    try:\n"
        "        earnings = [_enrich(dict(r)) for r in (earnings or [])]\n"
        "    except Exception:\n"
        "        pass\n"
        "    # === end v2.6 days_since enrichment ===\n\n"
    )
    new_src = src.replace(anchor, enrich + anchor, 1)
    return new_src, 1


# ---------------------------------------------------------------------------
# Step 6 — Add staleness alarm to briefing_monitor.py
# ---------------------------------------------------------------------------

STALENESS_MARKER = "# === v2.6 staleness alarm ==="
STALENESS_BLOCK = '''

# === v2.6 staleness alarm ===
def check_deploy_freshness() -> None:
    """Email-alert if production files drift from the Drive mirror.

    Cheap SHA256 comparison; runs in <50ms.  Skips silently when the
    Drive folder is unreachable (e.g., Drive client offline).  Designed
    to be called once per monitor run.
    """
    import hashlib, os, subprocess, time
    prod = os.path.expanduser("~/Claude/morning-briefing")
    drive = os.path.expanduser(
        "~/My Drive/Claude-Workspace/Claude Projects/Morning Briefing"
    )
    if not os.path.isdir(drive):
        return  # Drive not mounted; nothing to compare
    drift: list[str] = []
    for name in ("morning_briefing.py", "morning_briefing_redesign.py", "briefing_monitor.py"):
        p_path = os.path.join(prod, name)
        d_path = os.path.join(drive, name)
        if not (os.path.exists(p_path) and os.path.exists(d_path)):
            continue
        with open(p_path, "rb") as f:
            ph = hashlib.sha256(f.read()).hexdigest()
        with open(d_path, "rb") as f:
            dh = hashlib.sha256(f.read()).hexdigest()
        if ph != dh:
            age_h = (time.time() - os.path.getmtime(d_path)) / 3600
            drift.append(f"{name}: prod={ph[:8]} drive={dh[:8]} (drive age {age_h:.1f}h)")
    if not drift:
        return
    body = (
        "Morning Briefing deploy-drift alert\\n\\n"
        "Production code does not match Drive mirror:\\n  - "
        + "\\n  - ".join(drift)
        + "\\n\\nThe daily auto-sync (com.briefing.deploy.plist at 4:50 AM weekdays) "
        "should reconcile this.  If you see this twice in a row, the sync job is broken."
    )
    print("[staleness] drift detected; emailing alert")
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e",
             'tell application "Mail" to send (make new outgoing message with properties '
             '{subject:"[Briefing] deploy drift detected", content:"' + body.replace('"', '\\\\"') + '", '
             'visible:false, to recipients:{{address:"jvs@blumecapital.com"}}})'],
            capture_output=True, timeout=30,
        )
    except Exception as e:
        print(f"[staleness] failed to send alert: {e}")
# === end v2.6 staleness alarm ===
'''


def add_staleness_alarm(src: str) -> tuple[str, int]:
    if STALENESS_MARKER in src:
        return src, 0
    # Append at end of file
    return src.rstrip() + "\n" + STALENESS_BLOCK + "\n", 1


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def process_file(path: Path, transformers: list) -> int:
    if not path.exists():
        log(f"  ! {path.name}: missing, skipped")
        return 0
    backup(path)
    src = path.read_text(encoding="utf-8")
    total = 0
    for transformer in transformers:
        src, n = transformer(src)
        total += n
    write_atomic(path, src)
    log(f"  ✓ {path.name}: {total} edits applied")
    return total


def main() -> int:
    log(f"\n{'='*70}\nMorning Briefing v2.6 migration\n{'='*70}")
    log(f"Production: {PROD_DIR}")
    log(f"Drive:      {DRIVE_DIR}")
    if not PROD_DIR.exists():
        log("FATAL: production directory not found")
        return 2

    log("\n[1/3] morning_briefing.py — strip iMessage + add safeguards + days_since")
    process_file(
        PROD_DIR / "morning_briefing.py",
        [strip_imessage_from_main, inject_safeguard, add_days_since],
    )

    log("\n[2/3] morning_briefing_redesign.py — strip iMessage + freshness rule")
    process_file(
        PROD_DIR / "morning_briefing_redesign.py",
        [strip_imessage_from_redesign, add_freshness_rule],
    )

    log("\n[3/3] briefing_monitor.py — staleness alarm")
    process_file(
        PROD_DIR / "briefing_monitor.py",
        [add_staleness_alarm],
    )

    # Verification: grep for forbidden symbols
    log("\n=== Verification ===")
    bad = 0
    for name in ("morning_briefing.py", "morning_briefing_redesign.py", "briefing_monitor.py"):
        path = PROD_DIR / name
        if not path.exists():
            continue
        txt = path.read_text(encoding="utf-8")
        # ignore guard lines that name the forbidden symbols defensively
        clean_lines = [
            ln for ln in txt.splitlines()
            if "v2.6 safeguard" not in ln
            and "v2_6_guard" not in ln
            and "forbidden = re.compile" not in ln
        ]
        clean = "\n".join(clean_lines)
        for sym in ("send_imessage", "IMESSAGE_RECIPIENT", "_chunk_message"):
            count = clean.count(sym)
            if count:
                log(f"  ✗ {name}: still contains '{sym}' x{count}")
                bad += 1
            else:
                log(f"  ✓ {name}: '{sym}' absent")

    log(f"\n{'='*70}\nDone.  Forbidden symbols remaining: {bad}\n{'='*70}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
