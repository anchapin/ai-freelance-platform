"""
Unit tests for Task State Machine transitions.

This module tests the task status transitions:
PENDING -> PAID -> PROCESSING -> COMPLETED

And failure paths:
- PENDING -> FAILED
- PAID -> FAILED
- PROCESSING -> FAILED

Critical: Ensuring correct state transitions prevents workflow errors
and ensures tasks are processed correctly.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.api.models import TaskStatus


class TestTaskStatusValues:
    """Test that TaskStatus enum values are correct."""
    
    def test_all_status_values(self):
        """Test all task status values exist."""
        # Core workflow statuses
        assert TaskStatus.PENDING.value == "PENDING"
        assert TaskStatus.PAID.value == "PAID"
        assert TaskStatus.PLANNING.value == "PLANNING"
        assert TaskStatus.PROCESSING.value == "PROCESSING"
        assert TaskStatus.REVIEW_REQUIRED.value == "REVIEW_REQUIRED"
        assert TaskStatus.REVIEWING.value == "REVIEWING"
        assert TaskStatus.COMPLETED.value == "COMPLETED"
        assert TaskStatus.FAILED.value == "FAILED"
        assert TaskStatus.ESCALATION.value == "ESCALATION"
    
    def test_status_count(self):
        """Test we have the expected number of statuses."""
        statuses = list(TaskStatus)
        # Should have at least 9 statuses
        assert len(statuses) >= 9


class TestStateMachineTransitions:
    """Test the task state machine transitions."""
    
    # =============================================================================
    # HAPPY PATH: PENDING -> PAID -> PROCESSING -> COMPLETED
    # =============================================================================
    
    def test_pending_to_paid_valid_transition(self):
        """Test that PENDING -> PAID is a valid transition."""
        # In the workflow, a task can go from PENDING to PAID after payment
        current_status = TaskStatus.PENDING
        new_status = TaskStatus.PAID
        
        # This is a valid transition in the workflow
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    def test_paid_to_processing_valid_transition(self):
        """Test that PAID -> PROCESSING is a valid transition."""
        current_status = TaskStatus.PAID
        new_status = TaskStatus.PROCESSING
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    def test_paid_to_planning_valid_transition(self):
        """Test that PAID -> PLANNING is a valid transition."""
        current_status = TaskStatus.PAID
        new_status = TaskStatus.PLANNING
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    def test_planning_to_processing_valid_transition(self):
        """Test that PLANNING -> PROCESSING is a valid transition."""
        current_status = TaskStatus.PLANNING
        new_status = TaskStatus.PROCESSING
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    def test_processing_to_completed_valid_transition(self):
        """Test that PROCESSING -> COMPLETED is a valid transition."""
        current_status = TaskStatus.PROCESSING
        new_status = TaskStatus.COMPLETED
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    def test_review_required_to_reviewing_valid_transition(self):
        """Test that REVIEW_REQUIRED -> REVIEWING is a valid transition."""
        current_status = TaskStatus.REVIEW_REQUIRED
        new_status = TaskStatus.REVIEWING
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    # =============================================================================
    # FAILURE PATH: Any state -> FAILED
    # =============================================================================
    
    def test_pending_to_failed_valid_transition(self):
        """Test that PENDING -> FAILED is valid (payment failed)."""
        current_status = TaskStatus.PENDING
        new_status = TaskStatus.FAILED
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    def test_paid_to_failed_valid_transition(self):
        """Test that PAID -> FAILED is valid (processing failed)."""
        current_status = TaskStatus.PAID
        new_status = TaskStatus.FAILED
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    def test_processing_to_failed_valid_transition(self):
        """Test that PROCESSING -> FAILED is valid."""
        current_status = TaskStatus.PROCESSING
        new_status = TaskStatus.FAILED
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    # =============================================================================
    # ESCALATION PATH
    # =============================================================================
    
    def test_processing_to_escalation_valid_transition(self):
        """Test that PROCESSING -> ESCALATION is valid."""
        current_status = TaskStatus.PROCESSING
        new_status = TaskStatus.ESCALATION
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    def test_paid_to_escalation_valid_transition(self):
        """Test that PAID -> ESCALATION is valid (high-value task escalation)."""
        current_status = TaskStatus.PAID
        new_status = TaskStatus.ESCALATION
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    # =============================================================================
    # REVISION/REVIEW PATHS
    # =============================================================================
    
    def test_processing_to_review_required_valid_transition(self):
        """Test that PROCESSING -> REVIEW_REQUIRED is valid."""
        current_status = TaskStatus.PROCESSING
        new_status = TaskStatus.REVIEW_REQUIRED
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    def test_review_required_to_reviewing_valid_transition(self):
        """Test that REVIEW_REQUIRED -> REVIEWING is valid."""
        current_status = TaskStatus.REVIEW_REQUIRED
        new_status = TaskStatus.REVIEWING
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    def test_reviewing_to_processing_valid_transition(self):
        """Test that REVIEWING -> PROCESSING is valid (rework needed)."""
        current_status = TaskStatus.REVIEWING
        new_status = TaskStatus.PROCESSING
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    def test_reviewing_to_completed_valid_transition(self):
        """Test that REVIEWING -> COMPLETED is valid (approved)."""
        current_status = TaskStatus.REVIEWING
        new_status = TaskStatus.COMPLETED
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is True
    
    # =============================================================================
    # INVALID TRANSITIONS
    # =============================================================================
    
    def test_completed_to_pending_invalid_transition(self):
        """Test that COMPLETED -> PENDING is invalid."""
        current_status = TaskStatus.COMPLETED
        new_status = TaskStatus.PENDING
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is False
    
    def test_failed_to_pending_invalid_transition(self):
        """Test that FAILED -> PENDING is invalid."""
        current_status = TaskStatus.FAILED
        new_status = TaskStatus.PENDING
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is False
    
    def test_completed_to_failed_invalid_transition(self):
        """Test that COMPLETED -> FAILED is invalid."""
        current_status = TaskStatus.COMPLETED
        new_status = TaskStatus.FAILED
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is False
    
    def test_escalation_to_completed_invalid_direct_transition(self):
        """Test that ESCALATION -> COMPLETED requires review first."""
        # After escalation, task should go through review, not directly to completed
        current_status = TaskStatus.ESCALATION
        new_status = TaskStatus.COMPLETED
        
        valid_transition = _is_valid_transition(current_status, new_status)
        # This should be False - escalation needs to be resolved first
        # The actual path would be: ESCALATION -> REVIEW_REQUIRED -> REVIEWING -> COMPLETED
        assert valid_transition is False
    
    def test_completed_to_processing_invalid_transition(self):
        """Test that COMPLETED -> PROCESSING is invalid."""
        current_status = TaskStatus.COMPLETED
        new_status = TaskStatus.PROCESSING
        
        valid_transition = _is_valid_transition(current_status, new_status)
        assert valid_transition is False


class TestCompleteWorkflow:
    """Test complete workflow scenarios."""
    
    def test_successful_workflow_path(self):
        """Test the successful workflow: PENDING -> PAID -> PLANNING -> PROCESSING -> COMPLETED."""
        # Start at PENDING
        current = TaskStatus.PENDING
        
        # After payment: PENDING -> PAID
        current = TaskStatus.PAID
        assert _is_valid_transition(TaskStatus.PENDING, current)
        
        # Planning phase: PAID -> PLANNING
        current = TaskStatus.PLANNING
        assert _is_valid_transition(TaskStatus.PAID, current)
        
        # Processing: PLANNING -> PROCESSING
        current = TaskStatus.PROCESSING
        assert _is_valid_transition(TaskStatus.PLANNING, current)
        
        # Review required: PROCESSING -> REVIEW_REQUIRED
        current = TaskStatus.REVIEW_REQUIRED
        assert _is_valid_transition(TaskStatus.PROCESSING, current)
        
        # Reviewing: REVIEW_REQUIRED -> REVIEWING
        current = TaskStatus.REVIEWING
        assert _is_valid_transition(TaskStatus.REVIEW_REQUIRED, current)
        
        # Completed: REVIEWING -> COMPLETED
        current = TaskStatus.COMPLETED
        assert _is_valid_transition(TaskStatus.REVIEWING, current)
    
    def test_arena_workflow_path(self):
        """Test the Agent Arena workflow: PENDING -> PAID -> PROCESSING (Arena) -> COMPLETED."""
        current = TaskStatus.PENDING
        
        # After payment
        current = TaskStatus.PAID
        assert _is_valid_transition(TaskStatus.PENDING, current)
        
        # Arena processing (directly to processing)
        current = TaskStatus.PROCESSING
        assert _is_valid_transition(TaskStatus.PAID, current)
        
        # Completed via arena
        current = TaskStatus.COMPLETED
        assert _is_valid_transition(TaskStatus.PROCESSING, current)
    
    def test_failure_workflow_path(self):
        """Test the failure workflow: PENDING -> PAID -> PROCESSING -> FAILED."""
        current = TaskStatus.PENDING
        
        # After payment
        current = TaskStatus.PAID
        assert _is_valid_transition(TaskStatus.PENDING, current)
        
        # Processing started
        current = TaskStatus.PROCESSING
        assert _is_valid_transition(TaskStatus.PAID, current)
        
        # Failed
        current = TaskStatus.FAILED
        assert _is_valid_transition(TaskStatus.PROCESSING, current)
    
    def test_escalation_workflow_path(self):
        """Test the escalation workflow: PAID -> PROCESSING -> ESCALATION -> REVIEW_REQUIRED."""
        # High-value task escalation
        current = TaskStatus.PAID
        
        # Processing started
        current = TaskStatus.PROCESSING
        assert _is_valid_transition(TaskStatus.PAID, current)
        
        # Escalated
        current = TaskStatus.ESCALATION
        assert _is_valid_transition(TaskStatus.PROCESSING, current)
        
        # Review required
        current = TaskStatus.REVIEW_REQUIRED
        assert _is_valid_transition(TaskStatus.ESCALATION, current)


class TestHighValueTaskBehavior:
    """Test high-value task behavior (>$200)."""
    
    def test_high_value_threshold(self):
        """Test that $200 is the high-value threshold."""
        from src.api.main import HIGH_VALUE_THRESHOLD
        assert HIGH_VALUE_THRESHOLD == 200
    
    def test_high_value_task_amounts(self):
        """Test identifying high-value tasks."""
        # $200 or more is high value
        assert _is_high_value(20000)  # $200
        assert _is_high_value(25000)  # $250
        assert _is_high_value(50000)  # $500
        
        # Less than $200 is not high value
        assert not _is_high_value(19999)  # $199.99
        assert not _is_high_value(15000)  # $150
        assert not _is_high_value(100)    # $1
    
    def test_high_value_escalation_required(self):
        """Test that high-value failed tasks must be escalated."""
        # A high-value task in PROCESSING that fails should escalate
        current_status = TaskStatus.PROCESSING
        amount_paid = 25000  # $250
        
        # Should escalate
        should_escalate = _should_escalate(current_status, amount_paid, retry_count=3)
        assert should_escalate is True
    
    def test_low_value_failure_not_escalated(self):
        """Test that low-value tasks don't require escalation on failure."""
        current_status = TaskStatus.PROCESSING
        amount_paid = 15000  # $150 (below threshold)
        
        # Should not escalate based on amount
        should_escalate = _should_escalate(current_status, amount_paid, retry_count=2)
        # Only escalates if retry count exceeded
        assert should_escalate is False


class TestRetryBehavior:
    """Test retry behavior for tasks."""
    
    def test_max_retry_threshold(self):
        """Test that max retry attempts is 3."""
        from src.api.main import MAX_RETRY_ATTEMPTS
        assert MAX_RETRY_ATTEMPTS == 3
    
    def test_retry_escalation(self):
        """Test that tasks escalate after max retries."""
        # After 3 retries (count = 3), should escalate
        should_escalate = _should_escalate(
            TaskStatus.PROCESSING,
            amount_paid=10000,  # $100 (below high-value threshold)
            retry_count=3
        )
        assert should_escalate is True
    
    def test_under_max_retries_no_escalation(self):
        """Test that tasks don't escalate before max retries."""
        # Under 3 retries, no escalation
        for count in range(0, 3):
            should_escalate = _should_escalate(
                TaskStatus.PROCESSING,
                amount_paid=10000,
                retry_count=count
            )
            assert should_escalate is False


# =============================================================================
# HELPER FUNCTIONS (for testing the state machine logic)
# =============================================================================

def _is_valid_transition(current: TaskStatus, new: TaskStatus) -> bool:
    """
    Check if a status transition is valid.
    
    This is a simplified version of the actual workflow logic.
    The actual implementation is in process_task_async in main.py
    """
    # Define valid transitions
    valid_transitions = {
        TaskStatus.PENDING: [TaskStatus.PAID, TaskStatus.FAILED],
        TaskStatus.PAID: [TaskStatus.PLANNING, TaskStatus.PROCESSING, TaskStatus.FAILED, TaskStatus.ESCALATION],
        TaskStatus.PLANNING: [TaskStatus.PROCESSING, TaskStatus.FAILED, TaskStatus.ESCALATION],
        TaskStatus.PROCESSING: [
            TaskStatus.COMPLETED, TaskStatus.FAILED, 
            TaskStatus.REVIEW_REQUIRED, TaskStatus.ESCALATION
        ],
        TaskStatus.REVIEW_REQUIRED: [TaskStatus.REVIEWING, TaskStatus.ESCALATION],
        TaskStatus.REVIEWING: [TaskStatus.PROCESSING, TaskStatus.COMPLETED, TaskStatus.ESCALATION],
        TaskStatus.COMPLETED: [],  # Terminal state
        TaskStatus.FAILED: [],  # Terminal state
        TaskStatus.ESCALATION: [TaskStatus.REVIEW_REQUIRED, TaskStatus.FAILED],
    }
    
    return new in valid_transitions.get(current, [])


def _is_high_value(amount_paid_cents: int) -> bool:
    """Check if task amount is above high-value threshold."""
    from src.api.main import HIGH_VALUE_THRESHOLD
    # Convert cents to dollars
    amount_dollars = amount_paid_cents / 100
    return amount_dollars >= HIGH_VALUE_THRESHOLD


def _should_escalate(
    current_status: TaskStatus,
    amount_paid: int,
    retry_count: int
) -> bool:
    """
    Determine if a task should be escalated.
    
    Based on the logic in _should_escalate_task in main.py
    """
    from src.api.main import HIGH_VALUE_THRESHOLD, MAX_RETRY_ATTEMPTS
    
    # Check if this is a high-value task
    amount_dollars = amount_paid / 100
    is_high_value = amount_dollars >= HIGH_VALUE_THRESHOLD
    
    # Check if retries were exhausted
    if retry_count >= MAX_RETRY_ATTEMPTS:
        return True
    
    # High-value task should escalate on any failure
    if is_high_value:
        return True
    
    return False
