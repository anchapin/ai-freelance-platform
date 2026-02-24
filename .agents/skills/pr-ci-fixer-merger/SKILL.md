---
name: pr-ci-fixer-merger
description: "Iteratively fixes CI failures in open PRs and merges them when tests pass. Handles merge conflicts and coordinates multi-PR merges. Use when PRs have failing CI checks or when ready to merge PRs."
---

# PR CI Fixer & Merger

Automates the workflow of fixing CI failures in pull requests and merging them to main when all checks pass.

## Capabilities

- **Check PR Status**: Monitor CI check status for each open PR
- **Identify Failures**: Parse CI logs to identify test failures, lint issues, and other problems
- **Fix Code**: Automatically fix common issues (imports, type hints, test fixes)
- **Iterate**: Commit fixes and re-run CI until all checks pass
- **Merge Strategy**: Merge PRs in dependency order with conflict resolution
- **Reporting**: Provide detailed status on PR merge progress

## Workflow

### Phase 1: Check CI Status
```
For each open PR:
1. Get current CI status (pytest, linting, type checks)
2. Parse failure logs
3. Categorize failures (test failures, lint errors, import errors, etc)
```

### Phase 2: Fix Issues Iteratively
```
For each failing PR:
1. Identify root cause of failure
2. Apply targeted fix
3. Commit with clear message
4. Push to PR branch
5. Wait for CI to complete
6. Repeat until all checks pass
```

### Phase 3: Merge PRs
```
In dependency order:
1. Resolve any merge conflicts
2. Merge to main with squash or merge commit
3. Update next PR base branch if needed
4. Repeat until all PRs merged
```

## Usage

### Check PR Status
```bash
amp check-pr-status
```

Outputs table with current CI status for each open PR:
- PR number and title
- Current status (all checks passing / failures)
- Number of failing tests
- Last updated

### Fix PR Failures
```bash
amp fix-pr-failures --pr <pr-number>
```

Or fix all failing PRs:
```bash
amp fix-all-pr-failures
```

This will:
1. Check current failure status
2. Apply fixes iteratively
3. Report completion status

### Merge PRs
```bash
amp merge-prs --order dependency
```

Merges all open PRs in dependency order when CI passes.

With conflict resolution:
```bash
amp merge-prs --resolve-conflicts
```

Will attempt to resolve merge conflicts automatically using standard strategies.

## Configuration

Create `.agents/pr-config.yaml`:

```yaml
# PR Configuration
prs:
  - number: 9
    title: "Issue #8: Distributed Lock"
    depends-on: []
    
  - number: 10
    title: "Issue #6: Vector DB Decouple"
    depends-on: [9]
    
  - number: 11
    title: "Issue #5: Task Composition"
    depends-on: [10]
    
  - number: 12
    title: "Issue #4: Playwright Leaks"
    depends-on: [11]

# Auto-fix strategies
auto-fix:
  - strategy: pytest-import-error
    action: add-import
    
  - strategy: pytest-type-error
    action: fix-type-hint
    
  - strategy: pylint-import-error
    action: check-import
    
  - strategy: test-assertion-error
    action: review-test

# Merge settings
merge:
  base-branch: main
  strategy: squash  # or 'merge' for merge commits
  delete-branch: true
  require-ci-pass: true
```

## Common Issues & Fixes

### Import Errors
```
ERROR: ModuleNotFoundError: No module named 'src.api.models_composition'
```

Fix: Ensure module is properly importable, check `__init__.py` files

### Type Hint Errors
```
ERROR: NameError: name 'Float' is not defined
```

Fix: Add missing imports from sqlalchemy

### Test Failures
```
FAILED test_X: AssertionError: expected X got Y
```

Fix: Review test logic, update assertion or implementation

### Merge Conflicts
```
CONFLICT: merge conflict in src/api/models.py
```

Fix: Automatically resolve using strategies:
- Take ours (current branch)
- Take theirs (incoming branch)
- Manual merge with conflict markers

## Dependency Management

PRs can have dependencies specified:
```yaml
pr-9:  depends-on: []           # No dependencies
pr-10: depends-on: [9]          # Depends on PR #9
pr-11: depends-on: [10]         # Depends on PR #10
pr-12: depends-on: [11]         # Depends on PR #11
```

When merging, respects dependency order:
1. Merge PR #9 first
2. Once merged, update PR #10 base to latest main
3. Merge PR #10
4. Continue with #11, #12

## Reporting

After CI check:
```
PR #9 (Issue #8): ✅ ALL CHECKS PASSING
PR #10 (Issue #6): ❌ 2 FAILURES
  - test_vector_db_decouple.py::TestAsyncRAGService::test_get_few_shot_examples_success
  - test_vector_db_decouple.py::TestBackgroundJobQueue::test_queue_job_failure_with_retry

PR #11 (Issue #5): ⏳ RUNNING
PR #12 (Issue #4): ⏳ PENDING (waiting for #11)
```

After fixing:
```
PR #9 (Issue #8): ✅ MERGED to main
PR #10 (Issue #6): ✅ ALL CHECKS PASSING - Ready to merge
PR #11 (Issue #5): ✅ ALL CHECKS PASSING - Ready to merge
PR #12 (Issue #4): ✅ ALL CHECKS PASSING - Ready to merge
```

## Implementation Details

### Check Status
1. Use `gh pr checks` to get CI status
2. Parse pytest output for test failures
3. Parse linting output for style issues
4. Categorize by error type

### Fix Strategy
1. Parse error message to identify issue
2. Apply targeted fix based on error type
3. Commit with descriptive message
4. Push to PR branch (creates new CI run)
5. Poll for CI completion
6. Repeat if still failing

### Merge Strategy
1. Verify all CI checks passing
2. Identify merge conflicts (if any)
3. Attempt automatic resolution
4. Perform merge
5. Verify merge successful
6. Update next PR if dependent

## Error Handling

- **CI Timeout**: If CI takes >30min, check logs manually
- **Merge Conflict**: Attempt auto-resolve, escalate to user if complex
- **Unknown Failure**: Log full error output, ask user for guidance
- **Dependency Issue**: Don't merge if dependent PR hasn't merged yet

## Example Workflow

```
User: "Fix CI and merge all PRs"

Agent:
1. ✅ PR #9: All checks passing
2. ❌ PR #10: 2 test failures
   - Fixing test_async_rag_service.py...
   - Committed fix, waiting for CI
   - ✅ CI passed after fix
3. ✅ PR #11: All checks passing
4. ✅ PR #12: All checks passing

Merging in dependency order:
1. ✅ Merged PR #9 to main
2. ✅ Merged PR #10 to main
3. ✅ Merged PR #11 to main
4. ✅ Merged PR #12 to main

All PRs successfully merged! 🎉
```

## Troubleshooting

### PR Still Failing After Fix
1. Check error message for different issue
2. Review test logic
3. Check dependencies with other PRs
4. Ask user for guidance

### Merge Conflict Too Complex
1. Auto-resolution attempted but failed
2. Show conflict markers to user
3. Ask user to resolve manually
4. Proceed with merge

### CI Check Timeout
1. Check last CI run status
2. If still running, wait up to 10 minutes more
3. If stuck, check GitHub Actions logs
4. May need to re-trigger CI run

## See Also

- GitHub CLI: `gh pr --help`
- pytest: `pytest --help`
- ruff: `ruff check --help`
