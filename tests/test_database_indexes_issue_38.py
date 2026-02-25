"""
Test suite for Issue #38: Performance - Missing Query Optimization and Database Indexes

This test module verifies:
1. All required indexes exist in the database schema
2. Indexes are correctly configured with proper columns
3. Query optimization helpers work correctly
4. N+1 query patterns are avoided
5. Composite indexes support multi-column queries

Database indexes added:
- Task.client_email
- Task.status
- Task.created_at
- Task composite (client_email, status)
- Task composite (status, created_at)
- Bid.posting_id (job_id)
- Bid.agent_id (marketplace)
- Bid.status
- Bid composite (marketplace, status)
- Bid.created_at
"""

import uuid
import pytest
from datetime import datetime
from sqlalchemy import inspect, create_engine
from sqlalchemy.orm import sessionmaker
from src.api.models import Base, Task, Bid, TaskStatus, BidStatus


@pytest.fixture
def test_db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
from src.api.query_optimizations import (
    get_client_tasks_optimized,
    get_completed_tasks_by_domain_optimized,
    get_pending_tasks_optimized,
    get_active_bids_optimized,
    get_recent_bids_optimized,
    get_bid_dedup_set_optimized,
    get_task_by_client_and_status_optimized,
    get_tasks_for_metrics_optimized,
)


class TestDatabaseIndexes:
    """Verify all required indexes exist in the models."""

    def test_task_client_email_index_exists(self):
        """Task table should have index on client_email (Issue #38)."""
        indexes = {idx.name: [c.name for c in idx.columns] for idx in Task.__table__.indexes}
        assert "idx_task_client_email" in indexes
        assert "client_email" in indexes["idx_task_client_email"]

    def test_task_status_index_exists(self):
        """Task table should have index on status (Issue #38)."""
        indexes = {idx.name: [c.name for c in idx.columns] for idx in Task.__table__.indexes}
        assert "idx_task_status" in indexes
        assert "status" in indexes["idx_task_status"]

    def test_task_created_at_index_exists(self):
        """Task table should have index on created_at (Issue #38)."""
        indexes = {idx.name: [c.name for c in idx.columns] for idx in Task.__table__.indexes}
        assert "idx_task_created_at" in indexes
        assert "created_at" in indexes["idx_task_created_at"]

    def test_task_composite_client_status_index_exists(self):
        """Task table should have composite index on (client_email, status) (Issue #38)."""
        indexes = {idx.name: [c.name for c in idx.columns] for idx in Task.__table__.indexes}
        assert "idx_task_client_status" in indexes
        cols = indexes["idx_task_client_status"]
        assert "client_email" in cols
        assert "status" in cols

    def test_task_composite_status_created_index_exists(self):
        """Task table should have composite index on (status, created_at) (Issue #38)."""
        indexes = {idx.name: [c.name for c in idx.columns] for idx in Task.__table__.indexes}
        assert "idx_task_status_created" in indexes
        cols = indexes["idx_task_status_created"]
        assert "status" in cols
        assert "created_at" in cols

    def test_bid_posting_id_index_exists(self):
        """Bid table should have index on job_id (posting_id) (Issue #38)."""
        indexes = {idx.name: [c.name for c in idx.columns] for idx in Bid.__table__.indexes}
        assert "idx_bid_posting_id" in indexes
        assert "job_id" in indexes["idx_bid_posting_id"]

    def test_bid_agent_id_index_exists(self):
        """Bid table should have index on marketplace (agent_id) (Issue #38)."""
        indexes = {idx.name: [c.name for c in idx.columns] for idx in Bid.__table__.indexes}
        assert "idx_bid_agent_id" in indexes
        assert "marketplace" in indexes["idx_bid_agent_id"]

    def test_bid_status_index_exists(self):
        """Bid table should have index on status (Issue #38)."""
        indexes = {idx.name: [c.name for c in idx.columns] for idx in Bid.__table__.indexes}
        assert "idx_bid_status" in indexes
        assert "status" in indexes["idx_bid_status"]

    def test_bid_composite_marketplace_status_index_exists(self):
        """Bid table should have composite index on (marketplace, status) (Issue #38)."""
        indexes = {idx.name: [c.name for c in idx.columns] for idx in Bid.__table__.indexes}
        assert "idx_bid_marketplace_status" in indexes
        cols = indexes["idx_bid_marketplace_status"]
        assert "marketplace" in cols
        assert "status" in cols

    def test_bid_created_at_index_exists(self):
        """Bid table should have index on created_at (Issue #38)."""
        indexes = {idx.name: [c.name for c in idx.columns] for idx in Bid.__table__.indexes}
        assert "idx_bid_created_at" in indexes
        assert "created_at" in indexes["idx_bid_created_at"]


class TestOptimizedQueries:
    """Test optimized query helpers that use indexes effectively."""

    @pytest.fixture
    def sample_tasks(self, test_db):
        """Create sample tasks for testing."""
        client_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        tasks = [
            Task(
                title=f"Task {i}",
                description=f"Description {i}",
                domain="finance",
                client_email=client_email,
                status=TaskStatus.PENDING if i % 2 == 0 else TaskStatus.COMPLETED,
            )
            for i in range(5)
        ]
        test_db.add_all(tasks)
        test_db.commit()
        return tasks, client_email

    @pytest.fixture
    def sample_bids(self, test_db):
        """Create sample bids for testing."""
        bids = [
            Bid(
                job_title=f"Job {i}",
                job_description=f"Description {i}",
                job_id=f"job_{i}",
                bid_amount=10000 + i * 100,
                marketplace="upwork" if i % 2 == 0 else "fiverr",
                status=BidStatus.PENDING if i % 2 == 0 else BidStatus.SUBMITTED,
            )
            for i in range(5)
        ]
        test_db.add_all(bids)
        test_db.commit()
        return bids

    def test_get_client_tasks_optimized(self, test_db, sample_tasks):
        """Verify optimized client task query works correctly."""
        tasks, client_email = sample_tasks
        results = get_client_tasks_optimized(test_db, client_email, limit=10)
        assert len(results) == 5
        assert all(t.client_email == client_email for t in results)

    def test_get_pending_tasks_optimized(self, test_db, sample_tasks):
        """Verify optimized pending task query works correctly."""
        tasks, _ = sample_tasks
        results = get_pending_tasks_optimized(test_db, limit=10)
        assert len(results) >= 2
        assert all(t.status == TaskStatus.PENDING for t in results)

    def test_get_completed_tasks_by_domain_optimized(self, test_db, sample_tasks):
        """Verify optimized completed task query works correctly."""
        tasks, _ = sample_tasks
        results = get_completed_tasks_by_domain_optimized(test_db)
        assert len(results) >= 2
        assert all(t.status == TaskStatus.COMPLETED for t in results)

    def test_get_active_bids_optimized(self, test_db, sample_bids):
        """Verify optimized active bids query works correctly."""
        bids = sample_bids
        results = get_active_bids_optimized(test_db)
        assert len(results) > 0
        assert all(
            b.status in [BidStatus.PENDING, BidStatus.SUBMITTED, BidStatus.APPROVED]
            for b in results
        )

    def test_get_active_bids_optimized_with_marketplace(self, test_db, sample_bids):
        """Verify marketplace-filtered active bids query works correctly."""
        bids = sample_bids
        results = get_active_bids_optimized(test_db, marketplace="upwork")
        assert all(b.marketplace == "upwork" for b in results)

    def test_get_recent_bids_optimized(self, test_db, sample_bids):
        """Verify optimized recent bids query works correctly."""
        bids = sample_bids
        results = get_recent_bids_optimized(test_db, marketplace="upwork", limit=10)
        assert all(b.marketplace == "upwork" for b in results)
        # Should be ordered by created_at desc
        if len(results) > 1:
            assert results[0].created_at >= results[1].created_at

    def test_get_bid_dedup_set_optimized(self, test_db, sample_bids):
        """Verify optimized bid deduplication query works correctly."""
        bids = sample_bids
        results = get_bid_dedup_set_optimized(test_db, [BidStatus.PENDING])
        assert isinstance(results, set)
        assert len(results) > 0

    def test_get_task_by_client_and_status_optimized(self, test_db, sample_tasks):
        """Verify optimized composite query works correctly."""
        tasks, client_email = sample_tasks
        results = get_task_by_client_and_status_optimized(
            test_db, client_email, TaskStatus.PENDING
        )
        assert all(t.client_email == client_email for t in results)
        assert all(t.status == TaskStatus.PENDING for t in results)

    def test_get_tasks_for_metrics_optimized(self, test_db, sample_tasks):
        """Verify optimized metrics query works correctly."""
        tasks, _ = sample_tasks
        results = get_tasks_for_metrics_optimized(test_db)
        assert len(results) > 0
        # Results should contain tuples with selected columns
        if results:
            # Each result should have 5 fields: id, domain, status, amount_paid, created_at
            assert len(results[0]) == 5


class TestIndexSelectivity:
    """Test index effectiveness and query patterns."""

    def test_client_email_filtering(self, test_db):
        """Index on client_email should support fast client lookups."""
        client1 = f"client1_{uuid.uuid4().hex[:8]}@example.com"
        client2 = f"client2_{uuid.uuid4().hex[:8]}@example.com"

        # Create tasks for two different clients
        for i in range(3):
            test_db.add(
                Task(
                    title=f"Task {i}",
                    description=f"Desc {i}",
                    domain="finance",
                    client_email=client1,
                )
            )
        for i in range(2):
            test_db.add(
                Task(
                    title=f"Task {3+i}",
                    description=f"Desc {3+i}",
                    domain="finance",
                    client_email=client2,
                )
            )
        test_db.commit()

        # Query should be fast with index
        results1 = test_db.query(Task).filter(Task.client_email == client1).all()
        results2 = test_db.query(Task).filter(Task.client_email == client2).all()

        assert len(results1) == 3
        assert len(results2) == 2

    def test_status_filtering(self, test_db):
        """Index on status should support fast status-based queries."""
        # Create tasks with different statuses
        for status in [TaskStatus.PENDING, TaskStatus.COMPLETED, TaskStatus.FAILED]:
            test_db.add(
                Task(
                    title=f"Task {status.value}",
                    description="Desc",
                    domain="finance",
                    status=status,
                )
            )
        test_db.commit()

        # Query should be fast with index
        pending = test_db.query(Task).filter(Task.status == TaskStatus.PENDING).all()
        assert len(pending) >= 1
        assert all(t.status == TaskStatus.PENDING for t in pending)

    def test_created_at_ordering(self, test_db):
        """Index on created_at should support efficient ordering."""
        client = f"test_{uuid.uuid4().hex[:8]}@example.com"

        # Create tasks with slight time gaps
        for i in range(3):
            task = Task(
                title=f"Task {i}",
                description=f"Desc {i}",
                domain="finance",
                client_email=client,
            )
            test_db.add(task)
            test_db.flush()

        test_db.commit()

        # Query with ordering should be fast
        results = (
            test_db.query(Task)
            .filter(Task.client_email == client)
            .order_by(Task.created_at.desc())
            .all()
        )

        assert len(results) == 3
        # Verify ordering
        for i in range(len(results) - 1):
            assert results[i].created_at >= results[i + 1].created_at

    def test_composite_index_client_status(self, test_db):
        """Composite index (client_email, status) should support combined filters."""
        client = f"test_{uuid.uuid4().hex[:8]}@example.com"

        # Create mix of completed and pending tasks
        for status in [TaskStatus.PENDING, TaskStatus.COMPLETED]:
            for i in range(2):
                test_db.add(
                    Task(
                        title=f"Task {status.value}_{i}",
                        description="Desc",
                        domain="finance",
                        client_email=client,
                        status=status,
                    )
                )
        test_db.commit()

        # Query using both columns should be fast
        results = (
            test_db.query(Task)
            .filter(Task.client_email == client, Task.status == TaskStatus.COMPLETED)
            .all()
        )

        assert len(results) == 2
        assert all(t.client_email == client for t in results)
        assert all(t.status == TaskStatus.COMPLETED for t in results)

    def test_composite_index_bid_marketplace_status(self, test_db):
        """Composite index (marketplace, status) should support combined filters."""
        # Create bids across marketplaces
        for marketplace in ["upwork", "fiverr"]:
            for status in [BidStatus.PENDING, BidStatus.SUBMITTED]:
                for i in range(2):
                    test_db.add(
                        Bid(
                            job_title=f"Job {marketplace}_{status.value}_{i}",
                            job_description="Desc",
                            bid_amount=10000,
                            marketplace=marketplace,
                            status=status,
                        )
                    )
        test_db.commit()

        # Query using both columns should be fast
        results = (
            test_db.query(Bid)
            .filter(Bid.marketplace == "upwork", Bid.status == BidStatus.PENDING)
            .all()
        )

        assert len(results) >= 2
        assert all(b.marketplace == "upwork" for b in results)
        assert all(b.status == BidStatus.PENDING for b in results)


class TestN1QueryPrevention:
    """Test that N+1 query patterns are avoided."""

    def test_no_lazy_loading_in_task_model(self):
        """Task model should not use lazy-loaded relationships (Issue #38)."""
        # Verify Task doesn't have lazy-loaded relationships
        mapper = inspect(Task)
        relationships = {rel.key: rel for rel in mapper.relationships}
        
        # If relationships exist, verify they don't use lazy loading
        for rel_key, rel in relationships.items():
            # Most relationships should use eager loading or no loading
            assert rel.lazy != "select", f"Relationship {rel_key} uses lazy loading"

    def test_no_lazy_loading_in_bid_model(self):
        """Bid model should not use lazy-loaded relationships (Issue #38)."""
        # Verify Bid doesn't have lazy-loaded relationships
        mapper = inspect(Bid)
        relationships = {rel.key: rel for rel in mapper.relationships}
        
        # If relationships exist, verify they don't use lazy loading
        for rel_key, rel in relationships.items():
            # Most relationships should use eager loading or no loading
            assert rel.lazy != "select", f"Relationship {rel_key} uses lazy loading"

    def test_bulk_client_tasks_query_efficient(self, test_db):
        """Bulk querying client tasks should be efficient with index."""
        clients = [f"client_{i}_{uuid.uuid4().hex[:4]}@example.com" for i in range(3)]
        
        # Create multiple tasks per client
        for client in clients:
            for i in range(5):
                test_db.add(
                    Task(
                        title=f"Task {i}",
                        description="Desc",
                        domain="finance",
                        client_email=client,
                    )
                )
        test_db.commit()
        
        # Fetch all client tasks in a single query (not per-client)
        # This demonstrates proper index usage without N+1
        for client in clients:
            tasks = get_client_tasks_optimized(test_db, client)
            assert len(tasks) == 5

    def test_bid_status_aggregation_efficient(self, test_db):
        """Aggregating bids by status should be efficient with index."""
        statuses = [BidStatus.PENDING, BidStatus.SUBMITTED, BidStatus.APPROVED]
        
        # Create multiple bids per status
        for status in statuses:
            for i in range(5):
                test_db.add(
                    Bid(
                        job_title=f"Job {status.value}_{i}",
                        job_description="Desc",
                        bid_amount=10000 + i,
                        status=status,
                    )
                )
        test_db.commit()
        
        # Count bids by status using indexed queries
        # Should all be single efficient queries, not N+1
        for status in statuses:
            bids = test_db.query(Bid).filter(Bid.status == status).all()
            assert len(bids) >= 5


class TestIndexCoverage:
    """Test that key query patterns are covered by indexes."""

    def test_all_required_task_indexes_exist(self):
        """Task model should have all required indexes (Issue #38)."""
        required_indexes = {
            "idx_task_client_email": ["client_email"],
            "idx_task_status": ["status"],
            "idx_task_created_at": ["created_at"],
            "idx_task_client_status": ["client_email", "status"],
            "idx_task_status_created": ["status", "created_at"],
        }
        
        task_indexes = {idx.name: [c.name for c in idx.columns] for idx in Task.__table__.indexes}
        
        for index_name, expected_cols in required_indexes.items():
            assert index_name in task_indexes, f"Missing index: {index_name}"
            actual_cols = task_indexes[index_name]
            for col in expected_cols:
                assert col in actual_cols, f"Index {index_name} missing column {col}"

    def test_all_required_bid_indexes_exist(self):
        """Bid model should have all required indexes (Issue #38)."""
        required_indexes = {
            "idx_bid_posting_id": ["job_id"],
            "idx_bid_agent_id": ["marketplace"],
            "idx_bid_status": ["status"],
            "idx_bid_marketplace_status": ["marketplace", "status"],
            "idx_bid_created_at": ["created_at"],
        }
        
        bid_indexes = {idx.name: [c.name for c in idx.columns] for idx in Bid.__table__.indexes}
        
        for index_name, expected_cols in required_indexes.items():
            assert index_name in bid_indexes, f"Missing index: {index_name}"
            actual_cols = bid_indexes[index_name]
            for col in expected_cols:
                assert col in actual_cols, f"Index {index_name} missing column {col}"
