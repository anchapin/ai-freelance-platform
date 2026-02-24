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

from .database import get_db, init_db
from .models import Task, TaskStatus
from ..agent_execution.executor import execute_data_visualization


def process_task_async(task_id: str):
    """
    Process a task asynchronously after payment is confirmed.
    
    This function is called as a background task when a task is marked as PAID.
    It retrieves the task from the database, executes the data visualization,
    and updates the database with the result.
    
    Args:
        task_id: The ID of the task to process
    """
    # Create a new database session for this background task
    from .database import SessionLocal
    
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
        
        # Use the CSV data stored in the task, or fall back to sample data if not provided
        csv_data = task.csv_data
        if not csv_data:
            print(f"Warning: No CSV data found for task {task_id}, using sample data")
            csv_data = """category,value
Sales,150
Marketing,200
Engineering,300
Operations,120
Support,180"""
        
        # Execute the data visualization with the user's CSV data
        result = execute_data_visualization(
            csv_data=csv_data,
            user_request=f"Create a {task.domain} visualization for {task.title}"
        )
        
        # Update the task with the result
        if result.get("success"):
            task.result_image_url = result.get("image_url", "")
            task.status = TaskStatus.COMPLETED
        else:
            task.status = TaskStatus.FAILED
        
        db.commit()
        print(f"Task {task_id} processed successfully, status: {task.status}")
        
    except Exception as e:
        print(f"Error processing task {task_id}: {str(e)}")
        # Mark as failed on error
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = TaskStatus.FAILED
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

# Domain pricing configuration
DOMAIN_PRICES = {
    "accounting": 150,
    "legal": 250,
    "data_analysis": 200,
}

# Base URL for success/cancel pages (configure in production)
BASE_URL = os.environ.get("BASE_URL", "http://localhost:5173")


class TaskSubmission(BaseModel):
    """Model for task submission data."""
    domain: str
    title: str
    description: str
    csvContent: str | None = None


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
    
    Calculates price based on domain and creates a real Stripe checkout session.
    Stores the task in the database with PENDING status.
    """
    # Validate domain
    if task.domain not in DOMAIN_PRICES:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid domain. Must be one of: {', '.join(DOMAIN_PRICES.keys())}"
        )
    
    # Get price for domain
    amount = DOMAIN_PRICES[task.domain]
    
    try:
        # Create a task in the database with PENDING status
        new_task = Task(
            id=str(uuid.uuid4()),
            title=task.title,
            description=task.description,
            domain=task.domain,
            status=TaskStatus.PENDING,
            stripe_session_id=None,  # Will be updated after Stripe session is created
            csv_data=task.csvContent  # Store the CSV content if provided
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
    """Get available domains and their prices."""
    return {
        "domains": [
            {"value": domain, "label": domain.replace("_", " ").title(), "price": price}
            for domain, price in DOMAIN_PRICES.items()
        ]
    }


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
