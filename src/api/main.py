"""
FastAPI backend for ArbitrageAI.
Provides endpoints for creating checkout sessions and processing task submissions.
"""
import os
import uuid
import json
import re
import secrets
import time as _time
from fastapi import FastAPI, HTTPException, Request, Depends, Header, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator, ValidationInfo, Field
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
import stripe

from datetime import datetime, timedelta, timezone
from .database import get_db, init_db
from .models import Task, TaskStatus, ReviewStatus, ArenaCompetition, ArenaCompetitionStatus, EscalationLog
from ..agent_execution.executor import execute_task, OutputFormat
from .experience_logger import experience_logger

# Import logging module
from ..utils.logger import get_logger

# Import Config Manager (Issue #26)
from ..config.config_manager import ConfigManager

# Import file validation utility (Issue #34)
from ..utils.file_validator import validate_file_upload, MAX_FILE_SIZE_BYTES

# Import telemetry for observability
from ..utils.telemetry import init_observability

# Import notifications for Telegram alerts
from ..utils.notifications import TelegramNotifier

# Import Market Scanner for autonomous job scanning
from ..agent_execution.market_scanner import run_single_scan

# Import LLM Service for proposal generation
from ..llm_service import LLMService

# Import Bid model for tracking bids
from .models import Bid, BidStatus

# Import client authentication for dashboard endpoints (Issue #17)
from ..utils.client_auth import generate_client_token, verify_client_token

# Import contextlib for lifespan
from contextlib import asynccontextmanager

# Import asyncio and random for autonomous loop
import asyncio
import random
import logging

# Import Agent execution modules
from ..agent_execution.planning import (
    ResearchAndPlanOrchestrator,
    ContextExtractor,
    WorkPlanGenerator,
    get_client_preferences_from_tasks,
    save_client_preferences
)

# Import Agent Arena modules
from ..agent_execution.arena import (
    ArenaRouter,
    CompetitionType,
    run_agent_arena,
    ArenaLearningLogger
)

# Import Scheduler modules
from ..agent_execution.scheduler import TaskScheduler
from .scheduler_endpoints import register_scheduler_routes
from .analytics import register_analytics_routes

# Initialize logger
logger = get_logger(__name__)

# Import Experience Vector Database for few-shot learning (RAG)
try:
    from ..experience_vector_db import store_successful_task
    EXPERIENCE_DB_AVAILABLE = True
except ImportError:
    EXPERIENCE_DB_AVAILABLE = False
    # Use basic logging for import errors before app logger is ready
    logging.warning("Experience Vector Database not available, few-shot learning disabled")

# =============================================================================
# ESCALATION & HUMAN-IN-THE-LOOP (HITL) CONFIGURATION (Pillar 1.7)
# =============================================================================

# High-value threshold for profit protection (in dollars) (Issue #26: Magic Number)
# Tasks with amount_paid >= HIGH_VALUE_THRESHOLD will always be escalated on failure
HIGH_VALUE_THRESHOLD = ConfigManager.get("HIGH_VALUE_THRESHOLD")

# Maximum number of retry attempts before escalation (matches executor.py)
MAX_RETRY_ATTEMPTS = ConfigManager.get("MAX_RETRY_ATTEMPTS")

# =============================================================================
# DELIVERY ENDPOINT SECURITY (Issue #18)
# =============================================================================


class DeliveryTokenRequest(BaseModel):
    """Validated request model for delivery endpoint (Issue #18)."""

    task_id: str = Field(..., min_length=1, max_length=64, description="Task ID")
    token: str = Field(..., min_length=20, max_length=256, description="Delivery token")

    @field_validator("task_id", mode="before")
    @classmethod
    def validate_task_id(cls, v: Any) -> Any:
        """Sanitize task_id - allow UUID format only."""
        if not isinstance(v, str):
            return v
        v = v.lower().strip()
        if not re.match(r"^[a-f0-9\-]{36}$", v):
            raise ValueError("Invalid task_id format (must be UUID)")
        return v

    @field_validator("token", mode="before")
    @classmethod
    def validate_token(cls, v: Any) -> Any:
        """Sanitize token - alphanumeric, hyphens, underscores only."""
        if not isinstance(v, str):
            return v
        v = v.strip()
        if not re.match(r"^[a-zA-Z0-9\-_]+$", v):
            raise ValueError("Invalid token format (contains invalid characters)")
        return v


class DeliveryResponse(BaseModel):
    """Validated response model for delivery endpoint."""

    task_id: str
    title: str
    domain: str
    result_type: str
    result_url: Optional[str] = None
    result_image_url: Optional[str] = None
    result_document_url: Optional[str] = None
    result_spreadsheet_url: Optional[str] = None
    delivered_at: str


def _sanitize_string(value: str, max_length: int = 500) -> str:
    """
    Sanitize string input to prevent injection attacks.
    Removes null bytes and limits length.
    """
    if not isinstance(value, str):
        return value
    # Remove null bytes
    sanitized = value.replace("\x00", "")
    # Truncate to max length
    return sanitized[:max_length].strip()


# Delivery token TTL in hours (configurable via env)
DELIVERY_TOKEN_TTL_HOURS = ConfigManager.get("DELIVERY_TOKEN_TTL_HOURS")

# Rate limiting: max failed delivery attempts per task before lockout
DELIVERY_MAX_FAILED_ATTEMPTS = ConfigManager.get("DELIVERY_MAX_FAILED_ATTEMPTS")
DELIVERY_LOCKOUT_SECONDS = ConfigManager.get("DELIVERY_LOCKOUT_SECONDS")

# IP-based rate limiting (Issue #18)
DELIVERY_MAX_ATTEMPTS_PER_IP = ConfigManager.get("DELIVERY_MAX_ATTEMPTS_PER_IP")
DELIVERY_IP_LOCKOUT_SECONDS = ConfigManager.get("DELIVERY_IP_LOCKOUT_SECONDS")

# In-memory rate limiter: { task_id: (fail_count, first_fail_timestamp) }
_delivery_rate_limits: dict[str, tuple[int, float]] = {}

# IP-level rate limiter: { ip: (attempt_count, first_attempt_timestamp) }
_delivery_ip_rate_limits: dict[str, tuple[int, float]] = {}


class AddressValidationModel(BaseModel):
    """Validation model for delivery addresses."""
    address: str
    city: str
    postal_code: str
    country: str

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-zA-Z0-9\s,.-]+$", v):
            raise ValueError("Contains invalid characters")
        return v

    @field_validator("city", "country")
    @classmethod
    def validate_no_numbers(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-zA-Z\s,.-]+$", v):
            raise ValueError("Contains invalid characters or numbers")
        return v

    @field_validator("country")
    @classmethod
    def validate_country_code(cls, v: str) -> str:
        if len(v) != 2 or not v.isalpha():
            raise ValueError("Must be a 2-letter ISO country code")
        return v.upper()


class DeliveryAmountModel(BaseModel):
    """Validation model for delivery amounts."""
    amount_cents: int
    currency: str = "USD"

    @field_validator("amount_cents")
    @classmethod
    def validate_positive_amount(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Amount must be positive")
        if v > 100000000:  # $1M in cents
            raise ValueError("Amount exceeds maximum allowed")
        return v

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        if v.upper() not in ["USD", "EUR", "GBP"]:
            raise ValueError("Unsupported currency")
        return v.upper()


class DeliveryTimestampModel(BaseModel):
    """Validation model for delivery timestamps."""
    created_at: datetime
    expires_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_not_future(cls, v: datetime) -> datetime:
        if v > datetime.now(v.tzinfo or timezone.utc):
            raise ValueError("Created at cannot be in the future")
        return v

    @field_validator("expires_at")
    @classmethod
    def validate_not_past(cls, v: datetime, info: ValidationInfo) -> datetime:
        if v < datetime.now(v.tzinfo or timezone.utc):
            raise ValueError("Expires at cannot be in the past")
        
        # Check logical ordering if created_at is available
        created_at = info.data.get("created_at")
        if created_at and v <= created_at:
            raise ValueError("Expires at must be after created at")
            
        # Max TTL check (e.g., 7 days)
        if v > datetime.now(timezone.utc) + timedelta(days=7):
            raise ValueError("Expires at too far in future")
            
        return v


def _check_delivery_rate_limit(task_id: str) -> bool:
    """
    Check if a task_id is rate-limited for delivery attempts.

    Returns True if the request is allowed, False if rate-limited.
    """
    entry = _delivery_rate_limits.get(task_id)
    if entry is None:
        return True

    fail_count, first_fail_ts = entry
    # Reset if lockout window has passed
    if _time.time() - first_fail_ts > DELIVERY_LOCKOUT_SECONDS:
        del _delivery_rate_limits[task_id]
        return True

    return fail_count < DELIVERY_MAX_FAILED_ATTEMPTS


def _record_delivery_failure(task_id: str, ip: str = None) -> None:
    """
    Record a failed delivery attempt for rate limiting (Issue #18).
    
    Increments failure counts for the specific task_id.
    Note: IP-level counter is already incremented at the start of the request.
    """
    # 1. Record task-level failure
    entry = _delivery_rate_limits.get(task_id)
    if entry is None:
        _delivery_rate_limits[task_id] = (1, _time.time())
    else:
        fail_count, first_fail_ts = entry
        _delivery_rate_limits[task_id] = (fail_count + 1, first_fail_ts)


def _should_escalate_task(task, retry_count: int, error_message: str = None) -> tuple:
    """
    Determine if a task should be escalated to human review.
    
    Escalation criteria (Pillar 1.7):
    1. Agent failed after MAX_RETRY_ATTEMPTS (3 retries)
    2. High-value task ($200+) failed (profit protection)
    
    Args:
        task: The Task object
        retry_count: Number of retry attempts made
        error_message: Optional error message from the failure
        
    Returns:
        Tuple of (should_escalate: bool, reason: str or None)
    """
    # Check if this is a high-value task
    amount_dollars = (task.amount_paid / 100) if task.amount_paid else 0
    is_high_value = amount_dollars >= HIGH_VALUE_THRESHOLD
    
    # Check if retries were exhausted
    if retry_count >= MAX_RETRY_ATTEMPTS:
        reason = "max_retries_exceeded"
        if is_high_value:
            reason = "max_retries_exceeded_high_value"
        return True, reason
    
    # High-value task failed - always escalate for profit protection
    if is_high_value and error_message:
        reason = "high_value_task_failed"
        return True, reason
    
    return False, None


async def _escalate_task(db, task, reason: str, error_message: str = None):
    """
    Escalate a task to human review with idempotent notification.
    
    Uses a database transaction (savepoint) to atomically update the task
    status and create the EscalationLog entry. The notification is sent
    after the DB commit succeeds, preventing inconsistent state where the
    task is marked ESCALATION but the log entry is missing.
    
    Idempotency: Uses idempotency_key (task_id_reason) to prevent duplicate
    Telegram notifications on retry.
    
    Args:
        db: Database session
        task: The Task object to escalate
        reason: Reason for escalation
        error_message: Optional error details
    """
    # Get logger instance
    logger = get_logger(__name__)
    
    # Log the escalation for profit protection
    amount_dollars = (task.amount_paid / 100) if task.amount_paid else 0
    is_high_value = amount_dollars >= HIGH_VALUE_THRESHOLD
    
    logger.warning(f"[ESCALATION] Task {task.id} escalated: {reason}")
    logger.warning(f"[ESCALATION] Amount: ${amount_dollars}, High-value: {is_high_value}")
    logger.warning("[ESCALATION] Human reviewer notification required to prevent refund")
    
    if error_message:
        logger.warning(f"[ESCALATION] Error: {error_message[:200]}...")
    
    # Check for idempotency via EscalationLog
    # Format: "task_id_reason"
    idempotency_key = f"{task.id}_{reason}"
    should_send_notification = False
    escalation_log = None
    
    try:
        # Use a savepoint so that if escalation log fails, we can still
        # update the task status without losing the outer transaction
        db.begin_nested()
        
        # Update task status atomically with escalation log
        task.status = TaskStatus.ESCALATION
        task.escalation_reason = reason
        task.escalated_at = datetime.now(timezone.utc)
        task.last_error = error_message
        task.review_status = ReviewStatus.PENDING
        
        escalation_log = db.query(EscalationLog).filter(
            EscalationLog.idempotency_key == idempotency_key
        ).first()
        
        if escalation_log is None:
            # First escalation - create new log
            escalation_log = EscalationLog(
                task_id=task.id,
                reason=reason,
                error_message=error_message,
                idempotency_key=idempotency_key,
                amount_paid=task.amount_paid,
                domain=task.domain,
                client_email=task.client_email,
                notification_sent=False,
                notification_attempt_count=0
            )
            db.add(escalation_log)
        
        # Determine if notification should be sent (before commit)
        should_send_notification = (
            is_high_value and
            not escalation_log.notification_sent
        )
        
        # Commit the savepoint - task status + escalation log are now persisted
        db.commit()
        
    except Exception as e:
        db.rollback()
        # If the savepoint fails, still try to update task status
        logger.error(f"[ESCALATION] Error in escalation transaction: {e}")
        task.status = TaskStatus.ESCALATION
        task.escalation_reason = reason
        task.escalated_at = datetime.now(timezone.utc)
        task.last_error = error_message
        task.review_status = ReviewStatus.PENDING
        db.commit()
        return
    
    # Send notification AFTER DB commit succeeds to prevent inconsistent state
    if should_send_notification and escalation_log is not None:
        try:
            notifier = TelegramNotifier()
            context = f"Reason: {reason}"
            if error_message:
                context += f"\nError: {error_message[:200]}"
            
            notification_sent = await notifier.request_human_help(
                task_id=task.id,
                context=context,
                amount_paid=task.amount_paid,
                domain=task.domain,
                client_email=task.client_email
            )
            
            # Update escalation log with notification result
            escalation_log.notification_sent = notification_sent
            escalation_log.notification_attempt_count += 1
            escalation_log.last_notification_attempt_at = datetime.now(timezone.utc)
            
            if notification_sent:
                logger.info(f"[ESCALATION] Telegram notification sent for high-value task {task.id}")
            else:
                escalation_log.notification_error = "Notification returned False after retries"
                logger.warning(f"[ESCALATION] Telegram notification failed for task {task.id}")
            
            db.commit()
        except Exception as e:
            # Log error but don't raise - task status is already committed
            escalation_log.notification_attempt_count += 1
            escalation_log.last_notification_attempt_at = datetime.now(timezone.utc)
            escalation_log.notification_error = str(e)[:500]
            logger.error(f"[ESCALATION] Failed to send Telegram notification: {e}")
            db.commit()
    elif escalation_log is not None and not should_send_notification:
        # Not first notification or not high-value - just increment attempt count
        escalation_log.notification_attempt_count += 1
        escalation_log.last_notification_attempt_at = datetime.now(timezone.utc)
        db.commit()


async def process_task_async(task_id: str, use_planning_workflow: bool = True):
    """
    Process a task asynchronously after payment is confirmed.
    
    This function is called as a background task when a task is marked as PAID.
    It retrieves the task from the database, executes the appropriate task
    using the Research & Plan workflow (or TaskRouter as fallback), and updates
    the database with the result.
    
    The Research & Plan workflow includes:
    1. Context Extraction: Agent analyzes uploaded files (PDF/Excel) to extract context
    2. Work Plan Generation: Agent creates a detailed work plan
    3. Plan Execution: Agent executes the plan in the E2B sandbox
    4. Artifact Review: ArtifactReviewer checks the final document against the plan
    
    For high-value tasks (is_high_value=True), the Agent Arena is used to guarantee
    faster completion and higher success rate by running two agents in parallel.
    
    Args:
        task_id: The ID of the task to process
        use_planning_workflow: Whether to use the Research & Plan workflow (default: True)
    """
    # Create a new database session for this background task
    from .database import SessionLocal
    import os
    
    # Initialize logger
    logger = get_logger(__name__)
    
    db = SessionLocal()
    try:
        # Retrieve the task from the database
        task = db.query(Task).filter(Task.id == task_id).first()
        
        if not task:
            logger.error(f"Task {task_id} not found for processing")
            return
        
        if task.status != TaskStatus.PAID:
            logger.warning(f"Task {task_id} is not in PAID status, current status: {task.status}")
            return
        
        # Get API key from environment
        e2b_api_key = os.environ.get("E2B_API_KEY")
        
        # Build the user request - include title and description for better routing
        user_request = task.description or f"Create a {task.domain} visualization for {task.title}"
        
        # Use the CSV data stored in the task, or fall back to sample data if not provided
        csv_data = task.csv_data
        if not csv_data and not task.file_content:
            logger.warning(f"No data found for task {task_id}, using sample data")
            csv_data = """category,value
Sales,150
Marketing,200
Engineering,300
Operations,120
Support,180"""
        
        # =====================================================
        # HIGH-VALUE TASK: Route to Agent Arena for guaranteed success
        # This ensures faster completion and higher success rate for paying clients
        # =====================================================
        if task.is_high_value:
            logger.info("HIGH-VALUE TASK - Routing to Agent Arena")
            
            # Update status to indicate arena processing
            task.status = TaskStatus.PROCESSING
            db.commit()
            
            # Run the arena competition
            arena_result = await run_agent_arena(
                user_request=user_request,
                domain=task.domain,
                csv_data=csv_data,
                file_content=task.file_content,
                filename=task.filename,
                file_type=task.file_type,
                api_key=e2b_api_key,
                competition_type=CompetitionType.MODEL,  # Model competition: local vs cloud
                task_revenue=task.amount_paid or 500,
                enable_learning=True,
                task_data={
                    "id": task.id,
                    "domain": task.domain,
                    "description": user_request,
                    "client_email": task.client_email
                }
            )
            
            # Extract the winning result
            winner = arena_result.get("winner")
            winning_agent = arena_result.get(winner, {})
            winning_result = winning_agent.get("result", {})
            
            # Get review info from the winning agent
            review_approved = winning_result.get("approved", False)
            review_feedback = winning_result.get("feedback", "")
            
            # Determine output format from work plan if available
            try:
                plan_data = json.loads(task.work_plan) if task.work_plan else {}
                output_format = plan_data.get("output_format", "image")
            except (json.JSONDecodeError, AttributeError, TypeError):
                output_format = "image"
            
            # Store the winning artifact URL
            winning_artifact_url = arena_result.get("winning_artifact_url", "")
            
            if winning_artifact_url:
                # Store result based on output format
                task.result_type = output_format
                
                if output_format in ["docx", "pdf"]:
                    task.result_document_url = winning_artifact_url
                elif output_format == "xlsx":
                    task.result_spreadsheet_url = winning_artifact_url
                else:
                    task.result_image_url = winning_artifact_url
            
            # Store arena execution details
            task.execution_log = {
                "arena_result": arena_result,
                "winner": winner,
                "profit_breakdown": {
                    "agent_a": arena_result.get("agent_a", {}).get("profit", {}),
                    "agent_b": arena_result.get("agent_b", {}).get("profit", {})
                }
            }
            task.review_approved = review_approved
            task.review_feedback = review_feedback
            task.retry_count = 0
            
            if review_approved:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.utcnow()
                logger.info(f"COMPLETED via Agent Arena (winner: {winner})")
                
                # Log success to learning systems
                experience_logger.log_success(task)
                
                # Log to arena learning systems
                try:
                    from ..agent_execution.arena import ArenaLearningLogger
                    arena_logger = ArenaLearningLogger()
                    arena_logger.log_winner(arena_result, {
                        "id": task.id,
                        "domain": task.domain,
                        "description": user_request
                    })
                except Exception as e:
                    logger.error(f"Error logging arena learning: {e}")
            else:
                # Arena failed - escalate for human review
                error_message = f"Arena competition failed. Winner feedback: {review_feedback}"
                task.last_error = error_message
                await _escalate_task(db, task, "arena_failed", error_message)
                logger.warning("Arena FAILED - ESCALATED for human review")
            
            db.commit()
            logger.info(f"processed via Arena, final status: {task.status}")
            return
        
        # Update task status to PLANNING if using planning workflow
        if use_planning_workflow:
            task.status = TaskStatus.PLANNING
            db.commit()
        
        if use_planning_workflow:
            # =====================================================
            # RESEARCH & PLAN WORKFLOW (NEW AUTONOMY CORE)
            # =====================================================
            logger.info("Using Research & Plan workflow")
            
            # Step 1 & 2: Extract context and generate work plan
            if use_planning_workflow:
                task.plan_status = "GENERATING"  # Update plan status
                db.commit()
                
                # CLIENT PREFERENCE MEMORY (Pillar 2.5 Gap): Get preferences BEFORE generating work plan
                client_preferences = None
                if task.client_email:
                    logger.info(f"Loading client preferences for {task.client_email}")
                    client_preferences = get_client_preferences_from_tasks(task.client_email)
                    if client_preferences.get("has_history"):
                        logger.info(f"Found {client_preferences['total_previous_tasks']} previous tasks with preferences")
                    else:
                        logger.info("No previous task history found")
                
                # Extract context from files
                context_extractor = ContextExtractor()
                extracted_context = context_extractor.extract_context(
                    file_content=task.file_content,
                    csv_data=csv_data,
                    filename=task.filename,
                    file_type=task.file_type,
                    domain=task.domain
                )
                
                # Store extracted context in task
                task.extracted_context = extracted_context
                
                # Generate work plan WITH client preferences
                plan_generator = WorkPlanGenerator()
                plan_result = plan_generator.create_work_plan(
                    user_request=user_request,
                    domain=task.domain,
                    extracted_context=extracted_context,
                    client_preferences=client_preferences  # Pass preferences to avoid review failures
                )
                
                if plan_result.get("success"):
                    work_plan = plan_result["plan"]
                    task.work_plan = json.dumps(work_plan)
                    task.plan_status = "APPROVED"
                    task.plan_generated_at = datetime.now(timezone.utc)
                    logger.info(f"Work plan generated - {work_plan.get('title', 'Untitled')}")
                else:
                    task.plan_status = "REJECTED"
                    logger.warning(f"Plan generation failed - {plan_result.get('error')}")
                
                db.commit()
            
            # Step 3: Execute the plan in E2B sandbox
            task.status = TaskStatus.PROCESSING
            db.commit()
            
            # Execute the workflow
            orchestrator = ResearchAndPlanOrchestrator()
            workflow_result = orchestrator.execute_workflow(
                user_request=user_request,
                domain=task.domain,
                csv_data=csv_data,
                file_content=task.file_content,
                filename=task.filename,
                file_type=task.file_type,
                api_key=e2b_api_key
            )
            
            # Store execution log
            task.execution_log = workflow_result.get("steps", {})
            task.retry_count = workflow_result.get("steps", {}).get("plan_execution", {}).get("result", {}).get("retry_count", 0)
            
            # Step 4: Get review results
            review_result = workflow_result.get("steps", {}).get("artifact_review", {})
            task.review_approved = review_result.get("approved", False)
            task.review_feedback = review_result.get("feedback", "")
            task.review_attempts = review_result.get("attempts", 0)
            
            if workflow_result.get("success"):
                # Get the artifact URL
                artifact_url = workflow_result.get("artifact_url", "")
                
                # Determine output format from work plan
                try:
                    plan_data = json.loads(task.work_plan) if task.work_plan else {}
                    output_format = plan_data.get("output_format", "image")
                except (json.JSONDecodeError, AttributeError, TypeError):
                    output_format = "image"
                
                # Store result based on output format (diverse output types)
                task.result_type = output_format
                
                if output_format in ["docx", "pdf"]:
                    # For documents
                    task.result_document_url = artifact_url
                elif output_format == "xlsx":
                    # For spreadsheets
                    task.result_spreadsheet_url = artifact_url
                else:
                    # For images/visualizations (default)
                    task.result_image_url = artifact_url
                
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.utcnow()
                logger.info(f"Completed successfully with Research & Plan workflow (output: {output_format})")
                
                # ==========================================================
                # NEW: Log this success to our continuous learning dataset!
                # ==========================================================
                experience_logger.log_success(task)
                
                # EXPERIENCE VECTOR DATABASE (RAG for Few-Shot Learning): Store successful task
                if EXPERIENCE_DB_AVAILABLE and task.review_approved:
                    # Extract the generated code from execution log if available
                    generated_code = ""
                    if task.execution_log:
                        plan_exec = task.execution_log.get("plan_execution", {})
                        if plan_exec.get("result", {}).get("code"):
                            generated_code = plan_exec["result"]["code"]
                    
                    # Store the experience for future few-shot learning
                    if generated_code:
                        # Extract CSV headers
                        csv_headers = []
                        if csv_data:
                            first_line = csv_data.strip().split('\n')[0]
                            csv_headers = [h.strip() for h in first_line.split(',')]
                        
                        store_successful_task(
                            task_id=task_id,
                            user_request=user_request,
                            generated_code=generated_code,
                            domain=task.domain,
                            task_type="visualization",  # Could be extracted from result_type
                            output_format=output_format,
                            csv_headers=csv_headers
                        )
                        logger.info("Stored experience for few-shot learning")
                
                # CLIENT PREFERENCE MEMORY (Pillar 2.5 Gap): Save preferences after task completion
                if task.client_email and task.review_feedback:
                    logger.info("Saving client preferences for future tasks")
                    save_client_preferences(
                        client_email=task.client_email,
                        task_id=task_id,
                        review_feedback=task.review_feedback,
                        review_approved=task.review_approved or False,
                        domain=task.domain,
                        db_session=db
                    )
                else:
                    logger.info("No client email or feedback to save preferences")
            else:
                # Workflow failed - check if should escalate instead of marking as FAILED
                error_message = workflow_result.get("message", "Workflow failed")
                task.last_error = error_message
                
                # Check if should escalate based on retry count and high-value status
                should_escalate, escalation_reason = _should_escalate_task(
                    task, 
                    task.retry_count or 0, 
                    error_message
                )
                
                if should_escalate:
                    # ESCALATE to human review (Pillar 1.7)
                    await _escalate_task(db, task, escalation_reason, error_message)
                    logger.warning(f"ESCALATED for human review - {escalation_reason}")
                else:
                    # Mark as FAILED for non-high-value tasks that exhausted retries
                    task.status = TaskStatus.FAILED
                    task.review_feedback = error_message
                    logger.error(f"Failed - {error_message}")
                
                # CLIENT PREFERENCE MEMORY (Pillar 2.5 Gap): Save preferences even on failure
                if task.client_email and task.review_feedback:
                    logger.info("Saving client preferences (from failed task)")
                    save_client_preferences(
                        client_email=task.client_email,
                        task_id=task_id,
                        review_feedback=task.review_feedback,
                        review_approved=False,  # Failed task
                        domain=task.domain,
                        db_session=db
                    )
        
        else:
            # =====================================================
            # LEGACY WORKFLOW (Original TaskRouter)
            # =====================================================
            logger.info("Using legacy TaskRouter workflow")
            
            result = execute_task(
                domain=task.domain,
                user_request=user_request,
                csv_data=csv_data or "",
                file_type=task.file_type,
                file_content=task.file_content,
                filename=task.filename
            )
            
            # Update the task with the result based on output format (diverse output types)
            if result.get("success"):
                # Check if this is a document/spreadsheet (non-image) result
                output_format = result.get("output_format", "image")
                
                # Store result_type for tracking
                task.result_type = output_format
                
                if output_format in [OutputFormat.DOCX, OutputFormat.PDF]:
                    # For documents, store in result_document_url
                    task.result_document_url = result.get("file_url", result.get("image_url", ""))
                elif output_format == OutputFormat.XLSX:
                    # For spreadsheets, store in result_spreadsheet_url
                    task.result_spreadsheet_url = result.get("file_url", result.get("image_url", ""))
                else:
                    # For images/visualizations, store in result_image_url
                    task.result_image_url = result.get("image_url", "")
                
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.utcnow()
                logger.info(f"completed successfully with format: {output_format}")
                
                # ==========================================================
                # NEW: Log this success to our continuous learning dataset!
                # ==========================================================
                experience_logger.log_success(task)
            else:
                # Legacy workflow failed - check if should escalate
                error_message = result.get('message', 'Unknown error')
                task.last_error = error_message
                
                # Get retry count from result if available
                retry_count = result.get("retry_count", 0)
                
                # Check if should escalate based on retry count and high-value status
                should_escalate, escalation_reason = _should_escalate_task(
                    task, 
                    retry_count, 
                    error_message
                )
                
                if should_escalate:
                    # ESCALATE to human review (Pillar 1.7)
                    await _escalate_task(db, task, escalation_reason, error_message)
                    logger.warning(f"ESCALATED for human review - {escalation_reason}")
                else:
                    # Mark as FAILED
                    task.status = TaskStatus.FAILED
                    task.review_feedback = error_message
                    logger.error(f"failed: {error_message}")
        
        db.commit()
        logger.info(f"processed, final status: {task.status}")
        
    except Exception as e:
        logger.error(f"Error processing task: {str(e)}")
        # Check if should escalate instead of marking as failed
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                error_message = str(e)
                task.last_error = error_message
                
                # Check if should escalate based on high-value status
                should_escalate, escalation_reason = _should_escalate_task(
                    task, 
                    task.retry_count or 0, 
                    error_message
                )
                
                if should_escalate:
                    # ESCALATE to human review (Pillar 1.7)
                    await _escalate_task(db, task, escalation_reason, error_message)
                    logger.warning(f"ESCALATED for human review - {escalation_reason}")
                else:
                    # Mark as FAILED
                    task.status = TaskStatus.FAILED
                    task.review_feedback = error_message
                    db.commit()
        except Exception:
            pass
    finally:
        db.close()



# Configure Stripe (use environment variable in production)
# In production, use: os.environ.get('STRIPE_SECRET_KEY')
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "sk_test_placeholder")

# Stripe webhook secret (use environment variable in production)
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_placeholder")

# =============================================================================
# PRICING ENGINE - Task Price Formula (Pillar 1.4)
# Price = Base Rate × Complexity × Urgency
# =============================================================================

# Base rates per domain (USD)
DOMAIN_BASE_RATES = {
    "accounting": 100,
    "legal": 175,
    "data_analysis": 150,
}

# Complexity multipliers
COMPLEXITY_MULTIPLIERS = {
    "simple": 1.0,
    "medium": 1.5,
    "complex": 2.0,
}

# Urgency multipliers
URGENCY_MULTIPLIERS = {
    "standard": 1.0,
    "rush": 1.25,
    "urgent": 1.5,
}


def calculate_task_price(
    domain: str,
    complexity: str = "medium",
    urgency: str = "standard"
) -> int:
    """
    Calculate task price using the Task Price Formula:
    Price = Base Rate × Complexity × Urgency
    
    Args:
        domain: The domain of the task (accounting, legal, data_analysis)
        complexity: Task complexity (simple, medium, complex)
        urgency: Task urgency (standard, rush, urgent)
    
    Returns:
        Calculated price in USD (cents for Stripe)
    
    Raises:
        ValueError: If domain, complexity, or urgency is invalid
    """
    # Validate domain
    if domain not in DOMAIN_BASE_RATES:
        valid_domains = ", ".join(DOMAIN_BASE_RATES.keys())
        raise ValueError(f"Invalid domain '{domain}'. Must be one of: {valid_domains}")
    
    # Validate complexity
    if complexity not in COMPLEXITY_MULTIPLIERS:
        valid_complexities = ", ".join(COMPLEXITY_MULTIPLIERS.keys())
        raise ValueError(f"Invalid complexity '{complexity}'. Must be one of: {valid_complexities}")
    
    # Validate urgency
    if urgency not in URGENCY_MULTIPLIERS:
        valid_urgencies = ", ".join(URGENCY_MULTIPLIERS.keys())
        raise ValueError(f"Invalid urgency '{urgency}'. Must be one of: {valid_urgencies}")
    
    # Calculate price: Base Rate × Complexity × Urgency
    base_rate = DOMAIN_BASE_RATES[domain]
    complexity_multiplier = COMPLEXITY_MULTIPLIERS[complexity]
    urgency_multiplier = URGENCY_MULTIPLIERS[urgency]
    
    price = base_rate * complexity_multiplier * urgency_multiplier
    
    # Round to nearest dollar
    return round(price)


# Legacy support - map old flat prices to new base rates for backward compatibility
# The old prices were: accounting=$150, legal=$250, data_analysis=$200 (assumed medium complexity, standard urgency)
DOMAIN_PRICES = DOMAIN_BASE_RATES  # Keep for backward compatibility

# Base URL for success/cancel pages (configure in production)
BASE_URL = os.environ.get("BASE_URL", "http://localhost:5173")


class TaskSubmission(BaseModel):
    """Model for task submission data."""
    domain: str
    title: str
    description: str
    csvContent: str | None = None
    # New fields for file uploads (Issue #34: Security Validation)
    file_type: str | None = None  # csv, excel, pdf
    file_content: str | None = None  # Base64-encoded file content
    filename: str | None = None  # Original filename
    # Pricing factors (Pillar 1.4: Base Rate × Complexity × Urgency)
    complexity: str = "medium"  # simple, medium, complex
    urgency: str = "standard"  # standard, rush, urgent
    # Client tracking
    client_email: str | None = None  # Client email for history tracking

    @field_validator("file_content")
    @classmethod
    def validate_file_upload_content(cls, v, info: ValidationInfo):
        """
        Comprehensive file upload validation (Issue #34).
        Performs size, type, and signature validation before processing.
        """
        values = info.data
        filename = values.get("filename")
        file_type = values.get("file_type")

        if v and filename:
            try:
                # Validate using the comprehensive pipeline
                # This performs sanitization, extension check, size check, and signature check
                validate_file_upload(
                    filename=filename,
                    file_content_base64=v,
                    file_type=file_type
                )
            except ValueError as e:
                # Propagate validation errors as Pydantic errors (returns 422 to client)
                raise ValueError(f"File validation failed: {str(e)}")

        return v

    @field_validator("filename")
    @classmethod
    def validate_filename_present_with_content(cls, v, info: ValidationInfo):
        """Ensure filename is provided if file_content is present."""
        values = info.data
        if values.get("file_content") and not v:
            raise ValueError("filename is required when file_content is provided")
        return v



class CheckoutResponse(BaseModel):
    """Model for checkout session response."""
    session_id: str
    url: str
    amount: int
    domain: str
    title: str
    client_auth_token: str = None  # HMAC token for dashboard access (Issue #17)


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB and Observability
    init_db()
    init_observability()
    
    # Start autonomous scanning loop if enabled
    await start_autonomous_loop()
    
    yield
    # Shutdown logic goes here


# Update your FastAPI initialization to use the lifespan
app = FastAPI(title="ArbitrageAI API", lifespan=lifespan)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "ArbitrageAI API is running"}


@app.post("/api/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(task: TaskSubmission, db: Session = Depends(get_db)):
    """
    Create a Stripe checkout session based on task submission.
    
    Calculates price using the Task Price Formula (Pillar 1.4):
    Price = Base Rate × Complexity × Urgency
    
    Creates a real Stripe checkout session.
    Stores the task in the database with PENDING status.
    """
    # Calculate price using the Task Price Formula
    try:
        amount = calculate_task_price(
            domain=task.domain,
            complexity=task.complexity,
            urgency=task.urgency
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    try:
        # Sanitize filename and validate file if present (Issue #34)
        sanitized_filename = task.filename
        if task.file_content and task.filename:
            try:
                sanitized_filename, _, _ = validate_file_upload(
                    filename=task.filename,
                    file_content_base64=task.file_content,
                    file_type=task.file_type
                )
            except ValueError as e:
                # Should have been caught by Pydantic validator, but safety first
                raise HTTPException(status_code=422, detail=f"File validation failed: {str(e)}")

        # Determine if this is a high-value task (Pillar 1.7 - Profit Protection)
        is_high_value = amount >= HIGH_VALUE_THRESHOLD
        
        # Create a task in the database with PENDING status
        new_task = Task(
            id=str(uuid.uuid4()),
            title=task.title,
            description=task.description,
            domain=task.domain,
            status=TaskStatus.PENDING,
            stripe_session_id=None,  # Will be updated after Stripe session is created
            csv_data=task.csvContent,  # Store the CSV content if provided
            file_type=task.file_type,  # Store file type (csv, excel, pdf)
            file_content=task.file_content,  # Store base64-encoded file content
            filename=sanitized_filename,  # Store sanitized filename (Issue #34)
            client_email=task.client_email,  # Store client email for history tracking
            amount_paid=amount * 100,  # Store amount in cents
            delivery_token=secrets.token_urlsafe(32),  # Cryptographically strong token (Issue #18)
            delivery_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=DELIVERY_TOKEN_TTL_HOURS),
            is_high_value=is_high_value  # Mark as high-value for profit protection
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)
        
        # Create Stripe checkout session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f'{task.domain.title()} Task: {task.title}',
                        'description': task.description[:500] if task.description else '',
                    },
                    'unit_amount': amount * 100,  # Stripe uses cents
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{BASE_URL}/cancel',
            metadata={
                'task_id': new_task.id,
                'domain': task.domain,
                'title': task.title,
            },
            # Inform user that document generation may take up to 10 minutes
            billing_address_collection='required',
            shipping_address_collection=None,
            customer_email=task.client_email,
        )
        
        # Update task with Stripe session ID
        new_task.stripe_session_id = checkout_session.id
        db.commit()
        
        # Generate client auth token for dashboard access (Issue #17)
        client_token = None
        if task.client_email:
            client_token = generate_client_token(task.client_email)

        return CheckoutResponse(
            session_id=checkout_session.id,
            url=checkout_session.url,
            amount=amount,
            domain=task.domain,
            title=task.title,
            client_auth_token=client_token
        )
        
    except stripe.error.APIConnectionError as e:
        logger.error(f"Stripe network error: {e}")
        raise HTTPException(
            status_code=503,
            detail="Stripe API is temporarily unavailable (network timeout). Please try again later."
        )
    except stripe.error.StripeError as e:
        logger.error(f"Stripe general error: {e}")
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")
    except OperationalError as e:
        logger.error(f"Database operational error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred. Our team has been notified."
        )
    except Exception as e:
        # Check for concurrency conflicts (Issue #29)
        from sqlalchemy.orm.exc import StaleDataError
        if isinstance(e, StaleDataError):
            logger.warning(f"Concurrency conflict detected: {e}")
            raise HTTPException(
                status_code=409,
                detail="A concurrency conflict occurred. Please try again."
            )
        
        logger.error(f"Unexpected error creating checkout session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/api/domains")
async def get_domains():
    """
    Get available domains and their pricing configuration.
    
    Returns:
        - domains: List of available domains with base rates
        - complexity: Available complexity levels and their multipliers
        - urgency: Available urgency levels and their multipliers
    """
    return {
        "domains": [
            {"value": domain, "label": domain.replace("_", " ").title(), "base_price": price}
            for domain, price in DOMAIN_BASE_RATES.items()
        ],
        "complexity": [
            {"value": key, "label": key.title(), "multiplier": value}
            for key, value in COMPLEXITY_MULTIPLIERS.items()
        ],
        "urgency": [
            {"value": key, "label": key.title(), "multiplier": value}
            for key, value in URGENCY_MULTIPLIERS.items()
        ]
    }


@app.get("/api/calculate-price")
async def get_price_estimate(
    domain: str,
    complexity: str = "medium",
    urgency: str = "standard"
):
    """
    Calculate a price estimate based on domain, complexity, and urgency.
    
    Query parameters:
        domain: The task domain (accounting, legal, data_analysis)
        complexity: Task complexity (simple, medium, complex)
        urgency: Task urgency (standard, rush, urgent)
    
    Returns:
        Calculated price and breakdown of the calculation
    """
    try:
        amount = calculate_task_price(domain, complexity, urgency)
        base_rate = DOMAIN_BASE_RATES[domain]
        complexity_mult = COMPLEXITY_MULTIPLIERS[complexity]
        urgency_mult = URGENCY_MULTIPLIERS[urgency]
        
        return {
            "domain": domain,
            "complexity": complexity,
            "urgency": urgency,
            "base_rate": base_rate,
            "complexity_multiplier": complexity_mult,
            "urgency_multiplier": urgency_mult,
            "calculated_price": amount,
            "formula": f"${base_rate} × {complexity_mult} × {urgency_mult} = ${amount}"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))



@app.post("/api/webhook")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    stripe_signature: str = Header(None)
):
    """
    Stripe webhook endpoint to handle checkout events.
    
    Listens for checkout.session.completed events and updates task status to PAID.
    When a task is marked as PAID, a background task is added to process the task asynchronously.
    """
    payload = await request.body()
    
    try:
        # Verify webhook signature if secret is configured
        if STRIPE_WEBHOOK_SECRET != "whsec_placeholder":
            try:
                event = stripe.Webhook.construct_event(
                    payload, stripe_signature, STRIPE_WEBHOOK_SECRET
                )
            except stripe.error.SignatureVerificationError:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Invalid signature"}
                )
        else:
            # For development/testing without webhook secret
            event = json.loads(payload)
        
        # Handle the checkout.session.completed event
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            session_id = session.get('id')
            
            # Look up task by stripe_session_id
            task = db.query(Task).filter(Task.stripe_session_id == session_id).first()
            
            if task:
                # Update task status to PAID
                task.status = TaskStatus.PAID
                db.commit()
                
                # Add background task to process the visualization asynchronously
                background_tasks.add_task(process_task_async, task.id)
                
                return {"status": "success", "message": f"Task {task.id} marked as PAID, processing started"}
            else:
                return {"status": "warning", "message": f"No task found for session {session_id}"}
        
        # Handle other event types if needed
        elif event['type'] == 'checkout.session.expired':
            session = event['data']['object']
            session_id = session.get('id')
            
            task = db.query(Task).filter(Task.stripe_session_id == session_id).first()
            
            if task:
                task.status = TaskStatus.FAILED
                db.commit()
                
                return {"status": "success", "message": f"Task {task.id} marked as FAILED (expired)"}
        
        # Return 200 for events we don't handle
        return {"status": "received"}
        
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON payload"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Internal error: {str(e)}"}
        )


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str, db: Session = Depends(get_db)):
    """Get task by ID."""
    task = db.query(Task).filter(Task.id == task_id).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task.to_dict()


@app.get("/api/session/{session_id}")
async def get_task_by_session(session_id: str, db: Session = Depends(get_db)):
    """
    Get task ID and authentication token by Stripe checkout session ID.
    
    This endpoint is used by the Success component after Stripe redirects
    back to the application with the session_id in the URL.
    
    Returns task ID and client authentication token (if email was provided)
    so the frontend can store the token for authenticated dashboard requests.
    
    Security: Issue #17 - Client authentication for dashboard access
    """
    task = db.query(Task).filter(Task.stripe_session_id == session_id).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found for this session")
    
    # Generate client auth token if email was provided
    client_token = None
    if task.client_email:
        client_token = generate_client_token(task.client_email)
    
    return {
        "task_id": task.id,
        "client_email": task.client_email,
        "client_auth_token": client_token
    }


# =============================================================================
# CLIENT DASHBOARD ENDPOINTS (Pillar 1.5)
# - Historical tasks display
# - Repeat-client discounts (loyalty pricing)
# - Secure delivery links
# =============================================================================

# Repeat-client discount tiers
REPEAT_CLIENT_DISCOUNTS = {
    0: 0.0,      # First order - no discount
    1: 0.05,     # 2nd order - 5% discount
    2: 0.10,     # 3rd order - 10% discount
    5: 0.15,     # 6th+ order - 15% discount
}

# Maximum discount cap
MAX_DISCOUNT = 0.15


def get_client_discount(completed_tasks_count: int) -> float:
    """
    Calculate repeat-client discount based on number of completed tasks.
    
    Args:
        completed_tasks_count: Number of previously completed tasks for the client
    
    Returns:
        Discount percentage (0.0 to 0.15)
    """
    if completed_tasks_count >= 5:
        return 0.15
    elif completed_tasks_count >= 2:
        return 0.10
    elif completed_tasks_count >= 1:
        return 0.05
    return 0.0


def get_discount_tier(completed_tasks_count: int) -> int:
    """Get the discount tier based on completed tasks count."""
    if completed_tasks_count >= 5:
        return 5
    elif completed_tasks_count >= 2:
        return 2
    elif completed_tasks_count >= 1:
        return 1
    return 0


@app.get("/api/client/history")
async def get_client_task_history(
    email: str,
    token: str,
    db: Session = Depends(get_db)
):
    """
    Get task history for a client by email (authenticated — Issue #17).

    Requires a valid HMAC token proving ownership of the email address.
    The token is provided when a task is created.

    Query parameters:
        email: Client email address
        token: HMAC authentication token for this email
    """
    if not verify_client_token(email, token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    # Get all tasks for this client
    tasks = db.query(Task).filter(Task.client_email == email).order_by(
        Task.id.desc()  # Most recent first
    ).all()
    
    # Calculate statistics
    total_tasks = len(tasks)
    completed_tasks = [t for t in tasks if t.status == TaskStatus.COMPLETED]
    completed_count = len(completed_tasks)
    
    # Calculate total spent (in dollars)
    total_spent = sum(t.amount_paid or 0 for t in completed_tasks) / 100
    
    # Get current discount
    current_discount = get_client_discount(completed_count)
    current_tier = get_discount_tier(completed_count)
    
    # Determine next discount tier
    next_tier_info = None
    if current_tier == 0:
        next_tier_info = {"tasks_needed": 1, "discount": 0.05, "label": "5% off"}
    elif current_tier == 1:
        next_tier_info = {"tasks_needed": 1, "discount": 0.10, "label": "10% off"}
    elif current_tier == 2:
        next_tier_info = {"tasks_needed": 3, "discount": 0.15, "label": "15% off"}
    else:
        next_tier_info = None  # Already at max discount
    
    # Convert tasks to dictionaries
    task_list = []
    for task in tasks:
        task_dict = task.to_dict()
        # Add amount in dollars for display
        if task.amount_paid:
            task_dict["amount_dollars"] = task.amount_paid / 100
        task_list.append(task_dict)
    
    return {
        "tasks": task_list,
        "stats": {
            "total_tasks": total_tasks,
            "completed_tasks": completed_count,
            "in_progress_tasks": len([t for t in tasks if t.status == TaskStatus.PAID]),
            "failed_tasks": len([t for t in tasks if t.status == TaskStatus.FAILED]),
            "total_spent": round(total_spent, 2)
        },
        "discount": {
            "current_tier": current_tier,
            "discount_percentage": current_discount,
            "completed_orders": completed_count
        },
        "next_discount": next_tier_info
    }


@app.get("/api/client/discount-info")
async def get_client_discount_info(
    email: str,
    token: str,
    db: Session = Depends(get_db)
):
    """
    Get discount information for a client (authenticated — Issue #17).

    Requires a valid HMAC token proving ownership of the email address.
    """
    if not verify_client_token(email, token):
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    # Count completed tasks for this client
    completed_count = db.query(Task).filter(
        Task.client_email == email,
        Task.status == TaskStatus.COMPLETED
    ).count()
    
    current_discount = get_client_discount(completed_count)
    current_tier = get_discount_tier(completed_count)
    
    # Determine next discount tier
    next_tier_info = None
    if current_tier == 0:
        next_tier_info = {"tasks_needed": 1, "discount": 0.05, "label": "5% off"}
    elif current_tier == 1:
        next_tier_info = {"tasks_needed": 1, "discount": 0.10, "label": "10% off"}
    elif current_tier == 2:
        next_tier_info = {"tasks_needed": 3, "discount": 0.15, "label": "15% off"}
    
    return {
        "email": email,
        "completed_orders": completed_count,
        "current_tier": current_tier,
        "current_discount": current_discount,
        "next_tier": next_tier_info,
        "tiers": [
            {"tier": 0, "label": "New Client", "min_orders": 0, "discount": 0},
            {"tier": 1, "label": "Returning Client", "min_orders": 1, "discount": 0.05},
            {"tier": 2, "label": "Loyal Client", "min_orders": 2, "discount": 0.10},
            {"tier": 5, "label": "VIP Client", "min_orders": 5, "discount": 0.15},
        ]
    }


def _check_delivery_ip_rate_limit(ip: str) -> bool:
    """Check if an IP is rate-limited for delivery attempts (Issue #18)."""
    entry = _delivery_ip_rate_limits.get(ip)
    if entry is None:
        return True
    
    attempt_count, first_attempt_ts = entry
    # Reset if lockout window has passed
    if _time.time() - first_attempt_ts > DELIVERY_IP_LOCKOUT_SECONDS:
        del _delivery_ip_rate_limits[ip]
        return True
        
    return attempt_count < DELIVERY_MAX_ATTEMPTS_PER_IP


def _record_ip_delivery_attempt(ip: str) -> None:
    """Record a delivery attempt from an IP."""
    entry = _delivery_ip_rate_limits.get(ip)
    if entry is None:
        _delivery_ip_rate_limits[ip] = (1, _time.time())
    else:
        attempt_count, first_attempt_ts = entry
        _delivery_ip_rate_limits[ip] = (attempt_count + 1, first_attempt_ts)


@app.get("/api/delivery/{task_id}/{token}")
async def get_secure_delivery(
    task_id: str,
    token: str,
    request: Request,
    db: Session = Depends(get_db)
) -> DeliveryResponse:
    """
    Secure delivery link endpoint with comprehensive validation (Issue #18).

    Security Measures:
    1. Input Validation: Pydantic model validates task_id (UUID) and token format
    2. IP-based Rate Limiting: Max 20 attempts per IP per hour
    3. Task-based Rate Limiting: Max 5 failed attempts per task per hour
    4. Token Verification: Constant-time comparison to prevent timing attacks
    5. Token Expiration: Configurable TTL (default 1 hour)
    6. One-Time Use: Token invalidated after successful download
    7. Status Validation: Task must be COMPLETED
    8. Audit Logging: All attempts logged for security analysis
    9. Input Sanitization: String fields sanitized for injection prevention
    """
    logger = get_logger(__name__)
    client_ip = request.client.host if request.client else "unknown"

    # 1. INPUT VALIDATION - Pydantic validation with strict rules
    try:
        validated = DeliveryTokenRequest(task_id=task_id, token=token)
        validated_task_id = validated.task_id
        validated_token = validated.token
    except Exception as e:
        logger.warning(f"[DELIVERY] Validation failed: {str(e)} ip={client_ip}")
        _record_delivery_failure(task_id, client_ip)
        raise HTTPException(status_code=400, detail=f"Invalid input: {str(e)}")

    # 2. IP-level rate limiting (Issue #18)
    if not _check_delivery_ip_rate_limit(client_ip):
        logger.warning(f"[DELIVERY] IP rate limited: ip={client_ip}")
        raise HTTPException(status_code=429, detail="Too many delivery requests from your IP. Try again later.")
    _record_ip_delivery_attempt(client_ip)

    # 3. Task-level rate limiting
    if not _check_delivery_rate_limit(validated_task_id):
        logger.warning(f"[DELIVERY] Task rate limited: task={validated_task_id} ip={client_ip}")
        _record_delivery_failure(validated_task_id, client_ip)
        raise HTTPException(status_code=429, detail="Too many failed attempts for this task. Try again later.")

    task = db.query(Task).filter(Task.id == validated_task_id).first()

    if not task:
        _record_delivery_failure(validated_task_id, client_ip)
        logger.warning(f"[DELIVERY] Not found: task={validated_task_id} ip={client_ip}")
        raise HTTPException(status_code=404, detail="Task not found")

    # 4. Token verification (constant-time comparison)
    if not task.delivery_token or not secrets.compare_digest(task.delivery_token, validated_token):
        _record_delivery_failure(validated_task_id, client_ip)
        logger.warning(f"[DELIVERY] Invalid token: task={validated_task_id} ip={client_ip}")
        raise HTTPException(status_code=403, detail="Invalid delivery token")

    # 5. Token expiration check
    if task.delivery_token_expires_at:
        expires_at = task.delivery_token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            _record_delivery_failure(validated_task_id, client_ip)
            logger.warning(f"[DELIVERY] Expired token: task={validated_task_id} ip={client_ip}")
            raise HTTPException(status_code=403, detail="Delivery link has expired")

    # 6. One-time use check
    if task.delivery_token_used:
        _record_delivery_failure(validated_task_id, client_ip)
        logger.warning(f"[DELIVERY] Already used token: task={validated_task_id} ip={client_ip}")
        raise HTTPException(status_code=403, detail="Delivery link has already been used")

    # Verify the task is completed
    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Task is not ready for delivery. Current status: {task.status.value}"
        )

    # 5. Invalidate token (one-time use)
    task.delivery_token_used = True
    db.commit()

    # Return the delivery data with sanitized output
    result_url = None
    if task.result_type in ["docx", "pdf"]:
        result_url = _sanitize_string(task.result_document_url) if task.result_document_url else None
    elif task.result_type == "xlsx":
        result_url = _sanitize_string(task.result_spreadsheet_url) if task.result_spreadsheet_url else None
    else:
        result_url = _sanitize_string(task.result_image_url) if task.result_image_url else None

    logger.info(f"[DELIVERY] Success: task={validated_task_id} ip={client_ip}")

    return JSONResponse(
        content={
            "task_id": task.id,
            "title": _sanitize_string(task.title),
            "domain": _sanitize_string(task.domain),
            "result_type": task.result_type,
            "result_url": result_url,
            "result_image_url": _sanitize_string(task.result_image_url) if task.result_image_url else None,
            "result_document_url": _sanitize_string(task.result_document_url) if task.result_document_url else None,
            "result_spreadsheet_url": _sanitize_string(task.result_spreadsheet_url) if task.result_spreadsheet_url else None,
            "delivered_at": datetime.now(timezone.utc).isoformat()
        },
        headers={
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate",
            "Content-Security-Policy": "default-src 'none'"
        }
    )


@app.post("/api/client/calculate-price-with-discount")
async def calculate_price_with_discount(
    domain: str,
    complexity: str = "medium",
    urgency: str = "standard",
    email: str | None = None,
    token: str | None = None,
    db: Session = Depends(get_db)
):
    """
    Calculate price with repeat-client discount applied (authenticated).

    If email and token are provided, validates ownership and calculates
    the discount based on the client's completed task history.
    """
    # First calculate base price
    base_price = calculate_task_price(domain, complexity, urgency)

    # Default response without discount
    response = {
        "base_price": base_price,
        "discount": 0,
        "discount_percentage": 0,
        "final_price": base_price,
        "is_repeat_client": False,
        "completed_orders": 0
    }

    # If client email provided, check for repeat-client discount
    if email:
        # Require both email and token for authentication
        if not token:
            logger.warning("[CLIENT_AUTH] Partial auth parameters provided: email without token")
            raise HTTPException(
                status_code=401,
                detail="Both email and token must be provided for authentication",
            )

        # Verify token matches email
        if not verify_client_token(email, token):
            logger.warning(f"[CLIENT_AUTH] Invalid token for email: {email}")
            raise HTTPException(status_code=401, detail="Invalid authentication token")

        completed_count = db.query(Task).filter(
            Task.client_email == email,
            Task.status == TaskStatus.COMPLETED
        ).count()
        logger.info(f"Repeat client check for {email}: {completed_count} completed tasks")

        if completed_count > 0:
            discount = get_client_discount(completed_count)
            discount_amount = round(base_price * discount)
            final_price = base_price - discount_amount

            response = {
                "base_price": base_price,
                "discount": discount_amount,
                "discount_percentage": discount,
                "final_price": final_price,
                "is_repeat_client": True,
                "completed_orders": completed_count,
                "discount_tier": get_discount_tier(completed_count)
            }
    elif token:
        # Token provided without email
        logger.warning("[CLIENT_AUTH] Partial auth parameters provided: token without email")
        raise HTTPException(
            status_code=401,
            detail="Both email and token must be provided for authentication",
        )

    return response

# =============================================================================
# ADMIN METRICS ENDPOINT (Pillar 1.6)
# - Completion rates tracking
# - Average turnaround time
# - Revenue per domain
# =============================================================================


@app.get("/api/admin/metrics")
async def get_admin_metrics(
    db: Session = Depends(get_db)
):
    """
    Get admin metrics including completion rates, average turnaround time, and revenue per domain.
    
    Returns:
        - completion_rates: Overall and per-domain completion rates
        - turnaround_time: Average time from PAID to COMPLETED status
        - revenue: Total revenue and revenue breakdown by domain
    """
    # Get all tasks
    all_tasks = db.query(Task).all()
    total_tasks = len(all_tasks)
    
    if total_tasks == 0:
        return {
            "completion_rates": {
                "overall": {"completed": 0, "total": 0, "rate": 0.0},
                "by_domain": {}
            },
            "turnaround_time": {
                "average_hours": 0.0,
                "sample_size": 0
            },
            "revenue": {
                "total": 0.0,
                "by_domain": {}
            }
        }
    
    # Count tasks by status
    completed_count = sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETED)
    failed_count = sum(1 for t in all_tasks if t.status == TaskStatus.FAILED)
    pending_count = sum(1 for t in all_tasks if t.status == TaskStatus.PENDING)
    paid_count = sum(1 for t in all_tasks if t.status == TaskStatus.PAID)
    
    # Calculate overall completion rate (completed / (completed + failed))
    completed_or_failed = completed_count + failed_count
    overall_completion_rate = (completed_count / completed_or_failed * 100) if completed_or_failed > 0 else 0.0
    
    # Calculate completion rate by domain
    domain_stats = {}
    for domain in DOMAIN_BASE_RATES.keys():
        domain_tasks = [t for t in all_tasks if t.domain == domain]
        domain_completed = [t for t in domain_tasks if t.status == TaskStatus.COMPLETED]
        domain_failed = [t for t in domain_tasks if t.status == TaskStatus.FAILED]
        domain_total = len(domain_tasks)
        domain_completed_or_failed = len(domain_completed) + len(domain_failed)
        
        domain_completion_rate = (
            len(domain_completed) / domain_completed_or_failed * 100 
            if domain_completed_or_failed > 0 else 0.0
        )
        
        # Calculate revenue for this domain (only from completed tasks)
        domain_revenue = sum(t.amount_paid or 0 for t in domain_completed) / 100
        
        domain_stats[domain] = {
            "total": domain_total,
            "completed": len(domain_completed),
            "failed": len(domain_failed),
            "pending": len([t for t in domain_tasks if t.status == TaskStatus.PENDING]),
            "in_progress": len([t for t in domain_tasks if t.status == TaskStatus.PAID]),
            "completion_rate": round(domain_completion_rate, 2),
            "revenue": round(domain_revenue, 2)
        }
    
    # Calculate total revenue
    total_revenue = sum(t.amount_paid or 0 for t in all_tasks if t.status == TaskStatus.COMPLETED and t.amount_paid) / 100
    
    # For turnaround time, we would need created_at and updated_at fields
    # Since these may not exist in the current model, we'll return a placeholder
    # that indicates the feature is available but needs timestamp fields
    turnaround_time_hours = 0.0
    sample_size = 0
    
    # Check if Task model has timestamp fields
    if hasattr(Task, 'created_at') and hasattr(Task, 'updated_at'):
        # Calculate turnaround time for completed tasks
        completed_tasks = [t for t in all_tasks if t.status == TaskStatus.COMPLETED]
        total_hours = 0.0
        for task in completed_tasks:
            if task.created_at and task.updated_at:
                time_diff = (task.updated_at - task.created_at).total_seconds() / 3600
                total_hours += time_diff
                sample_size += 1
        
        if sample_size > 0:
            turnaround_time_hours = total_hours / sample_size
    
    return {
        "completion_rates": {
            "overall": {
                "completed": completed_count,
                "failed": failed_count,
                "pending": pending_count,
                "in_progress": paid_count,
                "total": total_tasks,
                "rate": round(overall_completion_rate, 2)
            },
            "by_domain": domain_stats
        },
        "turnaround_time": {
            "average_hours": round(turnaround_time_hours, 2),
            "sample_size": sample_size,
            "note": "Requires created_at and updated_at timestamp fields in Task model"
        },
        "revenue": {
            "total": round(total_revenue, 2),
            "by_domain": {domain: stats["revenue"] for domain, stats in domain_stats.items()},
            "currency": "USD"
        }
    }


# =============================================================================
# AGENT ARENA ENDPOINTS
# - Run A/B competitions between agent variants
# - Track winner and profit scores
# - Build DPO dataset from competitions
# =============================================================================


class ArenaSubmission(BaseModel):
    """Model for arena competition submission."""
    domain: str
    user_request: str
    csv_data: str | None = None
    file_content: str | None = None
    filename: str | None = None
    file_type: str | None = None
    competition_type: str = "model"  # "model", "prompt", "tooling"
    task_revenue: int | None = None  # Revenue in cents
    task_id: str | None = None  # Associated task ID (optional)


@app.post("/api/arena/run")
async def run_arena_competition(
    submission: ArenaSubmission,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Run an Agent Arena competition.
    
    This endpoint runs two agent variants in parallel and determines the winner
    based on quality (PlanReviewer approval) + profit score.
    
    The winning artifact is returned to the client, and both agents' results
    are logged for learning (DPO dataset).
    """
    
    # Map competition type string to enum
    comp_type_map = {
        "model": CompetitionType.MODEL,
        "prompt": CompetitionType.PROMPT,
        "tooling": CompetitionType.TOOLING
    }
    competition_type = comp_type_map.get(submission.competition_type, CompetitionType.MODEL)
    
    # Get task revenue (default if not provided)
    task_revenue = submission.task_revenue or 500  # Default $5.00
    
    # Create arena router
    arena = ArenaRouter(competition_type=competition_type)
    
    # Run the arena natively (it's already async!)
    result = await arena.run_arena(
        user_request=submission.user_request,
        domain=submission.domain,
        csv_data=submission.csv_data,
        file_content=submission.file_content,
        filename=submission.filename,
        file_type=submission.file_type,
        task_revenue=task_revenue
    )
    
    # Save the competition to the database
    competition_record = ArenaCompetition(
        task_id=submission.task_id,
        competition_type=result["competition_type"],
        domain=submission.domain,
        user_request=submission.user_request,
        task_revenue=task_revenue,
        status=ArenaCompetitionStatus.COMPLETED,
        
        # Agent A stats
        agent_a_name=result["agent_a"]["config"]["name"],
        agent_a_model=result["agent_a"]["config"]["model"],
        agent_a_approved=result["agent_a"]["result"].get("approved", False),
        agent_a_profit=result["agent_a"]["profit"]["profit"],
        
        # Agent B stats
        agent_b_name=result["agent_b"]["config"]["name"],
        agent_b_model=result["agent_b"]["config"]["model"],
        agent_b_approved=result["agent_b"]["result"].get("approved", False),
        agent_b_profit=result["agent_b"]["profit"]["profit"],
        
        winner=result["winner"],
        win_reason=result["win_reason"],
        winning_artifact_url=result["winning_artifact_url"]
    )
    db.add(competition_record)
    db.commit()
    
    # Log to learning systems (in background)
    if submission.task_id:
        background_tasks.add_task(
            _log_arena_learning,
            result,
            submission.task_id,
            submission.domain,
            submission.user_request
        )
    
    # Return the winning result to the client
    return {
        "status": "success",
        "winner": result["winner"],
        "win_reason": result["win_reason"],
        "artifact_url": result["winning_artifact_url"],
        "competition_type": result["competition_type"],
        "profit_breakdown": {
            "agent_a": result["agent_a"]["profit"],
            "agent_b": result["agent_b"]["profit"]
        },
        "agent_configs": {
            "agent_a": result["agent_a"]["config"],
            "agent_b": result["agent_b"]["config"]
        }
    }


async def _log_arena_learning(
    arena_result: dict,
    task_id: str,
    domain: str,
    user_request: str
):
    """Log arena results to learning systems."""
    # Get logger for this function
    logger = get_logger(__name__)
    
    try:
        arena_logger = ArenaLearningLogger()
        
        # Create task data for logging
        task_data = {
            "id": task_id,
            "domain": domain,
            "description": user_request
        }
        
        # Log winner and loser
        arena_logger.log_winner(arena_result, task_data)
        arena_logger.log_loser(arena_result, task_data)
        
        logger.info(f"Learning data logged for task {task_id}")
    except Exception as e:
        logger.error(f"Error logging learning data: {e}")


@app.get("/api/arena/history")
async def get_arena_history(
    db: Session = Depends(get_db),
    limit: int = 20
):
    """
    Get arena competition history.
    
    Returns recent arena competitions and their results.
    """
    from .models import ArenaCompetition
    
    competitions = db.query(ArenaCompetition).order_by(
        ArenaCompetition.created_at.desc()
    ).limit(limit).all()
    
    return {
        "competitions": [c.to_dict() for c in competitions],
        "total": len(competitions)
    }


@app.get("/api/arena/stats")
async def get_arena_stats(db: Session = Depends(get_db)):
    """
    Get arena statistics.
    
    Returns aggregated statistics about arena competitions,
    including win rates for each agent type.
    """
    from .models import ArenaCompetition, ArenaCompetitionStatus
    
    # Get all completed competitions
    completed = db.query(ArenaCompetition).filter(
        ArenaCompetition.status == ArenaCompetitionStatus.COMPLETED
    ).all()
    
    if not completed:
        return {
            "total_competitions": 0,
            "agent_a_wins": 0,
            "agent_b_wins": 0,
            "agent_a_win_rate": 0.0,
            "agent_b_win_rate": 0.0,
            "avg_profit_agent_a": 0.0,
            "avg_profit_agent_b": 0.0
        }
    
    agent_a_wins = sum(1 for c in completed if c.winner == "agent_a")
    agent_b_wins = sum(1 for c in completed if c.winner == "agent_b")
    
    total = len(completed)
    
    # Calculate average profits
    avg_profit_a = sum(c.agent_a_profit or 0 for c in completed) / total if total > 0 else 0
    avg_profit_b = sum(c.agent_b_profit or 0 for c in completed) / total if total > 0 else 0
    
    return {
        "total_competitions": total,
        "agent_a_wins": agent_a_wins,
        "agent_b_wins": agent_b_wins,
        "agent_a_win_rate": round(agent_a_wins / total * 100, 2) if total > 0 else 0.0,
        "agent_b_win_rate": round(agent_b_wins / total * 100, 2) if total > 0 else 0.0,
        "avg_profit_agent_a": round(avg_profit_a / 100, 2),  # Convert to dollars
        "avg_profit_agent_b": round(avg_profit_b / 100, 2),
    }


# =============================================================================
# AUTONOMOUS JOB SCANNING LOOP
# - Background task that scans marketplace for new jobs
# - Evaluates jobs using LLM and filters suitable ones
# - Sends Telegram notifications for user approval before bidding
# =============================================================================

# Autonomous loop configuration
AUTONOMOUS_SCAN_ENABLED = os.environ.get("AUTONOMOUS_SCAN_ENABLED", "false").lower() == "true"
AUTONOMOUS_SCAN_INTERVAL_MIN = int(ConfigManager.get("MARKET_SCAN_INTERVAL")) // 60
AUTONOMOUS_SCAN_INTERVAL_MAX = (int(ConfigManager.get("MARKET_SCAN_INTERVAL")) // 60) * 2

AUTONOMOUS_MIN_BID_THRESHOLD = ConfigManager.get("MIN_BID_THRESHOLD")


async def generate_proposal(job_title: str, job_description: str, bid_amount: int) -> str:
    """
    Generate a proposal for a job using LLM.
    
    Args:
        job_title: The job title
        job_description: The job description
        bid_amount: The proposed bid amount in dollars
        
    Returns:
        Generated proposal text
    """
    logger = get_logger(__name__)
    
    try:
        # Use LLM with stealth mode for human-like typing
        llm = LLMService.with_cloud()
        
        prompt = f"""Generate a professional proposal for the following freelance job:

Job Title: {job_title}

Job Description: {job_description}

Your Bid: ${bid_amount}

Write a compelling proposal that:
1. Introduces your relevant skills and experience
2. Explains how you'll approach the project
3. Mentions any relevant tools or technologies
4. Includes a timeline for completion

Keep it concise but professional. Around 150-200 words."""
        
        result = llm.complete(
            prompt=prompt,
            temperature=0.7,
            max_tokens=500,
            stealth_mode=True  # Add human-like delay
        )
        
        return result.get("content", "Proposal generation failed.")
        
    except Exception as e:
        logger.error(f"Error generating proposal: {e}")
        return f"Professional proposal for {job_title} - ${bid_amount} budget"


async def run_autonomous_loop():
    """
    Autonomous background loop that:
    1. Scans marketplace for new jobs
    2. Filters out jobs already in Bids table
    3. Evaluates jobs for suitability
    4. Generates proposals for suitable jobs
    5. Sends Telegram notification for user approval
    """
    from .database import SessionLocal
    
    logger = get_logger(__name__)
    logger.info("[AUTONOMOUS] Starting autonomous job scanning loop")
    
    # Initialize notifier
    notifier = TelegramNotifier()
    
    while True:
        try:
            logger.info("[AUTONOMOUS] Scanning marketplace for new jobs...")
            
            # Scan marketplace for jobs
            scan_result = await run_single_scan(max_posts=10)
            
            if not scan_result.get("success"):
                logger.warning(f"[AUTONOMOUS] Scan failed: {scan_result.get('message')}")
            else:
                suitable_jobs = scan_result.get("suitable_jobs", [])
                logger.info(f"[AUTONOMOUS] Found {len(suitable_jobs)} suitable jobs")
                
                # Get database session
                db = SessionLocal()
                
                try:
                    # Get all existing job IDs/URLs we've already bid on
                    existing_bids = db.query(Bid).filter(
                        Bid.status.in_([BidStatus.SUBMITTED, BidStatus.PENDING, BidStatus.APPROVED])
                    ).all()
                    
                    # Create set of existing job identifiers for quick lookup
                    existing_job_titles = {bid.job_title for bid in existing_bids}
                    
                    logger.info(f"[AUTONOMOUS] Already have {len(existing_job_titles)} bids in progress")
                    
                    # Process each suitable job
                    for job in suitable_jobs:
                        job_title = job.get("posting", {}).get("title", "")
                        job_description = job.get("posting", {}).get("description", "")
                        bid_amount = job.get("evaluation", {}).get("bid_amount", 0)
                        
                        # Skip if already bid on this job
                        if job_title in existing_job_titles:
                            logger.info(f"[AUTONOMOUS] Skipping already-bid job: {job_title}")
                            continue
                        
                        # Skip if below minimum bid threshold
                        if bid_amount < AUTONOMOUS_MIN_BID_THRESHOLD:
                            logger.info(f"[AUTONOMOUS] Skipping low-value job: {job_title} (${bid_amount})")
                            continue
                        
                        logger.info(f"[AUTONOMOUS] Processing job: {job_title} - ${bid_amount}")
                        
                        # Generate proposal
                        proposal = await generate_proposal(
                            job_title=job_title,
                            job_description=job_description,
                            bid_amount=bid_amount
                        )
                        
                        # Create bid record with PENDING status
                        bid = Bid(
                            job_title=job_title,
                            job_description=job_description[:2000],  # Limit description length
                            job_url=job.get("posting", {}).get("url"),
                            bid_amount=bid_amount * 100,  # Store in cents
                            proposal=proposal,
                            status=BidStatus.PENDING,
                            is_suitable=job.get("evaluation", {}).get("is_suitable", True),
                            evaluation_reasoning=job.get("evaluation", {}).get("reasoning", ""),
                            evaluation_confidence=int(job.get("evaluation", {}).get("confidence", 0.5) * 100),
                            marketplace=os.environ.get("MARKETPLACE_URL", "unknown"),
                            skills_matched=job.get("posting", {}).get("skills", [])
                        )
                        db.add(bid)
                        db.commit()
                        
                        # Send Telegram notification for approval
                        notification_message = f"""🤖 *New Job Opportunity*

*Title:* {job_title}
*Bid Amount:* ${bid_amount}
*Confidence:* {int(job.get('evaluation', {}).get('confidence', 0.5) * 100)}%

*Evaluation:*
{job.get('evaluation', {}).get('reasoning', 'No reasoning provided')}

*Proposal Preview:*
{proposal[:300]}...

Reply with APPROVE to submit bid or REJECT to skip."""

                        await notifier.send_urgent_message(notification_message)
                        logger.info(f"[AUTONOMOUS] Sent notification for approval: {job_title}")
                        
                finally:
                    db.close()
                    
        except Exception as e:
            logger.error(f"[AUTONOMOUS] Error in scan loop: {e}")
        
        # Random sleep between 15-30 minutes
        sleep_minutes = random.randint(AUTONOMOUS_SCAN_INTERVAL_MIN, AUTONOMOUS_SCAN_INTERVAL_MAX)
        logger.info(f"[AUTONOMOUS] Sleeping for {sleep_minutes} minutes until next scan...")
        await asyncio.sleep(sleep_minutes * 60)


# =============================================================================
# FASTAPI STARTUP - Start autonomous loop if enabled
# =============================================================================

# Track if autonomous loop is running
_autonomous_loop_task = None


async def start_autonomous_loop():
    """Start the autonomous scanning loop if enabled."""
    global _autonomous_loop_task
    
    if AUTONOMOUS_SCAN_ENABLED:
        logger = get_logger(__name__)
        logger.info("[STARTUP] Autonomous scanning is ENABLED")
        
        # Create and start the background task
        _autonomous_loop_task = asyncio.create_task(run_autonomous_loop())
        logger.info("[STARTUP] Autonomous scanning loop started")
    else:
        logger = get_logger(__name__)
        logger.info("[STARTUP] Autonomous scanning is DISABLED (set AUTONOMOUS_SCAN_ENABLED=true to enable)")

# Register scheduler routes
register_scheduler_routes(app)
register_analytics_routes(app)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
