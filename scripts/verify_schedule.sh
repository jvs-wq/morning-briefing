#!/bin/bash
# verify_schedule.sh — health check for the morning-briefing + lunarcrush-brief launchd schedule.
#
# Designed to run as a one-shot on Mon 2026-05-18 at 9:00 AM PT, two weekends after the
# 2026-05-02 weekend cleanup, to confirm:
#   1. All 8 launchd agents are still loaded
#   2. The Sunday weekend_preview ran on 5/3, 5/10, 5/17 (latest log mtime is a Sunday)
#   3. The Saturday LunarCrush weekly digest ran on 5/9, 5/16 (latest log mtime is a Saturday)
#   4. No weekday-mode briefings (morning/premarket/recap) fired on any Saturday or Sunday
#      in the past 14 days — checked via `log show` against launchd
#
# Posts a one-paragraph summary to iMessage. Self-removes the triggering plist after running.
#
# Safe to run manually anytime: `bash scripts/verify_schedule.sh`. Self-removal is gated
# on the plist actually being installed.

set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_DIR/.env"
SELF_PLIST="$HOME/Library/LaunchAgents/com.briefing.verify_schedule.plist"

# Load .env to get IMESSAGE_RECIPIENT
if [ -f "$ENV_FILE" ]; then
    set -a; . "$ENV_FILE"; set +a
fi

if [ -z "${IMESSAGE_RECIPIENT:-}" ]; then
    echo "ERROR: IMESSAGE_RECIPIENT not set in $ENV_FILE — cannot deliver summary." >&2
    exit 1
fi

NOW=$(date "+%a %b %d %H:%M %Z")
findings=()
issues=0

# -----------------------------------------------------------------------------
# Check 1 — All 8 agents loaded
# -----------------------------------------------------------------------------
expected_agents=(
    "com.briefing.morning"
    "com.briefing.premarket"
    "com.briefing.recap"
    "com.briefing.weekend_preview"
    "com.briefing.monitor"
    "com.lunarcrush.evening"
    "com.lunarcrush.weekly"
    "com.lunarcrush.review"
)
loaded=$(launchctl list | awk '{print $3}')
missing=()
for agent in "${expected_agents[@]}"; do
    if ! grep -qx "$agent" <<<"$loaded"; then
        missing+=("$agent")
    fi
done
if [ ${#missing[@]} -eq 0 ]; then
    findings+=("✓ All 8 agents loaded")
else
    findings+=("✗ Missing agents: ${missing[*]}")
    issues=$((issues + 1))
fi

# -----------------------------------------------------------------------------
# Check 2 — Sunday weekend_preview log mtime is on a Sunday
# -----------------------------------------------------------------------------
wp_log="/tmp/briefing-weekend_preview.log"
wp_err="/tmp/briefing-weekend_preview.err"
if [ -f "$wp_log" ]; then
    wp_mtime=$(stat -f %m "$wp_log")
    wp_dow=$(date -j -f %s "$wp_mtime" +%u)   # 1=Mon..7=Sun
    wp_when=$(date -j -f %s "$wp_mtime" "+%a %b %d %H:%M")
    if [ "$wp_dow" = "7" ]; then
        findings+=("✓ weekend_preview last ran $wp_when (Sun, expected)")
    else
        findings+=("✗ weekend_preview last ran $wp_when — expected Sunday")
        issues=$((issues + 1))
    fi
    # Surface any stderr content from the most recent run
    if [ -s "$wp_err" ]; then
        err_tail=$(tail -3 "$wp_err" | tr '\n' ' ' | cut -c1-200)
        findings+=("  stderr tail: $err_tail")
    fi
else
    findings+=("✗ /tmp/briefing-weekend_preview.log missing — never ran")
    issues=$((issues + 1))
fi

# -----------------------------------------------------------------------------
# Check 3 — Saturday lunarcrush weekly log mtime is on a Saturday
# -----------------------------------------------------------------------------
lc_log="/tmp/lunarcrush-weekly-launchd.log"
if [ -f "$lc_log" ]; then
    lc_mtime=$(stat -f %m "$lc_log")
    lc_dow=$(date -j -f %s "$lc_mtime" +%u)
    lc_when=$(date -j -f %s "$lc_mtime" "+%a %b %d %H:%M")
    if [ "$lc_dow" = "6" ]; then
        findings+=("✓ lunarcrush.weekly last ran $lc_when (Sat, expected)")
    else
        findings+=("✗ lunarcrush.weekly last ran $lc_when — expected Saturday")
        issues=$((issues + 1))
    fi
else
    findings+=("✗ /tmp/lunarcrush-weekly-launchd.log missing — never ran")
    issues=$((issues + 1))
fi

# -----------------------------------------------------------------------------
# Check 4 — No spurious weekday-mode fires on Sat/Sun in the past 14 days
# Reads launchd's own log via `log show`. Slow (~10-30s) but authoritative.
# -----------------------------------------------------------------------------
weekday_agents="com.briefing.morning|com.briefing.premarket|com.briefing.recap"
spurious=$(log show --last 14d --predicate 'subsystem == "com.apple.xpc.launchd" AND eventMessage CONTAINS "Service spawned"' 2>/dev/null \
    | grep -E "$weekday_agents" \
    | awk '{print $1, $2, $NF}' \
    | while read date time service; do
        dow=$(date -j -f "%Y-%m-%d" "$date" +%u 2>/dev/null)
        if [ "$dow" = "6" ] || [ "$dow" = "7" ]; then
            echo "$date $time $service"
        fi
    done)

if [ -z "$spurious" ]; then
    findings+=("✓ No weekday-mode fires on Sat/Sun in past 14 days")
else
    spurious_count=$(echo "$spurious" | wc -l | tr -d ' ')
    findings+=("✗ $spurious_count spurious weekend fires of weekday modes")
    issues=$((issues + 1))
fi

# -----------------------------------------------------------------------------
# Build summary + send iMessage
# -----------------------------------------------------------------------------
if [ $issues -eq 0 ]; then
    headline="✅ Schedule healthy ($NOW)"
else
    headline="⚠️ Schedule check found $issues issue(s) ($NOW)"
fi

summary="$headline"
for line in "${findings[@]}"; do
    summary="$summary
$line"
done

echo "$summary"

# Escape double quotes for AppleScript and send
escaped=$(printf '%s' "$summary" | sed 's/"/\\"/g')
osascript <<EOF
tell application "Messages"
    set targetService to 1st service whose service type = iMessage
    set targetBuddy to buddy "$IMESSAGE_RECIPIENT" of targetService
    send "$escaped" to targetBuddy
end tell
EOF

# -----------------------------------------------------------------------------
# Self-cleanup: if we were triggered by the one-shot plist, unload + remove it
# -----------------------------------------------------------------------------
if [ -f "$SELF_PLIST" ]; then
    echo "Self-removing one-shot plist: $SELF_PLIST"
    launchctl unload "$SELF_PLIST" 2>/dev/null || true
    rm -f "$SELF_PLIST"
fi
