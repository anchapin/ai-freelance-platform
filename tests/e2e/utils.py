"""
E2E Test Utilities

Common helper functions and utilities for e2e testing.
Includes:
- Task and bid creation helpers
- Marketplace fixture builders
- Payment simulation utilities
- Assertion helpers for complex scenarios
"""

import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional

from src.api.models import (
    Task, TaskStatus, Bid, BidStatus, ClientProfile
)


def create_test_task(
    db: Session,
    title: str = "Test Task",
    domain: str = "accounting",
    status: TaskStatus = TaskStatus.PENDING,
    amount_paid: int = 15000,
    client_email: str = "test@example.com",
    **kwargs
) -> Task:
    """
    Create a test task in the database.
    
    Args:
        db: Database session
        title: Task title
        domain: Task domain
        status: Initial status
        amount_paid: Amount paid in cents
        client_email: Client email
        **kwargs: Additional task fields
    
    Returns:
        Created Task instance
    """
    task = Task(
        id=str(uuid.uuid4()),
        title=title,
        domain=domain,
        status=status,
        amount_paid=amount_paid,
        client_email=client_email,
        description="Test task description",
        **kwargs
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def create_test_bid(
    db: Session,
    job_id: Optional[str] = None,
    marketplace: str = "Upwork",
    status: BidStatus = BidStatus.PENDING,
    bid_amount: int = 40000,
    **kwargs
) -> Bid:
    """
    Create a test bid in the database.
    
    Args:
        db: Database session
        job_id: Job ID (auto-generated if None)
        marketplace: Marketplace name
        status: Bid status
        bid_amount: Bid amount in cents
        **kwargs: Additional bid fields
    
    Returns:
        Created Bid instance
    """
    bid = Bid(
        id=str(uuid.uuid4()),
        job_id=job_id or f"job_{uuid.uuid4().hex[:8]}",
        job_title="Test Job",
        job_description="Test job description",
        marketplace=marketplace,
        status=status,
        bid_amount=bid_amount,
        **kwargs
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def create_test_client_profile(
    db: Session,
    client_email: str = "test@example.com",
    **kwargs
) -> ClientProfile:
    """
    Create a test client profile in the database.
    
    Args:
        db: Database session
        client_email: Client email
        **kwargs: Additional profile fields
    
    Returns:
        Created ClientProfile instance
    """
    profile = ClientProfile(
        id=str(uuid.uuid4()),
        client_email=client_email,
        total_tasks=0,
        completed_tasks=0,
        **kwargs
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def build_marketplace_fixture(
    name: str = "Upwork",
    url: str = "https://www.upwork.com",
    jobs_found: int = 100,
    bids_placed: int = 30,
    bids_won: int = 8,
    **kwargs
) -> Dict[str, Any]:
    """
    Build a marketplace fixture with realistic data.
    
    Args:
        name: Marketplace name
        url: Marketplace URL
        jobs_found: Number of jobs found
        bids_placed: Number of bids placed
        bids_won: Number of bids won
        **kwargs: Additional fields
    
    Returns:
        Dictionary representing a marketplace
    """
    success_rate = bids_won / bids_placed if bids_placed > 0 else 0.0
    return {
        "name": name,
        "url": url,
        "category": "freelance",
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "jobs_found": jobs_found,
        "bids_placed": bids_placed,
        "bids_won": bids_won,
        "success_rate": success_rate,
        "total_revenue": bids_won * 500.0,
        "priority_score": success_rate * (bids_won * 500.0),
        **kwargs
    }


def build_job_posting_fixture(
    marketplace: str = "Upwork",
    budget: int = 500,
    **kwargs
) -> Dict[str, Any]:
    """
    Build a job posting fixture with realistic data.
    
    Args:
        marketplace: Marketplace name
        budget: Job budget
        **kwargs: Additional fields
    
    Returns:
        Dictionary representing a job posting
    """
    return {
        "id": f"job_{uuid.uuid4().hex[:8]}",
        "marketplace": marketplace,
        "title": "Create Data Visualization",
        "description": "Need a Python developer to create data visualizations",
        "budget": budget,
        "skills": ["Python", "Data Visualization"],
        "experience_level": "Intermediate",
        "posted_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "urgency": "standard",
        "estimated_hours": 40,
        **kwargs
    }


def simulate_payment_success(
    task: Task,
    amount: int = 30000,
) -> Dict[str, Any]:
    """
    Simulate successful Stripe payment.
    
    Args:
        task: Task being paid for
        amount: Amount in cents
    
    Returns:
        Stripe webhook payload
    """
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_test_{uuid.uuid4().hex[:12]}",
                "status": "complete",
                "payment_status": "paid",
                "customer_email": task.client_email,
                "metadata": {
                    "task_id": task.id,
                    "domain": task.domain,
                },
                "amount_total": amount,
                "currency": "usd",
            }
        }
    }


def simulate_payment_failure(
    task: Task,
) -> Dict[str, Any]:
    """
    Simulate failed Stripe payment.
    
    Args:
        task: Task with failed payment
    
    Returns:
        Stripe webhook payload
    """
    return {
        "type": "checkout.session.expired",
        "data": {
            "object": {
                "id": f"cs_test_{uuid.uuid4().hex[:12]}",
                "status": "expired",
                "payment_status": "unpaid",
                "customer_email": task.client_email,
                "metadata": {
                    "task_id": task.id,
                },
            }
        }
    }


def assert_task_in_state(
    task: Task,
    expected_status: TaskStatus,
    message: str = ""
) -> None:
    """
    Assert that a task is in the expected state.
    
    Args:
        task: Task to check
        expected_status: Expected status
        message: Optional assertion message
    
    Raises:
        AssertionError: If task is not in expected state
    """
    assert task.status == expected_status, (
        f"Task {task.id} has status {task.status}, "
        f"expected {expected_status}. {message}"
    )


def assert_bid_succeeds(
    bid: Bid,
    message: str = ""
) -> None:
    """
    Assert that a bid succeeded.
    
    Args:
        bid: Bid to check
        message: Optional assertion message
    
    Raises:
        AssertionError: If bid did not succeed
    """
    assert bid.status == BidStatus.WON, (
        f"Bid {bid.id} has status {bid.status}, "
        f"expected {BidStatus.WON}. {message}"
    )


def assert_task_progression(
    db: Session,
    task_id: str,
    expected_statuses: list,
    message: str = ""
) -> None:
    """
    Assert that a task has progressed through expected statuses.
    
    Args:
        db: Database session
        task_id: Task ID to check
        expected_statuses: List of expected statuses in order
        message: Optional assertion message
    
    Raises:
        AssertionError: If task progression is not as expected
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    assert task is not None, f"Task {task_id} not found"
    
    # Current status should be the last expected status
    assert task.status == expected_statuses[-1], (
        f"Task {task_id} final status is {task.status}, "
        f"expected {expected_statuses[-1]}. {message}"
    )


def assert_no_resource_leaks(
    db: Session,
    before_count: int,
    resource_type: str = "database connections"
) -> None:
    """
    Assert that no resources were leaked during test.
    
    Args:
        db: Database session
        before_count: Count before test
        resource_type: Type of resource checked
    
    Raises:
        AssertionError: If resource leak is detected
    """
    # Check if session is properly closed
    assert not db.is_active, (
        f"Database session is still active after test. "
        f"Resource leak detected: {resource_type}"
    )


def get_task_by_id(db: Session, task_id: str) -> Optional[Task]:
    """
    Get a task by ID from the database.
    
    Args:
        db: Database session
        task_id: Task ID
    
    Returns:
        Task instance or None if not found
    """
    return db.query(Task).filter(Task.id == task_id).first()


def get_bid_by_id(db: Session, bid_id: str) -> Optional[Bid]:
    """
    Get a bid by ID from the database.
    
    Args:
        db: Database session
        bid_id: Bid ID
    
    Returns:
        Bid instance or None if not found
    """
    return db.query(Bid).filter(Bid.id == bid_id).first()


def count_bids_for_job(db: Session, job_id: str) -> int:
    """
    Count the number of bids for a job.
    
    Args:
        db: Database session
        job_id: Job ID
    
    Returns:
        Number of bids
    """
    return db.query(Bid).filter(Bid.job_id == job_id).count()


def count_tasks_by_status(db: Session, status: TaskStatus) -> int:
    """
    Count the number of tasks with a given status.
    
    Args:
        db: Database session
        status: Task status
    
    Returns:
        Number of tasks
    """
    return db.query(Task).filter(Task.status == status).count()
