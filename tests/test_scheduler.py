"""
Tests for the Advanced Task Scheduler and Cron Expressions.

Tests cron expression parsing, recurring tasks, intelligent scheduling,
pause/resume functionality, and schedule analytics.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
import pytz

from src.agent_execution.scheduler import (
    TaskScheduler,
    CronExpressionValidator,
    IntelligentScheduler,
    ScheduleStatus,
    ScheduleType,
    schedule_daily_task,
    schedule_weekly_task,
    schedule_monthly_task,
)


class TestCronExpressionValidator:
    """Test cron expression validation and utilities."""

    def test_validate_expression_valid(self):
        """Test validation of valid cron expressions."""
        valid_expressions = [
            "0 9 * * *",  # Daily at 9 AM
            "0 0 * * *",  # Daily at midnight
            "0 */6 * * *",  # Every 6 hours
            "*/30 * * * *",  # Every 30 minutes
            "0 9 * * 1-5",  # Weekdays at 9 AM
            "0 9 1 * *",  # First of month at 9 AM
        ]

        for expression in valid_expressions:
            assert CronExpressionValidator.validate_expression(expression)

    def test_validate_expression_invalid(self):
        """Test validation of invalid cron expressions."""
        invalid_expressions = [
            "invalid",  # Not a cron expression
            "0 25 * * *",  # Invalid hour (25)
            "60 * * * *",  # Invalid minute (60)
            "0 9 * * 8",  # Invalid day of week (8)
            "0 9 32 * *",  # Invalid day of month (32)
            "0 9 * * * *",  # Too many fields
            "0 9",  # Too few fields
        ]

        for expression in invalid_expressions:
            assert not CronExpressionValidator.validate_expression(expression)

    def test_get_next_occurrence(self):
        """Test getting next occurrence for cron expressions."""
        expression = "0 9 * * *"  # Daily at 9 AM
        next_time = CronExpressionValidator.get_next_occurrence(expression)

        assert isinstance(next_time, datetime)
        assert next_time.hour == 9
        assert next_time.minute == 0
        assert next_time >= datetime.now(pytz.UTC)

    def test_get_human_readable(self):
        """Test conversion to human-readable format."""
        test_cases = [
            ("0 9 * * *", "Every day at 9:00 AM"),
            ("0 17 * * *", "Every day at 5:00 PM"),
            ("0 0 * * *", "Every day at 12:00 AM"),
            ("0 12 * * *", "Every day at 12:00 PM"),
            ("0 0 * * 1", "Every Monday at 12:00 AM"),
            ("0 0 1 * *", "First day of every month at 12:00 AM"),
            ("0 */6 * * *", "Every 6 hours"),
            ("0 */12 * * *", "Every 12 hours"),
            ("*/30 * * * *", "Every 30 minutes"),
            ("*/15 * * * *", "Every 15 minutes"),
            ("custom", "Custom cron: custom"),
        ]

        for expression, expected in test_cases:
            result = CronExpressionValidator.get_human_readable(expression)
            assert result == expected


class TestIntelligentScheduler:
    """Test intelligent scheduling logic."""

    def test_should_avoid_peak_hours(self):
        """Test peak hours avoidance logic."""
        scheduler = IntelligentScheduler()

        # Mock schedule that avoids peak hours
        mock_schedule = Mock()
        mock_schedule.avoid_peak_hours = True
        assert scheduler.should_avoid_peak_hours(mock_schedule)

        # Mock schedule that doesn't avoid peak hours
        mock_schedule.avoid_peak_hours = False
        assert not scheduler.should_avoid_peak_hours(mock_schedule)

    def test_get_optimal_time_business_hours(self):
        """Test optimal time calculation during business hours."""
        scheduler = IntelligentScheduler()

        # Create a time during business hours (10 AM on a Monday)
        base_time = datetime(2023, 1, 2, 10, 0, 0)  # Monday

        # Mock schedule that avoids peak hours
        mock_schedule = Mock()
        mock_schedule.avoid_peak_hours = True

        optimal_time = scheduler.get_optimal_time(base_time, mock_schedule)

        # Should be moved to 5 PM (end of business hours)
        assert optimal_time.hour == 17
        assert optimal_time.minute == 0

    def test_get_optimal_time_after_hours(self):
        """Test optimal time calculation after business hours."""
        scheduler = IntelligentScheduler()

        # Create a time after business hours (6 PM)
        base_time = datetime(2023, 1, 1, 18, 0, 0)

        # Mock schedule that avoids peak hours
        mock_schedule = Mock()
        mock_schedule.avoid_peak_hours = True

        optimal_time = scheduler.get_optimal_time(base_time, mock_schedule)

        # Should be moved to next day morning (6 AM)
        assert optimal_time.hour == 6
        assert optimal_time.minute == 0
        assert optimal_time.day == 2  # Next day

    def test_get_optimal_time_weekend(self):
        """Test optimal time calculation on weekends."""
        scheduler = IntelligentScheduler()

        # Create a time on weekend (Saturday 10 AM)
        base_time = datetime(2023, 1, 7, 10, 0, 0)  # Saturday

        # Mock schedule that avoids peak hours
        mock_schedule = Mock()
        mock_schedule.avoid_peak_hours = True

        optimal_time = scheduler.get_optimal_time(base_time, mock_schedule)

        # Should be moved to next business day morning
        assert optimal_time.hour == 6
        assert optimal_time.minute == 0
        assert optimal_time.day == 9  # Monday

    def test_should_batch_tasks(self):
        """Test task batching logic."""
        scheduler = IntelligentScheduler()

        # Mock schedule with batching enabled
        mock_schedule = Mock()
        mock_schedule.batch_size = 5
        assert scheduler.should_batch_tasks(mock_schedule)

        # Mock schedule without batching
        mock_schedule.batch_size = 1
        assert not scheduler.should_batch_tasks(mock_schedule)

    def test_get_batch_window(self):
        """Test batch window calculation."""
        scheduler = IntelligentScheduler()

        base_time = datetime(2023, 1, 1, 9, 0, 0)
        start, end = scheduler.get_batch_window(base_time)

        assert start == base_time
        assert end == base_time + timedelta(minutes=30)  # Default batch window size


class TestTaskScheduler:
    """Test the main task scheduler."""

    @pytest.fixture
    async def scheduler(self, db_session: AsyncSession):
        """Create a task scheduler instance."""
        scheduler = TaskScheduler(db_session=db_session)
        await scheduler.initialize()
        yield scheduler
        await scheduler.shutdown()

    @pytest.fixture
    async def test_task_data(self):
        """Create test task data."""
        return {
            "title": "Test Task",
            "description": "Test Description",
            "domain": "test",
            "parameters": {"key": "value"},
        }

    @pytest.mark.asyncio
    async def test_schedule_task_once(self, scheduler, test_task_data):
        """Test scheduling a one-time task."""
        schedule_id = await scheduler.schedule_task(
            task_data=test_task_data,
            cron_expression="0 9 * * *",
            schedule_type=ScheduleType.ONCE,
            title="One-time Test Task",
        )

        assert schedule_id is not None

        # Verify schedule was created in database
        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule is not None
        assert schedule.title == "One-time Test Task"
        assert schedule.schedule_type == ScheduleType.ONCE
        assert schedule.cron_expression == "0 9 * * *"
        assert schedule.status == ScheduleStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_schedule_task_recurring(self, scheduler, test_task_data):
        """Test scheduling a recurring task."""
        schedule_id = await scheduler.schedule_task(
            task_data=test_task_data,
            cron_expression="0 9 * * *",
            schedule_type=ScheduleType.RECURRING,
            title="Recurring Test Task",
        )

        assert schedule_id is not None

        # Verify schedule was created
        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule is not None
        assert schedule.schedule_type == ScheduleType.RECURRING
        assert schedule.max_runs is None  # Unlimited

    @pytest.mark.asyncio
    async def test_schedule_task_with_max_runs(self, scheduler, test_task_data):
        """Test scheduling a task with maximum run limit."""
        schedule_id = await scheduler.schedule_task(
            task_data=test_task_data,
            cron_expression="0 9 * * *",
            schedule_type=ScheduleType.RECURRING,
            title="Limited Test Task",
            max_runs=5,
        )

        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule.max_runs == 5

    @pytest.mark.asyncio
    async def test_pause_schedule(self, scheduler, test_task_data):
        """Test pausing a scheduled task."""
        schedule_id = await scheduler.schedule_task(
            task_data=test_task_data,
            cron_expression="0 9 * * *",
            title="Test Task to Pause",
        )

        # Pause the schedule
        result = await scheduler.pause_schedule(schedule_id)
        assert result

        # Verify status changed
        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule.status == ScheduleStatus.PAUSED

    @pytest.mark.asyncio
    async def test_resume_schedule(self, scheduler, test_task_data):
        """Test resuming a paused scheduled task."""
        schedule_id = await scheduler.schedule_task(
            task_data=test_task_data,
            cron_expression="0 9 * * *",
            title="Test Task to Resume",
        )

        # Pause then resume
        await scheduler.pause_schedule(schedule_id)
        result = await scheduler.resume_schedule(schedule_id)
        assert result

        # Verify status changed back to active
        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule.status == ScheduleStatus.ACTIVE
        assert schedule.next_run_at is not None

    @pytest.mark.asyncio
    async def test_cancel_schedule(self, scheduler, test_task_data):
        """Test cancelling a scheduled task."""
        schedule_id = await scheduler.schedule_task(
            task_data=test_task_data,
            cron_expression="0 9 * * *",
            title="Test Task to Cancel",
        )

        # Cancel the schedule
        result = await scheduler.cancel_schedule(schedule_id)
        assert result

        # Verify status changed
        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule.status == ScheduleStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_list_schedules(self, scheduler, test_task_data):
        """Test listing scheduled tasks."""
        # Create multiple schedules
        schedule_ids = []
        for i in range(3):
            schedule_id = await scheduler.schedule_task(
                task_data=test_task_data,
                cron_expression=f"0 {9 + i} * * *",
                title=f"Test Task {i}",
            )
            schedule_ids.append(schedule_id)

        # List all schedules
        schedules = await scheduler.list_schedules()
        assert len(schedules) >= 3

        # List by status
        active_schedules = await scheduler.list_schedules(ScheduleStatus.ACTIVE)
        assert len(active_schedules) >= 3

    @pytest.mark.asyncio
    async def test_get_schedule_analytics(self, scheduler, test_task_data):
        """Test getting schedule analytics."""
        schedule_id = await scheduler.schedule_task(
            task_data=test_task_data,
            cron_expression="0 9 * * *",
            title="Test Task for Analytics",
        )

        # Get analytics
        analytics = await scheduler.get_schedule_analytics(schedule_id)

        assert analytics["schedule_id"] == schedule_id
        assert analytics["title"] == "Test Task for Analytics"
        assert analytics["total_executions"] == 0
        assert analytics["successful_executions"] == 0
        assert analytics["failed_executions"] == 0
        assert analytics["success_rate"] == 0.0
        assert analytics["avg_execution_time_ms"] == 0.0

    @pytest.mark.asyncio
    async def test_register_callback(self, scheduler):
        """Test registering a callback for a schedule."""

        async def test_callback(task_data):
            return "Task executed successfully"

        schedule_id = "test-schedule-id"
        await scheduler.register_callback(schedule_id, test_callback)

        assert schedule_id in scheduler._scheduled_callbacks
        assert scheduler._scheduled_callbacks[schedule_id] == test_callback

    @pytest.mark.asyncio
    async def test_common_schedule_creation(self):
        """Test creating common schedule configurations."""
        task_data = {"test": "data"}

        # Test daily schedule
        daily_config = TaskScheduler.create_common_schedule(
            task_data=task_data, schedule_type="daily_9am", title="Daily Report"
        )
        assert daily_config["cron_expression"] == "0 9 * * *"
        assert daily_config["description"] == "Every day at 9:00 AM"

        # Test weekly schedule
        weekly_config = TaskScheduler.create_common_schedule(
            task_data=task_data, schedule_type="weekly_monday", title="Weekly Report"
        )
        assert weekly_config["cron_expression"] == "0 9 * * 1"
        assert weekly_config["description"] == "Every Monday at 9:00 AM"

        # Test monthly schedule
        monthly_config = TaskScheduler.create_common_schedule(
            task_data=task_data, schedule_type="monthly_1st", title="Monthly Report"
        )
        assert monthly_config["cron_expression"] == "0 9 1 * *"
        assert monthly_config["description"] == "First day of every month at 9:00 AM"

        # Test invalid schedule type
        with pytest.raises(Exception):
            TaskScheduler.create_common_schedule(
                task_data=task_data, schedule_type="invalid", title="Invalid Schedule"
            )


class TestConvenienceFunctions:
    """Test convenience scheduling functions."""

    @pytest.fixture
    async def scheduler(self, db_session: AsyncSession):
        """Create a task scheduler instance."""
        scheduler = TaskScheduler(db_session=db_session)
        await scheduler.initialize()
        yield scheduler
        await scheduler.shutdown()

    @pytest.fixture
    def test_task_data(self):
        """Create test task data."""
        return {"test": "data"}

    @pytest.mark.asyncio
    async def test_schedule_daily_task(self, scheduler, test_task_data):
        """Test scheduling a daily task."""
        schedule_id = await schedule_daily_task(
            scheduler=scheduler,
            task_data=test_task_data,
            time_of_day="10:30",
            title="Daily Morning Task",
        )

        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule.cron_expression == "30 10 * * *"
        assert schedule.title == "Daily Morning Task"

    @pytest.mark.asyncio
    async def test_schedule_weekly_task(self, scheduler, test_task_data):
        """Test scheduling a weekly task."""
        schedule_id = await schedule_weekly_task(
            scheduler=scheduler,
            task_data=test_task_data,
            day_of_week=3,  # Wednesday
            time_of_day="14:00",
            title="Weekly Wednesday Task",
        )

        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule.cron_expression == "0 14 * * 3"
        assert schedule.title == "Weekly Wednesday Task"

    @pytest.mark.asyncio
    async def test_schedule_monthly_task(self, scheduler, test_task_data):
        """Test scheduling a monthly task."""
        schedule_id = await schedule_monthly_task(
            scheduler=scheduler,
            task_data=test_task_data,
            day_of_month=15,
            time_of_day="08:00",
            title="Monthly Mid-Month Task",
        )

        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule.cron_expression == "0 8 15 * *"
        assert schedule.title == "Monthly Mid-Month Task"


class TestSchedulerIntegration:
    """Integration tests for the scheduler."""

    @pytest.mark.asyncio
    async def test_scheduler_lifecycle(self, db_session: AsyncSession):
        """Test complete scheduler lifecycle."""
        scheduler = TaskScheduler(db_session=db_session)

        # Initialize
        await scheduler.initialize()
        assert scheduler.is_running

        # Shutdown
        await scheduler.shutdown()
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_scheduler_with_real_database(self, db_session: AsyncSession):
        """Test scheduler with real database operations."""
        scheduler = TaskScheduler(db_session=db_session)
        await scheduler.initialize()

        try:
            # Schedule a task
            task_data = {"test": "integration"}
            schedule_id = await scheduler.schedule_task(
                task_data=task_data,
                cron_expression="0 9 * * *",
                title="Integration Test Task",
            )

            # Verify it was created
            schedule = await scheduler.get_schedule(schedule_id)
            assert schedule is not None
            assert schedule.title == "Integration Test Task"

            # List schedules
            schedules = await scheduler.list_schedules()
            assert len(schedules) > 0

            # Get analytics
            analytics = await scheduler.get_schedule_analytics(schedule_id)
            assert analytics["schedule_id"] == schedule_id

        finally:
            await scheduler.shutdown()


class TestSchedulerAPIEndpoints:
    """Test the scheduler API endpoints."""

    def test_schedule_task_endpoint(self, client: TestClient):
        """Test the schedule task endpoint."""
        request_data = {
            "title": "API Test Task",
            "description": "Test task created via API",
            "domain": "test",
            "cron_expression": "0 9 * * *",
            "schedule_type": "RECURRING",
            "task_data": {"test": "data"},
            "timezone": "UTC",
            "avoid_peak_hours": True,
            "batch_size": 1,
            "priority": 1,
        }

        response = client.post("/api/scheduler/schedule", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "message" in data
        assert "schedule_id" in data
        assert "next_run_at" in data

    def test_schedule_task_invalid_cron(self, client: TestClient):
        """Test scheduling with invalid cron expression."""
        request_data = {
            "title": "Invalid Task",
            "cron_expression": "invalid",
            "schedule_type": "RECURRING",
            "task_data": {"test": "data"},
        }

        response = client.post("/api/scheduler/schedule", json=request_data)
        assert response.status_code == 400

        data = response.json()
        assert "Invalid cron expression" in data["detail"]

    def test_list_schedules_endpoint(self, client: TestClient):
        """Test the list schedules endpoint."""
        response = client.get("/api/scheduler/schedules")
        assert response.status_code == 200

        data = response.json()
        assert "schedules" in data

    def test_get_schedule_endpoint(self, client: TestClient):
        """Test getting a specific schedule."""
        # First create a schedule
        request_data = {
            "title": "Test Schedule",
            "cron_expression": "0 9 * * *",
            "schedule_type": "RECURRING",
            "task_data": {"test": "data"},
        }

        create_response = client.post("/api/scheduler/schedule", json=request_data)
        assert create_response.status_code == 200
        schedule_id = create_response.json()["schedule_id"]

        # Get the schedule
        response = client.get(f"/api/scheduler/schedules/{schedule_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == schedule_id
        assert data["title"] == "Test Schedule"

    def test_pause_schedule_endpoint(self, client: TestClient):
        """Test pausing a schedule via API."""
        # Create a schedule
        request_data = {
            "title": "Pause Test",
            "cron_expression": "0 9 * * *",
            "schedule_type": "RECURRING",
            "task_data": {"test": "data"},
        }

        create_response = client.post("/api/scheduler/schedule", json=request_data)
        schedule_id = create_response.json()["schedule_id"]

        # Pause it
        response = client.post(f"/api/scheduler/schedules/{schedule_id}/pause")
        assert response.status_code == 200

        data = response.json()
        assert "paused successfully" in data["message"]

    def test_validate_cron_endpoint(self, client: TestClient):
        """Test the cron validation endpoint."""
        # Test valid expression
        response = client.get("/api/scheduler/cron/validate?expression=0+9+*+*+*")
        assert response.status_code == 200

        data = response.json()
        assert data["valid"]
        assert "next_occurrence" in data
        assert "human_readable" in data

        # Test invalid expression
        response = client.get("/api/scheduler/cron/validate?expression=invalid")
        assert response.status_code == 200

        data = response.json()
        assert not data["valid"]
        assert "error" in data

    def test_common_cron_expressions_endpoint(self, client: TestClient):
        """Test the common cron expressions endpoint."""
        response = client.get("/api/scheduler/cron/common")
        assert response.status_code == 200

        data = response.json()
        assert "common_expressions" in data
        assert "daily_9am" in data["common_expressions"]
        assert "weekly_monday" in data["common_expressions"]

    def test_scheduler_status_endpoint(self, client: TestClient):
        """Test the scheduler status endpoint."""
        response = client.get("/api/scheduler/status")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert "schedule_counts" in data
        assert "total_executions" in data


# Helper function to create test data
def create_test_schedule_data():
    """Create test schedule data for testing."""
    return {
        "title": "Test Schedule",
        "description": "Test Description",
        "domain": "test",
        "cron_expression": "0 9 * * *",
        "schedule_type": "RECURRING",
        "task_data": {"test": "data", "parameters": {"key": "value"}},
        "timezone": "UTC",
        "avoid_peak_hours": True,
        "batch_size": 1,
        "priority": 1,
        "max_runs": None,
    }
