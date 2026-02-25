#!/usr/bin/env python3
"""
Check status of all open PRs and their CI checks.

Usage: python check-pr-status.py [--json]
"""

import subprocess
import json
import sys
from typing import Dict, List, Any

def run_command(cmd: str, check=True) -> str:
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=check
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {cmd}", file=sys.stderr)
        print(f"stderr: {e.stderr}", file=sys.stderr)
        raise

def get_pr_list() -> List[Dict[str, Any]]:
    """Get list of open PRs."""
    output = run_command(
        "gh pr list --state open --json number,title,headRefName,statusCheckRollup"
    )
    return json.loads(output)

def get_pr_checks(pr_number: int) -> Dict[str, Any]:
    """Get CI check status for a specific PR."""
    output = run_command(
        f"gh pr checks {pr_number} --json name,status,conclusion --jq '.' 2>/dev/null || echo '[]'",
        check=False
    )
    try:
        checks = json.loads(output)
        return checks
    except json.JSONDecodeError:
        return []

def format_status(status: str) -> str:
    """Format status with emoji."""
    if status == "PASS":
        return "✅ PASS"
    elif status == "FAIL":
        return "❌ FAIL"
    elif status == "PENDING":
        return "⏳ PENDING"
    elif status == "SKIPPED":
        return "⏭️  SKIPPED"
    else:
        return f"❓ {status}"

def print_table(prs: List[Dict[str, Any]]):
    """Print PR status as a table."""
    print("\n" + "="*100)
    print(f"{'PR':<5} {'Title':<45} {'Status':<20} {'Branch':<30}")
    print("="*100)
    
    for pr in prs:
        number = pr['number']
        title = pr['title'][:42] + "..." if len(pr['title']) > 45 else pr['title']
        
        # Get overall status
        checks = get_pr_checks(number)
        
        if not checks:
            status = "⏳ NO CHECKS YET"
        else:
            # Count results
            passed = sum(1 for c in checks if c.get('conclusion') == 'SUCCESS')
            failed = sum(1 for c in checks if c.get('conclusion') == 'FAILURE')
            pending = sum(1 for c in checks if c.get('status') == 'PENDING')
            
            total = len(checks)
            
            if failed > 0:
                status = f"❌ {failed}/{total} FAILED"
            elif pending > 0:
                status = f"⏳ {pending}/{total} RUNNING"
            elif passed == total:
                status = f"✅ {passed}/{total} PASSING"
            else:
                status = f"❓ {passed}/{total} OTHER"
        
        branch = pr['headRefName'][:27] + "..." if len(pr['headRefName']) > 30 else pr['headRefName']
        
        print(f"{number:<5} {title:<45} {status:<20} {branch:<30}")
    
    print("="*100 + "\n")

def print_detailed_checks(prs: List[Dict[str, Any]]):
    """Print detailed check results."""
    for pr in prs:
        number = pr['number']
        title = pr['title']
        
        checks = get_pr_checks(number)
        
        if not checks:
            continue
        
        # Check if any failures
        failures = [c for c in checks if c.get('conclusion') == 'FAILURE']
        
        if failures:
            print(f"\nPR #{number}: {title}")
            print(f"{'  Check':<50} {'Status':<20}")
            print("  " + "-"*68)
            for check in checks:
                name = check.get('name', 'Unknown')[:47] + "..." if len(check.get('name', 'Unknown')) > 50 else check.get('name', 'Unknown')
                conclusion = check.get('conclusion', 'UNKNOWN')
                status = format_status(conclusion)
                print(f"  {name:<50} {status:<20}")

def print_json(prs: List[Dict[str, Any]]):
    """Print results as JSON."""
    results = []
    
    for pr in prs:
        number = pr['number']
        checks = get_pr_checks(number)
        
        failed = sum(1 for c in checks if c.get('conclusion') == 'FAILURE')
        passed = sum(1 for c in checks if c.get('conclusion') == 'SUCCESS')
        pending = sum(1 for c in checks if c.get('status') == 'PENDING')
        
        results.append({
            "number": number,
            "title": pr['title'],
            "branch": pr['headRefName'],
            "checks": {
                "total": len(checks),
                "passed": passed,
                "failed": failed,
                "pending": pending,
                "details": checks
            },
            "all_passing": failed == 0 and pending == 0 and passed > 0
        })
    
    print(json.dumps(results, indent=2))

def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Check status of open PRs")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--detailed", action="store_true", help="Show detailed check results")
    args = parser.parse_args()
    
    try:
        prs = get_pr_list()
        
        if not prs:
            print("No open PRs found")
            return 0
        
        if args.json:
            print_json(prs)
        else:
            print_table(prs)
            
            if args.detailed:
                print_detailed_checks(prs)
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
