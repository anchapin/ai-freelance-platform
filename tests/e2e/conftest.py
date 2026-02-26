"""
E2E Test Configuration and Fixtures

Provides:
- Database session fixtures for e2e tests
- Mock marketplace fixtures
- LLM service mocks (OpenAI + Ollama)
- Stripe webhook fixtures
- Client authentication fixtures
- Common test data and utilities
"""

import pytest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.models import Base, TaskStatus
from src.api.models import ClientProfile


@pytest.fixture
def e2e_db():
    """Create in-memory SQLite database for e2e tests."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    
    session = SessionLocal()
    yield session
    
    session.close()
    engine.dispose()


@pytest.fixture
def mock_marketplace_list():
    """Mock list of discovered marketplaces."""
    return [
        {
            "name": "Upwork",
            "url": "https://www.upwork.com",
            "category": "freelance",
            "discovered_at": datetime.now(timezone.utc).isoformat(),
            "jobs_found": 150,
            "bids_placed": 45,
            "bids_won": 12,
            "success_rate": 0.267,
            "total_revenue": 4500.00,
            "priority_score": 1200.00,
        },
        {
            "name": "Fiverr",
            "url": "https://www.fiverr.com",
            "category": "freelance",
            "discovered_at": datetime.now(timezone.utc).isoformat(),
            "jobs_found": 200,
            "bids_placed": 80,
            "bids_won": 24,
            "success_rate": 0.300,
            "total_revenue": 6000.00,
            "priority_score": 1800.00,
        },
        {
            "name": "Toptal",
            "url": "https://www.toptal.com",
            "category": "remote",
            "discovered_at": datetime.now(timezone.utc).isoformat(),
            "jobs_found": 50,
            "bids_placed": 20,
            "bids_won": 8,
            "success_rate": 0.400,
            "total_revenue": 8000.00,
            "priority_score": 3200.00,
        },
    ]


@pytest.fixture
def mock_llm_service_openai():
    """Mock LLM service with OpenAI model."""
    service = AsyncMock()
    service.get_model.return_value = "gpt-4o"
    service.is_local.return_value = False
    
    # Mock response for code generation
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = """
import pandas as pd
import matplotlib.pyplot as plt

df = pd.DataFrame(data)
plt.figure(figsize=(10, 6))
plt.bar(df['category'], df['amount'])
plt.title('Data Visualization')
plt.savefig('output.png')
"""
    mock_response.usage = Mock()
    mock_response.usage.prompt_tokens = 1500
    mock_response.usage.completion_tokens = 500
    mock_response.usage.total_tokens = 2000
    mock_response.model = "gpt-4o"
    
    service.create_completion.return_value = mock_response
    return service


@pytest.fixture
def mock_llm_service_ollama():
    """Mock LLM service with Ollama local model."""
    service = AsyncMock()
    service.get_model.return_value = "llama3.2"
    service.is_local.return_value = True
    
    # Mock response for code generation
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = """
import pandas as pd
import matplotlib.pyplot as plt

df = pd.DataFrame(data)
plt.figure(figsize=(10, 6))
plt.bar(df['category'], df['amount'])
plt.title('Data Visualization')
plt.savefig('output.png')
"""
    mock_response.usage = Mock()
    mock_response.usage.prompt_tokens = 1200
    mock_response.usage.completion_tokens = 400
    mock_response.usage.total_tokens = 1600
    mock_response.model = "llama3.2"
    
    service.create_completion.return_value = mock_response
    return service


@pytest.fixture
def mock_stripe_webhook_payload():
    """Mock Stripe webhook payload for checkout.session.completed."""
    return {
        "id": "evt_test_webhook_123",
        "object": "event",
        "api_version": "2023-10-16",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_session_123",
                "object": "checkout.session",
                "status": "complete",
                "payment_status": "paid",
                "customer_email": "client@example.com",
                "metadata": {
                    "task_id": str(uuid.uuid4()),
                    "domain": "accounting",
                    "complexity": "medium",
                },
                "amount_total": 15000,  # $150.00
                "currency": "usd",
            }
        },
        "livemode": False,
        "pending_webhooks": 0,
        "request": {
            "id": None,
            "idempotency_key": str(uuid.uuid4()),
        },
    }


@pytest.fixture
def mock_stripe_signature():
    """Mock Stripe webhook signature."""
    return "t=1613131428,v1=test_signature_value"


@pytest.fixture
def mock_docker_sandbox_result():
    """Mock successful Docker sandbox execution result."""
    return {
        "success": True,
        "output": "Visualization created successfully",
        "artifact_url": "data:image/png;base64,iVBORw0KGgoAAAANS...",
        "execution_time_seconds": 45.2,
        "logs": [
            "Starting sandbox...",
            "Processing data...",
            "Generating visualization...",
            "Complete!",
        ],
    }


@pytest.fixture
def sample_marketplace_job():
    """Sample job posting from a marketplace."""
    return {
        "id": "job_12345",
        "marketplace": "Upwork",
        "title": "Create Financial Dashboard",
        "description": "Need a Python-based financial dashboard with real-time data visualization.",
        "budget": 500,
        "skills": ["Python", "Data Visualization", "Pandas"],
        "experience_level": "Intermediate",
        "posted_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "urgency": "rush",
        "estimated_hours": 40,
    }


@pytest.fixture
def sample_bid_data():
    """Sample bid data for placing on a job."""
    return {
        "job_id": "job_12345",
        "marketplace": "Upwork",
        "proposed_budget": 400,
        "proposal_text": "I can create this dashboard using Python and Plotly.",
        "estimated_delivery_days": 7,
        "hourly_rate": None,
        "fixed_price": True,
    }


@pytest.fixture
def sample_task_data():
    """Sample task data for execution."""
    return {
        "id": str(uuid.uuid4()),
        "title": "Create Sales Report",
        "description": "Create a comprehensive sales report with visualizations",
        "domain": "accounting",
        "status": TaskStatus.PAID,
        "complexity": "medium",
        "urgency": "standard",
        "client_email": "client@example.com",
        "csv_data": "month,sales\nJan,100000\nFeb,150000\nMar,200000",
        "amount_paid": 30000,  # $300.00
        "delivery_token": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc),
    }


@pytest.fixture
def client_auth_token():
    """Sample client authentication token."""
    from src.utils.client_auth import generate_client_token
    
    client_email = "client@example.com"
    token = generate_client_token(client_email)
    return {
        "email": client_email,
        "token": token,
    }


@pytest.fixture
def mock_client_profile(e2e_db):
    """Create a mock client profile in database."""
    profile = ClientProfile(
        id=str(uuid.uuid4()),
        client_email="client@example.com",
        preferred_colors=["blue", "green"],
        preferred_fonts=["Arial", "Times New Roman"],
        preferred_chart_types=["bar", "line"],
        preferred_output_formats=["png", "pdf"],
        style_preferences={"formal": True, "detailed": True},
        total_tasks=5,
        completed_tasks=4,
    )
    e2e_db.add(profile)
    e2e_db.commit()
    return profile


@pytest.fixture
def parametrize_llm_models():
    """Parametrize test with both OpenAI and Ollama models."""
    return [
        ("openai", "gpt-4o"),
        ("ollama", "llama3.2"),
    ]


@pytest.fixture
def mock_market_scanner():
    """Mock market scanner for autonomous job discovery."""
    scanner = AsyncMock()
    scanner.scan_marketplace.return_value = {
        "marketplace": "Upwork",
        "jobs_found": 25,
        "jobs_scanned": 100,
        "bids_placed": 8,
        "success_rate": 0.32,
        "total_revenue_potential": 2400.00,
    }
    return scanner


@pytest.fixture
def mock_bid_lock_manager():
    """Mock bid lock manager for distributed locking."""
    manager = AsyncMock()
    manager.acquire_bid_lock.return_value = str(uuid.uuid4())
    manager.release_bid_lock.return_value = True
    manager.is_bid_locked.return_value = False
    return manager


@pytest.fixture
def mock_vector_db():
    """Mock vector database for RAG enrichment."""
    db = AsyncMock()
    db.query_similar_tasks.return_value = [
        {
            "task_id": "task_001",
            "title": "Create Sales Chart",
            "similarity_score": 0.92,
        },
        {
            "task_id": "task_002",
            "title": "Generate Financial Report",
            "similarity_score": 0.85,
        },
    ]
    db.add_completed_task.return_value = True
    return db
