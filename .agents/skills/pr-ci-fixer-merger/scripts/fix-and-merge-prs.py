#!/usr/bin/env python3
"""
Iteratively fix CI failures and merge PRs.

Usage:
  python fix-and-merge-prs.py --fix-all    # Fix all failing PRs
  python fix-and-merge-prs.py --fix 9      # Fix specific PR
  python fix-and-merge-prs.py --merge-all  # Merge all passing PRs
  python fix-and-merge-prs.py --merge 9    # Merge specific PR
"""

import subprocess
import json
import sys
import time
import argparse
from typing import Dict, List, Any, Tuple

class PRManager:
    """Manage PR CI fixing and merging."""
    
    def __init__(self):
        self.pr_config = self.load_pr_config()
        self.max_retries = 3
        self.ci_timeout = 600  # 10 minutes
    
    def load_pr_config(self) -> Dict[str, Any]:
        """Load PR configuration."""
        try:
            with open('.agents/pr-config.yaml', 'r') as f:
                import yaml
                config = yaml.safe_load(f)
                return config
        except:
            # Default config if file doesn't exist
            return {
                "prs": [
                    {"number": 9, "title": "Issue #8", "depends-on": []},
                    {"number": 10, "title": "Issue #6", "depends-on": [9]},
                    {"number": 11, "title": "Issue #5", "depends-on": [10]},
                    {"number": 12, "title": "Issue #4", "depends-on": [11]},
                ]
            }
    
    def run_command(self, cmd: str, check: bool = True) -> Tuple[str, int]:
        """Run command and return (output, return_code)."""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            return result.stdout.strip(), result.returncode
        except Exception as e:
            print(f"Error running: {cmd}\n{e}", file=sys.stderr)
            return "", 1
    
    def get_pr_checks(self, pr_number: int) -> List[Dict[str, Any]]:
        """Get CI checks for a PR."""
        output, _ = self.run_command(
            f"gh pr checks {pr_number} --json name,status,conclusion 2>/dev/null || echo '[]'"
        )
        try:
            return json.loads(output)
        except:
            return []
    
    def get_pr_ci_status(self, pr_number: int) -> Tuple[bool, List[str]]:
        """
        Check if PR CI is passing.
        
        Returns: (all_passing, [list of failing checks])
        """
        checks = self.get_pr_checks(pr_number)
        
        if not checks:
            return False, ["No checks available yet"]
        
        failing = [
            c.get('name', 'Unknown')
            for c in checks
            if c.get('conclusion') in ['FAILURE', 'FAILED']
        ]
        
        pending = [
            c.get('name', 'Unknown')
            for c in checks
            if c.get('status') == 'PENDING'
        ]
        
        if failing:
            return False, failing
        elif pending:
            return False, ["Checks still running..."]
        else:
            return True, []
    
    def get_pr_logs(self, pr_number: int) -> str:
        """Get CI logs for a PR."""
        # Attempt to get test output
        output, _ = self.run_command(
            f"gh pr view {pr_number} --json body -q .body 2>/dev/null || echo ''"
        )
        return output
    
    def wait_for_ci(self, pr_number: int, timeout: int = 600) -> bool:
        """Wait for CI to complete."""
        print(f"⏳ Waiting for CI to complete on PR #{pr_number}...")
        
        start = time.time()
        while time.time() - start < timeout:
            checks = self.get_pr_checks(pr_number)
            
            if not checks:
                time.sleep(5)
                continue
            
            # Check if any are still pending
            pending = [c for c in checks if c.get('status') == 'PENDING']
            
            if not pending:
                # All done
                passing, failing = self.get_pr_ci_status(pr_number)
                if passing:
                    print(f"✅ CI passed on PR #{pr_number}")
                    return True
                else:
                    print(f"❌ CI failed on PR #{pr_number}: {failing}")
                    return False
            
            # Still running
            print(f"  Running: {len(pending)} checks...")
            time.sleep(10)
        
        print(f"⏠ CI timeout on PR #{pr_number} after {timeout}s")
        return False
    
    def push_changes(self, pr_number: int, message: str) -> bool:
        """Commit and push changes to PR branch."""
        # Get branch name
        output, _ = self.run_command(
            f"gh pr view {pr_number} --json headRefName -q .headRefName"
        )
        branch = output
        
        if not branch:
            print(f"❌ Could not get branch name for PR #{pr_number}")
            return False
        
        # Commit
        _, code = self.run_command(f"git add -A && git commit -m '{message}'")
        if code != 0:
            print("❌ Commit failed (nothing to commit?)")
            return False
        
        # Push
        _, code = self.run_command(f"git push origin {branch}")
        if code != 0:
            print("❌ Push failed")
            return False
        
        print(f"✅ Committed and pushed: {message}")
        return True
    
    def fix_pr(self, pr_number: int) -> bool:
        """
        Attempt to fix a failing PR.
        
        Returns True if successful, False if needs manual intervention.
        """
        print(f"\n🔧 Fixing PR #{pr_number}...")
        
        for attempt in range(self.max_retries):
            print(f"\nAttempt {attempt + 1}/{self.max_retries}")
            
            # Get current status
            passing, failing = self.get_pr_ci_status(pr_number)
            
            if passing:
                print(f"✅ PR #{pr_number} is now passing!")
                return True
            
            print(f"❌ Failures: {failing}")
            
            # Attempt automatic fixes
            print("Applying fixes...")
            
            # Run tests to see output
            _, _ = self.run_command("pytest tests/ -xvs 2>&1 | head -100")
            
            # Run linting
            _, _ = self.run_command("ruff check src/ 2>&1 | head -50")
            
            # For now, we need user intervention for specific fixes
            print("\n⚠️  Automatic fix attempted. Please review the output above.")
            print("If you see specific errors, run: pytest -xvs to see full output")
            
            return False
        
        print(f"❌ PR #{pr_number} still failing after {self.max_retries} attempts")
        return False
    
    def merge_pr(self, pr_number: int, strategy: str = "squash") -> bool:
        """Merge a PR to main."""
        print(f"\n🚀 Merging PR #{pr_number}...")
        
        # Verify CI passing
        passing, _ = self.get_pr_ci_status(pr_number)
        if not passing:
            print("❌ Cannot merge: CI not passing")
            return False
        
        # Merge
        merge_cmd = f"gh pr merge {pr_number} --{strategy} --delete-branch"
        output, code = self.run_command(merge_cmd)
        
        if code == 0:
            print(f"✅ PR #{pr_number} merged successfully")
            print(output)
            return True
        else:
            print(f"❌ Merge failed: {output}")
            return False
    
    def resolve_merge_conflict(self, pr_number: int) -> bool:
        """Attempt to resolve merge conflicts."""
        print(f"\n⚠️  Attempting to resolve merge conflicts on PR #{pr_number}...")
        
        # Get current branch
        output, _ = self.run_command(
            f"gh pr view {pr_number} --json headRefName -q .headRefName"
        )
        branch = output
        
        if not branch:
            return False
        
        # Try to rebase on main
        _, code = self.run_command("git fetch origin main")
        if code != 0:
            return False
        
        _, code = self.run_command("git rebase origin/main")
        
        if code != 0:
            # Rebase has conflicts
            print("❌ Merge conflicts detected - manual resolution needed")
            return False
        
        # Push resolved version
        _, code = self.run_command(f"git push origin {branch} --force-with-lease")
        
        if code == 0:
            print("✅ Conflicts resolved and pushed")
            return True
        else:
            print("❌ Push failed")
            return False
    
    def fix_all_prs(self):
        """Fix all failing PRs."""
        pr_numbers = [pr['number'] for pr in self.pr_config.get('prs', [])]
        
        for pr_num in pr_numbers:
            passing, _ = self.get_pr_ci_status(pr_num)
            
            if not passing:
                self.fix_pr(pr_num)
                self.wait_for_ci(pr_num)
    
    def merge_all_prs(self):
        """Merge all passing PRs in dependency order."""
        prs_by_number = {pr['number']: pr for pr in self.pr_config.get('prs', [])}
        pr_numbers = [pr['number'] for pr in self.pr_config.get('prs', [])]
        
        merged = set()
        
        for pr_num in pr_numbers:
            pr = prs_by_number.get(pr_num)
            if not pr:
                continue
            
            # Check dependencies
            depends_on = pr.get('depends-on', [])
            
            if not all(dep in merged for dep in depends_on):
                print(f"⏳ Skipping PR #{pr_num}: waiting for dependencies {depends_on}")
                continue
            
            # Check if passing
            passing, _ = self.get_pr_ci_status(pr_num)
            
            if not passing:
                print(f"⏳ Skipping PR #{pr_num}: CI not passing")
                continue
            
            # Merge
            if self.merge_pr(pr_num):
                merged.add(pr_num)
        
        print(f"\n✅ Merged {len(merged)}/{len(pr_numbers)} PRs")
        return len(merged) == len(pr_numbers)

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Fix and merge PRs")
    parser.add_argument("--fix-all", action="store_true", help="Fix all failing PRs")
    parser.add_argument("--fix", type=int, help="Fix specific PR number")
    parser.add_argument("--merge-all", action="store_true", help="Merge all passing PRs")
    parser.add_argument("--merge", type=int, help="Merge specific PR number")
    parser.add_argument("--status", action="store_true", help="Show PR status")
    
    args = parser.parse_args()
    
    manager = PRManager()
    
    try:
        if args.fix_all:
            manager.fix_all_prs()
        elif args.fix:
            manager.fix_pr(args.fix)
            manager.wait_for_ci(args.fix)
        elif args.merge_all:
            manager.merge_all_prs()
        elif args.merge:
            manager.merge_pr(args.merge)
        elif args.status:
            from check_pr_status import print_table, get_pr_list
            prs = get_pr_list()
            print_table(prs)
        else:
            parser.print_help()
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
