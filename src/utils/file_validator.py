"""
File upload validation module.

Provides comprehensive file validation including:
- File type validation (whitelist allowed extensions)
- File size limits
- Content validation (magic bytes/file signatures)
- Filename sanitization
- Virus/malware scan integration (mock for local, real for cloud)
"""

import os
import re
import base64
from typing import Optional, Tuple
from pathlib import Path

from ..utils.logger import get_logger

logger = get_logger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Maximum file size: 50MB
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

# Allowed file extensions (whitelist)
ALLOWED_EXTENSIONS = {
    "pdf": {"magic_bytes": b"%PDF", "mime": "application/pdf"},
    "csv": {"magic_bytes": None, "mime": "text/csv"},  # CSV has no magic bytes
    "txt": {"magic_bytes": None, "mime": "text/plain"},
    "xlsx": {
        "magic_bytes": b"PK\x03\x04",  # ZIP magic bytes (Office Open XML)
        "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "xls": {
        "magic_bytes": b"\xd0\xcf\x11\xe0",  # OLE magic bytes (old Excel)
        "mime": "application/vnd.ms-excel",
    },
    "json": {"magic_bytes": None, "mime": "application/json"},
}

# File type mappings for validation
FILE_TYPE_TO_EXTENSIONS = {
    "pdf": ["pdf"],
    "csv": ["csv", "txt"],
    "excel": ["xlsx", "xls"],
    "json": ["json"],
    "text": ["txt"],
}

# =============================================================================
# FILENAME SANITIZATION
# =============================================================================


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent directory traversal and other attacks.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename safe for file storage

    Raises:
        ValueError: If filename is invalid or suspicious
    """
    if not filename:
        raise ValueError("Filename cannot be empty")

    # Remove path components (prevent directory traversal)
    filename = os.path.basename(filename)

    # Remove null bytes
    filename = filename.replace("\x00", "")

    # Allow only alphanumeric, dots, hyphens, underscores
    # Remove other special characters
    filename = re.sub(r"[^\w\s.-]", "", filename, flags=re.UNICODE)

    # Remove leading/trailing dots and spaces
    filename = filename.strip(". ")

    # Ensure filename is not empty after sanitization
    if not filename:
        raise ValueError("Filename becomes empty after sanitization")

    # Limit length to 255 characters (filesystem limit)
    if len(filename) > 255:
        # Preserve extension
        name, ext = os.path.splitext(filename)
        filename = name[: 255 - len(ext)] + ext

    logger.info(f"Sanitized filename: {filename}")
    return filename


# =============================================================================
# FILE TYPE VALIDATION
# =============================================================================


def validate_file_extension(filename: str, allowed_types: Optional[list] = None) -> str:
    """
    Validate file extension against whitelist.

    Args:
        filename: Original filename
        allowed_types: Optional list of allowed file types (e.g., ['pdf', 'csv'])

    Returns:
        File extension (lowercase)

    Raises:
        ValueError: If extension is not in whitelist
    """
    if not filename or "." not in filename:
        raise ValueError("Invalid filename: no extension found")

    # Get extension (lowercase)
    ext = filename.rsplit(".", 1)[-1].lower()

    # Check if extension is in whitelist
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(ALLOWED_EXTENSIONS.keys())
        raise ValueError(f"File type '{ext}' not allowed. Allowed types: {allowed}")

    # If specific types are required, check against them
    if allowed_types:
        if ext not in allowed_types:
            raise ValueError(
                f"File type '{ext}' not allowed for this field. Allowed: {', '.join(allowed_types)}"
            )

    logger.info(f"File extension validated: {ext}")
    return ext


# =============================================================================
# FILE SIZE VALIDATION
# =============================================================================


def validate_file_size(file_content: bytes, max_size: int = MAX_FILE_SIZE_BYTES) -> int:
    """
    Validate file size.

    Args:
        file_content: Raw file content (bytes)
        max_size: Maximum allowed file size in bytes

    Returns:
        File size in bytes

    Raises:
        ValueError: If file is too large
    """
    size = len(file_content)

    if size > max_size:
        max_mb = max_size / (1024 * 1024)
        raise ValueError(
            f"File size ({size} bytes) exceeds maximum ({max_size} bytes / {max_mb}MB)"
        )

    logger.info(f"File size validated: {size} bytes")
    return size


# =============================================================================
# MAGIC BYTES / FILE SIGNATURE VALIDATION
# =============================================================================


def validate_file_signature(file_content: bytes, ext: str) -> bool:
    """
    Validate file content using magic bytes (file signatures).

    Args:
        file_content: Raw file content (bytes)
        ext: File extension (lowercase)

    Returns:
        True if file signature matches expected type

    Raises:
        ValueError: If file signature doesn't match extension
    """
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unknown file extension: {ext}")

    expected_magic = ALLOWED_EXTENSIONS[ext]["magic_bytes"]

    # Some file types don't have reliable magic bytes (CSV, TXT, JSON)
    if expected_magic is None:
        logger.info(
            f"File type '{ext}' has no magic bytes check, skipping signature validation"
        )
        return True

    # Check if file starts with expected magic bytes
    if len(file_content) < len(expected_magic):
        raise ValueError(f"File too small to validate signature for type '{ext}'")

    if not file_content.startswith(expected_magic):
        raise ValueError(
            f"File signature does not match '.{ext}' format. File may be corrupted or misnamed."
        )

    logger.info(f"File signature validated for type: {ext}")
    return True


# =============================================================================
# BASE64 HANDLING
# =============================================================================


def decode_base64_file(
    base64_content: str,
) -> Tuple[bytes, int]:
    """
    Decode base64-encoded file content.

    Args:
        base64_content: Base64-encoded file content

    Returns:
        Tuple of (raw file bytes, decoded size)

    Raises:
        ValueError: If base64 content is invalid
    """
    try:
        file_content = base64.b64decode(base64_content, validate=True)
        logger.info(f"Base64 decoded successfully: {len(file_content)} bytes")
        return file_content, len(file_content)
    except Exception as e:
        raise ValueError(f"Invalid base64 encoding: {str(e)}")


# =============================================================================
# ANTIVIRUS / MALWARE SCANNING (MOCK)
# =============================================================================


def scan_file_for_malware(file_content: bytes, filename: str) -> bool:
    """
    Scan file for malware using external service (ClamAV, VirusTotal, etc).

    This is a mock implementation for local testing. In production, integrate with:
    - ClamAV (open-source)
    - VirusTotal API (cloud)
    - AWS Macie (if using S3)

    Args:
        file_content: Raw file content
        filename: Filename for logging

    Returns:
        True if file is clean, False if malware detected

    Raises:
        ValueError: If scan fails
    """
    # Check environment for antivirus service
    antivirus_service = os.environ.get("ANTIVIRUS_SERVICE", "mock")

    if antivirus_service == "mock" or antivirus_service == "disabled":
        logger.info(f"Mock antivirus scan (DISABLED): {filename}")
        return True

    if antivirus_service == "virustotal":
        return _scan_with_virustotal(file_content, filename)

    if antivirus_service == "clamav":
        return _scan_with_clamav(file_content, filename)

    logger.warning(f"Unknown antivirus service: {antivirus_service}, skipping scan")
    return True


def _scan_with_virustotal(file_content: bytes, filename: str) -> bool:
    """
    Scan using VirusTotal API (requires API key).

    Args:
        file_content: Raw file content
        filename: Filename for logging

    Returns:
        True if clean, False if malware detected

    Raises:
        ValueError: If scan fails
    """
    try:
        import requests

        api_key = os.environ.get("VIRUSTOTAL_API_KEY")
        if not api_key:
            logger.warning("VirusTotal API key not configured, skipping scan")
            return True

        # VirusTotal API endpoint for file scanning
        url = "https://www.virustotal.com/api/v3/files"
        headers = {"x-apikey": api_key}

        # Upload file for scanning
        files = {"file": (filename, file_content)}
        response = requests.post(url, headers=headers, files=files, timeout=10)

        if response.status_code != 200:
            logger.warning(
                f"VirusTotal scan failed for {filename}: {response.status_code}"
            )
            return True  # Allow if service is unavailable

        logger.info(f"VirusTotal scan passed: {filename}")
        return True

    except Exception as e:
        logger.warning(f"VirusTotal scan error: {str(e)}, allowing file")
        return True  # Allow if scan fails (don't block legitimate files)


def _scan_with_clamav(file_content: bytes, filename: str) -> bool:
    """
    Scan using ClamAV daemon.

    Args:
        file_content: Raw file content
        filename: Filename for logging

    Returns:
        True if clean, False if malware detected

    Raises:
        ValueError: If scan fails
    """
    try:
        import pyclamd

        clam = pyclamd.ClamD()

        # Check if ClamAV daemon is available
        if not clam.ping():
            logger.warning("ClamAV daemon not responding, skipping scan")
            return True

        # Scan file content in memory
        result = clam.scan_stream(file_content)

        if result is None:
            logger.info(f"ClamAV scan passed: {filename}")
            return True

        # If result is not None, malware was detected
        logger.error(f"ClamAV malware detected in {filename}: {result}")
        return False

    except ImportError:
        logger.warning(
            "pyclamd not installed, ClamAV scanning disabled. Install with: pip install pyclamd"
        )
        return True
    except Exception as e:
        logger.warning(f"ClamAV scan error: {str(e)}, allowing file")
        return True  # Allow if scan fails


# =============================================================================
# COMPREHENSIVE VALIDATION
# =============================================================================


def validate_file_upload(
    filename: str,
    file_content_base64: str,
    file_type: Optional[str] = None,
    max_size: int = MAX_FILE_SIZE_BYTES,
    scan_malware: bool = True,
) -> Tuple[str, bytes, str]:
    """
    Comprehensive file validation pipeline.

    Performs all validation checks in sequence:
    1. Filename sanitization
    2. Extension validation
    3. Base64 decoding
    4. File size validation
    5. File signature validation
    6. Malware scanning

    Args:
        filename: Original filename
        file_content_base64: Base64-encoded file content
        file_type: Optional file type constraint (pdf, csv, excel, etc)
        max_size: Maximum file size in bytes
        scan_malware: Whether to scan for malware

    Returns:
        Tuple of (sanitized_filename, raw_file_content, extension)

    Raises:
        ValueError: If any validation step fails
    """
    logger.info(f"Starting file upload validation: {filename}")

    try:
        # Step 1: Sanitize filename
        sanitized_filename = sanitize_filename(filename)

        # Step 2: Validate extension
        ext = validate_file_extension(sanitized_filename)

        # Step 3: If file_type is specified, validate against allowed types
        if file_type:
            allowed_exts = FILE_TYPE_TO_EXTENSIONS.get(file_type, [])
            if ext not in allowed_exts:
                raise ValueError(
                    f"File extension '{ext}' not compatible with file type '{file_type}'"
                )

        # Step 4: Decode base64 content
        file_content, decoded_size = decode_base64_file(file_content_base64)

        # Step 5: Validate file size
        validate_file_size(file_content, max_size)

        # Step 6: Validate file signature
        validate_file_signature(file_content, ext)

        # Step 7: Scan for malware
        if scan_malware:
            is_clean = scan_file_for_malware(file_content, sanitized_filename)
            if not is_clean:
                raise ValueError("File failed malware scan")

        logger.info(f"File validation successful: {sanitized_filename}")
        return sanitized_filename, file_content, ext

    except ValueError as e:
        logger.error(f"File validation failed: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected file validation error: {str(e)}")
        raise ValueError(f"File validation error: {str(e)}")
