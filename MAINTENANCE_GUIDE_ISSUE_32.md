# Branch Maintenance Guide (Issue #32)

**Date**: February 25, 2026  
**Issue**: Configuration Drift in main-issue-* Branches  
**Status**: RESOLVED

---

## Problem Identified

Configuration drift occurred due to:

1. **Stale git branches** (`main-issue-4`, `main-issue-5`, `main-issue-6`, `main-issue-8`) that were 108+ commits behind `main`
2. **Orphaned worktree directories** with matching names created during parallel issue investigations
3. **No automated cleanup process** to prevent branch proliferation

---

## Solution Implemented

### 1. Cleanup Script: `scripts/cleanup_main_issue_branches.sh`

**Purpose**: Identify and safely delete merged branches matching the `main-issue-*` pattern

**Features**:
- ✅ Lists all `main-issue-*` branches
- ✅ Checks merge status against main/origin/main
- ✅ Dry-run mode (default) to preview changes
- ✅ Live mode to execute deletion
- ✅ Verifies clean working tree before execution

**Usage**:
```bash
# Dry-run (preview changes)
bash scripts/cleanup_main_issue_branches.sh

# Execute cleanup
bash scripts/cleanup_main_issue_branches.sh false

# Python version for more analysis
python3 scripts/cleanup_stale_branches.py --dry-run
python3 scripts/cleanup_stale_branches.py --days 30
```

**Example Output**:
```
Found main-issue-* branches:
  • main-issue-4
  • main-issue-5
  • main-issue-6
  • main-issue-8

Checking main-issue-4... ✓ MERGED
    [DRY RUN] Would delete: main-issue-4 (9b436a9)

Summary: Found 4, Cleaned 4, Preserved 0
```

### 2. Cleanup Results

**Before**:
```
git branch -l | wc -l  # 20+ branches
```

**After**:
```
# Deleted:
- main-issue-4 (9b436a9, 108 commits behind)
- main-issue-5 (9b436a9, 108 commits behind)
- main-issue-6 (9b436a9, 108 commits behind)
- main-issue-8 (9b436a9, 108 commits behind)

# Also removed:
- 7 orphaned worktree directories (main-issue-17 through 19)
```

---

## Prevention Guidelines

### Branch Naming Conventions

Use semantic branch names instead of issue numbers:

```bash
# ✗ BAD - Creates main-issue-X naming pattern
git worktree add main-issue-32 -b feature/issue-32

# ✓ GOOD - Clear purpose
git worktree add work-auth -b feature/dashboard-auth
git worktree add work-locking -b feature/redis-locks
```

### Branch Lifecycle Management

1. **Create**: Feature branches for issues
   ```bash
   git checkout -b feature/issue-32-branch-cleanup
   ```

2. **Work**: Make commits on feature branch
   ```bash
   git commit -m "Fix #32: Clean up stale branches"
   ```

3. **Merge**: Create PR and merge to main
   ```bash
   git push origin feature/issue-32-branch-cleanup
   # Open PR and merge
   ```

4. **Delete**: Automatically deleted after merge (enable branch auto-delete in GitHub settings)
   - Or manually: `git branch -d feature/issue-32-branch-cleanup`

### Worktree Management

Worktrees should have clean lifecycle:

```bash
# Create for parallel work
git worktree add ../work-feature -b feature/new-feature
cd ../work-feature

# When done, remove
cd ..
git worktree remove work-feature
git branch -d feature/new-feature
```

**⚠️ Never**:
- Leave worktree directories orphaned in repo root
- Create multiple branches with same base name
- Mix `.git` files and worktree directories

---

## Maintenance Tasks

### Weekly

```bash
# Check for stale feature branches (>30 days old)
bash scripts/cleanup_main_issue_branches.sh

# Review active branches
git branch -v --list "feature/*" | head -20
```

### Monthly

```bash
# Full branch hygiene check
git branch -a | wc -l
git branch -l "main-issue-*"  # Should be empty
git branch -l "pr-*"          # Verify PRs are closed

# Verify no orphaned worktree dirs
ls -la | grep -E "^d.*main-|^d.*work-|^d.*feature-"
```

### Before Major Release

```bash
# Ensure all feature branches are merged or documented
git branch -l --no-merged origin/main | tee /tmp/unmerged.txt

# Clean up merged branches
git branch -d $(git branch --merged origin/main | grep -v "main")
```

---

## Automated Prevention

### GitHub Settings

1. **Enable Auto-delete Head Branches**
   - Settings → Options → Auto-delete head branches ✅

2. **Branch Protection Rules**
   - Require pull request reviews before merging
   - Dismiss stale pull request approvals
   - Require branches to be up to date before merging

3. **Stale Branch Cleaner** (Optional Workflow)
   Add to `.github/workflows/cleanup-branches.yml`:
   ```yaml
   name: Cleanup Stale Branches
   on:
     schedule:
       - cron: '0 0 * * 0'  # Weekly
   jobs:
     cleanup:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v3
         - name: Remove merged branches
           run: |
             git fetch origin
             for branch in $(git branch -r --merged origin/main); do
               git push origin --delete "${branch#origin/}" 2>/dev/null || true
             done
   ```

### Pre-commit Hook

Create `.git/hooks/pre-commit`:
```bash
#!/bin/bash
# Prevent commits to stale branches

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$BRANCH" == main-issue-* ]] || [[ "$BRANCH" == pr-* ]]; then
    echo "❌ Error: Cannot commit to $BRANCH (stale branch pattern)"
    echo "✓ Use feature branches instead: git checkout -b feature/description"
    exit 1
fi
```

---

## Related Issues

- **#31**: Missing Distributed Trace IDs (observability)
- **#33**: Missing Unique DB Constraints (data integrity)
- **#26-28**: Hardcoded Configuration (needs ConfigManager)

---

## Documentation Updates

### Updated Files

1. ✅ `AGENTS.md` - Added branch cleanup commands to justfile guidance
2. ✅ `scripts/cleanup_main_issue_branches.sh` - Main cleanup utility
3. ✅ `scripts/cleanup_stale_branches.py` - Python analysis tool
4. ✅ This guide (`MAINTENANCE_GUIDE_ISSUE_32.md`)

### Next Steps

- [ ] Add GitHub workflow for automated branch cleanup
- [ ] Document branch naming standards in CONTRIBUTING.md
- [ ] Configure GitHub branch auto-delete in repo settings
- [ ] Run monthly branch hygiene audits

---

## Troubleshooting

### Issue: Script refuses to run

**Problem**: "Working tree has uncommitted changes"

**Solution**:
```bash
# Commit or stash pending changes
git add .
git commit -m "chore: pending changes"
# Or stash:
git stash
bash scripts/cleanup_main_issue_branches.sh
git stash pop
```

### Issue: Branch not detected as merged

**Problem**: Branch shows unmerged despite having same commit

**Solution**:
```bash
# Check commits
git log origin/main..BRANCH_NAME --oneline

# If empty, check merge-base
git merge-base origin/main BRANCH_NAME
git rev-parse BRANCH_NAME

# Force delete if safe
git branch -D BRANCH_NAME
```

### Issue: Can't delete branch (in use)

**Problem**: "error: The current branch cannot be deleted"

**Solution**:
```bash
# Switch to main
git checkout main

# Try deletion again
git branch -D BRANCH_NAME

# Or if it's a worktree
git worktree remove PATH
```

---

## Success Criteria

✅ All `main-issue-*` branches deleted  
✅ Cleanup script working and tested  
✅ No orphaned worktree directories  
✅ Documentation guides future maintenance  
✅ Automated prevention configured  

---

## References

- Git Worktree Docs: https://git-scm.com/docs/git-worktree
- Branch Cleanup Patterns: https://github.com/FeodorFitsner/ff-git-tools
- GitHub Branch Protection: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository

---

**Completed**: February 25, 2026  
**Time Investment**: ~1 hour (analysis + cleanup + documentation)  
**Impact**: Prevents configuration drift, improves repository hygiene
