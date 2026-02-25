"""
Tests for idempotent escalation workflow with transaction safety.

Covers:
- EscalationLog creation with idempotency key
- Duplicate escalation detection (no duplicate notifications)
- Transaction wrapping (task + escalation log committed atomically)
- Notification failure recovery (task status committed even if notification fails)
- Notification retry with exponential backoff
- High-value vs non-high-value notification gating

Closes #3
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.api.models import Task, TaskStatus, ReviewStatus, EscalationLog


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_db():
    """Create a mock database session with query support."""
    db = MagicMock()
    # Default: no existing escalation log
    db.query.return_value.filter.return_value.first.return_value = None
    return db


@pytest.fixture
def high_value_task():
    """Create a high-value task ($200+)."""
    task = MagicMock(spec=Task)
    task.id = "task-high-value-001"
    task.status = TaskStatus.PAID
    task.amount_paid = 25000  # $250.00
    task.domain = "data_analysis"
    task.client_email = "client@example.com"
    task.escalation_reason = None
    task.escalated_at = None
    task.last_error = None
    task.review_status = ReviewStatus.PENDING
    return task


@pytest.fixture
def low_value_task():
    """Create a low-value task (< $200)."""
    task = MagicMock(spec=Task)
    task.id = "task-low-value-001"
    task.status = TaskStatus.PAID
    task.amount_paid = 1000  # $10.00
    task.domain = "data_analysis"
    task.client_email = "client@example.com"
    task.escalation_reason = None
    task.escalated_at = None
    task.last_error = None
    task.review_status = ReviewStatus.PENDING
    return task


@pytest.fixture
def existing_escalation_log():
    """Create an existing escalation log (for duplicate detection)."""
    log = MagicMock(spec=EscalationLog)
    log.notification_sent = True
    log.notification_attempt_count = 1
    log.last_notification_attempt_at = datetime.now(timezone.utc)
    log.notification_error = None
    return log


# =============================================================================
# IDEMPOTENCY TESTS
# =============================================================================

class TestEscalationIdempotency:
    """Test that duplicate escalations are detected and don't re-send notifications."""

    @pytest.mark.asyncio
    async def test_first_escalation_creates_log(self, mock_db, high_value_task):
        """Test that first escalation creates a new EscalationLog."""
        from src.api.main import _escalate_task

        with patch("src.api.main.TelegramNotifier") as MockNotifier:
            mock_notifier = MockNotifier.return_value
            mock_notifier.request_human_help = AsyncMock(return_value=True)

            await _escalate_task(
                mock_db, high_value_task, "max_retries_exceeded", "Test error"
            )

        # Verify escalation log was added
        mock_db.add.assert_called_once()
        added_log = mock_db.add.call_args[0][0]
        assert isinstance(added_log, EscalationLog)
        assert added_log.task_id == "task-high-value-001"
        assert added_log.reason == "max_retries_exceeded"
        assert added_log.idempotency_key == "task-high-value-001_max_retries_exceeded"

    @pytest.mark.asyncio
    async def test_duplicate_escalation_skips_notification(
        self, mock_db, high_value_task, existing_escalation_log
    ):
        """Test that duplicate escalation does NOT re-send notification."""
        from src.api.main import _escalate_task

        # Return existing log (notification already sent)
        mock_db.query.return_value.filter.return_value.first.return_value = (
            existing_escalation_log
        )

        with patch("src.api.main.TelegramNotifier") as MockNotifier:
            mock_notifier = MockNotifier.return_value
            mock_notifier.request_human_help = AsyncMock(return_value=True)

            await _escalate_task(
                mock_db, high_value_task, "max_retries_exceeded", "Retry error"
            )

            # Notification should NOT be called again
            mock_notifier.request_human_help.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotency_key_format(self, mock_db, high_value_task):
        """Test idempotency key is correctly formatted as task_id_reason."""
        from src.api.main import _escalate_task

        with patch("src.api.main.TelegramNotifier") as MockNotifier:
            mock_notifier = MockNotifier.return_value
            mock_notifier.request_human_help = AsyncMock(return_value=True)

            await _escalate_task(
                mock_db, high_value_task, "high_value_task_failed", "Error"
            )

        added_log = mock_db.add.call_args[0][0]
        assert added_log.idempotency_key == "task-high-value-001_high_value_task_failed"


# =============================================================================
# TRANSACTION SAFETY TESTS
# =============================================================================

class TestTransactionSafety:
    """Test that task status and escalation log are committed atomically."""

    @pytest.mark.asyncio
    async def test_task_status_updated_to_escalation(self, mock_db, high_value_task):
        """Test task status is set to ESCALATION."""
        from src.api.main import _escalate_task

        with patch("src.api.main.TelegramNotifier") as MockNotifier:
            mock_notifier = MockNotifier.return_value
            mock_notifier.request_human_help = AsyncMock(return_value=True)

            await _escalate_task(
                mock_db, high_value_task, "max_retries_exceeded", "Error msg"
            )

        assert high_value_task.status == TaskStatus.ESCALATION
        assert high_value_task.escalation_reason == "max_retries_exceeded"
        assert high_value_task.last_error == "Error msg"
        assert high_value_task.review_status == ReviewStatus.PENDING

    @pytest.mark.asyncio
    async def test_begin_nested_called_for_savepoint(self, mock_db, low_value_task):
        """Test that begin_nested() is called for transaction savepoint."""
        from src.api.main import _escalate_task

        with patch("src.api.main.TelegramNotifier"):
            await _escalate_task(
                mock_db, low_value_task, "max_retries_exceeded"
            )

        mock_db.begin_nested.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_committed_even_on_savepoint_failure(self, mock_db, low_value_task):
        """Test task status is still committed even if savepoint fails."""
        from src.api.main import _escalate_task

        mock_db.begin_nested.side_effect = Exception("DB connection error")

        with patch("src.api.main.TelegramNotifier"):
            await _escalate_task(
                mock_db, low_value_task, "max_retries_exceeded", "Some error"
            )

        # Task status should still be updated
        assert low_value_task.status == TaskStatus.ESCALATION
        # Rollback should be called, then a final commit for just the task status
        mock_db.rollback.assert_called_once()
        mock_db.commit.assert_called()


# =============================================================================
# NOTIFICATION TESTS
# =============================================================================

class TestNotificationBehavior:
    """Test Telegram notification gating and failure recovery."""

    @pytest.mark.asyncio
    async def test_high_value_task_sends_notification(self, mock_db, high_value_task):
        """Test that high-value tasks trigger Telegram notification."""
        from src.api.main import _escalate_task

        with patch("src.api.main.TelegramNotifier") as MockNotifier:
            mock_notifier = MockNotifier.return_value
            mock_notifier.request_human_help = AsyncMock(return_value=True)

            await _escalate_task(
                mock_db, high_value_task, "max_retries_exceeded", "Error"
            )

            mock_notifier.request_human_help.assert_called_once_with(
                task_id="task-high-value-001",
                context="Reason: max_retries_exceeded\nError: Error",
                amount_paid=25000,
                domain="data_analysis",
                client_email="client@example.com"
            )

    @pytest.mark.asyncio
    async def test_low_value_task_skips_notification(self, mock_db, low_value_task):
        """Test that low-value tasks do NOT trigger Telegram notification."""
        from src.api.main import _escalate_task

        with patch("src.api.main.TelegramNotifier") as MockNotifier:
            mock_notifier = MockNotifier.return_value
            mock_notifier.request_human_help = AsyncMock(return_value=True)

            await _escalate_task(
                mock_db, low_value_task, "max_retries_exceeded"
            )

            mock_notifier.request_human_help.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_affect_task_status(
        self, mock_db, high_value_task
    ):
        """Test that notification failure doesn't prevent task status update."""
        from src.api.main import _escalate_task

        with patch("src.api.main.TelegramNotifier") as MockNotifier:
            mock_notifier = MockNotifier.return_value
            mock_notifier.request_human_help = AsyncMock(
                side_effect=Exception("Network error")
            )

            await _escalate_task(
                mock_db, high_value_task, "max_retries_exceeded", "Error"
            )

        # Task should still be marked as ESCALATION
        assert high_value_task.status == TaskStatus.ESCALATION
        # DB should have been committed (task status persisted before notification)
        assert mock_db.commit.call_count >= 2  # savepoint commit + notification error commit

    @pytest.mark.asyncio
    async def test_notification_sent_after_db_commit(self, mock_db, high_value_task):
        """Test that notification is sent AFTER db.commit(), not before."""
        from src.api.main import _escalate_task

        call_order = []

        def track_commit():
            call_order.append("commit")

        mock_db.commit.side_effect = track_commit

        with patch("src.api.main.TelegramNotifier") as MockNotifier:
            mock_notifier = MockNotifier.return_value

            async def track_notify(**kwargs):
                call_order.append("notify")
                return True

            mock_notifier.request_human_help = track_notify

            await _escalate_task(
                mock_db, high_value_task, "max_retries_exceeded", "Error"
            )

        # commit (savepoint) should happen before notify
        assert "commit" in call_order
        assert "notify" in call_order
        assert call_order.index("commit") < call_order.index("notify")


# =============================================================================
# SHOULD_ESCALATE DECISION TESTS
# =============================================================================

class TestShouldEscalateTask:
    """Test the _should_escalate_task decision logic."""

    def test_max_retries_exceeded(self):
        """Test escalation when max retries are exceeded."""
        from src.api.main import _should_escalate_task, MAX_RETRY_ATTEMPTS

        task = MagicMock()
        task.amount_paid = 1000  # $10 - low value

        should, reason = _should_escalate_task(task, MAX_RETRY_ATTEMPTS, "error")
        assert should is True
        assert reason == "max_retries_exceeded"

    def test_high_value_task_with_error(self):
        """Test escalation for high-value task with error."""
        from src.api.main import _should_escalate_task

        task = MagicMock()
        task.amount_paid = 25000  # $250 - high value

        should, reason = _should_escalate_task(task, 1, "error")
        assert should is True
        assert reason == "high_value_task_failed"

    def test_no_escalation_for_low_value_low_retries(self):
        """Test no escalation for low-value task with few retries."""
        from src.api.main import _should_escalate_task

        task = MagicMock()
        task.amount_paid = 1000  # $10

        should, reason = _should_escalate_task(task, 1, "error")
        assert should is False
        assert reason is None

    def test_high_value_max_retries_has_high_value_reason(self):
        """Test that high-value + max retries gives high_value reason."""
        from src.api.main import _should_escalate_task, MAX_RETRY_ATTEMPTS

        task = MagicMock()
        task.amount_paid = 25000  # $250

        should, reason = _should_escalate_task(task, MAX_RETRY_ATTEMPTS, "error")
        assert should is True
        assert reason == "max_retries_exceeded_high_value"

    def test_no_escalation_without_error_for_high_value(self):
        """Test no escalation for high-value task without an error message."""
        from src.api.main import _should_escalate_task

        task = MagicMock()
        task.amount_paid = 25000  # $250

        should, reason = _should_escalate_task(task, 1, None)
        assert should is False
        assert reason is None


# =============================================================================
# TELEGRAM NOTIFIER RETRY TESTS
# =============================================================================

class TestTelegramNotifierRetry:
    """Test exponential backoff retry logic in TelegramNotifier."""

    @pytest.mark.asyncio
    async def test_retries_on_http_error(self):
        """Test that _send_message retries on HTTP errors."""
        import httpx
        from src.utils.notifications import TelegramNotifier, MAX_NOTIFICATION_RETRIES

        notifier = TelegramNotifier()
        notifier.bot_token = "test-token"
        notifier.chat_id = "test-chat"

        with patch("src.utils.notifications.asyncio.sleep", new_callable=AsyncMock):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.post.side_effect = httpx.HTTPError("Connection refused")
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await notifier._send_message("Test message")

        assert result is False
        assert mock_client.post.call_count == MAX_NOTIFICATION_RETRIES

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(self):
        """Test that notification succeeds after a retry."""
        import httpx
        from src.utils.notifications import TelegramNotifier

        notifier = TelegramNotifier()
        notifier.bot_token = "test-token"
        notifier.chat_id = "test-chat"

        mock_response_fail = MagicMock()
        mock_response_fail.raise_for_status.side_effect = httpx.HTTPError("Timeout")

        mock_response_ok = MagicMock()
        mock_response_ok.raise_for_status.return_value = None
        mock_response_ok.json.return_value = {"ok": True}

        with patch("src.utils.notifications.asyncio.sleep", new_callable=AsyncMock):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.post.side_effect = [
                    mock_response_fail,  # First attempt fails
                    mock_response_ok     # Second attempt succeeds
                ]
                # Need to handle the side_effect properly for raise_for_status
                # Let's use a different approach
                call_count = 0

                async def mock_post(url, json):
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        raise httpx.HTTPError("Timeout")
                    return mock_response_ok

                mock_client.post = mock_post
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await notifier._send_message("Test message")

        assert result is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_skips_when_no_credentials(self):
        """Test that _send_message returns False when credentials are missing."""
        from src.utils.notifications import TelegramNotifier

        notifier = TelegramNotifier()
        notifier.bot_token = None
        notifier.chat_id = None

        result = await notifier._send_message("Test")
        assert result is False
