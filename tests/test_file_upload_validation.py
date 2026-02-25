"""
Unit tests for file upload validation (Issue #34).

Tests comprehensive file validation including:
- Filename sanitization
- File type/extension validation
- File size validation
- Magic bytes/signature validation
- Malware scanning (mock)
"""

import base64
import pytest
from pathlib import Path

from src.utils.file_validator import (
    sanitize_filename,
    validate_file_extension,
    validate_file_size,
    validate_file_signature,
    decode_base64_file,
    scan_file_for_malware,
    validate_file_upload,
    MAX_FILE_SIZE_BYTES,
    ALLOWED_EXTENSIONS,
)


# =============================================================================
# FILENAME SANITIZATION TESTS
# =============================================================================


class TestFilenamesSanitization:
    """Test filename sanitization."""

    def test_sanitize_valid_filename(self):
        """Test sanitization of valid filename."""
        assert sanitize_filename("document.pdf") == "document.pdf"
        assert sanitize_filename("my_file-2025.csv") == "my_file-2025.csv"

    def test_sanitize_remove_directory_traversal(self):
        """Test that directory traversal attempts are removed."""
        assert sanitize_filename("../../../etc/passwd") == "etcpasswd"
        assert sanitize_filename("..\\..\\windows\\system32") == "windowssystem32"

    def test_sanitize_remove_special_chars(self):
        """Test that special characters are removed."""
        assert (
            sanitize_filename("file@#$%^&*().pdf")
            == "file.pdf"
        )
        assert sanitize_filename("file[1].txt") == "file1.txt"

    def test_sanitize_remove_null_bytes(self):
        """Test that null bytes are removed."""
        assert sanitize_filename("file\x00.pdf") == "file.pdf"

    def test_sanitize_remove_leading_trailing_dots(self):
        """Test that leading/trailing dots are removed."""
        assert sanitize_filename(".hidden.pdf") == "hidden.pdf"
        assert sanitize_filename("file.pdf...") == "file.pdf"

    def test_sanitize_truncate_long_filename(self):
        """Test that long filenames are truncated to 255 chars."""
        long_name = "a" * 300 + ".pdf"
        result = sanitize_filename(long_name)
        assert len(result) <= 255
        assert result.endswith(".pdf")

    def test_sanitize_empty_filename(self):
        """Test that empty filename raises error."""
        with pytest.raises(ValueError, match="cannot be empty"):
            sanitize_filename("")

    def test_sanitize_whitespace_only(self):
        """Test that whitespace-only filename raises error."""
        with pytest.raises(ValueError, match="becomes empty"):
            sanitize_filename("   ")

    def test_sanitize_unicode_handling(self):
        """Test that unicode characters are preserved."""
        # Unicode alphanumeric should be preserved
        result = sanitize_filename("документ_2025.pdf")
        assert "2025" in result
        assert ".pdf" in result


# =============================================================================
# FILE EXTENSION VALIDATION TESTS
# =============================================================================


class TestFileExtensionValidation:
    """Test file extension validation."""

    def test_validate_allowed_extensions(self):
        """Test validation of allowed extensions."""
        assert validate_file_extension("document.pdf") == "pdf"
        assert validate_file_extension("data.csv") == "csv"
        assert validate_file_extension("spreadsheet.xlsx") == "xlsx"
        assert validate_file_extension("spreadsheet.xls") == "xls"

    def test_validate_case_insensitive(self):
        """Test that extension validation is case-insensitive."""
        assert validate_file_extension("FILE.PDF") == "pdf"
        assert validate_file_extension("Data.CSV") == "csv"
        assert validate_file_extension("Sheet.XlSx") == "xlsx"

    def test_validate_disallowed_extension(self):
        """Test that disallowed extensions are rejected."""
        with pytest.raises(ValueError, match="not allowed"):
            validate_file_extension("script.exe")

    def test_validate_with_allowed_types(self):
        """Test validation with specific allowed types."""
        # Should pass - pdf is in whitelist
        assert validate_file_extension("doc.pdf", allowed_types=["pdf"]) == "pdf"

        # Should fail - csv not in allowed_types
        with pytest.raises(ValueError):
            validate_file_extension("data.csv", allowed_types=["pdf", "xlsx"])

    def test_validate_no_extension(self):
        """Test that file without extension is rejected."""
        with pytest.raises(ValueError, match="no extension"):
            validate_file_extension("README")

    def test_validate_empty_filename(self):
        """Test that empty filename is rejected."""
        with pytest.raises(ValueError, match="Invalid filename"):
            validate_file_extension("")


# =============================================================================
# FILE SIZE VALIDATION TESTS
# =============================================================================


class TestFileSizeValidation:
    """Test file size validation."""

    def test_validate_small_file(self):
        """Test validation of small file."""
        content = b"Hello, World!"
        size = validate_file_size(content)
        assert size == len(content)

    def test_validate_exactly_max_size(self):
        """Test validation of file at exactly max size."""
        content = b"x" * MAX_FILE_SIZE_BYTES
        size = validate_file_size(content)
        assert size == MAX_FILE_SIZE_BYTES

    def test_validate_file_too_large(self):
        """Test that oversized files are rejected."""
        content = b"x" * (MAX_FILE_SIZE_BYTES + 1)
        with pytest.raises(ValueError, match="exceeds maximum"):
            validate_file_size(content)

    def test_validate_custom_max_size(self):
        """Test validation with custom max size."""
        content = b"x" * 1000
        # Should pass with 2000 byte limit
        assert validate_file_size(content, max_size=2000) == 1000

        # Should fail with 500 byte limit
        with pytest.raises(ValueError, match="exceeds maximum"):
            validate_file_size(content, max_size=500)

    def test_validate_empty_file(self):
        """Test validation of empty file."""
        content = b""
        size = validate_file_size(content)
        assert size == 0


# =============================================================================
# FILE SIGNATURE VALIDATION TESTS
# =============================================================================


class TestFileSignatureValidation:
    """Test file signature (magic bytes) validation."""

    def test_validate_pdf_signature(self):
        """Test PDF file signature validation."""
        # Valid PDF starts with %PDF
        pdf_content = b"%PDF-1.4\n..."
        assert validate_file_signature(pdf_content, "pdf") is True

    def test_validate_xlsx_signature(self):
        """Test XLSX file signature validation."""
        # XLSX is ZIP format, starts with PK
        xlsx_content = b"PK\x03\x04..."
        assert validate_file_signature(xlsx_content, "xlsx") is True

    def test_validate_xls_signature(self):
        """Test XLS file signature validation."""
        # XLS is OLE format, starts with D0CF
        xls_content = b"\xd0\xcf\x11\xe0..."
        assert validate_file_signature(xls_content, "xls") is True

    def test_validate_csv_no_signature(self):
        """Test that CSV (no magic bytes) passes."""
        csv_content = b"name,age,city\nJohn,30,NYC"
        assert validate_file_signature(csv_content, "csv") is True

    def test_validate_invalid_signature(self):
        """Test that invalid file signatures are rejected."""
        # PDF with wrong magic bytes
        with pytest.raises(ValueError, match="does not match"):
            validate_file_signature(b"NOT_PDF_DATA", "pdf")

    def test_validate_file_too_small(self):
        """Test that files smaller than magic bytes are rejected."""
        with pytest.raises(ValueError, match="too small"):
            validate_file_signature(b"ab", "pdf")

    def test_validate_unknown_extension(self):
        """Test that unknown extension raises error."""
        with pytest.raises(ValueError, match="Unknown file extension"):
            validate_file_signature(b"data", "unknown")


# =============================================================================
# BASE64 DECODING TESTS
# =============================================================================


class TestBase64Decoding:
    """Test base64 decoding."""

    def test_decode_valid_base64(self):
        """Test decoding valid base64 content."""
        original = b"Hello, World!"
        encoded = base64.b64encode(original).decode()
        decoded, size = decode_base64_file(encoded)
        assert decoded == original
        assert size == len(original)

    def test_decode_pdf_content(self):
        """Test decoding PDF content."""
        pdf_content = b"%PDF-1.4\ntest"
        encoded = base64.b64encode(pdf_content).decode()
        decoded, size = decode_base64_file(encoded)
        assert decoded == pdf_content

    def test_decode_invalid_base64(self):
        """Test that invalid base64 raises error."""
        with pytest.raises(ValueError, match="Invalid base64"):
            decode_base64_file("NOT_VALID_BASE64!!!!")

    def test_decode_empty_base64(self):
        """Test decoding empty base64."""
        decoded, size = decode_base64_file("")
        assert decoded == b""
        assert size == 0


# =============================================================================
# MALWARE SCANNING TESTS
# =============================================================================


class TestMalwareScanning:
    """Test malware scanning (mock)."""

    def test_scan_mock_returns_true(self):
        """Test that mock scan always returns True."""
        content = b"Any file content"
        result = scan_file_for_malware(content, "test.pdf")
        assert result is True

    def test_scan_with_different_file_types(self):
        """Test scanning different file types."""
        assert scan_file_for_malware(b"pdf content", "file.pdf") is True
        assert scan_file_for_malware(b"csv content", "data.csv") is True
        assert scan_file_for_malware(b"binary", "file.xlsx") is True


# =============================================================================
# COMPREHENSIVE VALIDATION TESTS
# =============================================================================


class TestComprehensiveValidation:
    """Test comprehensive file validation pipeline."""

    def test_validate_valid_pdf(self):
        """Test validation of valid PDF file."""
        pdf_content = b"%PDF-1.4\ntest content"
        encoded = base64.b64encode(pdf_content).decode()

        sanitized, content, ext = validate_file_upload(
            filename="document.pdf",
            file_content_base64=encoded,
            file_type="pdf",
            scan_malware=True,
        )

        assert sanitized == "document.pdf"
        assert content == pdf_content
        assert ext == "pdf"

    def test_validate_valid_csv(self):
        """Test validation of valid CSV file."""
        csv_content = b"name,age\nJohn,30\nJane,25"
        encoded = base64.b64encode(csv_content).decode()

        sanitized, content, ext = validate_file_upload(
            filename="data.csv",
            file_content_base64=encoded,
            file_type="csv",
        )

        assert sanitized == "data.csv"
        assert content == csv_content
        assert ext == "csv"

    def test_validate_valid_xlsx(self):
        """Test validation of valid XLSX file."""
        xlsx_content = b"PK\x03\x04...binary xlsx data..."
        encoded = base64.b64encode(xlsx_content).decode()

        sanitized, content, ext = validate_file_upload(
            filename="spreadsheet.xlsx",
            file_content_base64=encoded,
            file_type="excel",
        )

        assert sanitized == "spreadsheet.xlsx"
        assert content == xlsx_content
        assert ext == "xlsx"

    def test_validate_bad_extension(self):
        """Test that bad extensions are rejected."""
        content = b"executable content"
        encoded = base64.b64encode(content).decode()

        with pytest.raises(ValueError, match="not allowed"):
            validate_file_upload(
                filename="script.exe",
                file_content_base64=encoded,
            )

    def test_validate_file_too_large(self):
        """Test that oversized files are rejected."""
        large_content = b"x" * (MAX_FILE_SIZE_BYTES + 1)
        encoded = base64.b64encode(large_content).decode()

        with pytest.raises(ValueError, match="exceeds maximum"):
            validate_file_upload(
                filename="large.pdf",
                file_content_base64=encoded,
            )

    def test_validate_mismatched_signature(self):
        """Test that mismatched file signatures are rejected."""
        # CSV content but PDF extension
        csv_content = b"name,age\nJohn,30"
        encoded = base64.b64encode(csv_content).decode()

        with pytest.raises(ValueError, match="does not match"):
            validate_file_upload(
                filename="fake.pdf",
                file_content_base64=encoded,
            )

    def test_validate_sanitizes_filename(self):
        """Test that filename is sanitized."""
        pdf_content = b"%PDF-1.4\ntest"
        encoded = base64.b64encode(pdf_content).decode()

        sanitized, _, _ = validate_file_upload(
            filename="../../../evil.pdf",
            file_content_base64=encoded,
        )

        assert ".." not in sanitized
        assert "/" not in sanitized

    def test_validate_invalid_base64(self):
        """Test that invalid base64 is rejected."""
        with pytest.raises(ValueError, match="File validation error"):
            validate_file_upload(
                filename="document.pdf",
                file_content_base64="NOT_VALID_BASE64!!!!",
            )

    def test_validate_with_file_type_constraint(self):
        """Test validation with file type constraint."""
        pdf_content = b"%PDF-1.4\ntest"
        encoded = base64.b64encode(pdf_content).decode()

        # Should pass - pdf is in the csv file type
        # Actually should fail - pdf not in csv types
        with pytest.raises(ValueError, match="not compatible"):
            validate_file_upload(
                filename="document.pdf",
                file_content_base64=encoded,
                file_type="csv",
            )

    def test_validate_custom_max_size(self):
        """Test validation with custom max size."""
        small_content = b"%PDF-1.4\ntest"
        encoded = base64.b64encode(small_content).decode()

        # Should pass with high limit
        sanitized, content, ext = validate_file_upload(
            filename="document.pdf",
            file_content_base64=encoded,
            max_size=1000,
        )
        assert ext == "pdf"

        # Should fail with very low limit
        with pytest.raises(ValueError, match="exceeds maximum"):
            validate_file_upload(
                filename="document.pdf",
                file_content_base64=encoded,
                max_size=10,
            )

    def test_validate_disable_malware_scan(self):
        """Test disabling malware scan."""
        pdf_content = b"%PDF-1.4\ntest"
        encoded = base64.b64encode(pdf_content).decode()

        sanitized, content, ext = validate_file_upload(
            filename="document.pdf",
            file_content_base64=encoded,
            scan_malware=False,
        )
        assert ext == "pdf"


# =============================================================================
# ALLOWED EXTENSIONS CONFIGURATION TESTS
# =============================================================================


class TestAllowedExtensionsConfig:
    """Test allowed extensions configuration."""

    def test_pdf_has_magic_bytes(self):
        """Test that PDF has magic bytes defined."""
        assert "pdf" in ALLOWED_EXTENSIONS
        assert ALLOWED_EXTENSIONS["pdf"]["magic_bytes"] == b"%PDF"

    def test_xlsx_has_magic_bytes(self):
        """Test that XLSX has magic bytes defined."""
        assert "xlsx" in ALLOWED_EXTENSIONS
        assert ALLOWED_EXTENSIONS["xlsx"]["magic_bytes"] == b"PK\x03\x04"

    def test_csv_no_magic_bytes(self):
        """Test that CSV has no magic bytes (as expected)."""
        assert "csv" in ALLOWED_EXTENSIONS
        assert ALLOWED_EXTENSIONS["csv"]["magic_bytes"] is None

    def test_all_extensions_have_mime_type(self):
        """Test that all extensions have MIME type defined."""
        for ext, config in ALLOWED_EXTENSIONS.items():
            assert "mime" in config
            assert config["mime"] is not None
