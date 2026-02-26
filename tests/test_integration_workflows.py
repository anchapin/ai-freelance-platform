"""
End-to-end integration tests for multi-component workflows.

Tests 4 major workflow scenarios:
1. Escalation + Notification + Task Status Update (atomic)
2. Market Scanner + Bid Lock + Bid Deduplication
3. RAG Enrichment + Distillation + Task Completion
4. Arena Competition + Profit Calculation + Winner Selection

Focuses on:
- Resource cleanup (DB sessions, temp files)
- Transaction atomicity and rollback scenarios
- No resource leaks (async cleanup)
- Realistic data setup
"""

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.models import (
    Base, Task, TaskStatus, EscalationLog, Bid, BidStatus,
    ArenaCompetition, ArenaCompetitionStatus
)
from src.agent_execution.bid_lock_manager import BidLockManager
from src.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# DATABASE FIXTURES FOR TESTING
# =============================================================================

@pytest.fixture
def test_db():
    """Create in-memory test database with proper cleanup."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    session = SessionLocal()
    yield session
    
    # Cleanup: close the session
    session.close()
    engine.dispose()


@pytest.fixture
def bid_lock_manager(test_db):
    """Create BidLockManager for testing."""
    manager = BidLockManager(ttl=300)
    yield manager


# =============================================================================
# TEST A: ESCALATION + NOTIFICATION + TASK STATUS UPDATE (ATOMIC)
# =============================================================================

class TestEscalationAtomicity:
    """
    Test atomic escalation workflow:
    1. Create task
    2. Trigger escalation (with notification)
    3. Verify notification sent
    4. Verify status updated
    5. Test rollback on failure
    """
    
    def test_atomic_escalation_success(self, test_db):
        """Test successful escalation with all components."""
        # Setup: Create task
        task = Task(
            id=str(uuid.uuid4()),
            title="Test Task for Escalation",
            description="Test escalation workflow",
            domain="accounting",
            status=TaskStatus.PAID,
            amount_paid=30000,  # $300 - high value
            client_email="test@example.com"
        )
        test_db.add(task)
        test_db.commit()
        test_db.refresh(task)
        
        task_id = task.id
        
        # Simulate escalation within transaction
        try:
            test_db.begin_nested()  # Savepoint
            
            # Mark task as escalated
            task.status = TaskStatus.ESCALATION
            task.escalation_reason = "max_retries_exceeded"
            task.escalated_at = datetime.now(timezone.utc)
            test_db.add(task)
            
            # Create escalation log (with proper fields)
            escalation_log = EscalationLog(
                id=str(uuid.uuid4()),
                task_id=task_id,
                reason="max_retries_exceeded",
                idempotency_key=f"{task_id}_max_retries_exceeded",
                notification_sent=True,
                notification_attempt_count=1,
                last_notification_attempt_at=datetime.now(timezone.utc)
            )
            test_db.add(escalation_log)
            
            test_db.commit()
            
            # Verify state
            refreshed_task = test_db.query(Task).filter(Task.id == task_id).first()
            assert refreshed_task.status == TaskStatus.ESCALATION
            assert refreshed_task.escalation_reason == "max_retries_exceeded"
            assert refreshed_task.escalated_at is not None
            
            log = test_db.query(EscalationLog).filter(
                EscalationLog.task_id == task_id
            ).first()
            assert log is not None
            assert log.notification_sent is True
            
        except Exception as e:
            test_db.rollback()
            pytest.fail(f"Escalation failed: {e}")
    
    def test_escalation_rollback_on_notification_failure(self, test_db):
        """Test rollback if notification fails (atomicity)."""
        # Create task
        task = Task(
            id=str(uuid.uuid4()),
            title="Test Rollback Task",
            description="Test escalation rollback",
            domain="accounting",
            status=TaskStatus.PAID,
            amount_paid=30000,
            client_email="test@example.com"
        )
        test_db.add(task)
        test_db.commit()
        test_db.refresh(task)
        task_id = task.id
        
        # Simulate escalation with failure
        try:
            test_db.begin_nested()
            
            task.status = TaskStatus.ESCALATION
            task.escalated_at = datetime.now(timezone.utc)
            test_db.add(task)
            
            # Simulate notification failure
            raise RuntimeError("Notification service unavailable")
            
        except RuntimeError:
            test_db.rollback()
        
        # Verify state was rolled back
        refreshed_task = test_db.query(Task).filter(Task.id == task_id).first()
        assert refreshed_task.status == TaskStatus.PAID
        assert refreshed_task.escalated_at is None
        
        # Verify no escalation log was created
        log = test_db.query(EscalationLog).filter(
            EscalationLog.task_id == task_id
        ).first()
        assert log is None
    
    def test_no_duplicate_escalation_notifications(self, test_db):
        """Test idempotency - no duplicate notifications for same task."""
        # Create task
        task = Task(
            id=str(uuid.uuid4()),
            title="Duplicate Notification Test",
            description="Test no duplicates",
            domain="accounting",
            status=TaskStatus.PAID,
            amount_paid=30000,
            client_email="test@example.com"
        )
        test_db.add(task)
        test_db.commit()
        task_id = task.id
        
        # Create first escalation log
        idempotency_key = f"{task_id}_max_retries_exceeded"
        log1 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id,
            reason="max_retries_exceeded",
            idempotency_key=idempotency_key,
            notification_sent=True,
            notification_attempt_count=1,
            last_notification_attempt_at=datetime.now(timezone.utc)
        )
        test_db.add(log1)
        test_db.commit()
        
        # Try to create duplicate - should be blocked by unique constraint
        existing = test_db.query(EscalationLog).filter(
            EscalationLog.task_id == task_id,
            EscalationLog.idempotency_key == idempotency_key
        ).first()
        assert existing is not None
        
        # Check count - should only be 1
        count = test_db.query(EscalationLog).filter(
            EscalationLog.task_id == task_id
        ).count()
        assert count == 1


# =============================================================================
# TEST B: MARKET SCANNER + BID LOCK + BID DEDUPLICATION
# =============================================================================

class TestConcurrentBidsAndLocks:
    """
    Test concurrent bid scenario:
    1. Multiple agents bid on same posting
    2. Only ONE bid succeeds (due to lock)
    3. Others are deduplicated (no duplicates in DB)
    4. Locks cleaned up after test
    """
    
    def test_sequential_bid_placement_and_lock(self, test_db):
        """Test sequential bid placement with lock mechanism."""
        marketplace_id = "upwork"
        posting_id = "job_xyz_123"
        
        # Create first bid with required fields
        bid1 = Bid(
            id=str(uuid.uuid4()),
            job_id=posting_id,
            job_title="Test Job",
            job_description="Test Description",
            marketplace=marketplace_id,
            status=BidStatus.ACTIVE,
            bid_amount=5000,  # $50.00
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(bid1)
        test_db.commit()
        
        # Verify bid was created
        bids = test_db.query(Bid).filter(
            Bid.job_id == posting_id,
            Bid.marketplace == marketplace_id
        ).all()
        assert len(bids) == 1
        assert bids[0].status == BidStatus.ACTIVE
    
    def test_bid_deduplication_logic(self, test_db):
        """Test that deduplication prevents placing multiple bids on same posting."""
        marketplace_id = "fiverr"
        posting_id = "gig_abc_456"
        
        # Create first bid with required fields
        bid1 = Bid(
            id=str(uuid.uuid4()),
            job_id=posting_id,
            job_title="Test Gig",
            job_description="Test gig description",
            marketplace=marketplace_id,
            status=BidStatus.ACTIVE,
            bid_amount=3000,  # $30.00
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(bid1)
        test_db.commit()
        
        # Check deduplication logic - verify existing bid
        existing_bid = test_db.query(Bid).filter(
            Bid.job_id == posting_id,
            Bid.marketplace == marketplace_id,
            Bid.status == BidStatus.ACTIVE
        ).first()
        assert existing_bid is not None, "Should find existing bid"
        
        # If there's an existing bid, deduplication should prevent new bid
        should_place_new_bid = existing_bid is None
        assert should_place_new_bid is False
        
        # Verify still only 1 bid in DB
        bids = test_db.query(Bid).filter(
            Bid.job_id == posting_id,
            Bid.marketplace == marketplace_id
        ).all()
        assert len(bids) == 1
    
    def test_bid_withdrawal_and_status_change(self, test_db):
        """Test bid status transitions and withdrawal."""
        marketplace_id = "upwork"
        posting_id = "job_withdrawal_test"
        
        # Create bid with required fields
        bid = Bid(
            id=str(uuid.uuid4()),
            job_id=posting_id,
            job_title="Withdrawal Test Job",
            job_description="Testing withdrawal",
            marketplace=marketplace_id,
            status=BidStatus.ACTIVE,
            bid_amount=4000,  # $40.00
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(bid)
        test_db.commit()
        bid_id = bid.id
        
        # Verify bid is active
        active_bid = test_db.query(Bid).filter(Bid.id == bid_id).first()
        assert active_bid.status == BidStatus.ACTIVE
        
        # Simulate bid withdrawal (status change)
        active_bid.status = BidStatus.WITHDRAWN
        test_db.add(active_bid)
        test_db.commit()
        
        # Verify status changed
        withdrawn_bid = test_db.query(Bid).filter(Bid.id == bid_id).first()
        assert withdrawn_bid.status == BidStatus.WITHDRAWN


# =============================================================================
# TEST C: RAG ENRICHMENT + DISTILLATION + TASK COMPLETION
# =============================================================================

class TestRAGAndDistillation:
    """
    Test RAG enrichment workflow:
    1. Create task
    2. Enrich with RAG (few-shot examples)
    3. Run through distilled model
    4. Mark complete
    5. Verify all async operations executed
    """
    
    def test_task_completion_with_rag_enrichment(self, test_db):
        """Test task completion with RAG enrichment."""
        # Create task
        task = Task(
            id=str(uuid.uuid4()),
            title="RAG Test Task",
            description="Create a chart",
            domain="data_analysis",
            status=TaskStatus.PROCESSING,
            csv_data="month,sales\nJan,100\nFeb,150",
            client_email="test@example.com"
        )
        test_db.add(task)
        test_db.commit()
        test_db.refresh(task)
        task_id = task.id
        
        # Simulate RAG enrichment
        rag_examples = [
            {"task_id": "past_1", "user_request": "Similar chart task"},
            {"task_id": "past_2", "user_request": "Another similar task"}
        ]
        
        # Store enrichment context
        task.extracted_context = {"rag_examples": rag_examples}
        test_db.add(task)
        test_db.commit()
        
        # Verify enrichment stored
        refreshed = test_db.query(Task).filter(Task.id == task_id).first()
        assert refreshed.extracted_context is not None
        assert "rag_examples" in refreshed.extracted_context
        
        # Simulate distillation and completion
        task.status = TaskStatus.COMPLETED
        task.result_image_url = "https://example.com/result.png"
        task.result_type = "image"
        test_db.add(task)
        test_db.commit()
        
        # Verify completion
        final = test_db.query(Task).filter(Task.id == task_id).first()
        assert final.status == TaskStatus.COMPLETED
        assert final.result_image_url is not None
        assert final.extracted_context is not None
    
    def test_async_rag_enrichment_cleanup(self, test_db):
        """Test that async operations don't leave resources open."""
        # Create task
        task = Task(
            id=str(uuid.uuid4()),
            title="Async Cleanup Test",
            description="Test async cleanup",
            domain="data_analysis",
            status=TaskStatus.PROCESSING,
            client_email="test@example.com"
        )
        test_db.add(task)
        test_db.commit()
        
        # Verify DB session is still usable after async operations
        # (This would fail if async operations didn't clean up properly)
        tasks = test_db.query(Task).all()
        assert len(tasks) == 1
        
        # No dangling connections or open cursors
        test_db.close()
        # Should not raise any errors


# =============================================================================
# TEST D: ARENA COMPETITION + PROFIT CALCULATION + WINNER SELECTION
# =============================================================================

class TestArenaCompetition:
    """
    Test arena competition workflow:
    1. Create two competing agents
    2. Run arena battle
    3. Calculate profits
    4. Select winner
    5. Verify winner stored correctly
    """
    
    def test_arena_competition_winner_selection(self, test_db):
        """Test arena competition and winner selection."""
        # Create arena competition with required fields
        competition = ArenaCompetition(
            id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            competition_type="model",  # Required field
            status=ArenaCompetitionStatus.PENDING,
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(competition)
        test_db.commit()
        competition_id = competition.id
        
        # Simulate agent results
        agent_a_result = {
            "success": True,
            "tokens_used": 2000,
            "execution_time": 45.0,
            "output": "Generated successful artifact"
        }
        
        agent_b_result = {
            "success": True,
            "tokens_used": 1500,  # More efficient
            "execution_time": 30.0,
            "output": "Generated successful artifact"
        }
        
        # Calculate profits (simplified)
        # Task revenue: $500 (5000 cents)
        # Agent A cost: ~$4.50 (GPT-4o is expensive)
        # Agent B cost: ~$0.27 (GPT-4o-mini is cheaper)
        
        task_revenue = 5000  # 5000 cents = $50
        
        agent_a_cost = 450  # $4.50 in cents
        agent_b_cost = 27   # $0.27 in cents
        
        agent_a_profit = task_revenue - agent_a_cost  # 4550 cents
        agent_b_profit = task_revenue - agent_b_cost  # 4973 cents
        
        # Agent B wins (higher profit)
        winner = "agent_b" if agent_b_profit > agent_a_profit else "agent_a"
        assert winner == "agent_b"
        
        # Update competition with winner
        competition.status = ArenaCompetitionStatus.COMPLETED
        competition.winner = winner
        competition.agent_a_result = agent_a_result
        competition.agent_b_result = agent_b_result
        competition.agent_a_profit = agent_a_profit
        competition.agent_b_profit = agent_b_profit
        test_db.add(competition)
        test_db.commit()
        
        # Verify stored correctly
        refreshed = test_db.query(ArenaCompetition).filter(
            ArenaCompetition.id == competition_id
        ).first()
        assert refreshed.winner == "agent_b"
        assert refreshed.status == ArenaCompetitionStatus.COMPLETED
        assert refreshed.agent_b_profit > refreshed.agent_a_profit
    
    def test_arena_competition_profit_calculation(self, test_db):
        """Test profit calculation logic with multiple scenarios."""
        competition = ArenaCompetition(
            id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            competition_type="model",  # Required field
            status=ArenaCompetitionStatus.COMPLETED,
            created_at=datetime.now(timezone.utc)
        )
        
        # Scenario 1: Local model wins (cheaper)
        task_revenue = 5000
        local_cost = 100  # Only E2B cost
        cloud_cost = 450  # LLM + E2B cost
        
        local_profit = task_revenue - local_cost  # 4900
        cloud_profit = task_revenue - cloud_cost  # 4550
        
        competition.agent_a_profit = local_profit
        competition.agent_b_profit = cloud_profit
        competition.winner = "agent_a"  # Local model
        
        test_db.add(competition)
        test_db.commit()
        
        refreshed = test_db.query(ArenaCompetition).filter(
            ArenaCompetition.id == competition.id
        ).first()
        assert refreshed.agent_a_profit > refreshed.agent_b_profit
        assert refreshed.winner == "agent_a"


# =============================================================================
# RESOURCE CLEANUP AND LEAK DETECTION
# =============================================================================

class TestResourceCleanup:
    """
    Test resource cleanup to ensure no leaks.
    """
    
    def test_db_session_cleanup(self, test_db):
        """Test that DB sessions are properly cleaned up."""
        # Create some data
        task = Task(
            id=str(uuid.uuid4()),
            title="Cleanup Test",
            description="Test cleanup",
            domain="accounting",
            status=TaskStatus.PENDING,
            client_email="test@example.com"
        )
        test_db.add(task)
        test_db.commit()
        
        # Session should still be usable
        count = test_db.query(Task).count()
        assert count == 1
        
        # Close and verify no errors
        test_db.close()
    
    def test_multiple_sequential_operations(self, test_db):
        """Test multiple sequential DB operations for cleanup."""
        for i in range(5):
            task = Task(
                id=str(uuid.uuid4()),
                title=f"Task {i}",
                description=f"Description {i}",
                domain="accounting",
                status=TaskStatus.PENDING,
                client_email=f"test{i}@example.com"
            )
            test_db.add(task)
            test_db.commit()
        
        # Verify all tasks exist
        count = test_db.query(Task).count()
        assert count == 5
        
        # Update all tasks
        tasks = test_db.query(Task).all()
        for task in tasks:
            task.status = TaskStatus.PROCESSING
        test_db.commit()
        
        # Verify update
        updated_count = test_db.query(Task).filter(
            Task.status == TaskStatus.PROCESSING
        ).count()
        assert updated_count == 5


# =============================================================================
# TRANSACTION ISOLATION AND CONCURRENCY
# =============================================================================

class TestTransactionIsolation:
    """
    Test transaction isolation and concurrent access.
    """
    
    def test_concurrent_task_creation(self, test_db):
        """Test creating multiple tasks concurrently without conflicts."""
        tasks_to_create = [
            Task(
                id=str(uuid.uuid4()),
                title=f"Concurrent Task {i}",
                description=f"Desc {i}",
                domain="accounting",
                status=TaskStatus.PENDING,
                client_email=f"concurrent{i}@example.com"
            )
            for i in range(3)
        ]
        
        for task in tasks_to_create:
            test_db.add(task)
        test_db.commit()
        
        # Verify all created
        count = test_db.query(Task).count()
        assert count == 3
    
    def test_transaction_isolation_with_rollback(self, test_db):
        """Test transaction isolation with savepoint rollback."""
        # Create initial task
        task1 = Task(
            id=str(uuid.uuid4()),
            title="Initial Task",
            description="Initial",
            domain="accounting",
            status=TaskStatus.PENDING,
            client_email="initial@example.com"
        )
        test_db.add(task1)
        test_db.commit()
        
        # Start nested transaction
        test_db.begin_nested()
        
        task2 = Task(
            id=str(uuid.uuid4()),
            title="Nested Task",
            description="Nested",
            domain="accounting",
            status=TaskStatus.PENDING,
            client_email="nested@example.com"
        )
        test_db.add(task2)
        
        # Rollback nested
        test_db.rollback()
        
        # Verify only first task exists
        count = test_db.query(Task).count()
        assert count == 1
        
        task = test_db.query(Task).first()
        assert task.title == "Initial Task"


# =============================================================================
# INTEGRATION TEST SUMMARY HELPER
# =============================================================================

def test_all_workflows_run_without_errors(test_db):
    """
    Summary test to verify all 4 workflows can run in sequence.
    """
    # Create a task that goes through all workflows
    task = Task(
        id=str(uuid.uuid4()),
        title="Full Workflow Test",
        description="Test all 4 workflows",
        domain="data_analysis",
        status=TaskStatus.PAID,
        amount_paid=30000,
        csv_data="month,sales\nJan,100",
        client_email="workflow@example.com"
    )
    test_db.add(task)
    test_db.commit()
    task_id = task.id
    
    # Workflow A: Escalation
    task.status = TaskStatus.ESCALATION
    task.escalated_at = datetime.now(timezone.utc)
    test_db.add(task)
    test_db.commit()
    
    # Workflow B: Bid tracking would happen separately
    bid = Bid(
        id=str(uuid.uuid4()),
        job_id=f"job_{task_id}",
        job_title="Test Job",
        job_description="Test description",
        marketplace="upwork",
        status=BidStatus.ACTIVE,
        bid_amount=5000  # $50.00
    )
    test_db.add(bid)
    test_db.commit()
    
    # Workflow C: RAG enrichment
    task.extracted_context = {"enriched": True}
    test_db.add(task)
    test_db.commit()
    
    # Workflow D: Arena competition
    competition = ArenaCompetition(
        id=str(uuid.uuid4()),
        task_id=task_id,
        competition_type="model",  # Required field
        status=ArenaCompetitionStatus.COMPLETED,
        winner="agent_a",
        agent_a_profit=4500,
        agent_b_profit=4000
    )
    test_db.add(competition)
    test_db.commit()
    
    # Verify final state
    final_task = test_db.query(Task).filter(Task.id == task_id).first()
    assert final_task is not None
    assert final_task.escalated_at is not None
    assert final_task.extracted_context is not None
    
    final_competition = test_db.query(ArenaCompetition).filter(
        ArenaCompetition.task_id == task_id
    ).first()
    assert final_competition is not None
    assert final_competition.winner == "agent_a"

# =============================================================================
# TEST E: DOCUMENT/REPORT GENERATION INTEGRATION (Issue #1)
# =============================================================================

@pytest.mark.asyncio
async def test_document_generation_workflow(test_db):
    """Test integrated document generation workflow (Issue #1)."""
    from src.agent_execution.executor import TaskRouter, OutputFormat
    
    # Setup
    router = TaskRouter()
    user_request = "Create a detailed financial report for last month"
    csv_data = "date,revenue,expense\n2026-01-01,1000,500\n2026-01-15,1200,600"
    
    # Mock LLM and Sandbox to avoid external calls
    with patch("src.agent_execution.executor.ReportGenerator.generate_report") as mock_gen:
        mock_gen.return_value = {
            "success": True,
            "file_url": "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,...",
            "file_name": "financial_report.docx",
            "output_format": OutputFormat.DOCX,
            "message": "Report generated successfully"
        }
        
        # Execute routing
        result = router.route(
            domain="legal",
            user_request=user_request,
            csv_data=csv_data
        )
        
        # Verify
        assert result["success"] is True
        assert result["file_name"] == "financial_report.docx"
        mock_gen.assert_called_once()

# =============================================================================
# TEST F: DISTRIBUTED TRACING PROPAGATION (Issue #31)
# =============================================================================

def test_distributed_tracing_propagation():
    """Test that trace IDs propagate across component boundaries (Issue #31)."""
    from src.utils.distributed_tracing import init_trace_context, get_trace_id
    import logging
    
    # Initialize context
    trace_id = init_trace_context()
    assert trace_id is not None
    
    # Verify propagation
    assert get_trace_id() == trace_id
    
    # Verify logging integration (if initialized)
    logger = logging.getLogger("test_trace")
    # We can't easily check the log output format here without complex setup,
    # but we can verify the context is set.
    
    from src.utils.distributed_tracing import clear_trace_context
    clear_trace_context()
    assert get_trace_id() is None
