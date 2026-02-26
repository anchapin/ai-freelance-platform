"""
Tests for the advanced task scheduling system.

Tests cron expression validation, task scheduling, execution, pause/resume,
analytics, and intelligent scheduling features.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.agent_execution.scheduler import (
    TaskScheduler,
    CronExpressionValidator,
    IntelligentScheduler,
    ScheduleStatus,
    ScheduleType,
    schedule_daily_task,
    schedule_weekly_task,
    schedule_monthly_task
)
from src.api.models import ScheduledTask, ScheduleHistory
from src.agent_execution.errors import SchedulingError


class TestCronExpressionValidator:
    """Test cron expression validation and utilities."""
    
    def test_validate_valid_expression(self):
        """Test that valid cron expressions are accepted."""
        assert CronExpressionValidator.validate_expression("0 9 * * *") == True
        assert CronExpressionValidator.validate_expression("0 */6 * * *") == True
        assert CronExpressionValidator.validate_expression("*/30 * * * *") == True
    
    def test_validate_invalid_expression(self):
        """Test that invalid cron expressions are rejected."""
        assert CronExpressionValidator.validate_expression("invalid") == False
        assert CronExpressionValidator.validate_expression("0 25 * * *") == False  # Invalid hour
        assert CronExpressionValidator.validate_expression("0 9 * * * *") == False  # Too many fields
    
    def test_get_next_occurrence(self):
        """Test calculating next occurrence."""
        next_time = CronExpressionValidator.get_next_occurrence("0 9 * * *")
        assert isinstance(next_time, datetime)
        assert next_time.hour == 9
        assert next_time.minute == 0
    
    def test_get_human_readable(self):
        """Test human-readable expression conversion."""
        assert CronExpressionValidator.get_human_readable("0 9 * * *") == "Every day at 9:00 AM"
        assert CronExpressionValidator.get_human_readable("0 17 * * *") == "Every day at 5:00 PM"
        assert "Cron expression:" in CronExpressionValidator.get_human_readable("0 9 15 * *")


class TestIntelligentScheduler:
    """Test intelligent scheduling logic."""
    
    def test_should_avoid_peak_hours(self):
        """Test peak hours avoidance logic."""
        scheduler = IntelligentScheduler()
        
        # Create a mock schedule that avoids peak hours
        mock_schedule = Mock()
        mock_schedule.avoid_peak_hours = True
        
        assert scheduler.should_avoid_peak_hours(mock_schedule) == True
        
        # Create a mock schedule that doesn't avoid peak hours
        mock_schedule.avoid_peak_hours = False
        assert scheduler.should_avoid_peak_hours(mock_schedule) == False
    
    def test_get_optimal_time_avoid_peak_hours(self):
        """Test optimal time calculation avoiding peak hours."""
        scheduler = IntelligentScheduler()
        
        # Create a mock schedule that avoids peak hours
        mock_schedule = Mock()
        mock_schedule.avoid_peak_hours = True
        
        # Test with time during peak hours (10 AM)
        peak_time = datetime(2026, 2, 25, 10, 30, 0)
        optimal_time = scheduler.get_optimal_time(peak_time, mock_schedule)
        
        # Should be moved to 5 PM same day
        assert optimal_time.hour == 17
        assert optimal_time.minute == 0
        assert optimal_time.date() == peak_time.date()
    
    def test_get_optimal_time_after_peak_hours(self):
        """Test optimal time calculation after peak hours."""
        scheduler = IntelligentScheduler()
        
        # Create a mock schedule that avoids peak hours
        mock_schedule = Mock()
        mock_schedule.avoid_peak_hours = True
        
        # Test with time after peak hours (6 PM)
        after_peak_time = datetime(2026, 2, 25, 18, 30, 0)
        optimal_time = scheduler.get_optimal_time(after_peak_time, mock_schedule)
        
        # Should be moved to next day morning
        assert optimal_time.hour == 6
        assert optimal_time.minute == 0
        assert optimal_time.date() == (after_peak_time + timedelta(days=1)).date()
    
    def test_get_optimal_time_no_peak_avoidance(self):
        """Test optimal time calculation when not avoiding peak hours."""
        scheduler = IntelligentScheduler()
        
        # Create a mock schedule that doesn't avoid peak hours
        mock_schedule = Mock()
        mock_schedule.avoid_peak_hours = False
        
        # Test with time during peak hours
        peak_time = datetime(2026, 2, 25, 10, 30, 0)
        optimal_time = scheduler.get_optimal_time(peak_time, mock_schedule)
        
        # Should remain unchanged
        assert optimal_time == peak_time


class TestTaskScheduler:
    """Test the main task scheduler."""
    
    @pytest.fixture
    async def scheduler(self, db_session: AsyncSession):
        """Create a scheduler instance with database session."""
        scheduler = TaskScheduler(db_session)
        await scheduler.initialize()
        yield scheduler
        await scheduler.shutdown()
    
    @pytest.fixture
    async def mock_callback(self):
        """Create a mock callback function."""
        return AsyncMock(return_value="Task completed successfully")
    
    async def test_schedule_task_success(self, scheduler, mock_callback):
        """Test successful task scheduling."""
        task_data = {
            "title": "Test Task",
            "description": "Test Description",
            "domain": "test"
        }
        
        # Register callback
        schedule_id = await scheduler.schedule_task(
            task_data=task_data,
            cron_expression="0 9 * * *",
            title="Test Daily Task"
        )
        
        # Verify schedule was created
        assert schedule_id is not None
        
        # Get the created schedule
        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule is not None
        assert schedule.title == "Test Daily Task"
        assert schedule.cron_expression == "0 9 * * *"
        assert schedule.status == ScheduleStatus.ACTIVE
        assert schedule.schedule_type == ScheduleType.RECURRING
    
    async def test_schedule_task_invalid_cron(self, scheduler):
        """Test scheduling with invalid cron expression."""
        task_data = {"test": "data"}
        
        with pytest.raises(SchedulingError, match="Invalid cron expression"):
            await scheduler.schedule_task(
                task_data=task_data,
                cron_expression="invalid_cron"
            )
    
    async def test_pause_resume_schedule(self, scheduler):
        """Test pausing and resuming a schedule."""
        # Create a schedule
        schedule_id = await scheduler.schedule_task(
            task_data={"test": "data"},
            cron_expression="0 9 * * *"
        )
        
        # Pause the schedule
        result = await scheduler.pause_schedule(schedule_id)
        assert result == True
        
        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule.status == ScheduleStatus.PAUSED
        
        # Resume the schedule
        result = await scheduler.resume_schedule(schedule_id)
        assert result == True
        
        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule.status == ScheduleStatus.ACTIVE
        assert schedule.next_run_at is not None
    
    async def test_cancel_schedule(self, scheduler):
        """Test canceling a schedule."""
        # Create a schedule
        schedule_id = await scheduler.schedule_task(
            task_data={"test": "data"},
            cron_expression="0 9 * * *"
        )
        
        # Cancel the schedule
        result = await scheduler.cancel_schedule(schedule_id)
        assert result == True
        
        schedule = await scheduler.get_schedule(schedule_id)
        assert schedule.status == ScheduleStatus.CANCELLED
    
    async def test_list_schedules(self, scheduler):
        """Test listing schedules."""
        # Create multiple schedules
        schedule1_id = await scheduler.schedule_task(
            task_data={"test": "data1"},
            cron_expression="0 9 * * *",
            title="Schedule 1"
        )
        
        schedule2_id = await scheduler.schedule_task(
            task_data={"test": "data2"},
            cron_expression="0 17 * * *",
            title="Schedule 2"
        )
        
        # List all schedules
        all_schedules = await scheduler.list_schedules()
        assert len(all_schedules) >= 2
        
        # List active schedules
        active_schedules = await scheduler.list_schedules(ScheduleStatus.ACTIVE)
        assert len(active_schedules) >= 2
        
        # List paused schedules
        await scheduler.pause_schedule(schedule1_id)
        paused_schedules = await scheduler.list_schedules(ScheduleStatus.PAUSED)
        assert len(paused_schedules) >= 1
    
    async def test_schedule_analytics(self, scheduler, mock_callback):
        """Test schedule analytics."""
        # Create a schedule and register callback
        schedule_id = await scheduler.schedule_task(
            task_data={"test": "data"},
            cron_expression="0 9 * * *"
        )
        
        await scheduler.register_callback(schedule_id, mock_callback)
        
        # Get analytics
        analytics = await scheduler.get_schedule_analytics(schedule_id)
        
        assert analytics["schedule_id"] == schedule_id
        assert analytics["title"] is not None
        assert analytics["status"] == ScheduleStatus.ACTIVE
        assert analytics["total_executions"] == 0
        assert analytics["success_rate"] == 0.0
        assert analytics["cron_expression"] == "0 9 * * *"
        assert "human_readable" in analytics
    
    async def test_convenience_functions(self, scheduler):
        """Test convenience scheduling functions."""
        # Test daily task
        daily_id = await schedule_daily_task(
            scheduler,
            task_data={"test": "daily"},
            time_of_day="10:30",
            title="Daily Test"
        )
        
        daily_schedule = await scheduler.get_schedule(daily_id)
        assert daily_schedule.cron_expression == "30 10 * * *"
        assert daily_schedule.title == "Daily Test"
        
        # Test weekly task
        weekly_id = await schedule_weekly_task(
            scheduler,
            task_data={"test": "weekly"},
            day_of_week=2,  # Tuesday
            time_of_day="14:00",
            title="Weekly Test"
        )
        
        weekly_schedule = await scheduler.get_schedule(weekly_id)
        assert weekly_schedule.cron_expression == "0 14 * * 2"
        assert weekly_schedule.title == "Weekly Test"
        
        # Test monthly task
        monthly_id = await schedule_monthly_task(
            scheduler,
            task_data={"test": "monthly"},
            day_of_month=15,
            time_of_day="09:00",
            title="Monthly Test"
        )
        
        monthly_schedule = await scheduler.get_schedule(monthly_id)
        assert monthly_schedule.cron_expression == "0 9 15 * *"
        assert monthly_schedule.title == "Monthly Test"


class TestSchedulerIntegration:
    """Integration tests for the scheduler."""
    
    @pytest.fixture
    async def scheduler_with_db(self, db_session: AsyncSession):
        """Create a scheduler with database integration."""
        scheduler = TaskScheduler(db_session)
        await scheduler.initialize()
        yield scheduler
        await scheduler.shutdown()
    
    async def test_full_scheduling_workflow(self, scheduler_with_db, mock_callback):
        """Test complete scheduling workflow."""
        # Schedule a task
        task_data = {
            "title": "Integration Test Task",
            "description": "Testing full workflow",
            "domain": "integration"
        }
        
        schedule_id = await scheduler_with_db.schedule_task(
            task_data=task_data,
            cron_expression="0 9 * * *",
            title="Integration Test"
        )
        
        # Register callback
        await scheduler_with_db.register_callback(schedule_id, mock_callback)
        
        # Verify schedule exists
        schedule = await scheduler_with_db.get_schedule(schedule_id)
        assert schedule is not None
        assert schedule.title == "Integration Test"
        
        # Test pause/resume
        await scheduler_with_db.pause_schedule(schedule_id)
        schedule = await scheduler_with_db.get_schedule(schedule_id)
        assert schedule.status == ScheduleStatus.PAUSED
        
        await scheduler_with_db.resume_schedule(schedule_id)
        schedule = await scheduler_with_db.get_schedule(schedule_id)
        assert schedule.status == ScheduleStatus.ACTIVE
        
        # Test analytics
        analytics = await scheduler_with_db.get_schedule_analytics(schedule_id)
        assert analytics["schedule_id"] == schedule_id
        assert analytics["total_executions"] == 0
        
        # Test cancellation
        await scheduler_with_db.cancel_schedule(schedule_id)
        schedule = await scheduler_with_db.get_schedule(schedule_id)
        assert schedule.status == ScheduleStatus.CANCELLED


@pytest.mark.asyncio
class TestSchedulerDatabase:
    """Test database integration."""
    
    async def test_scheduled_task_model(self, db_session: AsyncSession):
        """Test ScheduledTask model creation and querying."""
        # Create a scheduled task
        task = ScheduledTask(
            title="Test Task",
            description="Test Description",
            domain="test",
            cron_expression="0 9 * * *",
            status=ScheduleStatus.ACTIVE
        )
        
        db_session.add(task)
        await db_session.commit()
        
        # Query the task
        result = await db_session.execute(
            select(ScheduledTask).where(ScheduledTask.title == "Test Task")
        )
        retrieved_task = result.scalar_one()
        
        assert retrieved_task.title == "Test Task"
        assert retrieved_task.cron_expression == "0 9 * * *"
        assert retrieved_task.status == ScheduleStatus.ACTIVE
    
    async def test_schedule_history_model(self, db_session: AsyncSession):
        """Test ScheduleHistory model creation and querying."""
        # Create a schedule history record
        history = ScheduleHistory(
            schedule_id="test-schedule-id",
            execution_start=datetime.utcnow(),
            status="STARTED",
            result="Test execution"
        )
        
        db_session.add(history)
        await db_session.commit()
        
        # Query the history
        result = await db_session.execute(
            select(ScheduleHistory).where(ScheduleHistory.schedule_id == "test-schedule-id")
        )
        retrieved_history = result.scalar_one()
        
        assert retrieved_history.schedule_id == "test-schedule-id"
        assert retrieved_history.status == "STARTED"
        assert retrieved_history.result == "Test execution"