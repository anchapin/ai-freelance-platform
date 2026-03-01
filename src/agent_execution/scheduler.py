"""
Advanced Task Scheduling System

Implements cron expression parsing, recurring tasks, and intelligent scheduling
for ArbitrageAI. Supports both one-time and recurring task scheduling with
pause/resume functionality and schedule analytics.

Features:
- Cron expression parser and validator
- Recurring task support (daily, weekly, monthly, custom)
- Intelligent scheduling (avoid peak hours, batch tasks)
- Persistent job queue with database storage
- Schedule history and analytics
- Pause/resume scheduling functionality
- Background worker for scheduled task execution

Usage:
    scheduler = TaskScheduler()
    await scheduler.schedule_task(
        task_data={
            "title": "Market Analysis",
            "description": "Daily market scan",
            "domain": "finance"
        },
        cron_expression="0 9 * * *",  # Daily at 9 AM
        recurring=True
    )
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable, Tuple
from croniter import croniter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import pytz

from .errors import SchedulingError
from ..api.models import ScheduledTask, ScheduleHistory
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ScheduleStatus:
    """Schedule status constants."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ScheduleType:
    """Schedule type constants."""

    ONCE = "ONCE"
    RECURRING = "RECURRING"


class CronExpressionValidator:
    """Validates cron expressions and provides utility methods."""

    @staticmethod
    def validate_expression(expression: str) -> bool:
        """Validate that a cron expression is valid (5-field format only)."""
        try:
            # Check that expression has exactly 5 fields
            parts = expression.split()
            if len(parts) != 5:
                return False

            # Test with current time
            cron = croniter(expression, datetime.now())
            # Get next occurrence to ensure it's valid
            cron.get_next(datetime)
            return True
        except Exception as e:
            logger.error(f"Invalid cron expression '{expression}': {e}")
            return False

    @staticmethod
    def get_next_occurrence(expression: str, timezone: str = "UTC") -> datetime:
        """Get the next occurrence for a cron expression."""
        try:
            tz = pytz.timezone(timezone)
            now = datetime.now(tz)
            cron = croniter(expression, now)
            next_time = cron.get_next(datetime)
            # Ensure the returned datetime is timezone-aware
            if next_time.tzinfo is None:
                next_time = tz.localize(next_time)
            return next_time
        except Exception as e:
            logger.error(f"Error calculating next occurrence for '{expression}': {e}")
            raise SchedulingError(f"Failed to calculate next occurrence: {e}")

    @staticmethod
    def get_human_readable(expression: str) -> str:
        """Convert cron expression to human-readable format."""
        # Simple mapping for common expressions
        common_expressions = {
            "0 9 * * *": "Every day at 9:00 AM",
            "0 17 * * *": "Every day at 5:00 PM",
            "0 0 * * *": "Every day at 12:00 AM",
            "0 12 * * *": "Every day at 12:00 PM",
            "0 0 * * 1": "Every Monday at 12:00 AM",
            "0 0 1 * *": "First day of every month at 12:00 AM",
            "0 */6 * * *": "Every 6 hours",
            "0 */12 * * *": "Every 12 hours",
            "*/30 * * * *": "Every 30 minutes",
            "*/15 * * * *": "Every 15 minutes",
        }

        if expression in common_expressions:
            return common_expressions[expression]

        # For custom expressions, provide a basic description
        parts = expression.split()
        if len(parts) == 5:
            minute, hour, day, month, dow = parts
            return f"Cron expression: {expression}"
        return f"Custom cron: {expression}"


class IntelligentScheduler:
    """Handles intelligent scheduling logic."""

    def __init__(self):
        self.peak_hours = [(9, 17)]  # 9 AM to 5 PM business hours
        self.batch_window_size = 30  # minutes

    def should_avoid_peak_hours(self, schedule: ScheduledTask) -> bool:
        """Check if schedule should avoid peak hours."""
        return schedule.avoid_peak_hours

    def get_optimal_time(
        self, base_time: datetime, schedule: ScheduledTask
    ) -> datetime:
        """Calculate optimal execution time avoiding peak hours."""
        if not self.should_avoid_peak_hours(schedule):
            return base_time

        # Check if it's a weekend (Saturday=5, Sunday=6 in Python's weekday)
        if base_time.weekday() >= 5:
            # Move to Monday morning
            days_until_monday = (7 - base_time.weekday()) % 7 or 7
            next_time = base_time.replace(
                hour=6, minute=0, second=0, microsecond=0
            ) + timedelta(days=days_until_monday)
            return next_time

        # Check if during peak hours (9 AM to 5 PM)
        hour = base_time.hour
        is_peak = any(start <= hour < end for start, end in self.peak_hours)

        if is_peak:
            # Move to end of peak hours (5 PM)
            return base_time.replace(hour=17, minute=0, second=0, microsecond=0)
        elif hour >= 17:
            # After business hours (5 PM or later), move to next day morning (6 AM)
            return base_time.replace(
                hour=6, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)

        return base_time

    def should_batch_tasks(self, schedule: ScheduledTask) -> bool:
        """Check if tasks should be batched."""
        return schedule.batch_size > 1

    def get_batch_window(self, base_time: datetime) -> Tuple[datetime, datetime]:
        """Get the time window for batching tasks."""
        start = base_time
        end = base_time + timedelta(minutes=self.batch_window_size)
        return start, end


class TaskScheduler:
    """Main task scheduler with cron expression support."""

    def __init__(self, db_session: Optional[AsyncSession] = None):
        self.db_session = db_session
        self.validator = CronExpressionValidator()
        self.intelligent_scheduler = IntelligentScheduler()
        self.is_running = False
        self.scheduler_task = None
        self._scheduled_callbacks: Dict[str, Callable] = {}

        # Peak hours configuration
        self.peak_hours_start = 9  # 9 AM
        self.peak_hours_end = 17  # 5 PM

    async def initialize(self):
        """Initialize the scheduler and update next run times."""
        logger.info("Initializing task scheduler...")

        # Update next run times for all active schedules
        await self._update_next_run_times()

        # Start the scheduler loop
        self.is_running = True
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Task scheduler initialized and running")

    async def shutdown(self):
        """Shutdown the scheduler gracefully."""
        logger.info("Shutting down task scheduler...")
        self.is_running = False

        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                logger.info("Scheduler task cancelled")

        logger.info("Task scheduler shutdown complete")

    async def schedule_task(
        self,
        task_data: Dict[str, Any],
        cron_expression: str,
        schedule_type: str = ScheduleType.RECURRING,
        title: Optional[str] = None,
        description: Optional[str] = None,
        domain: str = "general",
        timezone: str = "UTC",
        avoid_peak_hours: bool = True,
        batch_size: int = 1,
        priority: int = 1,
        max_runs: Optional[int] = None,
    ) -> str:
        """
        Schedule a new task.

        Args:
            task_data: Task data to be passed to the execution callback
            cron_expression: Cron expression for scheduling
            schedule_type: ONCE or RECURRING
            title: Task title
            description: Task description
            domain: Task domain
            timezone: Timezone for scheduling
            avoid_peak_hours: Whether to avoid peak business hours
            batch_size: Number of tasks to batch together
            priority: Task priority (1-10)
            max_runs: Maximum number of times to run (None for unlimited)

        Returns:
            Schedule ID
        """
        # Validate cron expression
        if not self.validator.validate_expression(cron_expression):
            raise SchedulingError(f"Invalid cron expression: {cron_expression}")

        # Generate title if not provided
        if not title:
            title = f"Scheduled Task - {cron_expression}"

        # Calculate next run time
        next_run = self.validator.get_next_occurrence(cron_expression, timezone)
        next_run = self.intelligent_scheduler.get_optimal_time(
            next_run, type("obj", (object,), {"avoid_peak_hours": avoid_peak_hours})
        )

        # Create scheduled task record
        schedule = ScheduledTask(
            title=title,
            description=description,
            domain=domain,
            cron_expression=cron_expression,
            schedule_type=schedule_type,
            timezone=timezone,
            next_run_at=next_run,
            avoid_peak_hours=avoid_peak_hours,
            batch_size=batch_size,
            priority=priority,
            max_runs=max_runs,
            status=ScheduleStatus.ACTIVE,
        )

        # Store task data as JSON for later retrieval
        schedule.task_data = json.dumps(task_data)

        try:
            self.db_session.add(schedule)
            await self.db_session.commit()
            logger.info(
                f"Task scheduled: {schedule.id} - {title} - Next run: {next_run}"
            )
            return schedule.id
        except Exception as e:
            await self.db_session.rollback()
            logger.error(f"Failed to schedule task: {e}")
            raise SchedulingError(f"Failed to schedule task: {e}")

    async def register_callback(self, schedule_id: str, callback: Callable):
        """Register a callback function for a scheduled task."""
        self._scheduled_callbacks[schedule_id] = callback

    async def pause_schedule(self, schedule_id: str) -> bool:
        """Pause a scheduled task."""
        try:
            schedule = await self._get_schedule(schedule_id)
            if schedule:
                schedule.status = ScheduleStatus.PAUSED
                await self.db_session.commit()
                logger.info(f"Paused schedule: {schedule_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to pause schedule {schedule_id}: {e}")
            return False

    async def resume_schedule(self, schedule_id: str) -> bool:
        """Resume a paused scheduled task."""
        try:
            schedule = await self._get_schedule(schedule_id)
            if schedule:
                schedule.status = ScheduleStatus.ACTIVE
                # Recalculate next run time
                next_run = self.validator.get_next_occurrence(
                    schedule.cron_expression, schedule.timezone
                )
                next_run = self.intelligent_scheduler.get_optimal_time(
                    next_run, schedule
                )
                schedule.next_run_at = next_run
                await self.db_session.commit()
                logger.info(f"Resumed schedule: {schedule_id} - Next run: {next_run}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to resume schedule {schedule_id}: {e}")
            return False

    async def cancel_schedule(self, schedule_id: str) -> bool:
        """Cancel a scheduled task."""
        try:
            schedule = await self._get_schedule(schedule_id)
            if schedule:
                schedule.status = ScheduleStatus.CANCELLED
                await self.db_session.commit()
                logger.info(f"Cancelled schedule: {schedule_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to cancel schedule {schedule_id}: {e}")
            return False

    async def get_schedule(self, schedule_id: str) -> Optional[ScheduledTask]:
        """Get schedule details."""
        return await self._get_schedule(schedule_id)

    async def list_schedules(self, status: Optional[str] = None) -> List[ScheduledTask]:
        """List all schedules, optionally filtered by status."""
        query = select(ScheduledTask)
        if status:
            query = query.where(ScheduledTask.status == status)

        result = await self.db_session.execute(query)
        return result.scalars().all()

    async def get_schedule_analytics(self, schedule_id: str) -> Dict[str, Any]:
        """Get analytics for a specific schedule."""
        schedule = await self._get_schedule(schedule_id)
        if not schedule:
            return {}

        # Get execution history
        history_query = (
            select(ScheduleHistory)
            .where(ScheduleHistory.schedule_id == schedule_id)
            .order_by(ScheduleHistory.execution_start.desc())
        )

        history_result = await self.db_session.execute(history_query)
        history = history_result.scalars().all()

        # Calculate analytics
        total_executions = len(history)
        successful_executions = len([h for h in history if h.status == "COMPLETED"])
        failed_executions = len([h for h in history if h.status == "FAILED"])

        avg_execution_time = 0
        if history:
            execution_times = [
                h.execution_time_ms for h in history if h.execution_time_ms
            ]
            if execution_times:
                avg_execution_time = sum(execution_times) / len(execution_times)

        success_rate = (
            (successful_executions / total_executions * 100)
            if total_executions > 0
            else 0
        )

        return {
            "schedule_id": schedule_id,
            "title": schedule.title,
            "status": schedule.status,
            "total_executions": total_executions,
            "successful_executions": successful_executions,
            "failed_executions": failed_executions,
            "success_rate": round(success_rate, 2),
            "avg_execution_time_ms": round(avg_execution_time, 2),
            "next_run_at": schedule.next_run_at.isoformat()
            if schedule.next_run_at
            else None,
            "cron_expression": schedule.cron_expression,
            "human_readable": self.validator.get_human_readable(
                schedule.cron_expression
            ),
            "recent_executions": [
                {
                    "execution_start": h.execution_start.isoformat(),
                    "execution_end": h.execution_end.isoformat()
                    if h.execution_end
                    else None,
                    "status": h.status,
                    "execution_time_ms": h.execution_time_ms,
                    "result": h.result,
                }
                for h in history[:10]  # Last 10 executions
            ],
        }

    async def _scheduler_loop(self):
        """Main scheduler loop that checks for due tasks."""
        while self.is_running:
            try:
                await self._check_and_execute_due_tasks()
                await asyncio.sleep(60)  # Check every minute
            except asyncio.CancelledError:
                logger.info("Scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(60)

    async def _check_and_execute_due_tasks(self):
        """Check for tasks due for execution and execute them."""
        now = datetime.now(pytz.UTC)

        # Find active schedules due for execution
        query = (
            select(ScheduledTask)
            .where(
                ScheduledTask.status == ScheduleStatus.ACTIVE,
                ScheduledTask.next_run_at <= now,
            )
            .order_by(ScheduledTask.priority.desc(), ScheduledTask.next_run_at.asc())
        )

        result = await self.db_session.execute(query)
        due_schedules = result.scalars().all()

        for schedule in due_schedules:
            await self._execute_schedule(schedule)

    async def _execute_schedule(self, schedule: ScheduledTask):
        """Execute a single schedule."""
        execution_start = datetime.now(pytz.UTC)
        history_record = ScheduleHistory(
            schedule_id=schedule.id, execution_start=execution_start, status="STARTED"
        )

        try:
            # Update schedule last run time
            schedule.last_run_at = execution_start

            # Execute the callback if registered
            callback = self._scheduled_callbacks.get(schedule.id)
            if callback:
                # Parse task data
                task_data = (
                    json.loads(schedule.task_data)
                    if hasattr(schedule, "task_data")
                    else {}
                )

                # Execute callback
                result = await callback(task_data)

                # Update history with success
                history_record.status = "COMPLETED"
                history_record.result = f"Success: {result}"

                # Update schedule stats
                schedule.run_count += 1
                schedule.last_run_result = "SUCCESS"
                schedule.last_run_error = None

                logger.info(f"Schedule {schedule.id} executed successfully")

            else:
                # No callback registered, just mark as completed
                history_record.status = "COMPLETED"
                history_record.result = "No callback registered"
                schedule.run_count += 1
                schedule.last_run_result = "NO_CALLBACK"

                logger.warning(f"No callback registered for schedule {schedule.id}")

            # Calculate execution time
            execution_end = datetime.now(pytz.UTC)
            execution_time = (execution_end - execution_start).total_seconds() * 1000
            history_record.execution_end = execution_end
            history_record.execution_time_ms = execution_time

            # Update average execution time
            if schedule.avg_execution_time == 0:
                schedule.avg_execution_time = execution_time
            else:
                schedule.avg_execution_time = (
                    schedule.avg_execution_time + execution_time
                ) / 2

            # Update next run time for recurring schedules
            if schedule.schedule_type == ScheduleType.RECURRING:
                next_run = self.validator.get_next_occurrence(
                    schedule.cron_expression, schedule.timezone
                )
                next_run = self.intelligent_scheduler.get_optimal_time(
                    next_run, schedule
                )
                schedule.next_run_at = next_run

                # Check if max runs reached
                if schedule.max_runs and schedule.run_count >= schedule.max_runs:
                    schedule.status = ScheduleStatus.COMPLETED
                    history_record.result += " | Schedule completed (max runs reached)"
                    logger.info(f"Schedule {schedule.id} completed (max runs reached)")

            # Update success rate
            total_runs = schedule.run_count
            successful_runs = len(
                [h for h in [history_record] if h.status == "COMPLETED"]
            )
            schedule.success_rate = (
                (successful_runs / total_runs * 100) if total_runs > 0 else 100.0
            )

            # Save changes
            self.db_session.add(history_record)
            await self.db_session.commit()

        except Exception as e:
            # Handle execution failure
            schedule.last_run_result = "FAILED"
            schedule.last_run_error = str(e)

            history_record.status = "FAILED"
            history_record.result = f"Error: {e}"
            history_record.execution_end = datetime.now(pytz.UTC)

            self.db_session.add(history_record)
            await self.db_session.commit()

            logger.error(f"Schedule {schedule.id} failed: {e}")

    async def _get_schedule(self, schedule_id: str) -> Optional[ScheduledTask]:
        """Get a schedule by ID."""
        query = select(ScheduledTask).where(ScheduledTask.id == schedule_id)
        result = await self.db_session.execute(query)
        return result.scalar_one_or_none()

    async def _update_next_run_times(self):
        """Update next run times for all active schedules."""
        schedules = await self.list_schedules(ScheduleStatus.ACTIVE)

        for schedule in schedules:
            try:
                next_run = self.validator.get_next_occurrence(
                    schedule.cron_expression, schedule.timezone
                )
                next_run = self.intelligent_scheduler.get_optimal_time(
                    next_run, schedule
                )
                schedule.next_run_at = next_run
                self.db_session.add(schedule)
            except Exception as e:
                logger.error(
                    f"Failed to update next run time for schedule {schedule.id}: {e}"
                )

        await self.db_session.commit()

    @staticmethod
    def create_common_schedule(
        task_data: Dict[str, Any],
        schedule_type: str,
        title: str,
        description: str = None,
        domain: str = "general",
    ) -> Dict[str, Any]:
        """Create common schedule configurations."""
        schedules = {
            "daily_9am": {
                "cron_expression": "0 9 * * *",
                "description": "Every day at 9:00 AM",
            },
            "daily_5pm": {
                "cron_expression": "0 17 * * *",
                "description": "Every day at 5:00 PM",
            },
            "weekly_monday": {
                "cron_expression": "0 9 * * 1",
                "description": "Every Monday at 9:00 AM",
            },
            "monthly_1st": {
                "cron_expression": "0 9 1 * *",
                "description": "First day of every month at 9:00 AM",
            },
            "every_6_hours": {
                "cron_expression": "0 */6 * * *",
                "description": "Every 6 hours",
            },
            "every_30_minutes": {
                "cron_expression": "*/30 * * * *",
                "description": "Every 30 minutes",
            },
        }

        if schedule_type in schedules:
            config = schedules[schedule_type].copy()
            config.update(
                {
                    "task_data": task_data,
                    "title": title,
                    "description": description or config["description"],
                    "domain": domain,
                }
            )
            return config

        raise SchedulingError(f"Unknown common schedule type: {schedule_type}")


# Convenience functions for common scheduling patterns
async def schedule_daily_task(
    scheduler: TaskScheduler,
    task_data: Dict[str, Any],
    time_of_day: str = "09:00",
    title: str = None,
    description: str = None,
    domain: str = "general",
    **kwargs,
) -> str:
    """Schedule a task to run daily at a specific time."""
    hour, minute = time_of_day.split(":")
    cron_expr = f"{minute} {hour} * * *"

    return await scheduler.schedule_task(
        task_data=task_data,
        cron_expression=cron_expr,
        title=title or f"Daily task at {time_of_day}",
        description=description,
        domain=domain,
        **kwargs,
    )


async def schedule_weekly_task(
    scheduler: TaskScheduler,
    task_data: Dict[str, Any],
    day_of_week: int = 1,  # 0=Monday, 6=Sunday
    time_of_day: str = "09:00",
    title: str = None,
    description: str = None,
    domain: str = "general",
    **kwargs,
) -> str:
    """Schedule a task to run weekly on a specific day and time."""
    hour, minute = time_of_day.split(":")
    cron_expr = f"{minute} {hour} * * {day_of_week}"

    return await scheduler.schedule_task(
        task_data=task_data,
        cron_expression=cron_expr,
        title=title or f"Weekly task on day {day_of_week} at {time_of_day}",
        description=description,
        domain=domain,
        **kwargs,
    )


async def schedule_monthly_task(
    scheduler: TaskScheduler,
    task_data: Dict[str, Any],
    day_of_month: int = 1,
    time_of_day: str = "09:00",
    title: str = None,
    description: str = None,
    domain: str = "general",
    **kwargs,
) -> str:
    """Schedule a task to run monthly on a specific day and time."""
    hour, minute = time_of_day.split(":")
    cron_expr = f"{minute} {hour} {day_of_month} * *"

    return await scheduler.schedule_task(
        task_data=task_data,
        cron_expression=cron_expr,
        title=title or f"Monthly task on day {day_of_month} at {time_of_day}",
        description=description,
        domain=domain,
        **kwargs,
    )
