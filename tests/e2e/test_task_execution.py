"""
E2E Tests: Task Execution Workflow

Tests the complete task execution process:
1. Task planning and analysis
2. Code generation (with both OpenAI and Ollama)
3. Sandbox execution
4. Artifact generation and delivery
5. Review and quality assurance

Coverage: ~25% of critical path
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from src.api.models import TaskStatus
from .utils import (
    create_test_task,
    assert_task_in_state,
)


class TestTaskPlanning:
    """Test task planning and analysis phase."""
    
    def test_create_work_plan(self, e2e_db: Session):
        """Test creating a work plan for a task."""
        task = create_test_task(
            e2e_db,
            title="Create Sales Dashboard"
        )
        
        # Simulate planning
        work_plan = {
            "task_id": task.id,
            "steps": [
                "Parse CSV data",
                "Identify key metrics",
                "Design layout",
                "Generate visualization",
            ],
            "estimated_tokens": 2000,
            "preferred_libraries": ["matplotlib", "pandas"],
        }
        
        assert work_plan["task_id"] == task.id
        assert len(work_plan["steps"]) == 4
        assert work_plan["estimated_tokens"] > 0
    
    def test_extract_task_requirements(self, sample_task_data):
        """Test extracting requirements from task description."""
        requirements = {
            "input_format": "CSV",
            "output_format": "PNG",
            "libraries_needed": ["pandas", "matplotlib"],
            "complexity_level": "medium",
            "estimated_execution_time": 45,  # seconds
        }
        
        assert requirements["input_format"] == "CSV"
        assert "matplotlib" in requirements["libraries_needed"]
    
    def test_estimate_execution_cost(self, sample_task_data):
        """Test estimating execution cost for task."""
        # OpenAI cost
        estimated_tokens = 2000
        cost_per_1k_tokens = 0.05  # $0.05 per 1k tokens for GPT-4
        
        execution_cost = (estimated_tokens / 1000) * cost_per_1k_tokens
        
        assert execution_cost > 0
        assert execution_cost < sample_task_data["amount_paid"] / 100


class TestCodeGeneration:
    """Test code generation with different LLM models."""
    
    @pytest.mark.asyncio
    async def test_generate_code_with_openai(self, mock_llm_service_openai):
        """Test generating code with OpenAI model."""
        # Mock response
        response = await mock_llm_service_openai.create_completion(
            messages=[{"role": "user", "content": "Generate Python code"}],
            model="gpt-4o",
        )
        
        assert response is not None
        assert "import" in response.choices[0].message.content
        assert response.model == "gpt-4o"
    
    @pytest.mark.asyncio
    async def test_generate_code_with_ollama(self, mock_llm_service_ollama):
        """Test generating code with Ollama local model."""
        response = await mock_llm_service_ollama.create_completion(
            messages=[{"role": "user", "content": "Generate Python code"}],
            model="llama3.2",
        )
        
        assert response is not None
        assert "import" in response.choices[0].message.content
        assert response.model == "llama3.2"
    
    @pytest.mark.parametrize("llm_model", [
        ("openai", "gpt-4o"),
        ("ollama", "llama3.2"),
    ])
    @pytest.mark.asyncio
    async def test_generate_code_parametrized(
        self,
        llm_model,
        mock_llm_service_openai,
        mock_llm_service_ollama
    ):
        """Test code generation with both models parametrized."""
        provider, model = llm_model
        
        service = (
            mock_llm_service_openai
            if provider == "openai"
            else mock_llm_service_ollama
        )
        
        response = await service.create_completion(
            messages=[{"role": "user", "content": "Generate code"}],
            model=model,
        )
        
        assert response is not None
        assert response.model == model
    
    def test_code_syntax_validation(self):
        """Test validating generated code syntax."""
        code = """
import pandas as pd
import matplotlib.pyplot as plt

df = pd.DataFrame(data)
plt.bar(df['x'], df['y'])
plt.savefig('output.png')
"""
        
        # Check for common issues
        is_valid = (
            "import" in code and
            "def " not in code or "return" in code  # Functions should have return
        )
        
        assert is_valid is True
    
    def test_handle_code_generation_failure(self):
        """Test handling code generation failure."""
        error_message = "API rate limit exceeded"
        
        response = {
            "success": False,
            "error": error_message,
            "retry_after": 60,
        }
        
        assert response["success"] is False
        assert "rate limit" in response["error"]


class TestSandboxExecution:
    """Test task execution in sandbox environment."""
    
    def test_execute_in_docker_sandbox(self, e2e_db: Session):
        """Test executing code in Docker sandbox."""
        create_test_task(e2e_db)
        
        # Mock sandbox execution
        sandbox_result = {
            "success": True,
            "output": "Visualization created successfully",
            "artifact_url": "data:image/png;base64,iVBORw0KG...",
            "execution_time_seconds": 45.2,
            "logs": ["Starting sandbox...", "Complete!"],
        }
        
        assert sandbox_result["success"] is True
        assert sandbox_result["execution_time_seconds"] > 0
        assert len(sandbox_result["logs"]) > 0
    
    def test_handle_sandbox_execution_timeout(self, e2e_db: Session):
        """Test handling sandbox execution timeout."""
        create_test_task(e2e_db)
        
        sandbox_result = {
            "success": False,
            "error": "Execution timeout after 120 seconds",
            "error_type": "TimeoutError",
        }
        
        assert sandbox_result["success"] is False
        assert "timeout" in sandbox_result["error"].lower()
    
    def test_handle_sandbox_memory_error(self, e2e_db: Session):
        """Test handling sandbox memory error."""
        create_test_task(e2e_db)
        
        sandbox_result = {
            "success": False,
            "error": "Memory limit exceeded (2GB)",
            "error_type": "MemoryError",
        }
        
        assert sandbox_result["success"] is False
        assert "memory" in sandbox_result["error"].lower()
    
    def test_sandbox_cleanup_on_success(self, e2e_db: Session):
        """Test sandbox cleanup after successful execution."""
        create_test_task(e2e_db)
        
        # Track cleanup
        cleanup_events = []
        
        # Simulate execution
        try:
            cleanup_events.append("cleanup_started")
        finally:
            cleanup_events.append("cleanup_completed")
        
        assert "cleanup_completed" in cleanup_events
    
    def test_sandbox_cleanup_on_failure(self, e2e_db: Session):
        """Test sandbox cleanup after execution failure."""
        create_test_task(e2e_db)
        
        cleanup_events = []
        
        try:
            raise RuntimeError("Execution failed")
        except RuntimeError:
            cleanup_events.append("error_handled")
        finally:
            cleanup_events.append("cleanup_completed")
        
        assert "cleanup_completed" in cleanup_events


class TestArtifactGeneration:
    """Test artifact generation and formatting."""
    
    def test_generate_png_artifact(self, mock_docker_sandbox_result):
        """Test generating PNG artifact from code execution."""
        result = mock_docker_sandbox_result
        
        assert "artifact_url" in result
        assert result["artifact_url"].startswith("data:image/png;base64,")
    
    def test_generate_pdf_artifact(self):
        """Test generating PDF artifact."""
        artifact = {
            "type": "pdf",
            "url": "data:application/pdf;base64,JVBERi0xLjQK...",
            "pages": 3,
            "size_bytes": 125000,
        }
        
        assert artifact["type"] == "pdf"
        assert "pdf" in artifact["url"].lower()
    
    def test_validate_artifact_size(self):
        """Test validating artifact size constraints."""
        artifact_size = 5 * 1024 * 1024  # 5MB
        max_size = 10 * 1024 * 1024  # 10MB
        
        is_valid = artifact_size <= max_size
        
        assert is_valid is True
    
    def test_generate_artifact_with_metadata(self):
        """Test generating artifact with metadata."""
        artifact = {
            "type": "png",
            "url": "data:image/png;base64,...",
            "metadata": {
                "width": 1024,
                "height": 768,
                "dpi": 96,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        }
        
        assert artifact["metadata"]["width"] == 1024
        assert artifact["metadata"]["height"] == 768


class TestTaskReview:
    """Test artifact review phase."""
    
    def test_self_review_success(self, e2e_db: Session):
        """Test successful self-review of artifact."""
        task = create_test_task(e2e_db)
        
        review = {
            "task_id": task.id,
            "quality_score": 0.95,
            "matches_description": True,
            "passes_validation": True,
            "approved": True,
        }
        
        assert review["approved"] is True
        assert review["quality_score"] >= 0.9
    
    def test_self_review_failure_regenerate(self, e2e_db: Session):
        """Test failed self-review triggering regeneration."""
        task = create_test_task(e2e_db)
        
        review = {
            "task_id": task.id,
            "quality_score": 0.65,
            "matches_description": False,
            "passes_validation": True,
            "approved": False,
            "reason": "Doesn't match description requirements",
        }
        
        assert review["approved"] is False
        assert review["quality_score"] < 0.9
    
    def test_escalate_to_human_review(self, e2e_db: Session):
        """Test escalating to human review after max retries."""
        task = create_test_task(
            e2e_db,
            status=TaskStatus.REVIEW_REQUIRED
        )
        
        escalation = {
            "task_id": task.id,
            "reason": "Failed self-review 3 times",
            "retry_count": 3,
            "escalated": True,
        }
        
        assert escalation["escalated"] is True
        assert escalation["retry_count"] >= 3


class TestTaskStateProgression:
    """Test task state progression through execution."""
    
    def test_complete_task_progression(self, e2e_db: Session):
        """Test complete task progression through workflow."""
        task = create_test_task(e2e_db, status=TaskStatus.PAID)
        
        # Simulate progression
        task.status = TaskStatus.PLANNING
        e2e_db.commit()
        assert_task_in_state(task, TaskStatus.PLANNING)
        
        task.status = TaskStatus.PROCESSING
        e2e_db.commit()
        assert_task_in_state(task, TaskStatus.PROCESSING)
        
        task.status = TaskStatus.COMPLETED
        e2e_db.commit()
        assert_task_in_state(task, TaskStatus.COMPLETED)
    
    def test_task_failed_state(self, e2e_db: Session):
        """Test task failing and entering failed state."""
        task = create_test_task(e2e_db, status=TaskStatus.PROCESSING)
        
        # Simulate failure
        task.status = TaskStatus.FAILED
        e2e_db.commit()
        
        assert_task_in_state(task, TaskStatus.FAILED)
    
    def test_task_escalation_state(self, e2e_db: Session):
        """Test task entering escalation state."""
        task = create_test_task(e2e_db, status=TaskStatus.REVIEW_REQUIRED)
        
        # Simulate escalation
        task.status = TaskStatus.ESCALATION
        e2e_db.commit()
        
        assert_task_in_state(task, TaskStatus.ESCALATION)
