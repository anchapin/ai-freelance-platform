
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from src.api.main import app, create_checkout_session
from src.api.models import Task, TaskStatus
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)

@pytest.fixture
def task_submission_payload():
    return {
        "domain": "accounting",
        "title": "Test Task",
        "description": "Test Description",
        "complexity": "medium",
        "urgency": "standard"
    }

@patch("src.api.main.stripe.checkout.Session.create")
def test_stripe_network_timeout(mock_stripe_create, mock_db, task_submission_payload):
    """Test handling of Stripe API timeouts (Issue #29)"""
    from pydantic import BaseModel
    class TaskSubmission(BaseModel):
        domain: str
        title: str
        description: str
        complexity: str = "medium"
        urgency: str = "standard"
        csvContent: str | None = None
        file_type: str | None = None
        file_content: str | None = None
        filename: str | None = None
        client_email: str | None = None

    import stripe
    mock_stripe_create.side_effect = stripe.error.APIConnectionError("Network timeout")
    
    task_obj = TaskSubmission(**task_submission_payload)
    
    with pytest.raises(HTTPException) as excinfo:
        import asyncio
        asyncio.run(create_checkout_session(task_obj, mock_db))
    
    assert excinfo.value.status_code == 503
    assert "Stripe API is temporarily unavailable" in excinfo.value.detail

def test_database_operational_error(mock_db, task_submission_payload):
    """Test handling of database connection failures (Issue #29)"""
    from pydantic import BaseModel
    class TaskSubmission(BaseModel):
        domain: str
        title: str
        description: str
        complexity: str = "medium"
        urgency: str = "standard"
        csvContent: str | None = None
        file_type: str | None = None
        file_content: str | None = None
        filename: str | None = None
        client_email: str | None = None

    mock_db.add.side_effect = OperationalError("connection failure", None, None)
    
    task_obj = TaskSubmission(**task_submission_payload)
    
    with pytest.raises(HTTPException) as excinfo:
        import asyncio
        asyncio.run(create_checkout_session(task_obj, mock_db))
    
    assert excinfo.value.status_code == 500
    assert "Database error occurred" in excinfo.value.detail
