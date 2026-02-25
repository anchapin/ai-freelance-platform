"""
Refactored Task Model Using Composition Pattern

Decompose the monolithic Task model into focused entities:
- Task: Core task information only
- TaskExecution: Execution-specific fields
- TaskPlanning: Planning and research fields
- TaskReview: Review and feedback fields
- TaskArena: Arena competition fields
- TaskOutput: Output results

Issue #5: Refactor overloaded Task model using composition pattern
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Enum,
    DateTime,
    Boolean,
    JSON,
    ForeignKey,
    Float,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


# ============================================================================
# ENUMS (existing, reused)
# ============================================================================


class TaskStatus(PyEnum):
    """Main task status."""

    PENDING = "PENDING"
    PAID = "PAID"
    PLANNING = "PLANNING"
    PROCESSING = "PROCESSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATION = "ESCALATION"


class ExecutionStatus(PyEnum):
    """Execution-specific status."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PlanningStatus(PyEnum):
    """Planning-specific status."""

    PENDING = "PENDING"
    GENERATING = "GENERATING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewStatus(PyEnum):
    """Review-specific status."""

    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class OutputType(PyEnum):
    """Output result types."""

    IMAGE = "IMAGE"
    DOCUMENT = "DOCUMENT"
    SPREADSHEET = "SPREADSHEET"
    PDF = "PDF"
    CODE = "CODE"
    OTHER = "OTHER"


# ============================================================================
# CORE TASK
# ============================================================================


class Task(Base):
    """
    Core Task model - reduced to essential fields only.

    Contains only the essential information needed for task tracking,
    client management, and billing. All other concerns are delegated to
    related entities via composition.
    """

    __tablename__ = "tasks_refactored"

    # Primary key and identifiers
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Task content
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    domain = Column(String, nullable=False)

    # Status
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False)

    # Billing and client
    stripe_session_id = Column(String, nullable=True)
    client_email = Column(String, nullable=True)
    amount_paid = Column(Integer, nullable=True)  # In cents
    delivery_token = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships to composed entities (one-to-one)
    execution = relationship(
        "TaskExecution", uselist=False, cascade="all, delete-orphan"
    )
    planning = relationship("TaskPlanning", uselist=False, cascade="all, delete-orphan")
    review = relationship("TaskReview", uselist=False, cascade="all, delete-orphan")
    arena = relationship("TaskArena", uselist=False, cascade="all, delete-orphan")
    outputs = relationship("TaskOutput", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "domain": self.domain,
            "status": self.status.value
            if isinstance(self.status, TaskStatus)
            else self.status,
            "stripe_session_id": self.stripe_session_id,
            "client_email": self.client_email,
            "amount_paid": self.amount_paid,
            "amount_dollars": (self.amount_paid / 100) if self.amount_paid else None,
            "delivery_token": self.delivery_token,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# EXECUTION COMPOSITION
# ============================================================================


class TaskExecution(Base):
    """
    Task execution state and results.

    Tracks the execution-specific information: status, retries, errors,
    logs, sandbox results, and artifacts.
    """

    __tablename__ = "task_executions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(
        String, ForeignKey("tasks_refactored.id"), unique=True, nullable=False
    )

    # Execution status and tracking
    status = Column(
        Enum(ExecutionStatus), default=ExecutionStatus.PENDING, nullable=False
    )
    retry_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    # Execution details
    execution_logs = Column(JSON, nullable=True)
    sandbox_result = Column(JSON, nullable=True)
    artifacts = Column(JSON, nullable=True)

    # Timestamps
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "status": self.status.value
            if isinstance(self.status, ExecutionStatus)
            else self.status,
            "retry_count": self.retry_count,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
        }


# ============================================================================
# PLANNING COMPOSITION
# ============================================================================


class TaskPlanning(Base):
    """
    Task planning and research results.

    Tracks planning-specific information: status, plan content,
    research findings, and generated files.
    """

    __tablename__ = "task_planning"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(
        String, ForeignKey("tasks_refactored.id"), unique=True, nullable=False
    )

    # Planning status
    status = Column(
        Enum(PlanningStatus), default=PlanningStatus.PENDING, nullable=False
    )

    # Plan and research
    plan_content = Column(Text, nullable=True)
    research_findings = Column(JSON, nullable=True)

    # File uploads from planning phase
    file_type = Column(String, nullable=True)  # csv, excel, pdf
    file_content = Column(Text, nullable=True)  # Base64-encoded
    filename = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "status": self.status.value
            if isinstance(self.status, PlanningStatus)
            else self.status,
            "plan_content": self.plan_content,
            "filename": self.filename,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# REVIEW COMPOSITION
# ============================================================================


class TaskReview(Base):
    """
    Task review and feedback.

    Tracks review-specific information: approval status, feedback,
    escalation requirements.
    """

    __tablename__ = "task_reviews"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(
        String, ForeignKey("tasks_refactored.id"), unique=True, nullable=False
    )

    # Review status
    status = Column(Enum(ReviewStatus), default=ReviewStatus.PENDING, nullable=False)
    approved = Column(Boolean, default=False)

    # Feedback
    review_feedback = Column(Text, nullable=True)
    reviewer_id = Column(String, nullable=True)

    # Escalation
    needs_escalation = Column(Boolean, default=False)
    escalation_reason = Column(String, nullable=True)

    # Timestamps
    reviewed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "status": self.status.value
            if isinstance(self.status, ReviewStatus)
            else self.status,
            "approved": self.approved,
            "review_feedback": self.review_feedback,
            "needs_escalation": self.needs_escalation,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }


# ============================================================================
# ARENA COMPOSITION
# ============================================================================


class TaskArena(Base):
    """
    Arena competition results.

    Tracks A/B testing data between different agent configurations,
    models, and strategies.
    """

    __tablename__ = "task_arenas"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(
        String, ForeignKey("tasks_refactored.id"), unique=True, nullable=False
    )

    # Competition metadata
    competition_id = Column(String, nullable=True)

    # Results
    winning_model = Column(String, nullable=True)
    local_score = Column(Float, nullable=True)
    cloud_score = Column(Float, nullable=True)
    profit_score = Column(Float, nullable=True)

    # Full results
    local_result = Column(JSON, nullable=True)
    cloud_result = Column(JSON, nullable=True)

    # Timestamps
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "competition_id": self.competition_id,
            "winning_model": self.winning_model,
            "local_score": self.local_score,
            "cloud_score": self.cloud_score,
            "profit_score": self.profit_score,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
        }


# ============================================================================
# OUTPUT COMPOSITION (polymorphic)
# ============================================================================


class TaskOutput(Base):
    """
    Task output results (polymorphic).

    Stores the various outputs a task can produce: images, documents,
    spreadsheets, etc. One task can have multiple outputs.
    """

    __tablename__ = "task_outputs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey("tasks_refactored.id"), nullable=False)

    # Output type and location
    output_type = Column(Enum(OutputType), nullable=False)
    output_url = Column(String, nullable=True)
    output_data = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "output_type": self.output_type.value
            if isinstance(self.output_type, OutputType)
            else self.output_type,
            "output_url": self.output_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
