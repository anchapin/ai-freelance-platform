import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Float,
    Enum,
    DateTime,
    Boolean,
    JSON,
    UniqueConstraint,
    Index,
)
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


class ArenaCompetitionStatus(PyEnum):
    """Status for arena competitions."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ClientProfile(Base):
    """
    Client Preference Memory (Pillar 2.5 Gap)

    Stores client preferences extracted from previous review feedback.
    This allows the agent to remember preferences like "Blue charts" or
    "Times New Roman font" to avoid failing ArtifactReviewer step.

    Cost Savings:
    - If agent knows preferences upfront, it avoids failing ArtifactReviewer
    - Saves an entire LLM retry cycle and reduces token costs
    """

    __tablename__ = "client_profiles"

    __table_args__ = (UniqueConstraint("client_email", name="unique_client_email"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    client_email = Column(
        String, nullable=False, index=True
    )  # Client email (indexed + unique, prevents duplicate profiles)

    # Extracted preferences from previous tasks
    preferred_colors = Column(JSON, nullable=True)  # e.g., ["blue", "green"]
    preferred_fonts = Column(JSON, nullable=True)  # e.g., ["Times New Roman", "Arial"]
    preferred_chart_types = Column(JSON, nullable=True)  # e.g., ["bar", "line"]
    preferred_output_formats = Column(JSON, nullable=True)  # e.g., ["image", "docx"]

    # General preferences (style, tone, formatting)
    style_preferences = Column(
        JSON, nullable=True
    )  # e.g., {"formal": true, "detailed": false}
    domain_specific_preferences = Column(
        JSON, nullable=True
    )  # Domain-specific preferences

    # Feedback history (raw feedback for reference)
    feedback_history = Column(JSON, nullable=True)  # List of past review feedback

    # Statistics
    total_tasks = Column(Integer, default=0)
    completed_tasks = Column(Integer, default=0)
    failed_tasks = Column(Integer, default=0)
    average_rating = Column(Integer, nullable=True)  # 1-5 rating if available

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_task_at = Column(DateTime, nullable=True)  # When the last task was completed

    def to_dict(self):
        return {
            "id": self.id,
            "client_email": self.client_email,
            "preferred_colors": self.preferred_colors,
            "preferred_fonts": self.preferred_fonts,
            "preferred_chart_types": self.preferred_chart_types,
            "preferred_output_formats": self.preferred_output_formats,
            "style_preferences": self.style_preferences,
            "domain_specific_preferences": self.domain_specific_preferences,
            "feedback_history": self.feedback_history,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "average_rating": self.average_rating,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_task_at": self.last_task_at.isoformat()
            if self.last_task_at
            else None,
        }

    def get_preferences_summary(self) -> str:
        """Get a human-readable summary of preferences for LLM prompts."""
        parts = []

        if self.preferred_colors:
            parts.append(f"Preferred colors: {', '.join(self.preferred_colors)}")
        if self.preferred_fonts:
            parts.append(f"Preferred fonts: {', '.join(self.preferred_fonts)}")
        if self.preferred_chart_types:
            parts.append(
                f"Preferred chart types: {', '.join(self.preferred_chart_types)}"
            )
        if self.preferred_output_formats:
            parts.append(
                f"Preferred output formats: {', '.join(self.preferred_output_formats)}"
            )

        if self.style_preferences:
            for key, value in self.style_preferences.items():
                if value:
                    parts.append(f"Style: {key}")

        return " | ".join(parts) if parts else "No preferences recorded"


class Task(Base):
    __tablename__ = "tasks"

    # Performance indexes and unique constraints (Issue #33, #38)
    __table_args__ = (
        UniqueConstraint("stripe_session_id", name="unique_stripe_session_id"),
        UniqueConstraint("delivery_token", name="unique_delivery_token"),
        Index("idx_task_client_email", "client_email"),
        Index("idx_task_status", "status"),
        Index("idx_task_created_at", "created_at"),
        Index("idx_task_client_status", "client_email", "status"),  # Composite
        Index("idx_task_status_created", "status", "created_at"),  # Composite
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    stripe_session_id = Column(
        String, nullable=True, index=True
    )  # Unique to prevent duplicate payment sessions (Issue #33)
    result_image_url = Column(String, nullable=True)  # For image/visualization outputs
    result_document_url = Column(
        String, nullable=True
    )  # For document outputs (docx, pdf)
    result_spreadsheet_url = Column(
        String, nullable=True
    )  # For spreadsheet outputs (xlsx)
    result_type = Column(String, nullable=True)  # Output type: image, docx, xlsx, pdf
    csv_data = Column(Text, nullable=True)
    # New fields for file uploads
    file_type = Column(String, nullable=True)  # csv, excel, pdf
    file_content = Column(Text, nullable=True)  # Base64-encoded file content
    filename = Column(String, nullable=True)  # Original filename
    # Client tracking fields
    client_email = Column(String, nullable=True)  # Client email for history tracking
    amount_paid = Column(Integer, nullable=True)  # Amount paid in cents
    delivery_token = Column(
        String, nullable=True, index=True
    )  # Unique token for secure delivery, one-time use (Issue #18, #33)
    delivery_token_expires_at = Column(
        DateTime, nullable=True
    )  # Token expiration (Issue #18)
    delivery_token_used = Column(
        Boolean, default=False
    )  # One-time use flag (Issue #18)
    # Timestamp fields for tracking turnaround time
    created_at = Column(DateTime, default=datetime.utcnow)  # Task creation timestamp
    completed_at = Column(DateTime, nullable=True)  # Task completion timestamp
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )  # Last update timestamp

    # === NEW: Research & Plan Workflow Fields ===
    # Work plan fields
    work_plan = Column(Text, nullable=True)  # JSON string containing the work plan
    plan_status = Column(Enum(PlanStatus), default=PlanStatus.PENDING, nullable=False)
    plan_generated_at = Column(DateTime, nullable=True)  # When the plan was generated

    # Analysis context from uploaded files
    extracted_context = Column(
        JSON, nullable=True
    )  # Extracted context from PDF/Excel files

    # Review fields for ArtifactReviewer
    review_feedback = Column(Text, nullable=True)  # Feedback from ArtifactReviewer
    review_approved = Column(
        Boolean, default=False
    )  # Whether the artifact was approved
    review_attempts = Column(Integer, default=0)  # Number of review attempts
    last_review_at = Column(
        DateTime, nullable=True
    )  # When the last review was performed

    # Execution tracking
    execution_log = Column(JSON, nullable=True)  # Log of execution steps
    retry_count = Column(Integer, default=0)  # Number of retries attempted

    # === NEW: Escalation & Human-in-the-Loop (HITL) Fields (Pillar 1.7) ===
    # Escalation tracking
    escalation_reason = Column(
        String, nullable=True
    )  # Why task was escalated (e.g., "max_retries_exceeded", "high_value_task_failed")
    escalated_at = Column(DateTime, nullable=True)  # When task was escalated
    last_error = Column(Text, nullable=True)  # The error that caused escalation

    # Human review fields
    review_status = Column(
        Enum(ReviewStatus), default=ReviewStatus.PENDING, nullable=False
    )  # Status of human review
    human_review_notes = Column(
        Text, nullable=True
    )  # Notes from human reviewer after fixing
    human_reviewer = Column(
        String, nullable=True
    )  # Email/name of who reviewed the escalated task
    reviewed_at = Column(DateTime, nullable=True)  # When human review was completed

    # Profit protection - indicates if this is a high-value task requiring special handling
    is_high_value = Column(
        Boolean, default=False
    )  # True if task value >= HIGH_VALUE_THRESHOLD

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
            "delivery_token_expires_at": self.delivery_token_expires_at.isoformat()
            if self.delivery_token_expires_at
            else None,
            "delivery_token_used": self.delivery_token_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            # New fields
            "work_plan": self.work_plan,
            "plan_status": self.plan_status.value
            if isinstance(self.plan_status, PlanStatus)
            else self.plan_status,
            "plan_generated_at": self.plan_generated_at.isoformat()
            if self.plan_generated_at
            else None,
            "extracted_context": self.extracted_context,
            "review_feedback": self.review_feedback,
            "review_approved": self.review_approved,
            "review_attempts": self.review_attempts,
            "last_review_at": self.last_review_at.isoformat()
            if self.last_review_at
            else None,
            "execution_log": self.execution_log,
            "retry_count": self.retry_count,
            # Escalation fields (Pillar 1.7)
            "escalation_reason": self.escalation_reason,
            "escalated_at": self.escalated_at.isoformat()
            if self.escalated_at
            else None,
            "last_error": self.last_error,
            "review_status": self.review_status.value
            if isinstance(self.review_status, ReviewStatus)
            else self.review_status,
            "human_review_notes": self.human_review_notes,
            "human_reviewer": self.human_reviewer,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "is_high_value": self.is_high_value,
        }


class BidStatus(PyEnum):
    """Status for job bids."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"  # User approved, bid submitted
    REJECTED = "REJECTED"  # User rejected the proposal
    SUBMITTED = "SUBMITTED"  # Bid submitted to marketplace
    WON = "WON"  # Bid was accepted
    LOST = "LOST"  # Bid was rejected by client
    ACTIVE = "ACTIVE"  # Bid is active on marketplace
    WITHDRAWN = "WITHDRAWN"  # Bid was withdrawn from marketplace
    DUPLICATE = "DUPLICATE"  # Bid was not placed due to deduplication


class Bid(Base):
    """
    Bid Model for Autonomous Job Scanning

    Stores bids made on freelance marketplace jobs.
    Used to track which jobs have already been bid on to avoid duplicates.

    Implements deduplication and distributed lock pattern to prevent race conditions
    where multiple scanner instances bid on the same posting simultaneously.

    Issue #33: Enforces unique constraint on (job_id, marketplace) to prevent
    duplicate bids on the same posting from different agent instances.
    """

    __tablename__ = "bids"

    # Unique constraints:
    # 1. (job_id, marketplace): Prevents duplicate bids on same posting (Issue #33)
    # 2. (marketplace, job_id, status): Only one ACTIVE bid per posting (at app level)
    __table_args__ = (
        UniqueConstraint(
            "job_id", "marketplace", name="unique_bid_per_posting"
        ),
        UniqueConstraint(
            "marketplace", "job_id", "status", name="unique_active_bid_per_posting"
        ),
        # Performance indexes (Issue #38)
        Index("idx_bid_posting_id", "job_id"),
        Index("idx_bid_agent_id", "marketplace"),
        Index("idx_bid_status", "status"),
        Index("idx_bid_marketplace_status", "marketplace", "status"),  # Composite
        Index("idx_bid_created_at", "created_at"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Job reference (from marketplace)
    job_title = Column(String, nullable=False)
    job_description = Column(Text, nullable=False)
    job_url = Column(String, nullable=True)
    job_id = Column(String, nullable=True)  # External marketplace job ID

    # Bid details
    bid_amount = Column(Integer, nullable=False)  # Bid amount in cents
    proposal = Column(Text, nullable=True)  # Generated proposal text
    status = Column(Enum(BidStatus), default=BidStatus.PENDING, nullable=False)

    # Evaluation data from market scanner
    is_suitable = Column(Boolean, default=False)
    evaluation_reasoning = Column(Text, nullable=True)
    evaluation_confidence = Column(Integer, nullable=True)  # 0-100

    # Market scanner data
    marketplace = Column(String, nullable=True)  # Which marketplace
    skills_matched = Column(JSON, nullable=True)  # List of matched skills

    # Withdrawal tracking (Issue #8: Distributed lock & deduplication)
    withdrawn_reason = Column(
        String, nullable=True
    )  # Reason for withdrawal (if status=WITHDRAWN)
    withdrawal_timestamp = Column(DateTime, nullable=True)  # When bid was withdrawn
    posting_cached_at = Column(
        DateTime, nullable=True
    )  # When posting was cached (for TTL validation)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)  # When bid was submitted

    def to_dict(self):
        return {
            "id": self.id,
            "job_title": self.job_title,
            "job_description": self.job_description,
            "job_url": self.job_url,
            "job_id": self.job_id,
            "bid_amount": self.bid_amount,
            "bid_amount_dollars": (self.bid_amount / 100) if self.bid_amount else None,
            "proposal": self.proposal,
            "status": self.status.value
            if isinstance(self.status, BidStatus)
            else self.status,
            "is_suitable": self.is_suitable,
            "evaluation_reasoning": self.evaluation_reasoning,
            "evaluation_confidence": self.evaluation_confidence,
            "marketplace": self.marketplace,
            "skills_matched": self.skills_matched,
            "withdrawn_reason": self.withdrawn_reason,
            "withdrawal_timestamp": self.withdrawal_timestamp.isoformat()
            if self.withdrawal_timestamp
            else None,
            "posting_cached_at": self.posting_cached_at.isoformat()
            if self.posting_cached_at
            else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "submitted_at": self.submitted_at.isoformat()
            if self.submitted_at
            else None,
        }


class ArenaCompetition(Base):
    """
    Agent Arena Competition Model

    Stores the results of A/B competitions between agent variants.
    Used for tracking which agent configurations perform better
    and for building the DPO (Direct Preference Optimization) dataset.
    """

    __tablename__ = "arena_competitions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, nullable=True)  # Associated task ID (if any)
    competition_type = Column(String, nullable=False)  # "model", "prompt", "tooling"
    status = Column(
        Enum(ArenaCompetitionStatus),
        default=ArenaCompetitionStatus.PENDING,
        nullable=False,
    )

    # Task metadata for reference
    domain = Column(String, nullable=True)
    task_revenue = Column(Integer, nullable=True)  # Revenue in cents
    user_request = Column(Text, nullable=True)

    # === Agent A Configuration & Results ===
    agent_a_name = Column(String, nullable=True)
    agent_a_model = Column(String, nullable=True)
    agent_a_is_local = Column(Boolean, default=False)
    agent_a_config = Column(JSON, nullable=True)  # Full config as JSON
    agent_a_result = Column(JSON, nullable=True)  # Full result as JSON
    agent_a_approved = Column(Boolean, default=False)
    agent_a_execution_time = Column(Integer, default=0)  # Seconds
    agent_a_tokens = Column(Integer, default=0)
    agent_a_cost = Column(Integer, default=0)  # In cents
    agent_a_profit = Column(Integer, default=0)  # In cents

    # === Agent B Configuration & Results ===
    agent_b_name = Column(String, nullable=True)
    agent_b_model = Column(String, nullable=True)
    agent_b_is_local = Column(Boolean, default=False)
    agent_b_config = Column(JSON, nullable=True)
    agent_b_result = Column(JSON, nullable=True)
    agent_b_approved = Column(Boolean, default=False)
    agent_b_execution_time = Column(Integer, default=0)
    agent_b_tokens = Column(Integer, default=0)
    agent_b_cost = Column(Integer, default=0)
    agent_b_profit = Column(Integer, default=0)

    # === Winner ===
    winner = Column(String, nullable=True)  # "agent_a" or "agent_b"
    win_reason = Column(Text, nullable=True)
    winning_artifact_url = Column(String, nullable=True)

    # === Learning Data (for DPO) ===
    dpo_logged = Column(Boolean, default=False)  # Whether logged to DPO dataset

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "competition_type": self.competition_type,
            "status": self.status.value
            if isinstance(self.status, ArenaCompetitionStatus)
            else self.status,
            "domain": self.domain,
            "task_revenue": self.task_revenue,
            "user_request": self.user_request,
            # Agent A
            "agent_a_name": self.agent_a_name,
            "agent_a_model": self.agent_a_model,
            "agent_a_is_local": self.agent_a_is_local,
            "agent_a_approved": self.agent_a_approved,
            "agent_a_execution_time": self.agent_a_execution_time,
            "agent_a_tokens": self.agent_a_tokens,
            "agent_a_cost": self.agent_a_cost,
            "agent_a_profit": self.agent_a_profit,
            # Agent B
            "agent_b_name": self.agent_b_name,
            "agent_b_model": self.agent_b_model,
            "agent_b_is_local": self.agent_b_is_local,
            "agent_b_approved": self.agent_b_approved,
            "agent_b_execution_time": self.agent_b_execution_time,
            "agent_b_tokens": self.agent_b_tokens,
            "agent_b_cost": self.agent_b_cost,
            "agent_b_profit": self.agent_b_profit,
            # Winner
            "winner": self.winner,
            "win_reason": self.win_reason,
            "winning_artifact_url": self.winning_artifact_url,
            # Learning
            "dpo_logged": self.dpo_logged,
            # Timestamps
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
        }


class EscalationLog(Base):
    """
    Escalation Log for tracking human-in-the-loop (HITL) escalations.

    Provides idempotency for escalation notifications and audit trail
    for escalation events. Prevents duplicate Telegram notifications
    when retries occur.

    Pillar 1.7 - Human-in-the-Loop (HITL) Escalation Idempotency

    Issue #33: Enforces unique constraint on (task_id, idempotency_key) to prevent
    duplicate escalation logs for the same task with the same idempotency key.
    This ensures idempotency is enforced at the database level.
    """

    __tablename__ = "escalation_logs"

    # Unique constraint: (task_id, idempotency_key) to ensure
    # only one escalation log per task per idempotency key
    __table_args__ = (
        UniqueConstraint(
            "task_id", "idempotency_key", name="unique_escalation_per_task"
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Task reference
    task_id = Column(String, nullable=False, index=True)

    # Escalation details
    reason = Column(
        String, nullable=False
    )  # e.g., "max_retries_exceeded", "high_value_task_failed"
    error_message = Column(Text, nullable=True)  # Optional error context

    # Notification tracking
    notification_sent = Column(
        Boolean, default=False
    )  # Whether Telegram notification was sent
    notification_attempt_count = Column(
        Integer, default=0
    )  # Number of notification attempts
    last_notification_attempt_at = Column(DateTime, nullable=True)
    notification_error = Column(
        Text, nullable=True
    )  # Error message if notification failed

    # Idempotency key (prevents duplicate notifications on retry)
    # Format: "task_id_escalation_reason"
    # Unique constraint is enforced via __table_args__ (Issue #33)
    idempotency_key = Column(String, nullable=False, index=True)

    # Task metadata at time of escalation
    amount_paid = Column(Integer, nullable=True)  # Amount in cents
    domain = Column(String, nullable=True)
    client_email = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(
        DateTime, nullable=True
    )  # When human reviewer resolved the escalation

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "reason": self.reason,
            "error_message": self.error_message,
            "notification_sent": self.notification_sent,
            "notification_attempt_count": self.notification_attempt_count,
            "last_notification_attempt_at": self.last_notification_attempt_at.isoformat()
            if self.last_notification_attempt_at
            else None,
            "notification_error": self.notification_error,
            "idempotency_key": self.idempotency_key,
            "amount_paid": self.amount_paid,
            "domain": self.domain,
            "client_email": self.client_email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


class DistributedLock(Base):
    """
    Database-backed distributed lock for cross-process synchronization.

    Uses a unique constraint on lock_key to implement atomic compare-and-set.
    A lock is considered held if it exists and has not expired (expires_at > now).

    Issue #19: Replace in-memory asyncio.Lock with DB-backed distributed lock.
    """

    __tablename__ = "distributed_locks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    lock_key = Column(String, nullable=False, unique=True, index=True)
    holder_id = Column(String, nullable=False)
    acquired_at = Column(Float, nullable=False)  # Unix timestamp for precision
    expires_at = Column(Float, nullable=False)  # Unix timestamp (acquired_at + ttl)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "lock_key": self.lock_key,
            "holder_id": self.holder_id,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PricingTier(PyEnum):
    """Pricing tiers for user quotas."""
    FREE = "FREE"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


class UserQuota(Base):
    """
    User quota and rate limit configuration.
    
    Issue #45: API Rate Limiting, Quotas, and Usage Analytics
    
    Tracks per-user quotas across pricing tiers:
    - Free: 10 tasks/month, 100 API calls/month, 60 compute minutes/month
    - Pro: 1000 tasks/month, 10000 API calls/month, 600 compute minutes/month
    - Enterprise: Unlimited
    """
    
    __tablename__ = "user_quotas"
    
    __table_args__ = (
        UniqueConstraint("user_id", name="unique_user_quota"),
        Index("user_id_tier_idx", "user_id", "tier"),
    )
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, unique=True, index=True)  # Email or user identifier
    tier = Column(Enum(PricingTier), default=PricingTier.FREE, nullable=False)
    
    # Monthly limits (resets on billing cycle)
    monthly_task_limit = Column(Integer, default=10)  # Free: 10, Pro: 1000, Enterprise: unlimited
    monthly_api_calls_limit = Column(Integer, default=100)  # Free: 100, Pro: 10000, Enterprise: unlimited
    monthly_compute_minutes_limit = Column(Integer, default=60)  # Free: 60, Pro: 600, Enterprise: unlimited
    
    # Rate limiting (requests per second + burst)
    rate_limit_rps = Column(Integer, default=10)  # Requests per second
    rate_limit_burst = Column(Integer, default=50)  # Burst capacity
    
    # Billing cycle tracking
    billing_cycle_start = Column(DateTime, nullable=False, default=datetime.utcnow)
    billing_cycle_end = Column(DateTime, nullable=False)
    
    # Quota thresholds for alerts
    alert_threshold_percentage = Column(Integer, default=80)  # Alert at 80% usage
    
    # Override flags (admin)
    override_rate_limit = Column(Boolean, default=False)
    override_quota = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "tier": self.tier.value if self.tier else None,
            "monthly_task_limit": self.monthly_task_limit,
            "monthly_api_calls_limit": self.monthly_api_calls_limit,
            "monthly_compute_minutes_limit": self.monthly_compute_minutes_limit,
            "rate_limit_rps": self.rate_limit_rps,
            "rate_limit_burst": self.rate_limit_burst,
            "billing_cycle_start": self.billing_cycle_start.isoformat() if self.billing_cycle_start else None,
            "billing_cycle_end": self.billing_cycle_end.isoformat() if self.billing_cycle_end else None,
            "alert_threshold_percentage": self.alert_threshold_percentage,
            "override_rate_limit": self.override_rate_limit,
            "override_quota": self.override_quota,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class QuotaUsage(Base):
    """
    Monthly quota usage tracking per user.
    
    Issue #45: API Rate Limiting, Quotas, and Usage Analytics
    
    Tracks actual usage against quotas. Resets each billing cycle.
    """
    
    __tablename__ = "quota_usage"
    
    __table_args__ = (
        UniqueConstraint("user_id", "billing_month", name="unique_user_month_usage"),
        Index("user_id_month_idx", "user_id", "billing_month"),
    )
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    billing_month = Column(String, nullable=False)  # YYYY-MM format
    
    # Tracked metrics
    task_count = Column(Integer, default=0)
    api_call_count = Column(Integer, default=0)
    compute_minutes_used = Column(Float, default=0.0)
    
    # Status tracking
    quota_exceeded = Column(Boolean, default=False)
    alert_sent_at_80_percent = Column(DateTime, nullable=True)
    alert_sent_at_100_percent = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "billing_month": self.billing_month,
            "task_count": self.task_count,
            "api_call_count": self.api_call_count,
            "compute_minutes_used": self.compute_minutes_used,
            "quota_exceeded": self.quota_exceeded,
            "alert_sent_at_80_percent": self.alert_sent_at_80_percent.isoformat() if self.alert_sent_at_80_percent else None,
            "alert_sent_at_100_percent": self.alert_sent_at_100_percent.isoformat() if self.alert_sent_at_100_percent else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RateLimitLog(Base):
    """
    Log of rate limit violations and enforcement.
    
    Issue #45: API Rate Limiting, Quotas, and Usage Analytics
    
    Tracks rate limit violations for debugging and analytics.
    """
    
    __tablename__ = "rate_limit_logs"
    
    __table_args__ = (
        Index("user_id_timestamp_idx", "user_id", "timestamp"),
    )
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    
    # Request details
    endpoint = Column(String, nullable=False)
    method = Column(String, nullable=False)  # GET, POST, etc.
    
    # Rate limiting details
    requests_in_window = Column(Integer, nullable=False)  # Current window request count
    rate_limit_rps = Column(Integer, nullable=False)  # Limit at time of request
    exceeded = Column(Boolean, default=False)  # Was limit exceeded?
    
    # Quota details
    quota_type = Column(String, nullable=True)  # task, api_call, compute_minute, etc.
    quota_used = Column(Integer, nullable=True)
    quota_limit = Column(Integer, nullable=True)
    quota_exceeded = Column(Boolean, default=False)
    
    # Response
    status_code = Column(Integer, nullable=False)
    response_time_ms = Column(Float, nullable=False)
    
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "endpoint": self.endpoint,
            "method": self.method,
            "requests_in_window": self.requests_in_window,
            "rate_limit_rps": self.rate_limit_rps,
            "exceeded": self.exceeded,
            "quota_type": self.quota_type,
            "quota_used": self.quota_used,
            "quota_limit": self.quota_limit,
            "quota_exceeded": self.quota_exceeded,
            "status_code": self.status_code,
            "response_time_ms": self.response_time_ms,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class ScheduledTask(Base):
    """Database model for scheduled tasks."""
    
    __tablename__ = "scheduled_tasks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, nullable=True)  # Reference to actual task when executed
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    domain = Column(String, nullable=False)
    cron_expression = Column(String, nullable=False)
    schedule_type = Column(String, default="RECURRING", nullable=False)
    status = Column(String, default="ACTIVE", nullable=False)
    task_data = Column(Text, nullable=True)  # JSON string containing task data
    
    # Scheduling metadata
    next_run_at = Column(DateTime, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    last_run_result = Column(String, nullable=True)  # SUCCESS, FAILED
    last_run_error = Column(Text, nullable=True)
    
    # Recurrence settings
    max_runs = Column(Integer, nullable=True)  # None for unlimited
    run_count = Column(Integer, default=0)
    timezone = Column(String, default="UTC")
    
    # Intelligent scheduling
    avoid_peak_hours = Column(Boolean, default=True)
    batch_size = Column(Integer, default=1)
    priority = Column(Integer, default=1)  # 1 (low) to 10 (high)
    
    # Analytics
    avg_execution_time = Column(Float, default=0.0)
    success_rate = Column(Float, default=100.0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # Auto-expire old schedules


class ScheduleHistory(Base):
    """Database model for schedule execution history."""
    
    __tablename__ = "schedule_history"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    schedule_id = Column(String, nullable=False, index=True)
    task_id = Column(String, nullable=True)
    execution_start = Column(DateTime, nullable=False)
    execution_end = Column(DateTime, nullable=True)
    status = Column(String, nullable=False)  # STARTED, COMPLETED, FAILED
    result = Column(Text, nullable=True)  # Success message or error details
    execution_time_ms = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
