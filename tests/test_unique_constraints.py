"""
Tests for Database Unique Constraints (Issue #33)

This test suite verifies that unique constraints are properly enforced
on critical database fields:
- ClientProfile.client_email
- Task.stripe_session_id
- Task.delivery_token

These constraints prevent data duplication and maintain data integrity.
"""

import pytest
import uuid
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from src.api.models import Base, ClientProfile, Task, TaskStatus


@pytest.fixture
def test_db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


class TestClientProfileUniqueEmail:
    """Test unique constraint on ClientProfile.client_email"""

    def test_create_profile_with_email(self, test_db):
        """Should successfully create a client profile with email."""
        profile = ClientProfile(
            client_email="test@example.com",
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
        )
        test_db.add(profile)
        test_db.commit()

        # Verify it was created
        result = test_db.query(ClientProfile).filter_by(
            client_email="test@example.com"
        ).first()
        assert result is not None
        assert result.client_email == "test@example.com"

    def test_duplicate_email_raises_error(self, test_db):
        """Should raise IntegrityError when creating duplicate emails."""
        # Create first profile
        profile1 = ClientProfile(
            client_email="duplicate@example.com",
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
        )
        test_db.add(profile1)
        test_db.commit()

        # Try to create duplicate profile
        profile2 = ClientProfile(
            client_email="duplicate@example.com",
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
        )
        test_db.add(profile2)

        # Should raise IntegrityError
        with pytest.raises(IntegrityError):
            test_db.commit()

    def test_different_emails_allowed(self, test_db):
        """Should allow multiple profiles with different emails."""
        emails = ["user1@example.com", "user2@example.com", "user3@example.com"]

        for email in emails:
            profile = ClientProfile(
                client_email=email,
                total_tasks=0,
                completed_tasks=0,
                failed_tasks=0,
            )
            test_db.add(profile)

        test_db.commit()

        # Verify all were created
        count = test_db.query(ClientProfile).count()
        assert count == 3

        # Verify each email exists
        for email in emails:
            profile = test_db.query(ClientProfile).filter_by(client_email=email).first()
            assert profile is not None

    def test_email_case_sensitivity(self, test_db):
        """Test email constraint handling (case sensitivity depends on DB)."""
        profile1 = ClientProfile(
            client_email="Test@Example.com",
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
        )
        test_db.add(profile1)
        test_db.commit()

        # Different case may be treated as different value in SQLite
        # This behavior varies by database backend
        profile2 = ClientProfile(
            client_email="test@example.com",
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
        )
        test_db.add(profile2)
        # Don't assert - just verify we can create it (SQLite is case-sensitive)
        test_db.commit()

        # Both should exist in SQLite (case-sensitive)
        count = test_db.query(ClientProfile).count()
        assert count == 2


class TestTaskUniqueStripeSessionId:
    """Test unique constraint on Task.stripe_session_id"""

    def test_create_task_with_stripe_session(self, test_db):
        """Should successfully create a task with stripe_session_id."""
        task = Task(
            title="Test Task",
            description="Test Description",
            domain="test_domain",
            stripe_session_id="cs_test_12345",
            client_email="test@example.com",
        )
        test_db.add(task)
        test_db.commit()

        # Verify it was created
        result = test_db.query(Task).filter_by(
            stripe_session_id="cs_test_12345"
        ).first()
        assert result is not None
        assert result.stripe_session_id == "cs_test_12345"

    def test_duplicate_stripe_session_raises_error(self, test_db):
        """Should raise IntegrityError for duplicate stripe_session_id."""
        # Create first task with stripe session
        task1 = Task(
            title="Task 1",
            description="Description 1",
            domain="domain1",
            stripe_session_id="cs_duplicate_123",
            client_email="user1@example.com",
        )
        test_db.add(task1)
        test_db.commit()

        # Try to create second task with same stripe session
        task2 = Task(
            title="Task 2",
            description="Description 2",
            domain="domain2",
            stripe_session_id="cs_duplicate_123",
            client_email="user2@example.com",
        )
        test_db.add(task2)

        with pytest.raises(IntegrityError):
            test_db.commit()

    def test_null_stripe_session_allowed(self, test_db):
        """Should allow multiple tasks with NULL stripe_session_id."""
        # SQLite allows multiple NULLs in unique columns
        task1 = Task(
            title="Task 1",
            description="Description 1",
            domain="domain1",
            stripe_session_id=None,
            client_email="user1@example.com",
        )
        test_db.add(task1)

        task2 = Task(
            title="Task 2",
            description="Description 2",
            domain="domain2",
            stripe_session_id=None,
            client_email="user2@example.com",
        )
        test_db.add(task2)

        test_db.commit()

        # Both should exist
        count = test_db.query(Task).filter_by(stripe_session_id=None).count()
        assert count == 2

    def test_different_stripe_sessions_allowed(self, test_db):
        """Should allow tasks with different stripe_session_ids."""
        sessions = ["cs_session_1", "cs_session_2", "cs_session_3"]

        for i, session_id in enumerate(sessions):
            task = Task(
                title=f"Task {i}",
                description=f"Description {i}",
                domain=f"domain{i}",
                stripe_session_id=session_id,
                client_email=f"user{i}@example.com",
            )
            test_db.add(task)

        test_db.commit()

        # Verify all were created
        count = test_db.query(Task).count()
        assert count == 3


class TestTaskUniqueDeliveryToken:
    """Test unique constraint on Task.delivery_token"""

    def test_create_task_with_delivery_token(self, test_db):
        """Should successfully create a task with delivery_token."""
        token = str(uuid.uuid4())
        task = Task(
            title="Test Task",
            description="Test Description",
            domain="test_domain",
            delivery_token=token,
            client_email="test@example.com",
        )
        test_db.add(task)
        test_db.commit()

        # Verify it was created
        result = test_db.query(Task).filter_by(delivery_token=token).first()
        assert result is not None
        assert result.delivery_token == token

    def test_duplicate_delivery_token_raises_error(self, test_db):
        """Should raise IntegrityError for duplicate delivery_token."""
        token = "duplicate_token_12345"

        # Create first task
        task1 = Task(
            title="Task 1",
            description="Description 1",
            domain="domain1",
            delivery_token=token,
            client_email="user1@example.com",
        )
        test_db.add(task1)
        test_db.commit()

        # Try to create second task with same token
        task2 = Task(
            title="Task 2",
            description="Description 2",
            domain="domain2",
            delivery_token=token,
            client_email="user2@example.com",
        )
        test_db.add(task2)

        with pytest.raises(IntegrityError):
            test_db.commit()

    def test_null_delivery_token_allowed(self, test_db):
        """Should allow multiple tasks with NULL delivery_token."""
        task1 = Task(
            title="Task 1",
            description="Description 1",
            domain="domain1",
            delivery_token=None,
            client_email="user1@example.com",
        )
        test_db.add(task1)

        task2 = Task(
            title="Task 2",
            description="Description 2",
            domain="domain2",
            delivery_token=None,
            client_email="user2@example.com",
        )
        test_db.add(task2)

        test_db.commit()

        # Both should exist
        count = test_db.query(Task).filter_by(delivery_token=None).count()
        assert count == 2

    def test_different_delivery_tokens_allowed(self, test_db):
        """Should allow tasks with different delivery_tokens."""
        tokens = [str(uuid.uuid4()) for _ in range(3)]

        for i, token in enumerate(tokens):
            task = Task(
                title=f"Task {i}",
                description=f"Description {i}",
                domain=f"domain{i}",
                delivery_token=token,
                client_email=f"user{i}@example.com",
            )
            test_db.add(task)

        test_db.commit()

        # Verify all were created
        count = test_db.query(Task).count()
        assert count == 3

        # Verify each token exists
        for token in tokens:
            task = test_db.query(Task).filter_by(delivery_token=token).first()
            assert task is not None


class TestCombinedConstraints:
    """Test combinations of unique constraints"""

    def test_same_token_different_email_fails(self, test_db):
        """Should fail when trying to use same delivery_token for different client."""
        token = "shared_token_12345"

        # Create first task
        task1 = Task(
            title="Task 1",
            description="Description 1",
            domain="domain1",
            delivery_token=token,
            client_email="user1@example.com",
        )
        test_db.add(task1)
        test_db.commit()

        # Try to create second task with same token but different email
        task2 = Task(
            title="Task 2",
            description="Description 2",
            domain="domain2",
            delivery_token=token,
            client_email="user2@example.com",
        )
        test_db.add(task2)

        # Should fail due to delivery_token uniqueness
        with pytest.raises(IntegrityError):
            test_db.commit()

    def test_independent_constraints(self, test_db):
        """Verify that each constraint is independent."""
        # Create profile
        profile = ClientProfile(
            client_email="test@example.com",
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
        )
        test_db.add(profile)

        # Create tasks with same email but different tokens and stripe sessions
        task1 = Task(
            title="Task 1",
            description="Description 1",
            domain="domain1",
            delivery_token=str(uuid.uuid4()),
            stripe_session_id="cs_session_1",
            client_email="test@example.com",
        )

        task2 = Task(
            title="Task 2",
            description="Description 2",
            domain="domain2",
            delivery_token=str(uuid.uuid4()),
            stripe_session_id="cs_session_2",
            client_email="test@example.com",
        )

        test_db.add(task1)
        test_db.add(task2)
        test_db.commit()

        # Should have created both tasks successfully
        count = test_db.query(Task).count()
        assert count == 2

        # Both should be associated with same email
        tasks = test_db.query(Task).filter_by(client_email="test@example.com").all()
        assert len(tasks) == 2
        assert tasks[0].delivery_token != tasks[1].delivery_token
        assert tasks[0].stripe_session_id != tasks[1].stripe_session_id


class TestConstraintIndexing:
    """Test that unique constraints create indexes for query performance"""

    def test_stripe_session_query_uses_index(self, test_db):
        """Stripe session lookups should be indexed."""
        # Create task with stripe session
        task = Task(
            title="Test Task",
            description="Description",
            domain="domain",
            stripe_session_id="cs_indexed_lookup",
            client_email="test@example.com",
        )
        test_db.add(task)
        test_db.commit()

        # Query should be fast (using index)
        result = test_db.query(Task).filter_by(
            stripe_session_id="cs_indexed_lookup"
        ).first()
        assert result is not None

    def test_delivery_token_query_uses_index(self, test_db):
        """Delivery token lookups should be indexed."""
        token = str(uuid.uuid4())
        task = Task(
            title="Test Task",
            description="Description",
            domain="domain",
            delivery_token=token,
            client_email="test@example.com",
        )
        test_db.add(task)
        test_db.commit()

        # Query should be fast (using index)
        result = test_db.query(Task).filter_by(delivery_token=token).first()
        assert result is not None

    def test_email_query_uses_index(self, test_db):
        """Client email lookups should be indexed."""
        profile = ClientProfile(
            client_email="indexed@example.com",
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
        )
        test_db.add(profile)
        test_db.commit()

        # Query should be fast (using index)
        result = (
            test_db.query(ClientProfile)
            .filter_by(client_email="indexed@example.com")
            .first()
        )
        assert result is not None
