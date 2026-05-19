#!/bin/bash
# deploy.sh — Morning Briefing Drive → production → GitHub deploy script
# ----------------------------------------------------------------------
# Purpose
#   Keep three sources in lockstep so the May 2026 deploy-drift class of
#   bug (Drive edits silently never reaching the iMac production tree)
#   cannot recur.  Run manually, or let com.briefing.deploy.plist invoke
#   it at 4:50 AM weekdays before the 5:00 AM morning brief.
#
# Flow
#   1. Validate Drive and prod are both reachable.
#   2. Compare SHAs of the three Python files; if Drive == prod, skip to
#      step 6 (still sync docs).
#   3. py_compile each file from Drive — refuse to deploy if any fails.
#   4. Copy Drive files → ~/Claude/morning-briefing/.
#   5. Run the v2.6 guard once via `python3 -c 'import morning_briefing'`
#      — guard self-aborts the script if any iMessage symbol returned.
#   6. Stage, commit, push to GitHub if there are changes.
#   7. Optionally reload launchd (--reload).
#
# Exit codes
#   0  success (or no-op)
#   1  Drive/prod path missing
#   2  py_compile failure (refused to deploy)
#   3  v2.6 guard failure (forbidden symbol detected)
#   4  git push failure
#   5  launchctl reload failure
#
# Usage
#   ./deploy.sh                 # sync + commit + push, do NOT touch launchd
#   ./deploy.sh --reload        # also unload/load all 5 LaunchAgents
#   ./deploy.sh --dry-run       # show what would change, do nothing

set -u

DRIVE="$HOME/My Drive/Claude-Workspace/Claude Projects/Morning Briefing"
PROD="$HOME/Claude/morning-briefing"
LOG="/tmp/briefing-deploy.log"
DO_RELOAD=0
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --reload)   DO_RELOAD=1 ;;
        --dry-run)  DRY_RUN=1 ;;
    esac
done

log() {
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] $*" | tee -a "$LOG"
}

log "===== deploy.sh start (reload=$DO_RELOAD dry_run=$DRY_RUN) ====="

if [ ! -d "$DRIVE" ]; then
    log "FATAL: Drive folder missing: $DRIVE"
    exit 1
fi
if [ ! -d "$PROD" ]; then
    log "FATAL: production folder missing: $PROD"
    exit 1
fi

# Files to keep in sync (Python first, docs second)
PY_FILES="morning_briefing.py morning_briefing_redesign.py briefing_monitor.py"
DOC_FILES="README.md PROJECT_STATE.md SETUP.md"

# 1. SHA comparison
log "Comparing SHAs..."
DRIFT=0
for f in $PY_FILES $DOC_FILES; do
    d_path="$DRIVE/$f"
    p_path="$PROD/$f"
    [ -f "$d_path" ] || continue
    if [ ! -f "$p_path" ]; then
        log "  + $f exists in Drive but not prod (will copy)"
        DRIFT=1
        continue
    fi
    d_sha=$(shasum -a 256 "$d_path" | awk '{print $1}')
    p_sha=$(shasum -a 256 "$p_path" | awk '{print $1}')
    if [ "$d_sha" != "$p_sha" ]; then
        log "  ~ $f drift: drive=${d_sha:0:8} prod=${p_sha:0:8}"
        DRIFT=1
    fi
done

if [ "$DRIFT" -eq 0 ]; then
    log "No drift detected; skipping sync."
else
    if [ "$DRY_RUN" -eq 1 ]; then
        log "(dry-run) would copy Drive → prod"
    else
        # 2. py_compile validation BEFORE we copy anything
        log "Validating Drive Python files compile..."
        for f in $PY_FILES; do
            d_path="$DRIVE/$f"
            [ -f "$d_path" ] || continue
            if ! /usr/bin/python3 -m py_compile "$d_path" 2>>"$LOG"; then
                log "FATAL: $f failed py_compile in Drive — refusing to deploy"
                exit 2
            fi
        done

        # 3. Copy
        log "Copying Drive → production..."
        for f in $PY_FILES $DOC_FILES; do
            d_path="$DRIVE/$f"
            p_path="$PROD/$f"
            [ -f "$d_path" ] || continue
            cp "$d_path" "$p_path"
            log "  copied $f"
        done

        # 4. Run the v2.6 guard once
        log "Running v2.6 guard..."
        if ! (cd "$PROD" && /usr/bin/python3 -c 'import morning_briefing' 2>/dev/null); then
            log "FATAL: v2.6 guard rejected the new code — see /tmp for stderr"
            exit 3
        fi
        log "  guard passed"
    fi
fi

# 5. Git commit + push if there are changes
cd "$PROD" || { log "FATAL: cannot cd to $PROD"; exit 1; }
if [ -n "$(git status --porcelain)" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
        log "(dry-run) would git commit + push the following:"
        git status --porcelain | tee -a "$LOG"
    else
        log "Committing and pushing to GitHub..."
        git add -A
        msg="deploy: Drive→prod sync $(date '+%Y-%m-%d %H:%M:%S')"
        if ! git commit -m "$msg" >>"$LOG" 2>&1; then
            log "  (no commit created — nothing to commit?)"
        fi
        if ! git push origin main >>"$LOG" 2>&1; then
            log "FATAL: git push failed"
            exit 4
        fi
        log "  pushed to origin/main"
    fi
else
    log "Working tree clean; nothing to commit."
fi

# 6. Optional launchd reload
if [ "$DO_RELOAD" -eq 1 ]; then
    log "Reloading LaunchAgents..."
    for j in morning premarket recap weekend_preview monitor; do
        plist="$HOME/Library/LaunchAgents/com.briefing.$j.plist"
        [ -f "$plist" ] || continue
        if [ "$DRY_RUN" -eq 1 ]; then
            log "(dry-run) would reload $j"
        else
            launchctl unload "$plist" 2>>"$LOG" || true
            if ! launchctl load "$plist" 2>>"$LOG"; then
                log "FATAL: failed to load $j"
                exit 5
            fi
            log "  reloaded $j"
        fi
    done
fi

log "===== deploy.sh done ====="
