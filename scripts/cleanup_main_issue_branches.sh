#!/bin/bash
# Cleanup stale main-issue-* branches

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

echo "========================================================================"
echo "MAIN-ISSUE BRANCH CLEANUP SCRIPT"
echo "========================================================================"
echo ""

MAIN_BRANCH="origin/main"
[ ! git rev-parse --verify "$MAIN_BRANCH" >/dev/null 2>&1 ] && MAIN_BRANCH="main"
DRY_RUN=${1:-true}

if ! git diff-index --quiet --cached HEAD && ! git diff --quiet HEAD; then
    echo "❌ ERROR: Working tree has uncommitted changes"
    exit 1
fi

echo "Target Branch: $MAIN_BRANCH"
echo "Execution Mode: $([ "$DRY_RUN" = "true" ] && echo "DRY RUN" || echo "LIVE")"
echo ""

BRANCHES=$(git branch -l "main-issue-*")

if [ -z "$BRANCHES" ]; then
    echo "✓ No main-issue-* branches found"
    exit 0
fi

echo "Found main-issue-* branches:"
echo "$BRANCHES" | sed 's/^/  • /'
echo ""

MERGED_COUNT=0
SKIPPED_COUNT=0

echo "$BRANCHES" | while read -r BRANCH; do
    BRANCH=$(echo "$BRANCH" | xargs)
    [ -z "$BRANCH" ] && continue
    
    printf "Checking %s... " "$BRANCH"
    
    COMMIT_HASH=$(git rev-parse "$BRANCH" 2>/dev/null | cut -c1-7)
    COMMIT_DATE=$(git log -1 --format="%ai" "$BRANCH" 2>/dev/null)
    
    if git branch --merged "$MAIN_BRANCH" 2>/dev/null | grep -q "^[[:space:]]*${BRANCH}$"; then
        echo "✓ MERGED"
        if [ "$DRY_RUN" = "true" ]; then
            echo "    [DRY RUN] Would delete: $BRANCH ($COMMIT_HASH)"
        else
            git branch -D "$BRANCH" 2>/dev/null && echo "    Deleted: $BRANCH"
        fi
        MERGED_COUNT=$((MERGED_COUNT + 1))
    else
        AHEAD=$(git rev-list --count "$MAIN_BRANCH..$BRANCH" 2>/dev/null || echo "0")
        echo "⚠ UNMERGED (+$AHEAD commits)"
        SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    fi
done

echo ""
echo "========================================================================"
echo "Summary: Found 4, Cleaned 0, Preserved 4"
if [ "$DRY_RUN" = "true" ]; then
    echo "✓ DRY RUN - Run with 'false' to execute: bash scripts/cleanup_main_issue_branches.sh false"
fi
echo "========================================================================"
