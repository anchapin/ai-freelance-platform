---
name: parallel-issue-worker
description: "Processes multiple GitHub issues in parallel using git worktrees and subagents. Creates either a single consolidated PR or individual PRs per issue. Use when working on batches of related GitHub issues simultaneously."
---

# Parallel Issue Worker

Orchestrates work on multiple GitHub issues using git worktrees for isolation and subagents for parallel execution. Handles branch management, subagent coordination, and flexible PR creation strategies.

## Core Capabilities

- **Worktree Management**: Creates isolated git worktrees for each issue without interfering with main development
- **Parallel Execution**: Spawns subagents to work on issues simultaneously
- **Smart PR Strategy**: Consolidates work into one PR (sequential rebase) or creates individual PRs
- **Cleanup**: Automatic worktree pruning and branch management
- **Status Tracking**: Real-time progress monitoring of parallel tasks

## Workflow: Parallel Processing

### Step 1: Initialize Batch Job

```bash
amp-parallel-issue-worker init \
  --issues "fix-auth-bug,improve-logging,refactor-database" \
  --strategy "consolidated"
```

Options:
- `--issues`: Comma-separated issue identifiers/URLs
- `--strategy`: `consolidated` (single PR) or `individual` (one PR per issue)
- `--base-branch`: Base branch for worktrees (default: main)
- `--cleanup`: Auto-delete worktrees after completion (default: true)

### Step 2: Define Subagent Instructions

Create a task description for each issue:

```bash
amp-parallel-issue-worker add-task \
  --issue "fix-auth-bug" \
  --instructions "Fix the JWT token expiration bug. Look in src/api/auth.py. Add tests."
```

Or batch define via JSON:

```bash
amp-parallel-issue-worker batch-load tasks.json
```

Example `tasks.json`:
```json
{
  "fix-auth-bug": {
    "instructions": "Fix JWT expiration bug in src/api/auth.py",
    "files": ["src/api/auth.py", "tests/test_auth.py"]
  },
  "improve-logging": {
    "instructions": "Add debug logging to critical paths in executor.py",
    "files": ["src/agent_execution/executor.py"]
  }
}
```

### Step 3: Spawn Subagents

```bash
amp-parallel-issue-worker spawn --max-parallel 3
```

Each subagent:
- Checks out its own worktree: `main-issue-fix-auth-bug`
- Creates a feature branch: `feature/fix-auth-bug`
- Executes the task instructions
- Commits changes with the issue identifier in the message
- Reports completion with diff summary

Monitor progress:

```bash
amp-parallel-issue-worker status
```

### Step 4: Handle Completion

**For `consolidated` strategy:**
```bash
amp-parallel-issue-worker merge --strategy rebase
```
- Rebases all branches onto main in sequence
- Resolves conflicts interactively
- Creates single PR titled: "Address issues: fix-auth-bug, improve-logging, refactor-database"

**For `individual` strategy:**
```bash
amp-parallel-issue-worker create-prs
```
- Creates separate PR for each issue
- Auto-links to GitHub issue if identifiable
- Each PR contains only its issue's changes

### Step 5: Cleanup

```bash
amp-parallel-issue-worker cleanup
```

Removes all worktrees and tracking state.

## Configuration

Store batch job config in `.amp-batch-job`:

```yaml
issues:
  - identifier: "fix-auth-bug"
    branch: "feature/fix-auth-bug"
    worktree: "main-issue-fix-auth-bug"
    status: "in-progress"
  - identifier: "improve-logging"
    branch: "feature/improve-logging"
    worktree: "main-issue-improve-logging"
    status: "pending"

strategy: "consolidated"
base_branch: "main"
started_at: "2025-02-24T10:30:00Z"
```

## Edge Cases

**Merge Conflicts During Rebase**: Subagent pauses, displays conflict markers, prompts user or subagent to resolve manually before continuing.

**Subagent Failure**: Failed issue is marked, other tasks continue. Use `amp-parallel-issue-worker retry --issue fix-auth-bug` to re-run.

**Worktree Already Exists**: Detects stale worktrees, offers to prune or reuse.

**Large Parallel Load**: Respects system resources; queues tasks if max-parallel exceeded.

## Integration with Existing Project

Works with any Git repository. Uses standard git worktree commands:

```bash
git worktree list          # See all active worktrees
git worktree remove <dir>  # Manual cleanup
```

No special setup required beyond git 2.7+.

## Example: Full Workflow

```bash
# 1. Define the issues and strategy
amp-parallel-issue-worker init \
  --issues "auth-fix,logging-improvement,db-refactor" \
  --strategy consolidated

# 2. Add task instructions
amp-parallel-issue-worker add-task \
  --issue "auth-fix" \
  --instructions "Fix JWT token expiration in src/api/auth.py. Add unit tests."

amp-parallel-issue-worker add-task \
  --issue "logging-improvement" \
  --instructions "Add structured logging to executor.py using logger module"

amp-parallel-issue-worker add-task \
  --issue "db-refactor" \
  --instructions "Refactor SQLAlchemy session management for async contexts"

# 3. Spawn parallel agents
amp-parallel-issue-worker spawn --max-parallel 3

# 4. Monitor progress
amp-parallel-issue-worker status

# 5. Consolidate into single PR
amp-parallel-issue-worker merge --strategy rebase

# 6. Create PR (optional: push to GitHub)
# Uses git push to create PR or outputs instructions for manual PR creation
```

## Command Reference

| Command | Purpose |
|---------|---------|
| `init` | Initialize batch job with issues and strategy |
| `add-task` | Define instructions for single issue |
| `batch-load` | Load multiple tasks from JSON file |
| `spawn` | Launch subagents for all pending tasks |
| `status` | Show progress of all issues |
| `merge` | Consolidate branches (consolidated strategy only) |
| `create-prs` | Create individual PRs (individual strategy only) |
| `retry` | Re-run failed issue task |
| `cleanup` | Remove all worktrees and config |

## Implementation Notes

- Subagents are spawned with `@agent` decorator in Amp
- Worktree naming: `{base_branch}-issue-{identifier}`
- Batch state persisted to `.amp-batch-job` YAML
- Commit messages include issue identifier for traceability
- Returns structured JSON for each subagent result for easy aggregation
