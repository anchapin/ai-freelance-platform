#!/bin/bash
# Cleanup stale main-issue-* branches
# These branches are typically created during issue investigations and should be removed
# once the work is complete and merged to main.

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "========================================================================"
echo "MAIN-ISSUE BRANCH CLEANUP SCRIPT"
echo "========================================================================"
echo ""

# Define main branch for merge checking - try origin/main, then main
MAIN_BRANCH="origin/main"
if ! git rev-parse --verify "$MAIN_BRANCH" >/dev/null 2>&1; then
    MAIN_BRANCH="main"
fi
DRY_RUN=${1:-true}

# Verify we're on a clean working tree
if ! git diff --quiet HEAD; then
    echo "❌ ERROR: Working tree has uncommitted changes"
    echo "   Commit or stash your changes before running this script"
    exit 1
fi

echo "Repository: $REPO_DIR"
echo "Target Branch: $MAIN_BRANCH"
echo "Execution Mode: $([ "$DRY_RUN" = "true" ] && echo "DRY RUN" || echo "LIVE")"
echo ""

# Find all main-issue-* branches
BRANCH_LIST=$(git branch -l "main-issue-*")

if [ -z "$BRANCH_LIST" ]; then
    echo "✓ No main-issue-* branches found"
    exit 0
fi

echo "Found the following main-issue-* branches:"
echo "$BRANCH_LIST" | sed 's/^/  • /'
echo ""

# Cleanup summary
DELETED=0
SKIPPED=0
MERGED_DELETED=0

while IFS= read -r branch; do
    branch=$(echo "$branch" | xargs)  # Trim whitespace
    [ -z "$branch" ] && continue
    
    echo -n "Checking $branch... "
    
    # Get branch info
    COMMIT_HASH=$(git rev-parse "$branch" 2>/dev/null | cut -c1-7)
    COMMIT_DATE=$(git log -1 --format="%ai" "$branch" 2>/dev/null)
    
    # Check if merged into main
    if git branch --merged "$MAIN_BRANCH" 2>/dev/null | grep -E "^\s*${branch}$" >/dev/null 2>&1; then
        echo "✓ MERGED"
        
        if [ "$DRY_RUN" = "true" ]; then
            echo "    [DRY RUN] Would delete: $branch (commit: $COMMIT_HASH, date: $COMMIT_DATE)"
        else
            git branch -D "$branch" 2>/dev/null
            echo "    Deleted branch: $branch"
        fi
        ((MERGED_DELETED++))
    else
        # Check if it's stale (no commits ahead of main)
        COMMITS_AHEAD=$(git rev-list --count "$MAIN_BRANCH..$branch" 2>/dev/null || echo "0")
        
        if [ "$COMMITS_AHEAD" = "0" ]; then
            echo "✓ MERGED (no new commits)"
            if [ "$DRY_RUN" = "true" ]; then
                echo "    [DRY RUN] Would delete: $branch"
            else
                git branch -D "$branch" 2>/dev/null
                echo "    Deleted branch: $branch"
            fi
            ((MERGED_DELETED++))
        else
            echo "⚠ UNMERGED (keeping)"
            echo "    Commits ahead of main: $COMMITS_AHEAD"
            echo "    Last commit: $COMMIT_DATE"
            ((SKIPPED++))
        fi
    fi
done <<< "$BRANCH_LIST"

echo ""
echo "========================================================================"
echo "CLEANUP SUMMARY"
echo "========================================================================"
echo "Total branches found: $((MERGED_DELETED + SKIPPED))"
echo "Branches cleaned: $MERGED_DELETED"
echo "Branches preserved: $SKIPPED"
echo ""

if [ "$DRY_RUN" = "true" ]; then
    echo "✓ DRY RUN COMPLETE - No changes made"
    echo "  Run with 'false' argument to execute:"
    echo "  bash scripts/cleanup_main_issue_branches.sh false"
else
    echo "✓ CLEANUP COMPLETE"
fi

echo "========================================================================"
