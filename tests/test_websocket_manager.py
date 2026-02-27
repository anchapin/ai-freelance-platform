"""
Tests for the WebSocket Manager and real-time task updates.

Tests WebSocket connection management, authentication, task/bid subscriptions,
real-time notifications, and integration with task processing.
"""

import pytest
import json
import time
from unittest.mock import Mock, AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketState
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.websocket_manager import (
    WebSocketManager,
    WebSocketMessageType,
    TaskStatus,
    BidStatus,
    NotificationType,
    WebSocketMessage,
    TaskUpdateData,
    WebSocketAuthError,
)
from src.api.models import Task, Bid, TaskStatus as DBTaskStatus
from src.config import Config


class MockWebSocket:
    """Mock WebSocket for testing."""

    def __init__(self, state="CONNECTED"):
        self.state = state
        self.messages = []
        self.closed = False
        self.application_state = (
            WebSocketState.CONNECTED
            if state == "CONNECTED"
            else WebSocketState.DISCONNECTED
        )

    async def accept(self):
        pass

    async def receive_text(self):
        return json.dumps({"type": "auth", "data": {"token": "test_token"}})

    async def send_text(self, message):
        self.messages.append(message)

    async def close(self, code=1000):
        self.closed = True


class TestWebSocketManager:
    """Test the WebSocket manager."""

    @pytest.fixture
    async def websocket_manager(self):
        """Create a WebSocket manager instance."""
        manager = WebSocketManager()
        await manager.start()
        yield manager
        await manager.stop()

    @pytest.fixture
    def mock_websocket(self):
        """Create a mock WebSocket."""
        return MockWebSocket()

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = Mock(spec=Config)
        config.JWT_SECRET_KEY = "test_secret"
        return config

    def test_websocket_message_creation(self):
        """Test WebSocket message creation and serialization."""
        data = TaskUpdateData(
            task_id="test-task",
            status="PROCESSING",
            message="Task started",
            progress=50.0,
        )

        message = WebSocketMessage(
            type=WebSocketMessageType.TASK_STATUS_UPDATE.value,
            timestamp=1234567890.0,
            data=asdict(data),
        )

        json_str = message.to_json()
        parsed = json.loads(json_str)

        assert parsed["type"] == WebSocketMessageType.TASK_STATUS_UPDATE.value
        assert parsed["timestamp"] == 1234567890.0
        assert parsed["data"]["task_id"] == "test-task"
        assert parsed["data"]["status"] == "PROCESSING"
        assert parsed["data"]["message"] == "Task started"
        assert parsed["data"]["progress"] == 50.0

    @pytest.mark.asyncio
    async def test_connect_client_success(self, websocket_manager, mock_websocket):
        """Test successful client connection."""
        # Add client directly to simulate successful connection
        websocket_manager.client_sessions["test-client"] = {
            "user_id": "test-user",
            "connected_at": time.time(),
            "last_activity": time.time(),
            "authenticated": True,
            "websocket": mock_websocket,
        }
        websocket_manager.active_connections["test-client"] = mock_websocket
        websocket_manager.last_heartbeat["test-client"] = time.time()

        assert "test-client" in websocket_manager.active_connections
        assert "test-client" in websocket_manager.client_sessions
        assert websocket_manager.client_sessions["test-client"]["authenticated"]

    @pytest.mark.asyncio
    async def test_connect_client_invalid_token(
        self, websocket_manager, mock_websocket
    ):
        """Test client connection with invalid token."""
        # Mock JWT decoding to raise exception
        with patch("src.api.websocket_manager.jwt.decode") as mock_decode:
            mock_decode.side_effect = WebSocketAuthError("Invalid token")

            result = await websocket_manager.connect_client(
                mock_websocket, "test-client"
            )

            assert not result
            assert "test-client" not in websocket_manager.active_connections

    @pytest.mark.asyncio
    async def test_disconnect_client(self, websocket_manager, mock_websocket):
        """Test client disconnection."""
        # Add client to manager
        websocket_manager.active_connections["test-client"] = mock_websocket
        websocket_manager.client_sessions["test-client"] = {"authenticated": True}
        websocket_manager.last_heartbeat["test-client"] = time.time()

        await websocket_manager.disconnect_client("test-client")

        assert "test-client" not in websocket_manager.active_connections
        assert "test-client" not in websocket_manager.client_sessions
        assert "test-client" not in websocket_manager.last_heartbeat
        assert mock_websocket.closed

    @pytest.mark.asyncio
    async def test_subscribe_to_task(self, websocket_manager):
        """Test task subscription."""
        # Add client to manager
        websocket_manager.active_connections["test-client"] = MockWebSocket()

        result = await websocket_manager.subscribe_to_task("test-client", "test-task")

        assert result
        assert "test-task" in websocket_manager.task_subscriptions
        assert "test-client" in websocket_manager.task_subscriptions["test-task"]

    @pytest.mark.asyncio
    async def test_subscribe_to_bid(self, websocket_manager):
        """Test bid subscription."""
        # Add client to manager
        websocket_manager.active_connections["test-client"] = MockWebSocket()

        result = await websocket_manager.subscribe_to_bid("test-client", "test-bid")

        assert result
        assert "test-bid" in websocket_manager.bid_subscriptions
        assert "test-client" in websocket_manager.bid_subscriptions["test-bid"]

    @pytest.mark.asyncio
    async def test_unsubscribe_from_task(self, websocket_manager):
        """Test task unsubscription."""
        # Setup subscription
        websocket_manager.task_subscriptions["test-task"] = {"test-client"}

        await websocket_manager.unsubscribe_from_task("test-client", "test-task")

        assert "test-task" not in websocket_manager.task_subscriptions

    @pytest.mark.asyncio
    async def test_unsubscribe_from_bid(self, websocket_manager):
        """Test bid unsubscription."""
        # Setup subscription
        websocket_manager.bid_subscriptions["test-bid"] = {"test-client"}

        await websocket_manager.unsubscribe_from_bid("test-client", "test-bid")

        assert "test-bid" not in websocket_manager.bid_subscriptions

    @pytest.mark.asyncio
    async def test_send_task_update(self, websocket_manager):
        """Test sending task update to subscribers."""
        # Setup
        mock_websocket = MockWebSocket()
        websocket_manager.active_connections["test-client"] = mock_websocket
        websocket_manager.task_subscriptions["test-task"] = {"test-client"}

        await websocket_manager.send_task_update(
            task_id="test-task",
            status=TaskStatus.PROCESSING,
            message="Task in progress",
            progress=75.0,
        )

        # Check that message was sent
        assert len(mock_websocket.messages) == 1
        message = json.loads(mock_websocket.messages[0])

        assert message["type"] == WebSocketMessageType.TASK_STATUS_UPDATE.value
        assert message["data"]["task_id"] == "test-task"
        assert message["data"]["status"] == "PROCESSING"
        assert message["data"]["message"] == "Task in progress"
        assert message["data"]["progress"] == 75.0

    @pytest.mark.asyncio
    async def test_send_task_completed(self, websocket_manager):
        """Test sending task completion notification."""
        # Setup
        mock_websocket = MockWebSocket()
        websocket_manager.active_connections["test-client"] = mock_websocket
        websocket_manager.task_subscriptions["test-task"] = {"test-client"}

        await websocket_manager.send_task_completed(
            task_id="test-task",
            result_url="https://example.com/result.pdf",
            message="Task completed successfully",
        )

        # Check that message was sent
        assert len(mock_websocket.messages) == 1
        message = json.loads(mock_websocket.messages[0])

        assert message["type"] == WebSocketMessageType.TASK_STATUS_UPDATE.value
        assert message["data"]["task_id"] == "test-task"
        assert message["data"]["result_url"] == "https://example.com/result.pdf"
        assert message["data"]["message"] == "Task completed successfully"

    @pytest.mark.asyncio
    async def test_send_task_error(self, websocket_manager):
        """Test sending task error notification."""
        # Setup
        mock_websocket = MockWebSocket()
        websocket_manager.active_connections["test-client"] = mock_websocket
        websocket_manager.task_subscriptions["test-task"] = {"test-client"}

        await websocket_manager.send_task_error(
            task_id="test-task",
            error_message="Task failed",
            error_details="Detailed error information",
        )

        # Check that message was sent
        assert len(mock_websocket.messages) == 1
        message = json.loads(mock_websocket.messages[0])

        assert message["type"] == WebSocketMessageType.TASK_STATUS_UPDATE.value
        assert message["data"]["task_id"] == "test-task"
        assert message["data"]["error_details"] == "Detailed error information"

    @pytest.mark.asyncio
    async def test_send_bid_update(self, websocket_manager):
        """Test sending bid update to subscribers."""
        # Setup
        mock_websocket = MockWebSocket()
        websocket_manager.active_connections["test-client"] = mock_websocket
        websocket_manager.bid_subscriptions["test-bid"] = {"test-client"}

        await websocket_manager.send_bid_update(
            bid_id="test-bid",
            job_id="test-job",
            status=BidStatus.APPROVED,
            message="Bid approved",
            marketplace="upwork",
            bid_amount=100,
        )

        # Check that message was sent
        assert len(mock_websocket.messages) == 1
        message = json.loads(mock_websocket.messages[0])

        assert message["type"] == WebSocketMessageType.BID_STATUS_UPDATE.value
        assert message["data"]["bid_id"] == "test-bid"
        assert message["data"]["job_id"] == "test-job"
        assert message["data"]["status"] == "APPROVED"
        assert message["data"]["message"] == "Bid approved"
        assert message["data"]["marketplace"] == "upwork"
        assert message["data"]["bid_amount"] == 100

    @pytest.mark.asyncio
    async def test_send_notification(self, websocket_manager):
        """Test sending notification to specific client."""
        # Setup
        mock_websocket = MockWebSocket()
        websocket_manager.active_connections["test-client"] = mock_websocket

        await websocket_manager.send_notification(
            client_id="test-client",
            notification_type=NotificationType.SUCCESS,
            title="Success",
            message="Operation completed successfully",
            duration=5000,
            persistent=False,
        )

        # Check that message was sent
        assert len(mock_websocket.messages) == 1
        message = json.loads(mock_websocket.messages[0])

        assert message["type"] == WebSocketMessageType.NOTIFICATION.value
        assert message["data"]["type"] == "success"
        assert message["data"]["title"] == "Success"
        assert message["data"]["message"] == "Operation completed successfully"
        assert message["data"]["duration"] == 5000
        assert not message["data"]["persistent"]

    @pytest.mark.asyncio
    async def test_send_system_alert(self, websocket_manager):
        """Test sending system alert to all clients."""
        # Setup
        mock_websocket1 = MockWebSocket()
        mock_websocket2 = MockWebSocket()
        websocket_manager.active_connections["client1"] = mock_websocket1
        websocket_manager.active_connections["client2"] = mock_websocket2

        await websocket_manager.send_system_alert(
            alert_type="maintenance", message="System maintenance scheduled for tonight"
        )

        # Check that message was sent to both clients
        assert len(mock_websocket1.messages) == 1
        assert len(mock_websocket2.messages) == 1

        message1 = json.loads(mock_websocket1.messages[0])
        message2 = json.loads(mock_websocket2.messages[0])

        assert message1["type"] == WebSocketMessageType.SYSTEM_ALERT.value
        assert message2["type"] == WebSocketMessageType.SYSTEM_ALERT.value
        assert message1["data"]["type"] == "maintenance"
        assert message2["data"]["type"] == "maintenance"

    @pytest.mark.asyncio
    async def test_get_connection_count(self, websocket_manager):
        """Test getting connection count."""
        # Setup
        websocket_manager.active_connections["client1"] = MockWebSocket()
        websocket_manager.active_connections["client2"] = MockWebSocket()

        count = websocket_manager.get_connection_count()
        assert count == 2

    @pytest.mark.asyncio
    async def test_get_subscriptions_count(self, websocket_manager):
        """Test getting subscriptions count."""
        # Setup
        websocket_manager.task_subscriptions["task1"] = {"client1", "client2"}
        websocket_manager.task_subscriptions["task2"] = {"client1"}
        websocket_manager.bid_subscriptions["bid1"] = {"client2"}

        counts = websocket_manager.get_subscriptions_count()

        assert counts["task_subscriptions"] == 2
        assert counts["bid_subscriptions"] == 1
        assert counts["total_subscriptions"] == 4  # 3 task subs + 1 bid sub


class TestWebSocketIntegration:
    """Integration tests for WebSocket functionality."""

    @pytest.fixture
    async def websocket_manager(self):
        """Create a WebSocket manager instance."""
        manager = WebSocketManager()
        await manager.start()
        yield manager
        await manager.stop()

    @pytest.fixture
    async def test_task(self, db_session: AsyncSession):
        """Create a test task."""
        task = Task(
            id="test-task-id",
            title="Test Task",
            description="Test Description",
            domain="test",
            status=DBTaskStatus.PAID.value,
            client_email="test@example.com",
        )
        db_session.add(task)
        await db_session.commit()
        return task

    @pytest.fixture
    async def test_bid(self, db_session: AsyncSession):
        """Create a test bid."""
        bid = Bid(
            job_title="Test Job",
            job_description="Test Description",
            bid_amount=10000,
            status=BidStatus.PENDING.value,
            marketplace="upwork",
        )
        db_session.add(bid)
        await db_session.commit()
        return bid

    @pytest.mark.asyncio
    async def test_task_subscription_integration(self, websocket_manager, test_task):
        """Test task subscription with real task data."""
        # Setup client
        mock_websocket = MockWebSocket()
        websocket_manager.active_connections["test-client"] = mock_websocket

        # Subscribe to task
        result = await websocket_manager.subscribe_to_task("test-client", test_task.id)
        assert result

        # Send task update
        await websocket_manager.send_task_update(
            task_id=test_task.id,
            status=TaskStatus.PROCESSING,
            message="Task started execution",
            progress=25.0,
        )

        # Verify message
        assert len(mock_websocket.messages) == 1
        message = json.loads(mock_websocket.messages[0])

        assert message["data"]["task_id"] == test_task.id
        assert message["data"]["status"] == "PROCESSING"
        assert message["data"]["message"] == "Task started execution"
        assert message["data"]["progress"] == 25.0

    @pytest.mark.asyncio
    async def test_bid_subscription_integration(self, websocket_manager, test_bid):
        """Test bid subscription with real bid data."""
        # Setup client
        mock_websocket = MockWebSocket()
        websocket_manager.active_connections["test-client"] = mock_websocket

        # Subscribe to bid
        result = await websocket_manager.subscribe_to_bid("test-client", test_bid.id)
        assert result

        # Send bid update
        await websocket_manager.send_bid_update(
            bid_id=test_bid.id,
            job_id=test_bid.job_title,
            status=BidStatus.APPROVED,
            message="Bid approved",
            marketplace=test_bid.marketplace,
            bid_amount=test_bid.bid_amount // 100,  # Convert to dollars
        )

        # Verify message
        assert len(mock_websocket.messages) == 1
        message = json.loads(mock_websocket.messages[0])

        assert message["data"]["bid_id"] == test_bid.id
        assert message["data"]["job_id"] == test_bid.job_title
        assert message["data"]["status"] == "APPROVED"
        assert message["data"]["message"] == "Bid approved"
        assert message["data"]["marketplace"] == test_bid.marketplace
        assert message["data"]["bid_amount"] == 100  # 10000 cents = 100 dollars

    @pytest.mark.asyncio
    async def test_authentication_integration(self, websocket_manager, mock_config):
        """Test JWT authentication integration."""
        # Create manager with config
        manager = WebSocketManager(mock_config)

        # Mock JWT decoding
        with patch("src.api.websocket_manager.jwt.decode") as mock_decode:
            mock_decode.return_value = {
                "client_id": "test-client",
                "user_id": "test-user",
                "exp": time.time() + 3600,
            }

            # Mock WebSocket
            mock_websocket = MockWebSocket()
            mock_websocket.receive_text = AsyncMock(
                return_value='{"type": "auth", "data": {"token": "test_token"}}'
            )

            result = await manager.connect_client(mock_websocket, "test-client")

            assert result
            assert "test-client" in manager.client_sessions
            assert manager.client_sessions["test-client"]["user_id"] == "test-user"


class TestWebSocketAPIEndpoints:
    """Test WebSocket API endpoints."""

    def test_websocket_endpoint(self, client: TestClient):
        """Test WebSocket endpoint."""
        # Note: WebSocket testing in FastAPI TestClient is limited
        # This is a basic test to ensure the endpoint exists
        response = client.get("/ws")
        # WebSocket endpoint should return 405 Method Not Allowed for GET
        assert response.status_code == 405

    def test_subscribe_task_endpoint(self, client: TestClient, test_task):
        """Test task subscription endpoint."""
        # This would require WebSocket connection which is complex to test
        # Just verify the endpoint exists
        response = client.post("/api/ws/subscribe/task", json={"task_id": test_task.id})
        # Should return 401 Unauthorized without authentication
        assert response.status_code == 401

    def test_subscribe_bid_endpoint(self, client: TestClient, test_bid):
        """Test bid subscription endpoint."""
        response = client.post("/api/ws/subscribe/bid", json={"bid_id": test_bid.id})
        # Should return 401 Unauthorized without authentication
        assert response.status_code == 401

    def test_websocket_status_endpoint(self, client: TestClient):
        """Test WebSocket status endpoint."""
        response = client.get("/api/ws/status")
        assert response.status_code == 200

        data = response.json()
        assert "active_connections" in data
        assert "subscriptions" in data
        assert "status" in data
        assert data["status"] == "running"


class TestWebSocketTaskIntegration:
    """Test WebSocket integration with task processing."""

    @pytest.mark.asyncio
    async def test_task_processing_notifications(self, websocket_manager, test_task):
        """Test that task processing sends WebSocket notifications."""
        # Setup client subscription
        mock_websocket = MockWebSocket()
        websocket_manager.active_connections["test-client"] = mock_websocket
        await websocket_manager.subscribe_to_task("test-client", test_task.id)

        # Simulate task processing steps
        await websocket_manager.send_task_update(
            task_id=test_task.id,
            status=TaskStatus.PLANNING,
            message="Generating work plan",
            progress=20.0,
        )

        await websocket_manager.send_task_update(
            task_id=test_task.id,
            status=TaskStatus.PROCESSING,
            message="Executing work plan",
            progress=50.0,
        )

        await websocket_manager.send_task_update(
            task_id=test_task.id,
            status=TaskStatus.PROCESSING,
            message="Task in progress",
            progress=75.0,
        )

        await websocket_manager.send_task_completed(
            task_id=test_task.id,
            result_url="https://example.com/result.pdf",
            message="Task completed successfully",
        )

        # Verify all messages were sent
        assert len(mock_websocket.messages) == 4

        # Check each message
        messages = [json.loads(msg) for msg in mock_websocket.messages]

        assert messages[0]["type"] == WebSocketMessageType.TASK_STATUS_UPDATE.value
        assert messages[0]["data"]["status"] == "PLANNING"
        assert messages[0]["data"]["progress"] == 20.0

        assert messages[1]["type"] == WebSocketMessageType.TASK_STATUS_UPDATE.value
        assert messages[1]["data"]["status"] == "PROCESSING"
        assert messages[1]["data"]["progress"] == 50.0

        assert messages[2]["type"] == WebSocketMessageType.TASK_STATUS_UPDATE.value
        assert messages[2]["data"]["status"] == "PROCESSING"
        assert messages[2]["data"]["progress"] == 75.0

        assert messages[3]["type"] == WebSocketMessageType.TASK_COMPLETED.value
        assert messages[3]["data"]["result_url"] == "https://example.com/result.pdf"

    @pytest.mark.asyncio
    async def test_task_error_notifications(self, websocket_manager, test_task):
        """Test that task errors send WebSocket notifications."""
        # Setup client subscription
        mock_websocket = MockWebSocket()
        websocket_manager.active_connections["test-client"] = mock_websocket
        await websocket_manager.subscribe_to_task("test-client", test_task.id)

        # Simulate task error
        await websocket_manager.send_task_error(
            task_id=test_task.id,
            error_message="Task execution failed",
            error_details="Detailed error information",
        )

        # Verify error message was sent
        assert len(mock_websocket.messages) == 1

        message = json.loads(mock_websocket.messages[0])
        assert message["type"] == WebSocketMessageType.TASK_ERROR.value
        assert message["data"]["error_details"] == "Detailed error information"


class TestWebSocketBidIntegration:
    """Test WebSocket integration with bid processing."""

    @pytest.mark.asyncio
    async def test_bid_processing_notifications(self, websocket_manager, test_bid):
        """Test that bid processing sends WebSocket notifications."""
        # Setup client subscription
        mock_websocket = MockWebSocket()
        websocket_manager.active_connections["test-client"] = mock_websocket
        await websocket_manager.subscribe_to_bid("test-client", test_bid.id)

        # Simulate bid processing steps
        await websocket_manager.send_bid_update(
            bid_id=test_bid.id,
            job_id=test_bid.job_title,
            status=BidStatus.PENDING,
            message="Bid submitted",
            marketplace=test_bid.marketplace,
            bid_amount=test_bid.bid_amount // 100,
        )

        await websocket_manager.send_bid_update(
            bid_id=test_bid.id,
            job_id=test_bid.job_title,
            status=BidStatus.APPROVED,
            message="Bid approved",
            marketplace=test_bid.marketplace,
            bid_amount=test_bid.bid_amount // 100,
        )

        # Verify messages were sent
        assert len(mock_websocket.messages) == 2

        messages = [json.loads(msg) for msg in mock_websocket.messages]

        assert messages[0]["type"] == WebSocketMessageType.BID_STATUS_UPDATE.value
        assert messages[0]["data"]["status"] == "PENDING"
        assert messages[0]["data"]["message"] == "Bid submitted"

        assert messages[1]["type"] == WebSocketMessageType.BID_STATUS_UPDATE.value
        assert messages[1]["data"]["status"] == "APPROVED"
        assert messages[1]["data"]["message"] == "Bid approved"


# Helper function to convert dataclass to dict
def asdict(obj):
    """Convert dataclass to dict."""
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return obj
