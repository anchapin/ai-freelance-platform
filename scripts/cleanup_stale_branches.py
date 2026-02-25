#!/usr/bin/env python3
"""
Cleanup script for stale git branches from issue tracking.

This script:
1. Identifies branches older than 30 days
2. Verifies all commits are merged to main
3. Safely deletes merged branches
4. Generates a cleanup report

Usage:
    python scripts/cleanup_stale_branches.py [--dry-run] [--days 30]
"""

import subprocess
import sys
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Tuple
import argparse
import json


@dataclass
class BranchInfo:
    name: str
    commit_hash: str
    last_commit_date: datetime
    is_merged: bool
    is_local: bool
    commits_ahead: int
    days_old: int


class BranchCleaner:
    """Safely clean up stale git branches."""

    def __init__(self, dry_run: bool = False, days_threshold: int = 30):
        self.dry_run = dry_run
        self.days_threshold = days_threshold
        self.stale_branches: List[BranchInfo] = []
        self.cleaned_branches: List[str] = []
        self.protected_branches = {"main", "develop", "master", "production"}

    def run_git_command(self, cmd: str) -> str:
        """Execute a git command and return output."""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            return result.stdout.strip()
        except Exception as e:
            print(f"Error running git command: {e}")
            return ""

    def get_all_branches(self) -> List[str]:
        """Get list of all local branches."""
        output = self.run_git_command("git branch -l")
        return [b.strip() for b in output.split('\n') if b.strip()]

    def get_branch_commit_info(self, branch: str) -> Tuple[str, datetime]:
        """Get the commit hash and last commit date for a branch."""
        commit_hash = self.run_git_command(f"git rev-parse {branch}")
        timestamp = self.run_git_command(
            f"git log -1 --format=%ai {branch}"
        )
        try:
            # Parse ISO format datetime
            dt = datetime.fromisoformat(timestamp.replace(" ", "T")[:19])
            return commit_hash[:7], dt
        except (ValueError, IndexError):
            return commit_hash[:7], datetime.now()

    def check_if_merged(self, branch: str, target: str = "main") -> Tuple[bool, int]:
        """Check if branch is merged into target and commits ahead."""
        # Check if branch is fully merged
        output = self.run_git_command(f"git branch --merged {target} | grep -E '\\s{branch}$'")
        is_merged = bool(output)

        # Count commits ahead
        try:
            ahead_output = self.run_git_command(
                f"git rev-list --count {target}..{branch}"
            )
            commits_ahead = int(ahead_output) if ahead_output else 0
        except (ValueError, TypeError):
            commits_ahead = 0

        return is_merged, commits_ahead

    def identify_stale_branches(self) -> List[BranchInfo]:
        """Identify branches older than threshold."""
        branches = self.get_all_branches()
        now = datetime.now()
        threshold = now - timedelta(days=self.days_threshold)

        for branch in branches:
            if branch in self.protected_branches:
                continue

            # Skip remote-tracking branches
            if branch.startswith("remotes/"):
                continue

            commit_hash, last_date = self.get_branch_commit_info(branch)
            is_merged, commits_ahead = self.check_if_merged(branch)
            days_old = (now - last_date).days

            if last_date < threshold:
                branch_info = BranchInfo(
                    name=branch,
                    commit_hash=commit_hash,
                    last_commit_date=last_date,
                    is_merged=is_merged,
                    is_local=True,
                    commits_ahead=commits_ahead,
                    days_old=days_old
                )
                self.stale_branches.append(branch_info)

        return self.stale_branches

    def delete_branch(self, branch: str) -> bool:
        """Delete a branch (local only)."""
        if self.dry_run:
            print(f"[DRY RUN] Would delete branch: {branch}")
            return True

        try:
            # Use -D to force delete (ignore merge status)
            output = self.run_git_command(f"git branch -D {branch}")
            self.cleaned_branches.append(branch)
            return True
        except Exception as e:
            print(f"Error deleting branch {branch}: {e}")
            return False

    def cleanup_merged_branches(self) -> dict:
        """Clean up branches that are merged to main."""
        summary = {
            "total_stale": len(self.stale_branches),
            "deletable": [],
            "unmerged": [],
            "protected": [],
        }

        for branch_info in self.stale_branches:
            if branch_info.name in self.protected_branches:
                summary["protected"].append(branch_info.name)
                continue

            if branch_info.is_merged:
                print(f"✓ Deleting merged branch: {branch_info.name} "
                      f"({branch_info.days_old} days old, commit: {branch_info.commit_hash})")
                self.delete_branch(branch_info.name)
                summary["deletable"].append(branch_info.name)
            else:
                print(f"⚠ Skipping unmerged branch: {branch_info.name} "
                      f"({branch_info.commits_ahead} commits ahead of main)")
                summary["unmerged"].append({
                    "branch": branch_info.name,
                    "commits_ahead": branch_info.commits_ahead,
                    "last_commit": branch_info.last_commit_date.isoformat()
                })

        return summary

    def generate_report(self, summary: dict) -> str:
        """Generate a cleanup report."""
        report = [
            "=" * 70,
            "GIT BRANCH CLEANUP REPORT",
            "=" * 70,
            f"Execution Mode: {'DRY RUN' if self.dry_run else 'LIVE'}",
            f"Timestamp: {datetime.now().isoformat()}",
            f"Age Threshold: {self.days_threshold} days",
            "",
            "SUMMARY",
            "-" * 70,
            f"Total Stale Branches Found: {summary['total_stale']}",
            f"Branches Deleted (Merged): {len(summary['deletable'])}",
            f"Branches Skipped (Unmerged): {len(summary['unmerged'])}",
            f"Branches Protected: {len(summary['protected'])}",
            ""
        ]

        if summary["deletable"]:
            report.append("DELETED BRANCHES")
            report.append("-" * 70)
            for branch in summary["deletable"]:
                report.append(f"  ✓ {branch}")
            report.append("")

        if summary["unmerged"]:
            report.append("UNMERGED BRANCHES (Preserved for safety)")
            report.append("-" * 70)
            for item in summary["unmerged"]:
                report.append(f"  ⚠ {item['branch']}")
                report.append(f"    Commits ahead: {item['commits_ahead']}")
                report.append(f"    Last commit: {item['last_commit']}")
            report.append("")

        if summary["protected"]:
            report.append("PROTECTED BRANCHES (Never deleted)")
            report.append("-" * 70)
            for branch in summary["protected"]:
                report.append(f"  ◆ {branch}")
            report.append("")

        report.extend([
            "=" * 70,
            "END OF REPORT",
            "=" * 70,
        ])

        return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(
        description="Clean up stale git branches from issue tracking"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without making changes"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Consider branches older than this many days as stale (default: 30)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Save report to file"
    )

    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("BRANCH CLEANUP UTILITY")
    print("=" * 70 + "\n")

    cleaner = BranchCleaner(dry_run=args.dry_run, days_threshold=args.days)

    print(f"Scanning for branches older than {args.days} days...\n")
    stale = cleaner.identify_stale_branches()

    if not stale:
        print("✓ No stale branches found!")
        return 0

    print(f"Found {len(stale)} stale branch(es):\n")
    for branch in stale:
        print(f"  • {branch.name} ({branch.days_old} days old, merged: {branch.is_merged})")

    print()
    summary = cleaner.cleanup_merged_branches()

    report = cleaner.generate_report(summary)
    print("\n" + report)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"\nReport saved to: {args.output}")

    return 0 if not args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
