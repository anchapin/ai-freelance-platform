"""
Task State Machine Validation

Prevents invalid state transitions in the refactored Task model.

Issue #5: Refactor overloaded Task model using composition pattern
"""

from typing import Set, Dict

from src.api.models_composition import (
    TaskStatus,
    ExecutionStatus,
    PlanningStatus,
    ReviewStatus,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TaskStateMachine:
    """
    Validates task state transitions.
    
    Enforces a state machine to prevent impossible task status transitions.
    """
    
    # Define valid transitions from each state
    VALID_TRANSITIONS: Dict[TaskStatus, Set[TaskStatus]] = {
        TaskStatus.PENDING: {TaskStatus.PLANNING, TaskStatus.FAILED},
        TaskStatus.PLANNING: {TaskStatus.PROCESSING, TaskStatus.FAILED},
        TaskStatus.PROCESSING: {
            TaskStatus.REVIEW_REQUIRED,
            TaskStatus.REVIEWING,
            TaskStatus.FAILED,
            TaskStatus.ESCALATION,
        },
        TaskStatus.REVIEW_REQUIRED: {TaskStatus.REVIEWING, TaskStatus.FAILED},
        TaskStatus.REVIEWING: {
            TaskStatus.COMPLETED,
            TaskStatus.PROCESSING,  # Can send back for fixes
            TaskStatus.ESCALATION,
        },
        TaskStatus.COMPLETED: set(),  # Terminal state
        TaskStatus.FAILED: {TaskStatus.PENDING},  # Can retry
        TaskStatus.ESCALATION: {TaskStatus.COMPLETED, TaskStatus.FAILED},
        TaskStatus.PAID: {TaskStatus.PLANNING},
    }
    
    @staticmethod
    def is_valid_transition(
        current_status: TaskStatus,
        new_status: TaskStatus
    ) -> bool:
        """
        Check if transition is valid.
        
        Args:
            current_status: Current task status
            new_status: Desired new status
            
        Returns:
            True if transition is allowed
        """
        if current_status not in TaskStateMachine.VALID_TRANSITIONS:
            return False
        
        return new_status in TaskStateMachine.VALID_TRANSITIONS[current_status]
    
    @staticmethod
    def validate_transition(
        current_status: TaskStatus,
        new_status: TaskStatus
    ) -> None:
        """
        Validate transition and raise exception if invalid.
        
        Args:
            current_status: Current task status
            new_status: Desired new status
            
        Raises:
            ValueError: If transition is invalid
        """
        if not TaskStateMachine.is_valid_transition(current_status, new_status):
            raise ValueError(
                f"Invalid task status transition: "
                f"{current_status.value} → {new_status.value}"
            )


class ExecutionStateMachine:
    """Validates execution state transitions."""
    
    VALID_TRANSITIONS: Dict[ExecutionStatus, Set[ExecutionStatus]] = {
        ExecutionStatus.PENDING: {ExecutionStatus.RUNNING, ExecutionStatus.FAILED},
        ExecutionStatus.RUNNING: {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED},
        ExecutionStatus.COMPLETED: set(),  # Terminal
        ExecutionStatus.FAILED: {ExecutionStatus.PENDING},  # Can retry
    }
    
    @staticmethod
    def is_valid_transition(
        current_status: ExecutionStatus,
        new_status: ExecutionStatus
    ) -> bool:
        if current_status not in ExecutionStateMachine.VALID_TRANSITIONS:
            return False
        return new_status in ExecutionStateMachine.VALID_TRANSITIONS[current_status]


class PlanningStateMachine:
    """Validates planning state transitions."""
    
    VALID_TRANSITIONS: Dict[PlanningStatus, Set[PlanningStatus]] = {
        PlanningStatus.PENDING: {PlanningStatus.GENERATING},
        PlanningStatus.GENERATING: {PlanningStatus.APPROVED, PlanningStatus.REJECTED},
        PlanningStatus.APPROVED: set(),  # Terminal
        PlanningStatus.REJECTED: {PlanningStatus.GENERATING},  # Can retry
    }
    
    @staticmethod
    def is_valid_transition(
        current_status: PlanningStatus,
        new_status: PlanningStatus
    ) -> bool:
        if current_status not in PlanningStateMachine.VALID_TRANSITIONS:
            return False
        return new_status in PlanningStateMachine.VALID_TRANSITIONS[current_status]


class ReviewStateMachine:
    """Validates review state transitions."""
    
    VALID_TRANSITIONS: Dict[ReviewStatus, Set[ReviewStatus]] = {
        ReviewStatus.PENDING: {ReviewStatus.IN_REVIEW},
        ReviewStatus.IN_REVIEW: {ReviewStatus.RESOLVED, ReviewStatus.REJECTED},
        ReviewStatus.RESOLVED: set(),  # Terminal
        ReviewStatus.REJECTED: {ReviewStatus.IN_REVIEW},  # Can re-review
    }
    
    @staticmethod
    def is_valid_transition(
        current_status: ReviewStatus,
        new_status: ReviewStatus
    ) -> bool:
        if current_status not in ReviewStateMachine.VALID_TRANSITIONS:
            return False
        return new_status in ReviewStateMachine.VALID_TRANSITIONS[current_status]


def validate_task_transition(
    task_id: str,
    current_status: TaskStatus,
    new_status: TaskStatus
) -> None:
    """
    Validate and log task status transition.
    
    Args:
        task_id: Task ID for logging
        current_status: Current status
        new_status: Desired status
        
    Raises:
        ValueError: If transition is invalid
    """
    try:
        TaskStateMachine.validate_transition(current_status, new_status)
        logger.info(f"Task {task_id}: {current_status.value} → {new_status.value}")
    except ValueError as e:
        logger.error(f"Task {task_id}: {e}")
        raise
