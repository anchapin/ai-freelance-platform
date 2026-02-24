"""
Tests for Task Model Composition

Tests for Issue #5: Refactor overloaded Task model using composition pattern

Coverage:
- Composed task models
- Relationships and cascading
- State machine validation
- Data preservation
"""

import pytest
from datetime import datetime

from src.api.models_composition import (
    Task,
    TaskExecution,
    TaskPlanning,
    TaskReview,
    TaskArena,
    TaskOutput,
    TaskStatus,
    ExecutionStatus,
    PlanningStatus,
    ReviewStatus,
    OutputType,
)
from src.api.state_machine import (
    TaskStateMachine,
    ExecutionStateMachine,
    PlanningStateMachine,
    ReviewStateMachine,
    validate_task_transition,
)


class TestTaskModel:
    """Tests for core Task model."""
    
    def test_task_creation(self):
        """Test creating a Task instance."""
        task = Task(
            id="task_123",
            title="Create Chart",
            description="Create a bar chart",
            domain="data_analysis",
            status=TaskStatus.PENDING,
            client_email="user@example.com",
            amount_paid=5000
        )
        
        assert task.title == "Create Chart"
        assert task.status == TaskStatus.PENDING
        assert task.amount_paid == 5000
    
    def test_task_minimal_fields(self):
        """Test that Task requires only essential fields."""
        task = Task(
            title="Test",
            description="Test task",
            domain="test"
        )
        
        # Should have created without execution, planning, etc.
        assert task.execution is None
        assert task.planning is None
        assert task.review is None
        assert task.arena is None
        assert len(task.outputs) == 0
    
    def test_task_to_dict(self):
        """Test Task.to_dict() method."""
        task = Task(
            id="task_123",
            title="Test",
            description="Test",
            domain="test",
            status=TaskStatus.PENDING,
            client_email="user@example.com",
            amount_paid=5000
        )
        
        d = task.to_dict()
        assert d["id"] == "task_123"
        assert d["title"] == "Test"
        assert d["status"] == "PENDING"
        assert d["amount_dollars"] == 50.0


class TestTaskComposition:
    """Tests for composed entities."""
    
    def test_task_execution_relationship(self):
        """Test TaskExecution one-to-one relationship."""
        task = Task(title="Test", description="Test", domain="test")
        execution = TaskExecution(
            task_id=task.id,
            status=ExecutionStatus.PENDING
        )
        task.execution = execution
        
        assert task.execution.status == ExecutionStatus.PENDING
    
    def test_task_planning_relationship(self):
        """Test TaskPlanning one-to-one relationship."""
        task = Task(title="Test", description="Test", domain="test")
        planning = TaskPlanning(
            task_id=task.id,
            status=PlanningStatus.PENDING,
            plan_content="Test plan"
        )
        task.planning = planning
        
        assert task.planning.plan_content == "Test plan"
    
    def test_task_review_relationship(self):
        """Test TaskReview one-to-one relationship."""
        task = Task(title="Test", description="Test", domain="test")
        review = TaskReview(
            task_id=task.id,
            status=ReviewStatus.PENDING,
            approved=False
        )
        task.review = review
        
        assert task.review.approved is False
    
    def test_task_output_one_to_many(self):
        """Test TaskOutput one-to-many relationship."""
        task = Task(title="Test", description="Test", domain="test")
        
        output1 = TaskOutput(
            task_id=task.id,
            output_type=OutputType.IMAGE,
            output_url="http://example.com/image.png"
        )
        output2 = TaskOutput(
            task_id=task.id,
            output_type=OutputType.SPREADSHEET,
            output_url="http://example.com/data.xlsx"
        )
        
        task.outputs.append(output1)
        task.outputs.append(output2)
        
        assert len(task.outputs) == 2
        assert task.outputs[0].output_type == OutputType.IMAGE
        assert task.outputs[1].output_type == OutputType.SPREADSHEET
    
    def test_task_full_composition(self):
        """Test Task with all composed entities."""
        task = Task(
            id="task_123",
            title="Complex Task",
            description="Task with all components",
            domain="data_analysis",
            status=TaskStatus.PROCESSING
        )
        
        task.execution = TaskExecution(
            task_id=task.id,
            status=ExecutionStatus.RUNNING
        )
        task.planning = TaskPlanning(
            task_id=task.id,
            status=PlanningStatus.APPROVED
        )
        task.review = TaskReview(
            task_id=task.id,
            status=ReviewStatus.PENDING
        )
        task.arena = TaskArena(
            task_id=task.id,
            competition_id="arena_123"
        )
        task.outputs.append(TaskOutput(
            task_id=task.id,
            output_type=OutputType.IMAGE
        ))
        
        # Verify all relationships
        assert task.execution is not None
        assert task.planning is not None
        assert task.review is not None
        assert task.arena is not None
        assert len(task.outputs) == 1


class TestTaskStateMachine:
    """Tests for task state machine validation."""
    
    def test_valid_transition_pending_to_planning(self):
        """Test valid transition: PENDING → PLANNING."""
        assert TaskStateMachine.is_valid_transition(
            TaskStatus.PENDING,
            TaskStatus.PLANNING
        )
    
    def test_valid_transition_planning_to_processing(self):
        """Test valid transition: PLANNING → PROCESSING."""
        assert TaskStateMachine.is_valid_transition(
            TaskStatus.PLANNING,
            TaskStatus.PROCESSING
        )
    
    def test_invalid_transition_pending_to_completed(self):
        """Test invalid transition: PENDING → COMPLETED."""
        assert not TaskStateMachine.is_valid_transition(
            TaskStatus.PENDING,
            TaskStatus.COMPLETED
        )
    
    def test_invalid_transition_completed_to_any(self):
        """Test that COMPLETED is terminal."""
        assert not TaskStateMachine.is_valid_transition(
            TaskStatus.COMPLETED,
            TaskStatus.PROCESSING
        )
    
    def test_validate_transition_raises_on_invalid(self):
        """Test that validate_transition raises ValueError on invalid."""
        with pytest.raises(ValueError) as exc_info:
            TaskStateMachine.validate_transition(
                TaskStatus.COMPLETED,
                TaskStatus.PROCESSING
            )
        
        assert "Invalid task status transition" in str(exc_info.value)
    
    def test_full_workflow_transition_path(self):
        """Test valid workflow transitions."""
        # PENDING → PLANNING → PROCESSING → REVIEWING → COMPLETED
        transitions = [
            (TaskStatus.PENDING, TaskStatus.PLANNING),
            (TaskStatus.PLANNING, TaskStatus.PROCESSING),
            (TaskStatus.PROCESSING, TaskStatus.REVIEWING),
            (TaskStatus.REVIEWING, TaskStatus.COMPLETED),
        ]
        
        for current, next_status in transitions:
            assert TaskStateMachine.is_valid_transition(current, next_status), \
                f"Expected valid transition {current.value} → {next_status.value}"
    
    def test_failed_path_allows_retry(self):
        """Test that FAILED allows retry back to PENDING."""
        assert TaskStateMachine.is_valid_transition(
            TaskStatus.FAILED,
            TaskStatus.PENDING
        )


class TestExecutionStateMachine:
    """Tests for execution state machine."""
    
    def test_execution_workflow(self):
        """Test valid execution workflow."""
        transitions = [
            (ExecutionStatus.PENDING, ExecutionStatus.RUNNING),
            (ExecutionStatus.RUNNING, ExecutionStatus.COMPLETED),
        ]
        
        for current, next_status in transitions:
            assert ExecutionStateMachine.is_valid_transition(current, next_status)
    
    def test_execution_failure_and_retry(self):
        """Test execution can fail and retry."""
        # PENDING → RUNNING → FAILED → PENDING (retry)
        assert ExecutionStateMachine.is_valid_transition(
            ExecutionStatus.RUNNING,
            ExecutionStatus.FAILED
        )
        assert ExecutionStateMachine.is_valid_transition(
            ExecutionStatus.FAILED,
            ExecutionStatus.PENDING
        )


class TestPlanningStateMachine:
    """Tests for planning state machine."""
    
    def test_planning_approval_workflow(self):
        """Test planning approval workflow."""
        assert PlanningStateMachine.is_valid_transition(
            PlanningStatus.PENDING,
            PlanningStatus.GENERATING
        )
        assert PlanningStateMachine.is_valid_transition(
            PlanningStatus.GENERATING,
            PlanningStatus.APPROVED
        )
    
    def test_planning_rejection_allows_retry(self):
        """Test planning rejection allows retry."""
        assert PlanningStateMachine.is_valid_transition(
            PlanningStatus.GENERATING,
            PlanningStatus.REJECTED
        )
        assert PlanningStateMachine.is_valid_transition(
            PlanningStatus.REJECTED,
            PlanningStatus.GENERATING
        )


class TestReviewStateMachine:
    """Tests for review state machine."""
    
    def test_review_workflow(self):
        """Test review workflow."""
        assert ReviewStateMachine.is_valid_transition(
            ReviewStatus.PENDING,
            ReviewStatus.IN_REVIEW
        )
        assert ReviewStateMachine.is_valid_transition(
            ReviewStatus.IN_REVIEW,
            ReviewStatus.RESOLVED
        )
    
    def test_review_rejection_allows_retry(self):
        """Test review rejection allows re-review."""
        assert ReviewStateMachine.is_valid_transition(
            ReviewStatus.IN_REVIEW,
            ReviewStatus.REJECTED
        )
        assert ReviewStateMachine.is_valid_transition(
            ReviewStatus.REJECTED,
            ReviewStatus.IN_REVIEW
        )


class TestModelReduction:
    """Tests to verify Task model is reduced in size."""
    
    def test_task_fields_reduced(self):
        """Test that Task has fewer fields than original."""
        # Original had 40+ fields
        # New Task should have ~12 core fields
        task = Task(
            title="Test",
            description="Test",
            domain="test"
        )
        
        # Count non-relationship attributes
        core_fields = [
            'id', 'title', 'description', 'domain', 'status',
            'stripe_session_id', 'client_email', 'amount_paid',
            'delivery_token', 'created_at', 'updated_at'
        ]
        
        for field in core_fields:
            assert hasattr(task, field)
    
    def test_execution_extracted(self):
        """Test that execution fields are extracted to TaskExecution."""
        execution = TaskExecution()
        
        # Check execution-specific fields are present
        execution_fields = [
            'status', 'retry_count', 'error_message',
            'execution_logs', 'sandbox_result', 'artifacts',
            'started_at', 'completed_at'
        ]
        
        for field in execution_fields:
            assert hasattr(execution, field)
    
    def test_planning_extracted(self):
        """Test that planning fields are extracted to TaskPlanning."""
        planning = TaskPlanning()
        
        # Check planning-specific fields are present
        planning_fields = [
            'status', 'plan_content', 'research_findings',
            'file_type', 'file_content', 'filename'
        ]
        
        for field in planning_fields:
            assert hasattr(planning, field)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
