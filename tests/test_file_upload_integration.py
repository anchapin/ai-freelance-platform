"""
Integration tests for file upload API endpoint (Issue #34).

Tests the create-checkout-session endpoint with file uploads.
"""

import base64
from fastapi.testclient import TestClient

from src.api.main import app

# Create test client
client = TestClient(app)


# =============================================================================
# FILE UPLOAD API TESTS
# =============================================================================


class TestFileUploadIntegration:
    """Test file upload validation in API endpoints."""

    def test_checkout_allows_missing_file(self):
        """Test that checkout without file upload still works."""
        payload = {
            "domain": "legal",
            "title": "Document Drafting",
            "description": "Please draft a contract",
            "complexity": "medium",
            "urgency": "standard",
            "client_email": "test@example.com",
        }

        response = client.post("/api/create-checkout-session", json=payload)

        # Should succeed (or fail with Stripe error, not validation error)
        if response.status_code >= 400:
            error_detail = response.json().get("detail", "")
            assert "File validation" not in error_detail

    def test_checkout_with_valid_pdf(self):
        """Test checkout session creation with valid PDF file."""
        # Create valid PDF content
        pdf_content = b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n0000000000 65535 f\ntrailer\n<< /Size 1 >>\nstartxref\n0\n%%EOF"
        encoded = base64.b64encode(pdf_content).decode()

        payload = {
            "domain": "legal",
            "title": "Contract Review",
            "description": "Please review this contract",
            "file_type": "pdf",
            "file_content": encoded,
            "filename": "contract.pdf",
            "complexity": "medium",
            "urgency": "standard",
            "client_email": "test@example.com",
        }

        response = client.post("/api/create-checkout-session", json=payload)

        # Should succeed or fail with Stripe error, not validation error
        if response.status_code >= 400:
            error_detail = response.json().get("detail", "")
            # Should NOT contain file validation errors
            assert "File validation" not in error_detail

    def test_checkout_with_valid_csv(self):
        """Test checkout session creation with valid CSV file."""
        csv_content = b"name,age,city\nJohn,30,NYC\nJane,25,LA"
        encoded = base64.b64encode(csv_content).decode()

        payload = {
            "domain": "data_analysis",
            "title": "Data Analysis",
            "description": "Analyze this data",
            "file_type": "csv",
            "file_content": encoded,
            "filename": "data.csv",
            "complexity": "medium",
            "urgency": "standard",
        }

        response = client.post("/api/create-checkout-session", json=payload)

        # Should succeed or fail with Stripe error, not file validation error
        if response.status_code >= 400:
            error_detail = response.json().get("detail", "")
            assert "File validation" not in error_detail

    def test_checkout_validation_catches_invalid_extension(self):
        """Test that invalid file extensions are caught during validation."""
        # Try uploading executable - validation should reject at Pydantic level
        content = b"MZ\x90\x00"  # EXE header
        encoded = base64.b64encode(content).decode()

        payload = {
            "domain": "data_analysis",
            "title": "Test",
            "description": "Test",
            "file_type": "csv",
            "file_content": encoded,
            "filename": "malware.exe",
            "complexity": "medium",
            "urgency": "standard",
        }

        response = client.post("/api/create-checkout-session", json=payload)

        # Validation happens before database insert
        # So we get a validation error, not a database error
        assert response.status_code >= 400

    def test_checkout_validation_catches_invalid_base64(self):
        """Test that invalid base64 content is rejected."""
        payload = {
            "domain": "data_analysis",
            "title": "Test",
            "description": "Test",
            "file_type": "csv",
            "file_content": "NOT_VALID_BASE64!!!!",
            "filename": "data.csv",
            "complexity": "medium",
            "urgency": "standard",
        }

        response = client.post("/api/create-checkout-session", json=payload)

        # Should be rejected by validation
        assert response.status_code >= 400
