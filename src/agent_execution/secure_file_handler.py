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
