"""
API endpoints for advanced task scheduling and cron expressions.

Provides REST endpoints for scheduling tasks with cron expressions,
managing recurring tasks, and viewing schedule analytics.
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from ..agent_execution.scheduler import (
    TaskScheduler,
    CronExpressionValidator,
    schedule_daily_task,
    schedule_weekly_task,
    schedule_monthly_task,
)
from ..api.database import get_db, get_async_db
from ..api.models import ScheduledTask, ScheduleHistory
from ..utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


class ScheduleTaskRequest(BaseModel):
    """Request model for scheduling a task."""

    title: str
    description: Optional[str] = None
    domain: str = "general"
    cron_expression: str
    schedule_type: str = "RECURRING"
    task_data: Dict[str, Any]
    timezone: str = "UTC"
    avoid_peak_hours: bool = True
    batch_size: int = 1
    priority: int = 1
    max_runs: Optional[int] = None


class ScheduleUpdateRequest(BaseModel):
    """Request model for updating a schedule."""

    title: Optional[str] = None
    description: Optional[str] = None
    cron_expression: Optional[str] = None
    avoid_peak_hours: Optional[bool] = None
    batch_size: Optional[int] = None
    priority: Optional[int] = None
    max_runs: Optional[int] = None


class ScheduleAnalyticsResponse(BaseModel):
    """Response model for schedule analytics."""

    schedule_id: str
    title: str
    status: str
    total_executions: int
    successful_executions: int
    failed_executions: int
    success_rate: float
    avg_execution_time_ms: float
    next_run_at: Optional[str] = None
    cron_expression: str
    human_readable: str
    recent_executions: List[Dict[str, Any]]


@router.post("/schedule")
async def schedule_task(
    request: ScheduleTaskRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Schedule a new task with cron expression.

    Supports both one-time and recurring tasks.
    """
    # Validate cron expression
    if not CronExpressionValidator.validate_expression(request.cron_expression):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid cron expression: {request.cron_expression}",
        )

    # Initialize scheduler
    scheduler = TaskScheduler(db_session=db)

    try:
        # Schedule the task
        schedule_id = await scheduler.schedule_task(
            task_data=request.task_data,
            cron_expression=request.cron_expression,
            schedule_type=request.schedule_type,
            title=request.title,
            description=request.description,
            domain=request.domain,
            timezone=request.timezone,
            avoid_peak_hours=request.avoid_peak_hours,
            batch_size=request.batch_size,
            priority=request.priority,
            max_runs=request.max_runs,
        )

        # Start scheduler if not already running
        background_tasks.add_task(scheduler.initialize)

        return {
            "message": "Task scheduled successfully",
            "schedule_id": schedule_id,
            "next_run_at": CronExpressionValidator.get_next_occurrence(
                request.cron_expression, request.timezone
            ).isoformat(),
            "human_readable": CronExpressionValidator.get_human_readable(
                request.cron_expression
            ),
        }

    except Exception as e:
        logger.error(f"Failed to schedule task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to schedule task: {e}")


@router.post("/schedule/daily")
async def schedule_daily_task_endpoint(
    request: ScheduleTaskRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Schedule a task to run daily at a specific time.

    Convenience endpoint for daily scheduling.
    """
    scheduler = TaskScheduler(db_session=db)

    try:
        schedule_id = await schedule_daily_task(
            scheduler=scheduler,
            task_data=request.task_data,
            time_of_day="09:00",  # Default to 9 AM
            title=request.title,
            description=request.description,
            domain=request.domain,
        )

        background_tasks.add_task(scheduler.initialize)

        return {
            "message": "Daily task scheduled successfully",
            "schedule_id": schedule_id,
            "cron_expression": "0 9 * * *",
            "next_run_at": CronExpressionValidator.get_next_occurrence(
                "0 9 * * *", request.timezone
            ).isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to schedule daily task: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to schedule daily task: {e}"
        )


@router.post("/schedule/weekly")
async def schedule_weekly_task_endpoint(
    background_tasks: BackgroundTasks,
    request: ScheduleTaskRequest,
    day_of_week: int = 1,  # Monday
    time_of_day: str = "09:00",
    db: AsyncSession = Depends(get_async_db),
):
    """
    Schedule a task to run weekly on a specific day and time.

    Convenience endpoint for weekly scheduling.
    """
    scheduler = TaskScheduler(db_session=db)

    try:
        schedule_id = await schedule_weekly_task(
            scheduler=scheduler,
            task_data=request.task_data,
            day_of_week=day_of_week,
            time_of_day=time_of_day,
            title=request.title,
            description=request.description,
            domain=request.domain,
        )

        background_tasks.add_task(scheduler.initialize)

        cron_expr = (
            f"{time_of_day.split(':')[1]} {time_of_day.split(':')[0]} * * {day_of_week}"
        )

        return {
            "message": "Weekly task scheduled successfully",
            "schedule_id": schedule_id,
            "cron_expression": cron_expr,
            "next_run_at": CronExpressionValidator.get_next_occurrence(
                cron_expr, request.timezone
            ).isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to schedule weekly task: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to schedule weekly task: {e}"
        )


@router.post("/schedule/monthly")
async def schedule_monthly_task_endpoint(
    background_tasks: BackgroundTasks,
    request: ScheduleTaskRequest,
    day_of_month: int = 1,
    time_of_day: str = "09:00",
    db: AsyncSession = Depends(get_async_db),
):
    """
    Schedule a task to run monthly on a specific day and time.

    Convenience endpoint for monthly scheduling.
    """
    scheduler = TaskScheduler(db_session=db)

    try:
        schedule_id = await schedule_monthly_task(
            scheduler=scheduler,
            task_data=request.task_data,
            day_of_month=day_of_month,
            time_of_day=time_of_day,
            title=request.title,
            description=request.description,
            domain=request.domain,
        )

        background_tasks.add_task(scheduler.initialize)

        cron_expr = f"{time_of_day.split(':')[1]} {time_of_day.split(':')[0]} {day_of_month} * *"

        return {
            "message": "Monthly task scheduled successfully",
            "schedule_id": schedule_id,
            "cron_expression": cron_expr,
            "next_run_at": CronExpressionValidator.get_next_occurrence(
                cron_expr, request.timezone
            ).isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to schedule monthly task: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to schedule monthly task: {e}"
        )


@router.get("/schedules")
async def list_schedules(status: Optional[str] = None, db: Session = Depends(get_db)):
    """
    List all scheduled tasks, optionally filtered by status.
    """
    scheduler = TaskScheduler(db_session=db)

    try:
        schedules = await scheduler.list_schedules(status)

        return {
            "schedules": [
                {
                    "id": s.id,
                    "title": s.title,
                    "description": s.description,
                    "domain": s.domain,
                    "cron_expression": s.cron_expression,
                    "schedule_type": s.schedule_type,
                    "status": s.status,
                    "timezone": s.timezone,
                    "avoid_peak_hours": s.avoid_peak_hours,
                    "batch_size": s.batch_size,
                    "priority": s.priority,
                    "max_runs": s.max_runs,
                    "run_count": s.run_count,
                    "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
                    "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                    "avg_execution_time": s.avg_execution_time,
                    "success_rate": s.success_rate,
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                }
                for s in schedules
            ]
        }

    except Exception as e:
        logger.error(f"Failed to list schedules: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list schedules: {e}")


@router.get("/schedules/{schedule_id}")
async def get_schedule(schedule_id: str, db: Session = Depends(get_db)):
    """
    Get details for a specific schedule.
    """
    scheduler = TaskScheduler(db_session=db)

    try:
        schedule = await scheduler.get_schedule(schedule_id)

        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")

        return {
            "id": schedule.id,
            "title": schedule.title,
            "description": schedule.description,
            "domain": schedule.domain,
            "cron_expression": schedule.cron_expression,
            "schedule_type": schedule.schedule_type,
            "status": schedule.status,
            "timezone": schedule.timezone,
            "avoid_peak_hours": schedule.avoid_peak_hours,
            "batch_size": schedule.batch_size,
            "priority": schedule.priority,
            "max_runs": schedule.max_runs,
            "run_count": schedule.run_count,
            "next_run_at": schedule.next_run_at.isoformat()
            if schedule.next_run_at
            else None,
            "last_run_at": schedule.last_run_at.isoformat()
            if schedule.last_run_at
            else None,
            "last_run_result": schedule.last_run_result,
            "last_run_error": schedule.last_run_error,
            "avg_execution_time": schedule.avg_execution_time,
            "success_rate": schedule.success_rate,
            "created_at": schedule.created_at.isoformat(),
            "updated_at": schedule.updated_at.isoformat(),
            "human_readable": CronExpressionValidator.get_human_readable(
                schedule.cron_expression
            ),
        }

    except Exception as e:
        logger.error(f"Failed to get schedule {schedule_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get schedule: {e}")


@router.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str, request: ScheduleUpdateRequest, db: Session = Depends(get_db)
):
    """
    Update an existing schedule.
    """
    scheduler = TaskScheduler(db_session=db)

    try:
        schedule = await scheduler.get_schedule(schedule_id)

        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")

        # Update fields if provided
        if request.title:
            schedule.title = request.title
        if request.description is not None:
            schedule.description = request.description
        if request.cron_expression:
            # Validate new cron expression
            if not CronExpressionValidator.validate_expression(request.cron_expression):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid cron expression: {request.cron_expression}",
                )
            schedule.cron_expression = request.cron_expression
            # Recalculate next run time
            next_run = CronExpressionValidator.get_next_occurrence(
                request.cron_expression, schedule.timezone
            )
            schedule.next_run_at = next_run
        if request.avoid_peak_hours is not None:
            schedule.avoid_peak_hours = request.avoid_peak_hours
        if request.batch_size:
            schedule.batch_size = request.batch_size
        if request.priority:
            schedule.priority = request.priority
        if request.max_runs is not None:
            schedule.max_runs = request.max_runs

        await db.commit()

        return {
            "message": "Schedule updated successfully",
            "schedule_id": schedule_id,
            "next_run_at": schedule.next_run_at.isoformat()
            if schedule.next_run_at
            else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update schedule {schedule_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update schedule: {e}")


@router.post("/schedules/{schedule_id}/pause")
async def pause_schedule(schedule_id: str, db: Session = Depends(get_db)):
    """
    Pause a scheduled task.
    """
    scheduler = TaskScheduler(db_session=db)

    try:
        success = await scheduler.pause_schedule(schedule_id)

        if not success:
            raise HTTPException(status_code=404, detail="Schedule not found")

        return {"message": f"Schedule {schedule_id} paused successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pause schedule {schedule_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to pause schedule: {e}")


@router.post("/schedules/{schedule_id}/resume")
async def resume_schedule(schedule_id: str, db: Session = Depends(get_db)):
    """
    Resume a paused scheduled task.
    """
    scheduler = TaskScheduler(db_session=db)

    try:
        success = await scheduler.resume_schedule(schedule_id)

        if not success:
            raise HTTPException(status_code=404, detail="Schedule not found")

        return {"message": f"Schedule {schedule_id} resumed successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resume schedule {schedule_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resume schedule: {e}")


@router.post("/schedules/{schedule_id}/cancel")
async def cancel_schedule(schedule_id: str, db: Session = Depends(get_db)):
    """
    Cancel a scheduled task.
    """
    scheduler = TaskScheduler(db_session=db)

    try:
        success = await scheduler.cancel_schedule(schedule_id)

        if not success:
            raise HTTPException(status_code=404, detail="Schedule not found")

        return {"message": f"Schedule {schedule_id} cancelled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel schedule {schedule_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel schedule: {e}")


@router.get("/schedules/{schedule_id}/analytics")
async def get_schedule_analytics(schedule_id: str, db: Session = Depends(get_db)):
    """
    Get analytics for a specific schedule.
    """
    scheduler = TaskScheduler(db_session=db)

    try:
        analytics = await scheduler.get_schedule_analytics(schedule_id)

        if not analytics:
            raise HTTPException(status_code=404, detail="Schedule not found")

        return analytics

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get analytics for schedule {schedule_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get schedule analytics: {e}"
        )


@router.get("/schedules/{schedule_id}/history")
async def get_schedule_history(
    schedule_id: str, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)
):
    """
    Get execution history for a specific schedule.
    """
    try:
        # Query schedule history
        history_query = (
            db.query(ScheduleHistory)
            .filter(ScheduleHistory.schedule_id == schedule_id)
            .order_by(ScheduleHistory.execution_start.desc())
            .offset(offset)
            .limit(limit)
        )

        history = history_query.all()

        return {
            "schedule_id": schedule_id,
            "history": [
                {
                    "id": h.id,
                    "task_id": h.task_id,
                    "execution_start": h.execution_start.isoformat(),
                    "execution_end": h.execution_end.isoformat()
                    if h.execution_end
                    else None,
                    "status": h.status,
                    "result": h.result,
                    "execution_time_ms": h.execution_time_ms,
                    "created_at": h.created_at.isoformat(),
                }
                for h in history
            ],
            "total": len(history),
            "limit": limit,
            "offset": offset,
        }

    except Exception as e:
        logger.error(f"Failed to get history for schedule {schedule_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get schedule history: {e}"
        )


@router.get("/cron/validate")
async def validate_cron_expression(expression: str):
    """
    Validate a cron expression.
    """
    try:
        is_valid = CronExpressionValidator.validate_expression(expression)

        if is_valid:
            next_occurrence = CronExpressionValidator.get_next_occurrence(expression)
            human_readable = CronExpressionValidator.get_human_readable(expression)

            return {
                "valid": True,
                "expression": expression,
                "next_occurrence": next_occurrence.isoformat(),
                "human_readable": human_readable,
            }
        else:
            return {
                "valid": False,
                "expression": expression,
                "error": "Invalid cron expression",
            }

    except Exception as e:
        logger.error(f"Failed to validate cron expression '{expression}': {e}")
        return {"valid": False, "expression": expression, "error": str(e)}


@router.get("/cron/common")
async def get_common_cron_expressions():
    """
    Get common cron expressions for reference.
    """
    common_expressions = {
        "daily_9am": {
            "expression": "0 9 * * *",
            "description": "Every day at 9:00 AM",
            "use_case": "Daily morning reports",
        },
        "daily_5pm": {
            "expression": "0 17 * * *",
            "description": "Every day at 5:00 PM",
            "use_case": "End of day summaries",
        },
        "weekly_monday": {
            "expression": "0 9 * * 1",
            "description": "Every Monday at 9:00 AM",
            "use_case": "Weekly reports",
        },
        "monthly_1st": {
            "expression": "0 9 1 * *",
            "description": "First day of every month at 9:00 AM",
            "use_case": "Monthly reports",
        },
        "every_6_hours": {
            "expression": "0 */6 * * *",
            "description": "Every 6 hours",
            "use_case": "Regular monitoring",
        },
        "every_30_minutes": {
            "expression": "*/30 * * * *",
            "description": "Every 30 minutes",
            "use_case": "Frequent monitoring",
        },
        "business_hours": {
            "expression": "0 9-17 * * 1-5",
            "description": "Every hour during business hours (9 AM - 5 PM, Mon-Fri)",
            "use_case": "Business hours monitoring",
        },
        "weekends_only": {
            "expression": "0 10 * * 0,6",
            "description": "Every Saturday and Sunday at 10:00 AM",
            "use_case": "Weekend tasks",
        },
    }

    return {
        "common_expressions": common_expressions,
        "note": "Use these as starting points and customize as needed",
    }


@router.get("/status")
async def get_scheduler_status(db: Session = Depends(get_db)):
    """
    Get scheduler status and statistics.
    """
    try:
        # Count schedules by status
        from sqlalchemy import func

        status_counts = (
            db.query(ScheduledTask.status, func.count(ScheduledTask.id).label("count"))
            .group_by(ScheduledTask.status)
            .all()
        )

        # Count total executions
        total_executions = db.query(func.count(ScheduleHistory.id)).scalar()

        # Count executions in last 24 hours
        yesterday = datetime.utcnow() - timedelta(hours=24)
        recent_executions = (
            db.query(func.count(ScheduleHistory.id))
            .filter(ScheduleHistory.execution_start >= yesterday)
            .scalar()
        )

        return {
            "status": "running",
            "schedule_counts": {status: count for status, count in status_counts},
            "total_executions": total_executions,
            "recent_executions_24h": recent_executions,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to get scheduler status: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get scheduler status: {e}"
        )


# Register the scheduler endpoints with the main app
def register_scheduler_routes(app):
    """Register scheduler routes with the main FastAPI app."""
    app.include_router(router)
