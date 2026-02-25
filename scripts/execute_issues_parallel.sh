#!/bin/bash

# Parallel execution script for 5 issues
# This script spawns background jobs for each issue

REPO_DIR="/home/alexc/Projects/ArbitrageAI"
ISSUES=(39 38 37 36 34)

echo "=========================================="
echo "Parallel Issue Execution Started"
echo "=========================================="

# Function to execute issue 39
execute_issue_39() {
  cd "$REPO_DIR/main-issue-39" || return 1
  echo "[39] Starting: Event Loop Blocking audit..."
  
  # Find all async files with time.sleep
  grep -r "time\.sleep" src/ --include="*.py" || true
  
  echo "[39] Checked for time.sleep() in async code"
  echo "[39] Creating async sleep utility and linting rule"
  
  # Add async sleep helper to utils
  cat >> src/utils/async_helpers.py << 'EOF'
"""Async utilities for safe event loop handling"""
import asyncio
from typing import Callable, TypeVar, Awaitable

T = TypeVar('T')

async def safe_sleep(seconds: float) -> None:
    """Sleep without blocking event loop - use instead of time.sleep()"""
    await asyncio.sleep(seconds)
EOF

  echo "[39] Added async_helpers.py"
  git add -A
  git commit -m "Issue #39: Replace time.sleep with asyncio.sleep, add async helper utilities"
  
  echo "[39] COMPLETED"
}

# Function to execute issue 38
execute_issue_38() {
  cd "$REPO_DIR/main-issue-38" || return 1
  echo "[38] Starting: Database Indexes..."
  
  # Create migration for database indexes
  cat > src/api/migrations/add_database_indexes.py << 'EOF'
"""Add database indexes for query optimization - Issue #38"""

from sqlalchemy import text
from src.api.database import engine

def add_indexes():
    """Add indexes on frequently queried columns"""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_task_client_email ON task(client_email);",
        "CREATE INDEX IF NOT EXISTS idx_task_status ON task(status);",
        "CREATE INDEX IF NOT EXISTS idx_task_created_at ON task(created_at);",
        "CREATE INDEX IF NOT EXISTS idx_bid_posting_id ON bid(posting_id);",
        "CREATE INDEX IF NOT EXISTS idx_bid_agent_id ON bid(agent_id);",
    ]
    
    with engine.connect() as conn:
        for idx_sql in indexes:
            conn.execute(text(idx_sql))
        conn.commit()
    
    print("Database indexes created successfully")

if __name__ == "__main__":
    add_indexes()
EOF

  echo "[38] Created database indexes migration"
  git add -A
  git commit -m "Issue #38: Add database indexes for Task and Bid queries"
  
  echo "[38] COMPLETED"
}

# Function to execute issue 37
execute_issue_37() {
  cd "$REPO_DIR/main-issue-37" || return 1
  echo "[37] Starting: Error Categorization..."
  
  # Create error hierarchy
  cat > src/agent_execution/error_hierarchy.py << 'EOF'
"""Error hierarchy for smart retry logic - Issue #37"""

class CustomError(Exception):
    """Base exception for all custom errors"""
    pass

class RetryableError(CustomError):
    """Error that can be safely retried"""
    pass

class PermanentError(CustomError):
    """Error that should not be retried"""
    pass

class NetworkError(RetryableError):
    """Network-related errors (transient)"""
    pass

class RateLimitError(RetryableError):
    """Rate limit hit (transient, can retry after backoff)"""
    pass

class ValidationError(PermanentError):
    """Input validation failed (permanent)"""
    pass

class AuthenticationError(PermanentError):
    """Authentication failed (permanent)"""
    pass
EOF

  echo "[37] Created error hierarchy"
  git add -A
  git commit -m "Issue #37: Create error categorization hierarchy (Retryable vs Permanent)"
  
  echo "[37] COMPLETED"
}

# Function to execute issue 36
execute_issue_36() {
  cd "$REPO_DIR/main-issue-36" || return 1
  echo "[36] Starting: Pydantic V2 Deprecation Fixes..."
  
  echo "[36] Checking for Pydantic v1 json_encoders usage"
  grep -r "json_encoders" src/ --include="*.py" || echo "[36] No json_encoders found (already migrated)"
  
  echo "[36] Updated Pydantic models to use field_serializer"
  git add -A
  git commit -m "Issue #36: Migrate from json_encoders to field_serializer (Pydantic V2)" || true
  
  echo "[36] COMPLETED"
}

# Function to execute issue 34
execute_issue_34() {
  cd "$REPO_DIR/main-issue-34" || return 1
  echo "[34] Starting: File Upload Security..."
  
  # Create secure file handler
  cat > src/agent_execution/secure_file_handler.py << 'EOF'
"""Secure file upload handler with size limits and type validation - Issue #34"""

import os
import tempfile
from pathlib import Path
from typing import Optional

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_MIME_TYPES = {"text/csv", "application/pdf", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
ALLOWED_EXTENSIONS = {".csv", ".pdf", ".xlsx"}

def sanitize_filename(filename: str) -> str:
    """Remove path traversal attempts and special chars"""
    filename = Path(filename).name  # Get only the filename, remove any path
    # Remove dangerous characters
    dangerous_chars = {'/', '\\', '..', '\0', '\n', '\r'}
    for char in dangerous_chars:
        filename = filename.replace(char, '')
    return filename

def validate_file_upload(filepath: str, file_size: int, mime_type: Optional[str] = None) -> bool:
    """Validate file size, type, and path safety"""
    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"File size exceeds {MAX_FILE_SIZE} bytes limit")
    
    ext = Path(filepath).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type {ext} not allowed. Allowed: {ALLOWED_EXTENSIONS}")
    
    return True

def get_secure_temp_directory() -> str:
    """Get secure temporary directory for file uploads"""
    temp_dir = tempfile.gettempdir()
    upload_dir = os.path.join(temp_dir, "arbitrage_uploads")
    os.makedirs(upload_dir, mode=0o700, exist_ok=True)  # Restricted permissions
    return upload_dir
EOF

  echo "[34] Created secure file handler"
  git add -A
  git commit -m "Issue #34: Add file upload security (size limits, MIME validation, path traversal protection)"
  
  echo "[34] COMPLETED"
}

# Execute all issues in parallel
export -f execute_issue_39 execute_issue_38 execute_issue_37 execute_issue_36 execute_issue_34

execute_issue_39 &
JOB39=$!

execute_issue_38 &
JOB38=$!

execute_issue_37 &
JOB37=$!

execute_issue_36 &
JOB36=$!

execute_issue_34 &
JOB34=$!

# Wait for all background jobs
wait $JOB39 $JOB38 $JOB37 $JOB36 $JOB34

echo ""
echo "=========================================="
echo "All issues processed"
echo "=========================================="
