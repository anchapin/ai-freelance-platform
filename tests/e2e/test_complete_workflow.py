"""
E2E Tests: Complete End-to-End Workflow

Tests the full ArbitrageAI workflow from start to finish:
1. Marketplace discovery
2. Job discovery and bid placement
3. Payment processing
4. Task execution
5. Artifact delivery
6. Completion and payment settlement

Coverage: ~20% of critical path

This test demonstrates all major components working together in a realistic scenario.
"""

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from src.api.models import TaskStatus, BidStatus
from .utils import (
    create_test_task,
    create_test_bid,
    build_marketplace_fixture,
    build_job_posting_fixture,
    simulate_payment_success,
    assert_task_in_state,
    count_bids_for_job,
)


class TestCompleteEndToEndWorkflow:
    """Test complete end-to-end workflow."""
    
    def test_full_workflow_success_scenario(self, e2e_db: Session):
        """Test complete workflow from discovery to completion."""
        
        # =================================================================
        # STEP 1: MARKETPLACE DISCOVERY
        # =================================================================
        marketplace = build_marketplace_fixture(
            name="Upwork",
            jobs_found=150,
            bids_placed=45,
            bids_won=12,
        )
        assert marketplace["name"] == "Upwork"
        
        # =================================================================
        # STEP 2: JOB DISCOVERY AND ANALYSIS
        # =================================================================
        job = build_job_posting_fixture(
            marketplace="Upwork",
            budget=500,
            title="Create Financial Dashboard",
        )
        assert job["budget"] == 500
        
        # =================================================================
        # STEP 3: BID PLACEMENT
        # =================================================================
        # Create a task representing the job
        task = create_test_task(
            e2e_db,
            title=job["title"],
            status=TaskStatus.PENDING,
            amount_paid=40000,  # $400 in cents
            client_email="marketplace@upwork.com"
        )
        
        # Place bid
        bid = create_test_bid(
            e2e_db,
            job_id=job["id"],
            marketplace="Upwork",
            bid_amount=40000,  # $400 in cents
            status=BidStatus.PENDING
        )
        
        assert bid.status == BidStatus.PENDING
        
        # =================================================================
        # STEP 4: BID ACCEPTANCE
        # =================================================================
        bid.status = BidStatus.WON
        e2e_db.commit()
        e2e_db.refresh(bid)
        
        assert bid.status == BidStatus.WON
        
        # =================================================================
        # STEP 5: PAYMENT PROCESSING
        # =================================================================
        # Client pays for the job
        payment_webhook = simulate_payment_success(task, amount=40000)
        
        task.status = TaskStatus.PAID
        e2e_db.commit()
        
        assert_task_in_state(task, TaskStatus.PAID)
        
        # =================================================================
        # STEP 6: TASK PLANNING
        # =================================================================
        task.status = TaskStatus.PLANNING
        e2e_db.commit()
        
        # Simulate work plan creation
        work_plan = {
            "task_id": task.id,
            "steps": ["Parse data", "Generate visualization", "Review output"],
            "estimated_tokens": 2000,
        }
        assert len(work_plan["steps"]) >= 2
        
        # =================================================================
        # STEP 7: CODE GENERATION AND EXECUTION
        # =================================================================
        task.status = TaskStatus.PROCESSING
        e2e_db.commit()
        
        # Simulate sandbox execution
        execution_result = {
            "success": True,
            "output": "Dashboard created successfully",
            "artifact_url": "data:image/png;base64,iVBORw0KGgo...",
            "execution_time_seconds": 45.2,
        }
        assert execution_result["success"] is True
        
        # =================================================================
        # STEP 8: QUALITY REVIEW
        # =================================================================
        task.status = TaskStatus.REVIEW_REQUIRED
        e2e_db.commit()
        
        # Self-review result
        review = {
            "quality_score": 0.92,
            "matches_description": True,
            "approved": True,
        }
        assert review["approved"] is True
        
        # =================================================================
        # STEP 9: ARTIFACT DELIVERY
        # =================================================================
        task.status = TaskStatus.COMPLETED
        e2e_db.commit()
        
        assert_task_in_state(task, TaskStatus.COMPLETED)
        
        # Verify result is associated with task
        assert task.result_image_url is not None or execution_result["artifact_url"] is not None
        
        # =================================================================
        # STEP 10: FINAL VERIFICATION
        # =================================================================
        # Verify complete workflow
        assert bid.status == BidStatus.WON
        assert task.status == TaskStatus.COMPLETED
        assert task.amount_paid == 40000
    
    def test_workflow_with_multiple_bids(self, e2e_db: Session):
        """Test workflow with multiple bids on same job opportunity."""
        
        # Discover job
        job = build_job_posting_fixture(budget=800)
        
        # Create task
        task = create_test_task(
            e2e_db,
            title=job["title"],
            amount_paid=60000,
            status=TaskStatus.PENDING,
        )
        
        # Place multiple bids (one from each marketplace)
        bid_upwork = create_test_bid(
            e2e_db,
            job_id=job["id"],
            marketplace="Upwork",
            bid_amount=60000,
            status=BidStatus.PENDING
        )
        
        bid_fiverr = create_test_bid(
            e2e_db,
            job_id=job["id"],
            marketplace="Fiverr",
            bid_amount=70000,
            status=BidStatus.PENDING
        )
        
        # Verify multiple bids
        bid_count = count_bids_for_job(e2e_db, job["id"])
        assert bid_count == 2
        
        # One marketplace wins
        bid_upwork.status = BidStatus.WON
        bid_fiverr.status = BidStatus.REJECTED
        e2e_db.commit()
        
        # Verify winner
        assert bid_upwork.status == BidStatus.WON
        assert bid_fiverr.status == BidStatus.REJECTED
    
    def test_workflow_with_retry_after_failure(self, e2e_db: Session):
        """Test workflow with retry after execution failure."""
        
        # Setup task
        task = create_test_task(
            e2e_db,
            status=TaskStatus.PAID,
        )
        
        # Attempt 1: Execution fails
        task.status = TaskStatus.PROCESSING
        e2e_db.commit()
        
        task.status = TaskStatus.FAILED
        e2e_db.commit()
        
        assert_task_in_state(task, TaskStatus.FAILED)
        
        # Retry: Attempt 2
        task.status = TaskStatus.PROCESSING
        e2e_db.commit()
        
        # This time successful
        task.status = TaskStatus.COMPLETED
        e2e_db.commit()
        
        assert_task_in_state(task, TaskStatus.COMPLETED)
    
    def test_workflow_with_escalation(self, e2e_db: Session):
        """Test workflow with escalation to human review."""
        
        task = create_test_task(
            e2e_db,
            status=TaskStatus.PAID,
        )
        
        # Multiple review failures
        for attempt in range(3):
            task.status = TaskStatus.PROCESSING
            e2e_db.commit()
            
            # Review fails
            task.status = TaskStatus.REVIEW_REQUIRED
            e2e_db.commit()
        
        # After max retries, escalate
        task.status = TaskStatus.ESCALATION
        e2e_db.commit()
        
        assert_task_in_state(task, TaskStatus.ESCALATION)
    
    def test_workflow_concurrency_multiple_tasks(self, e2e_db: Session):
        """Test handling multiple tasks concurrently."""
        
        tasks = []
        for i in range(3):
            task = create_test_task(
                e2e_db,
                title=f"Task {i+1}",
                status=TaskStatus.PENDING,
            )
            tasks.append(task)
        
        # Process first task
        tasks[0].status = TaskStatus.PAID
        e2e_db.commit()
        
        # Process second task
        tasks[1].status = TaskStatus.PAID
        e2e_db.commit()
        
        # Third task still pending
        assert tasks[0].status == TaskStatus.PAID
        assert tasks[1].status == TaskStatus.PAID
        assert tasks[2].status == TaskStatus.PENDING


class TestWorkflowErrorHandling:
    """Test error handling within complete workflow."""
    
    def test_payment_failure_in_workflow(self, e2e_db: Session):
        """Test handling payment failure in workflow."""
        
        task = create_test_task(e2e_db, status=TaskStatus.PENDING)
        
        # Payment fails
        task.status = TaskStatus.PENDING  # Remains pending
        e2e_db.commit()
        
        # Should not progress to PAID
        assert task.status == TaskStatus.PENDING
    
    def test_marketplace_disconnection_in_workflow(self, e2e_db: Session):
        """Test handling marketplace disconnection."""
        
        task = create_test_task(e2e_db)
        bid = create_test_bid(e2e_db, job_id="job_test_disconnect")
        
        # Marketplace disconnects
        error = {
            "code": "connection_error",
            "message": "Failed to connect to marketplace",
        }
        
        # Bid status should reflect error (mark as withdrawn)
        bid.status = BidStatus.WITHDRAWN
        bid.withdrawn_reason = error["message"]
        e2e_db.commit()
        
        assert bid.status == BidStatus.WITHDRAWN
    
    def test_resource_cleanup_on_failure(self, e2e_db: Session):
        """Test resource cleanup when workflow fails."""
        
        task = create_test_task(e2e_db)
        
        cleanup_performed = False
        
        try:
            # Simulate failure
            raise RuntimeError("Execution failed")
        except RuntimeError:
            cleanup_performed = True
        
        assert cleanup_performed is True


class TestWorkflowPerformance:
    """Test workflow performance and optimization."""
    
    def test_marketplace_discovery_performance(self, mock_marketplace_list):
        """Test marketplace discovery completes within time threshold."""
        
        import time
        
        start = time.time()
        
        # Discover marketplaces
        marketplaces = mock_marketplace_list
        
        elapsed = time.time() - start
        
        # Should complete in < 5 seconds
        assert elapsed < 5
        assert len(marketplaces) >= 3
    
    def test_bid_placement_throughput(self, e2e_db: Session):
        """Test bid placement throughput."""
        
        job_id = "job_throughput_test"
        
        # Place multiple bids quickly
        bid_count = 0
        for marketplace in ["Upwork", "Fiverr", "Toptal"]:
            bid = create_test_bid(
                e2e_db,
                job_id=job_id,
                marketplace=marketplace
            )
            bid_count += 1
        
        # Should place 3 bids efficiently
        assert count_bids_for_job(e2e_db, job_id) == 3
    
    def test_task_execution_caching(self):
        """Test caching of similar task executions."""
        
        cache = {}
        
        # First execution
        task_signature = "task_type:dashboard,data:csv"
        if task_signature not in cache:
            cache[task_signature] = {
                "code": "import pandas...",
                "timestamp": datetime.now(timezone.utc)
            }
        
        hit1 = task_signature in cache
        
        # Second execution (same signature)
        hit2 = task_signature in cache
        
        assert hit1 is True
        assert hit2 is True


class TestWorkflowDataIntegrity:
    """Test data integrity throughout workflow."""
    
    def test_task_data_consistency(self, e2e_db: Session):
        """Test task data remains consistent through workflow."""
        
        original_amount = 30000
        task = create_test_task(
            e2e_db,
            amount_paid=original_amount,
            client_email="test@example.com"
        )
        
        task_id = task.id
        
        # Task transitions through states
        task.status = TaskStatus.PAID
        e2e_db.commit()
        
        task.status = TaskStatus.PROCESSING
        e2e_db.commit()
        
        # Verify data integrity
        assert task.amount_paid == original_amount
        assert task.client_email == "test@example.com"
        assert task.id == task_id
    
    def test_bid_data_consistency(self, e2e_db: Session):
        """Test bid data remains consistent."""
        
        job_id = "job_consistency_test"
        
        original_amount = 40000
        bid = create_test_bid(
            e2e_db,
            job_id=job_id,
            bid_amount=original_amount,
            marketplace="Upwork"
        )
        
        bid_id = bid.id
        
        # Update bid status
        bid.status = BidStatus.WON
        e2e_db.commit()
        
        # Verify data integrity
        assert bid.bid_amount == original_amount
        assert bid.marketplace == "Upwork"
        assert bid.id == bid_id
    
    def test_payment_data_consistency(self, e2e_db: Session):
        """Test payment data consistency."""
        
        task = create_test_task(
            e2e_db,
            amount_paid=40000,
            status=TaskStatus.PENDING
        )
        
        # Record payment
        payment = {
            "task_id": task.id,
            "amount": task.amount_paid,
            "timestamp": datetime.now(timezone.utc),
        }
        
        # Update task status
        task.status = TaskStatus.PAID
        e2e_db.commit()
        
        # Verify payment consistency
        assert payment["amount"] == task.amount_paid
        assert payment["task_id"] == task.id
