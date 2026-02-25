"""
Pytest configuration and shared fixtures for ArbitrageAI tests.

This module provides:
- Mock fixtures for Stripe API
- Mock fixtures for E2B Sandbox
- Mock fixtures for OpenAI/Ollama LLM responses
- In-memory database for testing
- Sample task data
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

# Import the modules under test
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# =============================================================================
# PYTEST CONFIGURATION
# =============================================================================

# NOTE: Removed custom event_loop fixture - pytest-asyncio 0.21+ handles this automatically
# This fixture was causing "There is no current event loop" errors in CI.
# The default pytest-asyncio behavior is now used with function-scoped loops.


# =============================================================================
# STRIPE API MOCKS
# =============================================================================

@pytest.fixture
def mock_stripe_session():
    """Mock Stripe checkout session response."""
    mock = Mock()
    mock.id = "cs_test_mock_session_id"
    mock.url = "https://checkout.stripe.com/mock_url"
    mock.status = "open"
    mock.payment_status = "unpaid"
    mock.metadata = {"task_id": "test_task_id"}
    return mock


@pytest.fixture
def mock_stripe_session_completed():
    """Mock Stripe checkout session completed response."""
    mock = Mock()
    mock.id = "cs_test_mock_session_id"
    mock.status = "complete"
    mock.payment_status = "paid"
    mock.metadata = {"task_id": "test_task_id"}
    mock.customer_email = "test@example.com"
    mock.amount_total = 15000  # $150.00 in cents
    return mock


@pytest.fixture
def mock_stripe_error():
    """Mock Stripe error."""
    from stripe import StripeError
    return StripeError(message="Stripe API error", code="api_error")


@pytest.fixture
def mock_stripe_module(mock_stripe_session):
    """Mock entire Stripe module."""
    with patch('stripe.checkout.Session') as mock_session:
        mock_session.create.return_value = mock_stripe_session
        mock_session.retrieve.return_value = mock_stripe_session
        yield mock_session


# =============================================================================
# E2B SANDBOX MOCKS
# =============================================================================

@pytest.fixture
def mock_e2b_success_result():
    """Mock successful E2B execution result."""
    return {
        "success": True,
        "output": "Visualization created successfully",
        "artifact_url": "https://e2b.io/artifacts/test_visualization.png",
        "execution_time_seconds": 45.2,
        "logs": [
            "Starting E2B sandbox...",
            "Processing data...",
            "Generating visualization...",
            "Upload complete!"
        ]
    }


@pytest.fixture
def mock_e2b_failure_result():
    """Mock failed E2B execution result."""
    return {
        "success": False,
        "error": "Execution failed: Invalid data format",
        "execution_time_seconds": 12.3,
        "logs": [
            "Starting E2B sandbox...",
            "Error: Could not parse CSV data"
        ]
    }


@pytest.fixture
def mock_e2b_client():
    """Mock E2B client."""
    mock = AsyncMock()
    return mock


# =============================================================================
# OPENAI/OLLAMA LLM MOCKS
# =============================================================================

@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response with token usage."""
    mock = Mock()
    mock.choices = [Mock()]
    mock.choices[0].message.content = "Generated code output"
    mock.usage = Mock()
    mock.usage.prompt_tokens = 1500
    mock.usage.completion_tokens = 500
    mock.usage.total_tokens = 2000
    mock.model = "gpt-4o"
    return mock


@pytest.fixture
def mock_openai_response_mini():
    """Mock OpenAI API response for GPT-4o-mini."""
    mock = Mock()
    mock.choices = [Mock()]
    mock.choices[0].message.content = "Generated code output"
    mock.usage = Mock()
    mock.usage.prompt_tokens = 800
    mock.usage.completion_tokens = 300
    mock.usage.total_tokens = 1100
    mock.model = "gpt-4o-mini"
    return mock


@pytest.fixture
def mock_ollama_response():
    """Mock Ollama local model response."""
    mock = Mock()
    mock.choices = [Mock()]
    mock.choices[0].message.content = "Generated code from local model"
    mock.usage = Mock()
    mock.usage.prompt_tokens = 1200
    mock.usage.completion_tokens = 400
    mock.usage.total_tokens = 1600
    mock.model = "llama3.2"
    return mock


@pytest.fixture
def mock_openai_client(mock_openai_response):
    """Mock OpenAI client."""
    with patch('openai.OpenAI') as mock_client:
        mock_instance = Mock()
        mock_instance.chat.completions.create.return_value = mock_openai_response
        mock_client.return_value = mock_instance
        yield mock_instance


# =============================================================================
# DATABASE FIXTURES
# =============================================================================

@pytest.fixture
def sample_task_data():
    """Sample task data for testing."""
    return {
        "id": "test_task_123",
        "title": "Create Sales Chart",
        "description": "Create a bar chart showing monthly sales data",
        "domain": "data_analysis",
        "status": "PENDING",
        "complexity": "medium",
        "urgency": "standard",
        "client_email": "test@example.com",
        "csv_data": "month,sales\nJan,100\nFeb,150\nMar,200",
        "amount_paid": 15000,  # $150.00 in cents
        "delivery_token": "test_delivery_token_abc123",
    }


@pytest.fixture
def sample_task_data_high_value():
    """Sample high-value task data for testing."""
    return {
        "id": "test_task_high_value",
        "title": "Complex Financial Report",
        "description": "Create a comprehensive financial analysis",
        "domain": "accounting",
        "status": "PENDING",
        "complexity": "complex",
        "urgency": "rush",
        "client_email": "enterprise@example.com",
        "csv_data": "category,amount\nRevenue,500000\nExpenses,300000",
        "amount_paid": 37500,  # $375.00 in cents (high value > $200)
        "delivery_token": "test_delivery_token_high_value",
        "is_high_value": True,
    }


# =============================================================================
# COST CONFIGURATION FIXTURES
# =============================================================================

@pytest.fixture
def mock_cost_config():
    """Mock CostConfig for testing."""
    from src.agent_execution.arena import CostConfig
    return CostConfig()


# =============================================================================
# SAMPLE TASK STATUSES FOR STATE MACHINE TESTS
# =============================================================================

@pytest.fixture
def task_statuses():
    """All possible task statuses."""
    from src.api.models import TaskStatus
    return {
        "PENDING": TaskStatus.PENDING,
        "PAID": TaskStatus.PAID,
        "PLANNING": TaskStatus.PLANNING,
        "PROCESSING": TaskStatus.PROCESSING,
        "REVIEW_REQUIRED": TaskStatus.REVIEW_REQUIRED,
        "REVIEWING": TaskStatus.REVIEWING,
        "COMPLETED": TaskStatus.COMPLETED,
        "FAILED": TaskStatus.FAILED,
        "ESCALATION": TaskStatus.ESCALATION,
    }


# =============================================================================
# ARENA AGENT CONFIGURATIONS
# =============================================================================

@pytest.fixture
def mock_agent_config_cloud():
    """Mock agent configuration for cloud model."""
    from src.agent_execution.arena import AgentConfig
    
    mock_llm = Mock()
    mock_llm.get_model.return_value = "gpt-4o"
    mock_llm.is_local.return_value = False
    
    return AgentConfig(
        name="Agent_B_Cloud",
        llm_service=mock_llm,
        system_prompt_style="standard",
        max_retries=2,
        planning_time_multiplier=1.0
    )


@pytest.fixture
def mock_agent_config_local():
    """Mock agent configuration for local model."""
    from src.agent_execution.arena import AgentConfig
    
    mock_llm = Mock()
    mock_llm.get_model.return_value = "llama3.2"
    mock_llm.is_local.return_value = True
    
    return AgentConfig(
        name="Agent_A_Local",
        llm_service=mock_llm,
        system_prompt_style="standard",
        max_retries=0,
        planning_time_multiplier=2.0
    )


# =============================================================================
# PROFIT CALCULATION TEST DATA
# =============================================================================

@pytest.fixture
def profit_test_cases():
    """Test cases for profit calculations."""
    return {
        "gpt4o_success": {
            "input_tokens": 1500,
            "output_tokens": 500,
            "execution_time_seconds": 45.0,
            "task_revenue": 500,  # $5.00
            "expected_approx_cost": 4.50,  # ~$4.50 for GPT-4o
        },
        "gpt4o_mini_success": {
            "input_tokens": 800,
            "output_tokens": 300,
            "execution_time_seconds": 30.0,
            "task_revenue": 500,
            "expected_approx_cost": 0.27,  # ~$0.27 for GPT-4o-mini
        },
        "local_model_success": {
            "input_tokens": 1200,
            "output_tokens": 400,
            "execution_time_seconds": 60.0,
            "task_revenue": 500,
            "expected_approx_cost": 0.30,  # Only E2B cost
        },
    }


# =============================================================================
# PRICING TEST DATA
# =============================================================================

@pytest.fixture
def pricing_test_cases():
    """Test cases for pricing calculations."""
    return {
        # Domain: accounting, legal, data_analysis
        # Complexity: simple (1.0), medium (1.5), complex (2.0)
        # Urgency: standard (1.0), rush (1.25), urgent (1.5)
        
        # Base rates: accounting=$100, legal=$175, data_analysis=$150
        
        "accounting_simple_standard": {
            "domain": "accounting",
            "complexity": "simple",
            "urgency": "standard",
            "expected": 100,  # 100 * 1.0 * 1.0
        },
        "accounting_medium_standard": {
            "domain": "accounting",
            "complexity": "medium",
            "urgency": "standard",
            "expected": 150,  # 100 * 1.5 * 1.0
        },
        "accounting_complex_urgent": {
            "domain": "accounting",
            "complexity": "complex",
            "urgency": "urgent",
            "expected": 300,  # 100 * 2.0 * 1.5
        },
        "legal_medium_rush": {
            "domain": "legal",
            "complexity": "medium",
            "urgency": "rush",
            "expected": 328,  # 175 * 1.5 * 1.25 = 328.125 → 328
        },
        "data_analysis_complex_standard": {
            "domain": "data_analysis",
            "complexity": "complex",
            "urgency": "standard",
            "expected": 300,  # 150 * 2.0 * 1.0
        },
    }
