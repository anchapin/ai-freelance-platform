import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Text, Integer, Enum, DateTime, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class TaskStatus(PyEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    PLANNING = "PLANNING"  # Agent is analyzing files and creating work plan
    PROCESSING = "PROCESSING"  # Agent is executing the plan in E2B sandbox
    REVIEW_REQUIRED = "REVIEW_REQUIRED"  # Artifact needs review
    REVIEWING = "REVIEWING"  # ArtifactReviewer is checking the result
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATION = "ESCALATION"  # Requires human review after max retries (Pillar 1.7)


class ReviewStatus(PyEnum):
    """Status for human review of escalated tasks."""
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class PlanStatus(PyEnum):
    PENDING = "PENDING"
    GENERATING = "GENERATING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    stripe_session_id = Column(String, nullable=True)
    result_image_url = Column(String, nullable=True)  # For image/visualization outputs
    result_document_url = Column(String, nullable=True)  # For document outputs (docx, pdf)
    result_spreadsheet_url = Column(String, nullable=True)  # For spreadsheet outputs (xlsx)
    result_type = Column(String, nullable=True)  # Output type: image, docx, xlsx, pdf
    csv_data = Column(Text, nullable=True)
    # New fields for file uploads
    file_type = Column(String, nullable=True)  # csv, excel, pdf
    file_content = Column(Text, nullable=True)  # Base64-encoded file content
    filename = Column(String, nullable=True)  # Original filename
    # Client tracking fields
    client_email = Column(String, nullable=True)  # Client email for history tracking
    amount_paid = Column(Integer, nullable=True)  # Amount paid in cents
    delivery_token = Column(String, nullable=True)  # Secure token for delivery links
    # Timestamp fields for tracking turnaround time
    created_at = Column(DateTime, default=datetime.utcnow)  # Task creation timestamp
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # Last update timestamp
    
    # === NEW: Research & Plan Workflow Fields ===
    # Work plan fields
    work_plan = Column(Text, nullable=True)  # JSON string containing the work plan
    plan_status = Column(Enum(PlanStatus), default=PlanStatus.PENDING, nullable=False)
    plan_generated_at = Column(DateTime, nullable=True)  # When the plan was generated
    
    # Analysis context from uploaded files
    extracted_context = Column(JSON, nullable=True)  # Extracted context from PDF/Excel files
    
    # Review fields for ArtifactReviewer
    review_feedback = Column(Text, nullable=True)  # Feedback from ArtifactReviewer
    review_approved = Column(Boolean, default=False)  # Whether the artifact was approved
    review_attempts = Column(Integer, default=0)  # Number of review attempts
    last_review_at = Column(DateTime, nullable=True)  # When the last review was performed
    
    # Execution tracking
    execution_log = Column(JSON, nullable=True)  # Log of execution steps
    retry_count = Column(Integer, default=0)  # Number of retries attempted

    # === NEW: Escalation & Human-in-the-Loop (HITL) Fields (Pillar 1.7) ===
    # Escalation tracking
    escalation_reason = Column(String, nullable=True)  # Why task was escalated (e.g., "max_retries_exceeded", "high_value_task_failed")
    escalated_at = Column(DateTime, nullable=True)  # When task was escalated
    last_error = Column(Text, nullable=True)  # The error that caused escalation
    
    # Human review fields
    review_status = Column(Enum(ReviewStatus), default=ReviewStatus.PENDING, nullable=False)  # Status of human review
    human_review_notes = Column(Text, nullable=True)  # Notes from human reviewer after fixing
    human_reviewer = Column(String, nullable=True)  # Email/name of who reviewed the escalated task
    reviewed_at = Column(DateTime, nullable=True)  # When human review was completed
    
    # Profit protection - indicates if this is a high-value task requiring special handling
    is_high_value = Column(Boolean, default=False)  # True if task value >= HIGH_VALUE_THRESHOLD

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "domain": self.domain,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "stripe_session_id": self.stripe_session_id,
            "result_image_url": self.result_image_url,
            "result_document_url": self.result_document_url,
            "result_spreadsheet_url": self.result_spreadsheet_url,
            "result_type": self.result_type,
            "csv_data": self.csv_data,
            "file_type": self.file_type,
            "filename": self.filename,
            "client_email": self.client_email,
            "amount_paid": self.amount_paid,
            "amount_dollars": (self.amount_paid / 100) if self.amount_paid else None,
            "delivery_token": self.delivery_token,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            # New fields
            "work_plan": self.work_plan,
            "plan_status": self.plan_status.value if isinstance(self.plan_status, PlanStatus) else self.plan_status,
            "plan_generated_at": self.plan_generated_at.isoformat() if self.plan_generated_at else None,
            "extracted_context": self.extracted_context,
            "review_feedback": self.review_feedback,
            "review_approved": self.review_approved,
            "review_attempts": self.review_attempts,
            "last_review_at": self.last_review_at.isoformat() if self.last_review_at else None,
            "execution_log": self.execution_log,
            "retry_count": self.retry_count,
            # Escalation fields (Pillar 1.7)
            "escalation_reason": self.escalation_reason,
            "escalated_at": self.escalated_at.isoformat() if self.escalated_at else None,
            "last_error": self.last_error,
            "review_status": self.review_status.value if isinstance(self.review_status, ReviewStatus) else self.review_status,
            "human_review_notes": self.human_review_notes,
            "human_reviewer": self.human_reviewer,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "is_high_value": self.is_high_value,
        }
