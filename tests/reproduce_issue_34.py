
import base64
import pytest
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)

def test_oversized_file_upload_repro():
    """Reproduce missing file size validation"""
    # Create a 51MB "file" (exceeds 50MB limit)
    large_content = b"a" * (51 * 1024 * 1024)
    large_content_b64 = base64.b64encode(large_content).decode()
    
    payload = {
        "domain": "accounting",
        "title": "Large File Test",
        "description": "This should fail due to size",
        "file_content": large_content_b64,
        "filename": "large.pdf",
        "file_type": "pdf"
    }
    
    response = client.post("/api/create-checkout-session", json=payload)
    assert response.status_code == 422, f"Expected 422 for oversized file, got {response.status_code}"

def test_malicious_filename_repro():
    """Reproduce missing filename sanitization"""
    payload = {
        "domain": "accounting",
        "title": "Path Traversal Test",
        "description": "This should be sanitized",
        "file_content": base64.b64encode(b"dummy content").decode(),
        "filename": "../../../etc/passwd",
        "file_type": "pdf"
    }
    
    response = client.post("/api/create-checkout-session", json=payload)
    assert response.status_code == 422, "Expected 422 for malicious filename"
