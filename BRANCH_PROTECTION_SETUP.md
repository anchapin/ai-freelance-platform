# Branch Protection Setup for Main Branch

## Overview
This document provides steps to protect the `main` branch to prevent direct commits and require pull requests with proper review workflows.

## Steps to Enable Branch Protection

### Via GitHub Web UI (Recommended)

1. **Go to Repository Settings**
   - Navigate to: https://github.com/anchapin/arbitrageai/settings/branches

2. **Add Branch Protection Rule**
   - Click "Add rule"
   - Branch name pattern: `main`

3. **Configure Protection Settings**

   **Required PR Reviews:**
   - ✅ Require a pull request before merging
   - ✅ Require approvals (set to 1-2 reviewers)
   - ✅ Dismiss stale pull request approvals when new commits are pushed

   **Require Status Checks:**
   - ✅ Require status checks to pass before merging
   - ✅ Require branches to be up to date before merging
   - Select required checks:
     - `ci` (or your CI workflow name from `.github/workflows/`)

   **Enforce Rules:**
   - ✅ Include administrators (so rules apply to everyone)
   - ✅ Restrict who can push to matching branches (optional - allow only deploy roles)
   - ✅ Allow force pushes (optional - disable to prevent accidents)
   - ✅ Allow deletions (optional - disable to prevent accidental deletion)

4. **Save Protection Rule**
   - Click "Create" or "Update"

## Alternative: GitHub CLI Setup

If you prefer command-line automation, use the GitHub CLI:

```bash
# Install GitHub CLI if not already installed
# https://cli.github.com/

# Set branch protection
gh repo edit --enable-auto-merge --enable-delete-branch-on-merge

# Create branch protection rule
gh api repos/anchapin/arbitrageai/branches/main/protection \
  -X PUT \
  -f required_pull_request_reviews='{
    "dismissal_restrictions": {},
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1
  }' \
  -f required_status_checks='{
    "strict": true,
    "contexts": ["ci"]
  }' \
  -f enforce_admins=true \
  -f allow_force_pushes=false \
  -f allow_deletions=false
```

## Workflow for Developers

Once branch protection is enabled, developers must follow this workflow:

1. **Create a Feature Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Push to Origin**
   ```bash
   git push origin feature/your-feature-name
   ```

3. **Create a Pull Request**
   - Go to: https://github.com/anchapin/arbitrageai/compare/main...feature/your-feature-name
   - Or click "New Pull Request" on GitHub

4. **Wait for CI to Pass**
   - Automated tests must pass

5. **Get Code Review**
   - At least 1 reviewer must approve

6. **Merge to Main**
   - Squash, rebase, or create a merge commit (your choice)
   - Delete the feature branch

## Verification

To verify branch protection is active:

```bash
# Check current branch protection rules
gh api repos/anchapin/arbitrageai/branches/main/protection

# Or check in UI: Settings > Branches > Branch protection rules
```

## Benefits

- ✅ No accidental direct commits to main
- ✅ All changes go through code review
- ✅ CI/CD checks must pass before merge
- ✅ Maintains clean, reliable main branch
- ✅ Enforces team collaboration standards

## Troubleshooting

**"Can't push to main":**
- This is intentional! Create a feature branch instead
- `git checkout -b feature/your-changes && git push origin feature/your-changes`

**"Can't merge my PR":**
- Ensure all status checks pass (green checkmarks)
- Get required number of approvals
- Ensure your branch is up to date with main

**Need to merge without checks (emergency only):**
- Temporarily disable protection in Settings
- Merge the change
- Re-enable protection immediately
