"""
FastAPI backend for the AI Freelance Platform.
Provides endpoints for creating checkout sessions and processing task submissions.
"""
import os
import uuid
import json
import hmac
import hashlib
from fastapi import FastAPI, HTTPException, Request, Depends, Header, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
import stripe

from datetime import datetime
from .database import get_db, init_db
from .models import Task, TaskStatus, PlanStatus, ReviewStatus
from ..agent_execution.executor import execute_task, execute_data_visualization, TaskType, OutputFormat


# =============================================================================
# ESCALATION & HUMAN-IN-THE-LOOP (HITL) CONFIGURATION (Pillar 1.7)
# =============================================================================

# High-value threshold for profit protection (in dollars)
# Tasks with amount_paid >= HIGH_VALUE_THRESHOLD will always be escalated on failure
HIGH_VALUE_THRESHOLD = 200

# Maximum number of retry attempts before escalation (matches executor.py)
MAX_RETRY_ATTEMPTS = 3


from ..agent_execution.planning import (
    ResearchAndPlanOrchestrator,
    create_research_plan_workflow,
    ContextExtractor,
    WorkPlanGenerator
)


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


def _escalate_task(db, task, reason: str, error_message: str = None):
    """
    Escalate a task to human review.
    
    Args:
        db: Database session
        task: The Task object to escalate
        reason: Reason for escalation
        error_message: Optional error details
    """
    task.status = TaskStatus.ESCALATION
    task.escalation_reason = reason
    task.escalated_at = datetime.utcnow()
    task.last_error = error_message
    task.review_status = ReviewStatus.PENDING
    
    # Log the escalation for profit protection
    amount_dollars = (task.amount_paid / 100) if task.amount_paid else 0
    is_high_value = amount_dollars >= HIGH_VALUE_THRESHOLD
    
    print(f"[ESCALATION] Task {task.id} escalated: {reason}")
    print(f"[ESCALATION] Amount: ${amount_dollars}, High-value: {is_high_value}")
    print(f"[ESCALATION] Human reviewer notification required to prevent refund")
    
    if error_message:
        print(f"[ESCALATION] Error: {error_message[:200]}...")
    
    db.commit()


def process_task_async(task_id: str, use_planning_workflow: bool = True):
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
    
    Args:
        task_id: The ID of the task to process
        use_planning_workflow: Whether to use the Research & Plan workflow (default: True)
    """
    # Create a new database session for this background task
    from .database import SessionLocal
    import os
    
    db = SessionLocal()
    try:
        # Retrieve the task from the database
        task = db.query(Task).filter(Task.id == task_id).first()
        
        if not task:
            print(f"Task {task_id} not found for processing")
            return
        
        if task.status != TaskStatus.PAID:
            print(f"Task {task_id} is not in PAID status, current status: {task.status}")
            return
        
        # Get API key from environment
        e2b_api_key = os.environ.get("E2B_API_KEY")
        
        # Build the user request - include title and description for better routing
        user_request = task.description or f"Create a {task.domain} visualization for {task.title}"
        
        # Use the CSV data stored in the task, or fall back to sample data if not provided
        csv_data = task.csv_data
        if not csv_data and not task.file_content:
            print(f"Warning: No data found for task {task_id}, using sample data")
            csv_data = """category,value
Sales,150
Marketing,200
Engineering,300
Operations,120
Support,180"""
        
        # Update task status to PLANNING if using planning workflow
        if use_planning_workflow:
            task.status = TaskStatus.PLANNING
            db.commit()
        
        if use_planning_workflow:
            # =====================================================
            # RESEARCH & PLAN WORKFLOW (NEW AUTONOMY CORE)
            # =====================================================
            print(f"Task {task_id}: Using Research & Plan workflow")
            
            # Step 1 & 2: Extract context and generate work plan
            if use_planning_workflow:
                task.plan_status = "GENERATING"  # Update plan status
                db.commit()
                
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
                
                # Generate work plan
                plan_generator = WorkPlanGenerator()
                plan_result = plan_generator.create_work_plan(
                    user_request=user_request,
                    domain=task.domain,
                    extracted_context=extracted_context
                )
                
                if plan_result.get("success"):
                    work_plan = plan_result["plan"]
                    task.work_plan = json.dumps(work_plan)
                    task.plan_status = "APPROVED"
                    task.plan_generated_at = datetime.utcnow()
                    print(f"Task {task_id}: Work plan generated - {work_plan.get('title', 'Untitled')}")
                else:
                    task.plan_status = "REJECTED"
                    print(f"Task {task_id}: Plan generation failed - {plan_result.get('error')}")
                
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
                except:
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
                print(f"Task {task_id}: Completed successfully with Research & Plan workflow (output: {output_format})")
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
                    _escalate_task(db, task, escalation_reason, error_message)
                    print(f"Task {task_id}: ESCALATED for human review - {escalation_reason}")
                else:
                    # Mark as FAILED for non-high-value tasks that exhausted retries
                    task.status = TaskStatus.FAILED
                    task.review_feedback = error_message
                    print(f"Task {task_id}: Failed - {error_message}")
        
        else:
            # =====================================================
            # LEGACY WORKFLOW (Original TaskRouter)
            # =====================================================
            print(f"Task {task_id}: Using legacy TaskRouter workflow")
            
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
                print(f"Task {task_id} completed successfully with format: {output_format}")
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
                    _escalate_task(db, task, escalation_reason, error_message)
                    print(f"Task {task_id}: ESCALATED for human review - {escalation_reason}")
                else:
                    # Mark as FAILED
                    task.status = TaskStatus.FAILED
                    task.review_feedback = error_message
                    print(f"Task {task_id} failed: {error_message}")
        
        db.commit()
        print(f"Task {task_id} processed, final status: {task.status}")
        
    except Exception as e:
        print(f"Error processing task {task_id}: {str(e)}")
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
                    _escalate_task(db, task, escalation_reason, error_message)
                    print(f"Task {task_id}: ESCALATED for human review - {escalation_reason}")
                else:
                    # Mark as FAILED
                    task.status = TaskStatus.FAILED
                    task.review_feedback = error_message
                    db.commit()
        except Exception:
            pass
    finally:
        db.close()



# Initialize FastAPI app
app = FastAPI(title="AI Freelance Platform API")

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
    # New fields for file uploads
    file_type: str | None = None  # csv, excel, pdf
    file_content: str | None = None  # Base64-encoded file content
    filename: str | None = None  # Original filename
    # Pricing factors (Pillar 1.4: Base Rate × Complexity × Urgency)
    complexity: str = "medium"  # simple, medium, complex
    urgency: str = "standard"  # standard, rush, urgent
    # Client tracking
    client_email: str | None = None  # Client email for history tracking



class CheckoutResponse(BaseModel):
    """Model for checkout session response."""
    session_id: str
    url: str
    amount: int
    domain: str
    title: str


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    init_db()


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "AI Freelance Platform API is running"}


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
            filename=task.filename,  # Store original filename
            client_email=task.client_email,  # Store client email for history tracking
            amount_paid=amount * 100,  # Store amount in cents
            delivery_token=str(uuid.uuid4()),  # Generate secure delivery token
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
            }
        )
        
        # Update task with Stripe session ID
        new_task.stripe_session_id = checkout_session.id
        db.commit()
        
        return CheckoutResponse(
            session_id=checkout_session.id,
            url=checkout_session.url,
            amount=amount,
            domain=task.domain,
            title=task.title
        )
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")
    except Exception as e:
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
    Get task ID by Stripe checkout session ID.
    
    This endpoint is used by the Success component after Stripe redirects
    back to the application with the session_id in the URL.
    """
    task = db.query(Task).filter(Task.stripe_session_id == session_id).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found for this session")
    
    return {"task_id": task.id}


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
    db: Session = Depends(get_db)
):
    """
    Get task history for a client by email.
    
    Returns all tasks (completed, in-progress, failed) for the client.
    Includes repeat-client discount information based on completed tasks.
    
    Query parameters:
        email: Client email address
    
    Returns:
        - tasks: List of all tasks for the client
        - stats: Statistics including total tasks, completed tasks, total spent
        - discount: Current discount tier and percentage
        - next_discount: Information about next discount tier
    """
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
    db: Session = Depends(get_db)
):
    """
    Get discount information for a client.
    
    Returns the current discount tier and next tier information
    without requiring full task history.
    """
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


@app.get("/api/delivery/{task_id}/{token}")
async def get_secure_delivery(
    task_id: str,
    token: str,
    db: Session = Depends(get_db)
):
    """
    Secure delivery link endpoint.
    
    Verifies the token matches the task's delivery_token
    before returning the result.
    
    Path parameters:
        task_id: The task ID
        token: The secure delivery token
    
    Returns:
        Task result including the result_image_url
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Verify the token
    if task.delivery_token != token:
        raise HTTPException(status_code=403, detail="Invalid delivery token")
    
    # Verify the task is completed
    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=400, 
            detail=f"Task is not ready for delivery. Current status: {task.status.value}"
        )
    
    # Return the delivery data with diverse output types
    result_url = None
    if task.result_type in ["docx", "pdf"]:
        result_url = task.result_document_url
    elif task.result_type == "xlsx":
        result_url = task.result_spreadsheet_url
    else:
        # Default to image/visualization
        result_url = task.result_image_url
    
    return {
        "task_id": task.id,
        "title": task.title,
        "domain": task.domain,
        "result_type": task.result_type,
        "result_url": result_url,
        "result_image_url": task.result_image_url,
        "result_document_url": task.result_document_url,
        "result_spreadsheet_url": task.result_spreadsheet_url,
        "delivery_token": task.delivery_token,
        "delivered_at": task.updated_at.isoformat() if hasattr(task, 'updated_at') else None
    }


@app.post("/api/client/calculate-price-with-discount")
async def calculate_price_with_discount(
    domain: str,
    complexity: str = "medium",
    urgency: str = "standard",
    client_email: str | None = None,
    db: Session = Depends(get_db)
):
    """
    Calculate price with repeat-client discount applied.
    
    If client_email is provided, calculates the discount based on
    the client's completed task history.
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
    if client_email:
        completed_count = db.query(Task).filter(
            Task.client_email == client_email,
            Task.status == TaskStatus.COMPLETED
        ).count()
        
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
