#!/usr/bin/env python3
"""Wire check_deploy_freshness() into briefing_monitor.py main() so every
monitor run emails an alert if production code drifts from Drive.
"""
from __future__ import annotations
import re
from pathlib import Path

P = Path.home() / "Claude" / "morning-briefing" / "briefing_monitor.py"
src = P.read_text(encoding="utf-8")

if "check_deploy_freshness" not in src:
    raise SystemExit("staleness alarm function not present — run main migration first")

if "# v2.6 staleness wiring" in src:
    print("already wired")
    raise SystemExit(0)

# Find main()'s "if alert:" branch and inject a freshness check just before.
# We add the call into both the "all healthy" and "alert needed" paths so
# drift is surfaced regardless of brief health.
INJECT = '''
    # v2.6 staleness wiring — surface deploy drift in every monitor run
    _drift, _drift_lines = check_deploy_freshness()
    if _drift:
        drift_msg = (
            "DEPLOY DRIFT DETECTED — production code does not match Drive:\\n  "
            + "\\n  ".join(_drift_lines)
            + "\\n\\nThe daily auto-sync (com.briefing.deploy.plist at 4:50 AM weekdays) "
            "should reconcile this.  If you see this twice running, the sync job is broken."
        )
        print("\\n" + drift_msg)
        try:
            send_alert(drift_msg)
        except Exception as e:
            print(f"Failed to dispatch drift alert: {e}")

'''

# Insert just before the "# Send alert if needed" line
target = "    # Send alert if needed"
if target not in src:
    raise SystemExit("Could not find injection anchor")
new_src = src.replace(target, INJECT + "\n" + target, 1)
P.write_text(new_src, encoding="utf-8")
print("Wired staleness check into briefing_monitor.main()")
