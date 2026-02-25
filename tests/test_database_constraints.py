"""
Test Suite: Database Unique Constraints (Issue #33)

Tests for unique constraints added to Bid and EscalationLog models.
Verifies that duplicate entries are rejected at the database level,
preventing data integrity violations and race conditions.

Test Coverage:
1. Bid model constraints
   - Unique constraint on (job_id, marketplace)
   - Duplicate bids raise IntegrityError
   - Single fields can be duplicated (only combination is unique)

2. EscalationLog model constraints
   - Unique constraint on (task_id, idempotency_key)
   - Duplicate escalations raise IntegrityError
   - Different tasks with same key are allowed
   - Same task with different keys are allowed
"""

import pytest
import uuid
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError

from src.api.models import Base, Bid, BidStatus, EscalationLog


@pytest.fixture
def test_db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


class TestBidUniqueConstraints:
    """Tests for Bid model unique constraints."""

    def test_bid_unique_constraint_on_job_id_marketplace(self, test_db):
        """
        Test that (job_id, marketplace) combination is unique.
        Inserting duplicate (job_id, marketplace) should raise IntegrityError.
        """
        # Create first bid
        bid1 = Bid(
            id=str(uuid.uuid4()),
            job_title="Python Developer",
            job_description="Need Python expert",
            job_id="job_123",
            marketplace="upwork",
            bid_amount=5000,
            status=BidStatus.PENDING,
            is_suitable=True,
        )
        test_db.add(bid1)
        test_db.commit()

        # Try to create duplicate (job_id, marketplace) with different amount
        bid2 = Bid(
            id=str(uuid.uuid4()),
            job_title="Python Developer (Updated)",
            job_description="Need Python expert (Updated)",
            job_id="job_123",  # Same job_id
            marketplace="upwork",  # Same marketplace
            bid_amount=6000,  # Different amount
            status=BidStatus.PENDING,
            is_suitable=True,
        )
        test_db.add(bid2)

        # Should raise IntegrityError
        with pytest.raises(IntegrityError):
            test_db.commit()

    def test_bid_allows_same_job_different_marketplace(self, test_db):
        """
        Test that same job_id can be bid on in different marketplaces.
        """
        # Bid on same job in different marketplace
        bid1 = Bid(
            id=str(uuid.uuid4()),
            job_title="Python Developer",
            job_description="Need Python expert",
            job_id="job_123",
            marketplace="upwork",
            bid_amount=5000,
            status=BidStatus.PENDING,
            is_suitable=True,
        )
        test_db.add(bid1)
        test_db.commit()

        # Same job_id, different marketplace (should be allowed)
        bid2 = Bid(
            id=str(uuid.uuid4()),
            job_title="Python Developer",
            job_description="Need Python expert",
            job_id="job_123",
            marketplace="fiverr",  # Different marketplace
            bid_amount=5000,
            status=BidStatus.PENDING,
            is_suitable=True,
        )
        test_db.add(bid2)
        test_db.commit()

        # Verify both bids exist
        bids = test_db.query(Bid).all()
        assert len(bids) == 2
        assert bids[0].marketplace == "upwork"
        assert bids[1].marketplace == "fiverr"

    def test_bid_allows_different_job_same_marketplace(self, test_db):
        """
        Test that different jobs can be bid on in same marketplace.
        """
        # First bid
        bid1 = Bid(
            id=str(uuid.uuid4()),
            job_title="Python Developer",
            job_description="Need Python expert",
            job_id="job_123",
            marketplace="upwork",
            bid_amount=5000,
            status=BidStatus.PENDING,
            is_suitable=True,
        )
        test_db.add(bid1)
        test_db.commit()

        # Different job_id, same marketplace (should be allowed)
        bid2 = Bid(
            id=str(uuid.uuid4()),
            job_title="Java Developer",
            job_description="Need Java expert",
            job_id="job_456",  # Different job_id
            marketplace="upwork",
            bid_amount=5000,
            status=BidStatus.PENDING,
            is_suitable=True,
        )
        test_db.add(bid2)
        test_db.commit()

        # Verify both bids exist
        bids = test_db.query(Bid).all()
        assert len(bids) == 2
        assert bids[0].job_id == "job_123"
        assert bids[1].job_id == "job_456"

    def test_bid_duplicate_with_different_status(self, test_db):
        """
        Test that duplicate (job_id, marketplace) is rejected
        even if status differs.
        
        The (job_id, marketplace) unique constraint should enforce
        uniqueness regardless of status value.
        """
        # Create first bid with PENDING status
        bid1 = Bid(
            id=str(uuid.uuid4()),
            job_title="Python Developer",
            job_description="Need Python expert",
            job_id="job_123",
            marketplace="upwork",
            bid_amount=5000,
            status=BidStatus.PENDING,
            is_suitable=True,
        )
        test_db.add(bid1)
        test_db.commit()

        # Try to create duplicate with SUBMITTED status
        # This should fail due to (job_id, marketplace) constraint
        # NOT due to the (marketplace, job_id, status) constraint
        bid2 = Bid(
            id=str(uuid.uuid4()),
            job_title="Python Developer",
            job_description="Need Python expert",
            job_id="job_123",
            marketplace="upwork",
            bid_amount=5000,
            status=BidStatus.SUBMITTED,  # Different status
            is_suitable=True,
        )
        test_db.add(bid2)

        # Should raise IntegrityError from (job_id, marketplace) constraint
        with pytest.raises(IntegrityError):
            test_db.commit()

    def test_bid_multiple_duplicates_in_transaction(self, test_db):
        """
        Test that constraint is enforced within a transaction.
        """
        bid1 = Bid(
            id=str(uuid.uuid4()),
            job_title="Python Developer",
            job_description="Need Python expert",
            job_id="job_123",
            marketplace="upwork",
            bid_amount=5000,
            status=BidStatus.PENDING,
            is_suitable=True,
        )
        test_db.add(bid1)
        test_db.commit()

        # Create duplicate bids
        bid2 = Bid(
            id=str(uuid.uuid4()),
            job_title="Python Developer",
            job_description="Need Python expert",
            job_id="job_123",
            marketplace="upwork",
            bid_amount=5500,
            status=BidStatus.PENDING,
            is_suitable=True,
        )
        bid3 = Bid(
            id=str(uuid.uuid4()),
            job_title="Python Developer",
            job_description="Need Python expert",
            job_id="job_123",
            marketplace="upwork",
            bid_amount=6000,
            status=BidStatus.PENDING,
            is_suitable=True,
        )
        test_db.add(bid2)
        test_db.add(bid3)

        # First duplicate should raise error
        with pytest.raises(IntegrityError):
            test_db.commit()


class TestEscalationLogUniqueConstraints:
    """Tests for EscalationLog model unique constraints."""

    def test_escalation_log_unique_constraint_on_task_idempotency(self, test_db):
        """
        Test that (task_id, idempotency_key) combination is unique.
        Inserting duplicate (task_id, idempotency_key) should raise IntegrityError.
        """
        task_id = str(uuid.uuid4())
        idempotency_key = f"{task_id}_max_retries_exceeded"

        # Create first escalation log
        escalation1 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id,
            reason="max_retries_exceeded",
            error_message="Task failed after 3 retries",
            idempotency_key=idempotency_key,
            amount_paid=5000,
            domain="data_analysis",
            client_email="client@example.com",
        )
        test_db.add(escalation1)
        test_db.commit()

        # Try to create duplicate (task_id, idempotency_key)
        escalation2 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id,  # Same task_id
            reason="max_retries_exceeded",
            error_message="Task failed again",  # Different error message
            idempotency_key=idempotency_key,  # Same idempotency_key
            amount_paid=5000,
            domain="data_analysis",
            client_email="client@example.com",
        )
        test_db.add(escalation2)

        # Should raise IntegrityError
        with pytest.raises(IntegrityError):
            test_db.commit()

    def test_escalation_log_allows_different_tasks_same_key(self, test_db):
        """
        Test that different tasks can have escalations with same idempotency key prefix.
        (Idempotency key is only unique per (task_id, idempotency_key) pair)
        
        In practice, idempotency keys are formatted as: "{task_id}_{reason}"
        so different tasks will have different full keys anyway.
        """
        task_id_1 = str(uuid.uuid4())
        task_id_2 = str(uuid.uuid4())

        # Create escalation for task 1
        # Idempotency key includes task_id, so it's truly unique per task
        escalation1 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id_1,
            reason="max_retries_exceeded",
            error_message="Task failed",
            idempotency_key=f"{task_id_1}_max_retries",
            amount_paid=5000,
            domain="data_analysis",
            client_email="client1@example.com",
        )
        test_db.add(escalation1)
        test_db.commit()

        # Create escalation for task 2 with different key (allowed)
        escalation2 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id_2,  # Different task
            reason="max_retries_exceeded",
            error_message="Different task failed",
            idempotency_key=f"{task_id_2}_max_retries",  # Different key per task
            amount_paid=3000,
            domain="accounting",
            client_email="client2@example.com",
        )
        test_db.add(escalation2)
        test_db.commit()

        # Verify both escalations exist
        escalations = test_db.query(EscalationLog).all()
        assert len(escalations) == 2
        assert escalations[0].task_id == task_id_1
        assert escalations[1].task_id == task_id_2

    def test_escalation_log_allows_same_task_different_keys(self, test_db):
        """
        Test that same task can have multiple escalations with different keys.
        """
        task_id = str(uuid.uuid4())

        # Create first escalation
        escalation1 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id,
            reason="max_retries_exceeded",
            error_message="Task failed after retries",
            idempotency_key=f"{task_id}_max_retries",
            amount_paid=5000,
            domain="data_analysis",
            client_email="client@example.com",
        )
        test_db.add(escalation1)
        test_db.commit()

        # Create second escalation for same task with different key
        escalation2 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id,  # Same task
            reason="high_value_task_failed",
            error_message="High-value task failed",
            idempotency_key=f"{task_id}_high_value",  # Different key
            amount_paid=5000,
            domain="data_analysis",
            client_email="client@example.com",
        )
        test_db.add(escalation2)
        test_db.commit()

        # Verify both escalations exist
        escalations = test_db.query(EscalationLog).filter_by(task_id=task_id).all()
        assert len(escalations) == 2
        assert escalations[0].idempotency_key == f"{task_id}_max_retries"
        assert escalations[1].idempotency_key == f"{task_id}_high_value"

    def test_escalation_log_idempotency_in_retry_scenario(self, test_db):
        """
        Test idempotency behavior in a retry scenario.
        When a task is retried and fails again, the same idempotency key
        should not allow a new escalation log to be created.
        """
        task_id = str(uuid.uuid4())
        idempotency_key = f"{task_id}_max_retries_exceeded"

        # First escalation attempt
        escalation1 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id,
            reason="max_retries_exceeded",
            error_message="Attempt 1 failed",
            idempotency_key=idempotency_key,
            notification_sent=False,
            amount_paid=5000,
            domain="data_analysis",
            client_email="client@example.com",
        )
        test_db.add(escalation1)
        test_db.commit()

        # Simulate retry failure - try to create escalation with same key
        escalation2 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id,
            reason="max_retries_exceeded",
            error_message="Attempt 2 failed with different error",
            idempotency_key=idempotency_key,  # Same key (idempotent)
            notification_sent=False,
            amount_paid=5000,
            domain="data_analysis",
            client_email="client@example.com",
        )
        test_db.add(escalation2)

        # Should raise IntegrityError (prevents duplicate notification)
        with pytest.raises(IntegrityError):
            test_db.commit()

        # Need to rollback after failed commit
        test_db.rollback()

        # Verify original escalation is still there
        escalations = test_db.query(EscalationLog).filter_by(task_id=task_id).all()
        assert len(escalations) == 1
        assert escalations[0].error_message == "Attempt 1 failed"

    def test_escalation_log_multiple_tasks_multiple_keys(self, test_db):
        """
        Test complex scenario with multiple tasks and multiple keys.
        """
        # Task 1 with 2 escalation keys
        task_id_1 = str(uuid.uuid4())
        escalation1 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id_1,
            reason="max_retries_exceeded",
            idempotency_key=f"{task_id_1}_max_retries",
            amount_paid=5000,
        )
        escalation2 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id_1,
            reason="high_value_failed",
            idempotency_key=f"{task_id_1}_high_value",
            amount_paid=5000,
        )
        test_db.add(escalation1)
        test_db.add(escalation2)
        test_db.commit()

        # Task 2 with 2 escalation keys
        task_id_2 = str(uuid.uuid4())
        escalation3 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id_2,
            reason="max_retries_exceeded",
            idempotency_key=f"{task_id_2}_max_retries",
            amount_paid=3000,
        )
        escalation4 = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id_2,
            reason="high_value_failed",
            idempotency_key=f"{task_id_2}_high_value",
            amount_paid=3000,
        )
        test_db.add(escalation3)
        test_db.add(escalation4)
        test_db.commit()

        # Verify all 4 escalations exist
        escalations = test_db.query(EscalationLog).all()
        assert len(escalations) == 4

        # Verify by task
        task1_escalations = test_db.query(EscalationLog).filter_by(task_id=task_id_1).all()
        assert len(task1_escalations) == 2

        task2_escalations = test_db.query(EscalationLog).filter_by(task_id=task_id_2).all()
        assert len(task2_escalations) == 2


class TestConstraintIntegration:
    """Integration tests for all constraints together."""

    def test_both_models_with_unique_constraints(self, test_db):
        """
        Test that both Bid and EscalationLog constraints work together
        without interfering with each other.
        """
        # Create bid
        bid = Bid(
            id=str(uuid.uuid4()),
            job_title="Developer",
            job_description="Need developer",
            job_id="job_1",
            marketplace="upwork",
            bid_amount=5000,
            status=BidStatus.PENDING,
            is_suitable=True,
        )
        test_db.add(bid)
        test_db.commit()

        # Create escalation log
        task_id = str(uuid.uuid4())
        escalation = EscalationLog(
            id=str(uuid.uuid4()),
            task_id=task_id,
            reason="max_retries_exceeded",
            idempotency_key=f"{task_id}_max_retries",
            amount_paid=5000,
        )
        test_db.add(escalation)
        test_db.commit()

        # Verify both exist
        bids = test_db.query(Bid).all()
        escalations = test_db.query(EscalationLog).all()
        assert len(bids) == 1
        assert len(escalations) == 1

    def test_schema_verification(self, test_db):
        """
        Verify that constraints are properly defined in SQLAlchemy models.
        """
        # Check Bid model constraints
        bid_constraints = [c for c in Bid.__table__.constraints]
        unique_constraints = [c for c in bid_constraints if c.__class__.__name__ == 'UniqueConstraint']
        
        # Should have both our new constraint and the existing one
        constraint_names = [c.name for c in unique_constraints]
        assert 'unique_bid_per_posting' in constraint_names, \
            f"Expected 'unique_bid_per_posting' in {constraint_names}"
        assert 'unique_active_bid_per_posting' in constraint_names, \
            f"Expected 'unique_active_bid_per_posting' in {constraint_names}"

        # Check EscalationLog model constraints
        escalation_constraints = [c for c in EscalationLog.__table__.constraints]
        escalation_unique_constraints = [c for c in escalation_constraints if c.__class__.__name__ == 'UniqueConstraint']
        
        # Should have our new constraint
        escalation_constraint_names = [c.name for c in escalation_unique_constraints]
        assert 'unique_escalation_per_task' in escalation_constraint_names, \
            f"Expected 'unique_escalation_per_task' in {escalation_constraint_names}"
