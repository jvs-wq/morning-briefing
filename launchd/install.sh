#!/bin/bash
# Disaster-recovery install for morning-briefing launchd schedule.
#
# Copies every plist in this directory to ~/Library/LaunchAgents/ and loads
# them. Plists reference absolute paths — if your repo lives anywhere other
# than ~/Claude/morning-briefing/ or your username is not "jeffreystclaire",
# edit the plists in place before running this script (sed works fine; the
# paths are not encrypted).
#
# Usage:  bash launchd/install.sh
#
# Idempotent — safe to re-run. Each plist is unloaded (if present) before
# being copied and loaded again.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$TARGET_DIR"

for plist in "$SCRIPT_DIR"/*.plist; do
    name=$(basename "$plist")
    target="$TARGET_DIR/$name"
    label="${name%.plist}"

    echo "  • $label"
    launchctl unload "$target" 2>/dev/null || true
    cp "$plist" "$target"
    launchctl load "$target"
done

echo ""
echo "Loaded agents:"
launchctl list | grep -E "briefing" || true
