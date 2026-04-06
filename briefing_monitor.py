#!/usr/bin/env python3
"""
Morning Briefing Health Monitor
Checks log files after each launchd run and sends an alert via iMessage
if any failures are detected. Designed to be called by a launchd plist
~5 minutes after each briefing workflow.

Usage:
    python3 briefing_monitor.py morning    # Check morning briefing logs
    python3 briefing_monitor.py premarket  # Check premarket logs
    python3 briefing_monitor.py recap      # Check recap logs
    python3 briefing_monitor.py all        # Check all three

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
IMESSAGE_RECIPIENT = "jvs@blumecapital.com"
LOG_DIR = "/tmp"
MONITOR_LOG = "/tmp/briefing-monitor.log"

# What to look for in logs
FAILURE_PATTERNS = [
    "✗ Failed to send iMessage",
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
    "lunarcrush": "✓ LunarCrush brief delivered",
}

# Partial success (one channel delivered)
PARTIAL_PATTERNS = [
    "⚠ Briefing sent via iMessage only",
    "⚠ Briefing sent via Email only",
    "⚠ Update sent via iMessage only",
    "⚠ Update sent via Email only",
    "⚠ Recap sent via iMessage only",
    "⚠ Recap sent via Email only",
    "⚠ Brief sent via iMessage only",
    "⚠ Brief sent via Email only",
]

# API-level warnings (not failures, but degraded)
WARNING_PATTERNS = [
    "HTTP 429",              # Rate limited
    "HTTP 400",              # Bad request (batch limit?)
    "error for ",            # Logged exception from except handlers
    "returned HTTP",         # Non-200 response
    "timeout",               # Request timeout
]


def read_log(mode: str) -> tuple[str, str]:
    """Read stdout and stderr logs for a given mode."""
    log_path = os.path.join(LOG_DIR, f"briefing-{mode}.log")
    err_path = os.path.join(LOG_DIR, f"briefing-{mode}.err")

    stdout = ""
    stderr = ""

    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            stdout = f.read()
    if os.path.exists(err_path):
        with open(err_path, "r") as f:
            stderr = f.read()

    return stdout, stderr


def check_log_freshness(mode: str) -> tuple[bool, str]:
    """Check if logs are from today (workflow actually ran)."""
    log_path = os.path.join(LOG_DIR, f"briefing-{mode}.log")

    if not os.path.exists(log_path):
        return False, f"No log file found: {log_path}"

    mtime = datetime.fromtimestamp(os.path.getmtime(log_path))
    now = datetime.now()

    # Log should be from today (or within last 2 hours for edge cases)
    if now - mtime > timedelta(hours=2):
        age = now - mtime
        return False, f"Log is {age.seconds // 3600}h {(age.seconds % 3600) // 60}m old — workflow may not have run today"

    return True, f"Log updated {(now - mtime).seconds // 60}m ago"


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

    # Check for warnings
    for pattern in WARNING_PATTERNS:
        count = combined.lower().count(pattern.lower())
        if count > 0:
            result["warnings"].append(f"{pattern} × {count}")

    # Count API hits vs failures
    api_calls = combined.count("Found ")
    api_fails = combined.count("HTTP 4") + combined.count("HTTP 5")
    if api_fails > 0:
        result["api_errors"].append(f"{api_fails} API errors out of ~{api_calls} data fetches")

    # Check stderr for Python exceptions
    if stderr.strip():
        lines = stderr.strip().split("\n")
        # Get last few lines of traceback
        if "Traceback" in stderr:
            result["issues"].append("Python exception: " + lines[-1][:200])
        elif lines:
            result["warnings"].append("stderr: " + lines[-1][:200])

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
    """Send alert via iMessage."""
    escaped = message.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    applescript = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{IMESSAGE_RECIPIENT}" of targetService
        send "{escaped}" to targetBuddy
    end tell
    '''
    try:
        subprocess.run(
            ["osascript", "-e", applescript],
            check=True, capture_output=True, text=True, timeout=60
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


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "all":
        modes = ["morning", "premarket", "lunarcrush", "recap"]
    else:
        modes = [mode]

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

    # Send alert if needed
    alert = format_alert(results)
    if alert:
        print(f"\nSending alert to {IMESSAGE_RECIPIENT}...")
        if send_alert(alert):
            print("✓ Alert sent")
        else:
            print("✗ Alert send failed")
        sys.exit(1)
    else:
        print("\nAll healthy — no alert needed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
