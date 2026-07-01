#!/usr/bin/env python3
"""
Morning Briefing Health Monitor
Checks log files after each launchd run and sends an alert via email
if any failures are detected. Designed to be called by a launchd plist
~5 minutes after each briefing workflow.

Usage:
    python3 briefing_monitor.py morning              # Check morning briefing logs
    python3 briefing_monitor.py premarket lunarcrush # Check multiple workflows
    python3 briefing_monitor.py recap                # Check recap logs
    python3 briefing_monitor.py all                  # Check all four workflows
    python3 briefing_monitor.py --by-time            # Pick modes from current hour
                                                     # (used by the launchd plist)

Exit codes:
    0 = healthy
    1 = failures detected (alert sent)
    2 = logs missing (workflow may not have run)
"""

from __future__ import annotations

import os
import sys
import subprocess
import time
from datetime import datetime, timedelta

# ── Configuration ──────────────────────────────────────────────────────────
EMAIL_RECIPIENT = "jvs@blumecapital.com"
LOG_DIR = "/tmp"
MONITOR_LOG = "/tmp/briefing-monitor.log"

# Per-workflow log path overrides (when log filename doesn't match briefing-{mode}.log).
# Default path is LOG_DIR/briefing-{mode}.log / briefing-{mode}.err.
# No overrides currently: com.briefing.lunarcrush writes to the standard
# /tmp/briefing-lunarcrush.log|.err (the old /tmp/lunarcrush-evening-launchd.log
# override pointed at the retired sibling job and was removed 2026-07-01).
WORKFLOW_LOG_PATHS = {}

# Per-workflow maximum log age (hours). Monitor runs at 5:10 AM + 6:30 AM on weekdays;
# only morning is expected to have a fresh log at 5:10 AM. Everything else is checked
# against the prior day's run — the 26h window means "ran within the last daily cycle."
WORKFLOW_MAX_AGE_HOURS = {
    "morning":    3,    # 5:00 AM PT daily
    "premarket":  26,   # 6:20 AM PT daily — monitor runs BEFORE it at 5:10
    "recap":      26,   # 2:00 PM PT daily — monitor runs long after it
    "lunarcrush": 26,   # 5:30 PM PT Sunday social brief (checked only on the Sunday-evening monitor run)
}

# Stderr patterns that are known-expected noise and should NOT trigger a warning.
# - ETF/ADR symbols correctly lack earnings data / fundamentals (Yahoo v10 is also
#   dead per project memory, so quoteSummary 404s are routine).
# - Python 3.9 deprecation warnings from google-* packages are cosmetic.
# - urllib3/LibreSSL warning is cosmetic on this macOS box.
KNOWN_NOISE_PATTERNS = [
    "No earnings dates found, symbol may be delisted",
    "No fundamentals data found for symbol:",       # quoteSummary on ETFs/ADRs
    "Quote not found for symbol:",                  # Yahoo v10 dead — routine for BRKB/VWAPY
    "possibly delisted; no price data found",       # transient Yahoo flake on BRKB et al. — not a real delisting
    "NotOpenSSLWarning: urllib3 v2 only supports",
    "FutureWarning: You are using",                 # google-auth py3.9 warnings
    "FutureWarning: You are using a non-supported Python",
    "warnings.warn(",                                # the follow-on line to the above
    "warnings.warn(eol_message",
    "warnings.warn(message,",
    # LunarCrush per-topic / per-creator timeouts are routine on the rate-limited
    # Discover tier and are already retried in lunarcrush_brief.py
    "Timeout for topic/",
    "Timeout for creator/",
    # Subscription-gated endpoints return 402 — expected at current LC tier
    "Subscription required for ",
    "Time-series endpoint not available",
    # Rate-limit backoff messages are informational, not warnings
    "Rate limited (429), waiting",
]

# What to look for in logs
FAILURE_PATTERNS = [
    "✗ Failed to send email",
    "✗ Delivery failed",
    "Traceback (most recent call last)",
    "error -1712",           # AppleEvent timeout (App Nap)
    "error -1743",           # TCC Automation permission
    "Another .* briefing is already running",  # Stale lockfile
    "HTTP 401",              # API key expired
    "HTTP 403",              # API access denied
    "Legacy Endpoint",       # FMP dead endpoint (should never appear now)
]

# What indicates success
SUCCESS_PATTERNS = {
    "morning": "✓ Morning briefing delivered",
    "premarket": "✓ Pre-market update delivered",
    "recap": "✓ Market recap delivered",
    # lunarcrush_brief.py doesn't emit the ✓ marker; end-of-run is "Completed in Xs"
    # preceded by "Email sent". Match the wall-clock marker.
    "lunarcrush": "Completed in",
}

# Email-only dispatch: no partial-delivery states. If email fails, it's a FAILURE.
PARTIAL_PATTERNS: list[str] = []

# API-level warnings (not failures, but degraded)
WARNING_PATTERNS = [
    "HTTP 429",              # Rate limited
    "HTTP 400",              # Bad request (batch limit?)
    "error for ",            # Logged exception from except handlers
    "returned HTTP",         # Non-200 response
    "timeout",               # Request timeout
]


def _log_paths(mode: str) -> tuple[str, str]:
    """Resolve (stdout_log, stderr_log) paths for a mode, with per-workflow overrides."""
    if mode in WORKFLOW_LOG_PATHS:
        return WORKFLOW_LOG_PATHS[mode]
    return (
        os.path.join(LOG_DIR, f"briefing-{mode}.log"),
        os.path.join(LOG_DIR, f"briefing-{mode}.err"),
    )


def read_log(mode: str) -> tuple[str, str]:
    """Read stdout and stderr logs for a given mode."""
    log_path, err_path = _log_paths(mode)

    stdout = ""
    stderr = ""

    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            stdout = f.read()
    # Many workflows log to a single combined file (lunarcrush) — skip reading the
    # same file twice so we don't double-count noise.
    if err_path != log_path and os.path.exists(err_path):
        with open(err_path, "r") as f:
            stderr = f.read()

    return stdout, stderr


def check_log_freshness(mode: str) -> tuple[bool, str]:
    """Check if logs are recent enough per the workflow's schedule.

    Uses WORKFLOW_MAX_AGE_HOURS so a workflow that runs daily (e.g. recap at 2 PM)
    isn't flagged stale just because the monitor runs at 5:10 AM before today's
    recap has fired. A 26h window means "ran within the last daily cycle."
    """
    log_path, _ = _log_paths(mode)
    max_hours = WORKFLOW_MAX_AGE_HOURS.get(mode, 26)

    if not os.path.exists(log_path):
        return False, f"No log file found: {log_path}"

    mtime = datetime.fromtimestamp(os.path.getmtime(log_path))
    now = datetime.now()
    age = now - mtime

    if age > timedelta(hours=max_hours):
        hours = int(age.total_seconds() // 3600)
        mins = int((age.total_seconds() % 3600) // 60)
        return False, f"Log is {hours}h {mins}m old (max {max_hours}h for this workflow) — may not have run on schedule"

    return True, f"Log updated {int(age.total_seconds() // 60)}m ago"


def analyze_logs(mode: str) -> dict:
    """Analyze log files for a given workflow mode."""
    result = {
        "mode": mode,
        "status": "unknown",
        "issues": [],
        "warnings": [],
        "api_errors": [],
        "delivery": "unknown",
    }

    # Check freshness
    fresh, freshness_msg = check_log_freshness(mode)
    if not fresh:
        result["status"] = "stale"
        result["issues"].append(freshness_msg)
        return result

    stdout, stderr = read_log(mode)
    combined = stdout + "\n" + stderr

    # Check for success
    success_pattern = SUCCESS_PATTERNS.get(mode, "")
    if success_pattern and success_pattern in combined:
        result["delivery"] = "full"
    else:
        # Check for partial success
        for pat in PARTIAL_PATTERNS:
            if pat in combined:
                result["delivery"] = "partial"
                result["warnings"].append(pat.strip())
                break

    # Check for failures
    for pattern in FAILURE_PATTERNS:
        if pattern.lower() in combined.lower():
            # Find the actual line for context
            for line in combined.split("\n"):
                if pattern.lower() in line.lower():
                    result["issues"].append(line.strip()[:200])
                    break

    # Strip known-expected noise lines before pattern-matching so ETF fundamentals
    # 404s (XLE / VWAPY via Yahoo v10) and "No earnings dates found" don't inflate
    # warning counts.
    filtered_combined = "\n".join(
        ln for ln in combined.split("\n")
        if not any(pat in ln for pat in KNOWN_NOISE_PATTERNS)
    )

    # Check for warnings
    for pattern in WARNING_PATTERNS:
        count = filtered_combined.lower().count(pattern.lower())
        if count > 0:
            result["warnings"].append(f"{pattern} × {count}")

    # Count API hits vs failures (noise-filtered)
    api_calls = filtered_combined.count("Found ")
    api_fails = filtered_combined.count("HTTP 4") + filtered_combined.count("HTTP 5")
    if api_fails > 0:
        result["api_errors"].append(f"{api_fails} API errors out of ~{api_calls} data fetches")

    # Check stderr for Python exceptions. Known-expected noise is filtered first so
    # routine ETF "No earnings dates" and VWAPY/XLE quoteSummary 404s don't register.
    if stderr.strip():
        meaningful_lines = [
            ln for ln in stderr.strip().split("\n")
            if ln.strip() and not any(pat in ln for pat in KNOWN_NOISE_PATTERNS)
        ]
        if "Traceback" in stderr:
            # A real exception — surface the last line as before (tracebacks aren't noise).
            result["issues"].append("Python exception: " + stderr.strip().split("\n")[-1][:200])
        elif meaningful_lines:
            result["warnings"].append("stderr: " + meaningful_lines[-1][:200])

    # Determine overall status
    if result["issues"]:
        result["status"] = "FAILURE"
    elif result["delivery"] == "full" and not result["warnings"]:
        result["status"] = "healthy"
    elif result["delivery"] == "partial":
        result["status"] = "degraded"
    elif result["warnings"]:
        result["status"] = "warning"
    else:
        result["status"] = "FAILURE"  # No success pattern found
        result["issues"].append("No delivery confirmation found in logs")

    return result


def format_alert(results: list[dict]) -> str | None:
    """Format an alert message if any issues found. Returns None if all healthy."""
    needs_alert = any(r["status"] in ("FAILURE", "degraded", "stale") for r in results)

    if not needs_alert:
        return None

    lines = ["⚠ BRIEFING MONITOR", ""]

    for r in results:
        icon = {"healthy": "✓", "warning": "~", "degraded": "⚠", "FAILURE": "✗", "stale": "?", "unknown": "?"}
        lines.append(f"  {icon.get(r['status'], '?')} {r['mode'].upper()}: {r['status']}")

        for issue in r["issues"]:
            lines.append(f"    → {issue}")
        for warn in r["warnings"]:
            lines.append(f"    · {warn}")
        for api_err in r["api_errors"]:
            lines.append(f"    · {api_err}")
        lines.append("")

    return "\n".join(lines)


def send_alert(message: str) -> bool:
    """Send alert via Apple Mail."""
    # Wake Mail.app from App Nap
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Mail" to activate'],
            capture_output=True, text=True, timeout=30,
        )
        time.sleep(2)
    except Exception:
        pass  # Best effort

    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"⚠ Briefing Monitor Alert – {today}"
    escaped_subject = subject.replace('"', '\\"')
    escaped_body = message.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\r")

    applescript = f'''
    with timeout of 120 seconds
        tell application "Mail"
            set newMessage to make new outgoing message with properties {{subject:"{escaped_subject}", content:"{escaped_body}", visible:false}}
            tell newMessage
                make new to recipient at end of to recipients with properties {{address:"{EMAIL_RECIPIENT}"}}
                send
            end tell
        end tell
    end timeout
    '''
    try:
        subprocess.run(
            ["osascript", "-e", applescript],
            check=True, capture_output=True, text=True, timeout=130
        )
        return True
    except Exception as e:
        print(f"Failed to send alert: {e}")
        return False


def log_result(results: list[dict]):
    """Append monitoring results to persistent log."""
    try:
        with open(MONITOR_LOG, "a") as f:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for r in results:
                status = r["status"]
                issues = "; ".join(r["issues"]) if r["issues"] else "none"
                f.write(f"{now} | {r['mode']} | {status} | issues: {issues}\n")
    except Exception:
        pass


def _modes_for_current_time() -> list[str]:
    """Return the workflow modes the monitor should check right now.

    The launchd watchdog fires at:
      - 5:10 AM Mon–Fri  (validates morning, which ran at 5:00 AM)
      - 6:30 AM Mon–Fri  (validates premarket, which ran at 6:20 AM)
      - 1:25 PM Mon–Fri  (validates recap, which ran at 1:15 PM)
      - 6:00 PM Sunday   (validates LunarCrush 5:30 PM + weekend_preview 6:00 PM)

    Each slot should validate only the workflow that just ran — otherwise the
    1:25 PM weekday run reports "morning stale" because the morning log is
    8h+ old by then (its max age is 3h). Window boundaries are deliberately
    generous so a slightly-late launchd wake still picks the intended slot.

    Day-of-week awareness matters because LunarCrush moved from a weekday
    morning slot to Sunday evening as of v2.7.2 (2026-05-23): a 6 AM weekday
    check should no longer expect LunarCrush, and a Sunday evening check
    should not expect the weekday workflows.
    """
    now = datetime.now()
    h = now.hour
    is_sunday = now.weekday() == 6  # Python: Monday=0, Sunday=6

    if is_sunday and 17 <= h < 20:
        return ["lunarcrush"]
    if not is_sunday and 5 <= h < 6:
        return ["morning"]
    if not is_sunday and 6 <= h < 8:
        return ["premarket"]
    if not is_sunday and 13 <= h < 15:
        return ["recap"]
    # Off-schedule manual run: fall back to checking everything.
    return ["morning", "premarket", "lunarcrush", "recap"]


def main():
    # CLI accepts:
    #   (no args)                           → check all four workflows
    #   "all"                               → check all four workflows
    #   "--by-time"                         → pick modes from current hour
    #                                         (used by the monitor plist)
    #   one or more workflow names          → check only those workflows
    args = sys.argv[1:]
    if not args or args == ["all"]:
        modes = ["morning", "premarket", "lunarcrush", "recap"]
    elif args == ["--by-time"]:
        modes = _modes_for_current_time()
    else:
        modes = args

    results = [analyze_logs(m) for m in modes]

    # Log results
    log_result(results)

    # Print summary
    for r in results:
        status_icon = {"healthy": "✓", "warning": "~", "degraded": "⚠", "FAILURE": "✗"}.get(r["status"], "?")
        print(f"{status_icon} {r['mode']}: {r['status']} (delivery: {r['delivery']})")
        for issue in r["issues"]:
            print(f"  → {issue}")
        for warn in r["warnings"]:
            print(f"  · {warn}")


    # v2.6 staleness wiring — surface deploy drift in every monitor run
    _drift, _drift_lines = check_deploy_freshness()
    if _drift:
        drift_msg = (
            "DEPLOY DRIFT DETECTED — production code does not match Drive:\n  "
            + "\n  ".join(_drift_lines)
            + "\n\nThe daily auto-sync (com.briefing.deploy.plist at 4:50 AM weekdays) "
            "should reconcile this.  If you see this twice running, the sync job is broken."
        )
        print("\n" + drift_msg)
        try:
            send_alert(drift_msg)
        except Exception as e:
            print(f"Failed to dispatch drift alert: {e}")


    # Send alert if needed
    alert = format_alert(results)
    if alert:
        print(f"\nSending alert email to {EMAIL_RECIPIENT}...")
        if send_alert(alert):
            print("✓ Alert sent")
        else:
            print("✗ Alert send failed")
        sys.exit(1)
    else:
        print("\nAll healthy — no alert needed.")
        sys.exit(0)


# === v2.6 staleness alarm ===
def check_deploy_freshness() -> tuple[bool, list[str]]:
    """Compare production code SHAs against Drive mirror. Returns (drift_found, lines)."""
    import hashlib, os, time
    prod = os.path.expanduser("~/Claude/morning-briefing")
    drive = os.path.expanduser("~/My Drive/Claude-Workspace/Claude Projects/Morning Briefing")
    if not os.path.isdir(drive):
        return False, []
    drift = []
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
    return (len(drift) > 0), drift
# === end v2.6 staleness alarm ===


if __name__ == "__main__":
    main()


