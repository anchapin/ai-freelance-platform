"""
Async Background Job Queue

Non-blocking queue for RAG enrichment and distillation tasks.
Prevents blocking task execution on secondary systems like ChromaDB.

Issue #6: Decouple Experience Vector Database from task execution flow
"""

import asyncio
from typing import Callable, Any, Optional, Dict
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from src.utils.logger import get_logger

logger = get_logger(__name__)


class JobStatus(Enum):
    """Job execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class Job:
    """Represents a background job with timeout and fallback support."""

    job_id: str
    job_type: str  # "rag_enrichment", "distillation", etc
    status: JobStatus
    task_func: Callable
    task_args: tuple
    task_kwargs: dict
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: Optional[float] = None  # Job-specific timeout
    fallback_func: Optional[Callable] = None  # Fallback on timeout/failure


class BackgroundJobQueue:
    """
    Async background job queue for non-blocking operations.

    Features:
    - Queue jobs without blocking main thread
    - Automatic retry with exponential backoff
    - Metrics and monitoring
    - Dead-letter queue for failed jobs
    """

    def __init__(self, max_workers: int = 3, max_queue_size: int = 100):
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size

        # Job storage
        self.pending_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self.running_jobs: Dict[str, Job] = {}
        self.completed_jobs: Dict[str, Job] = {}
        self.failed_jobs: Dict[str, Job] = {}
        self.dead_letter_queue: Dict[str, Job] = {}  # Permanently failed jobs

        # Metrics
        self.jobs_queued = 0
        self.jobs_succeeded = 0
        self.jobs_failed = 0
        self.jobs_retried = 0
        self.jobs_dead_lettered = 0

        # Worker tasks
        self._workers = []
        self._running = False

        # State tracking for job completion
        self._job_state_lock = asyncio.Lock()

    async def start(self):
        """Start background workers."""
        if self._running:
            return

        self._running = True
        self._workers = []

        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(worker_id=i))
            self._workers.append(worker)

        logger.info(f"Background job queue started with {self.max_workers} workers")

    async def stop(self):
        """Stop background workers and wait for pending jobs."""
        if not self._running:
            return

        self._running = False

        # Wait for all workers to finish
        await asyncio.gather(*self._workers, return_exceptions=True)
        logger.info("Background job queue stopped")

    async def queue_job(
        self,
        job_type: str,
        task_func: Callable,
        task_args: tuple = (),
        task_kwargs: dict = None,
        job_id: Optional[str] = None,
        max_retries: int = 3,
        timeout_seconds: Optional[float] = None,
        fallback_func: Optional[Callable] = None,
    ) -> str:
        """
        Queue a background job with optional timeout and fallback.

        Args:
            job_type: Type of job (for tracking)
            task_func: Async callable to execute
            task_args: Positional arguments for task_func
            task_kwargs: Keyword arguments for task_func
            job_id: Optional job ID (auto-generated if not provided)
            max_retries: Maximum retry attempts on failure
            timeout_seconds: Optional timeout for job execution
            fallback_func: Optional fallback callable on timeout/failure

        Returns:
            Job ID
        """
        if not job_id:
            job_id = f"{job_type}_{datetime.now(timezone.utc).timestamp()}"

        job = Job(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            task_func=task_func,
            task_args=task_args,
            task_kwargs=task_kwargs or {},
            created_at=datetime.now(timezone.utc),
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
            fallback_func=fallback_func,
        )

        try:
            self.pending_queue.put_nowait(job)
            self.jobs_queued += 1
            logger.debug(f"Job queued: {job_id} (type: {job_type})")
            return job_id
        except asyncio.QueueFull:
            logger.error(f"Job queue full, cannot queue {job_id}")
            raise

    async def _worker(self, worker_id: int):
        """Worker coroutine that processes jobs."""
        while self._running:
            try:
                # Get job from queue with timeout
                job = await asyncio.wait_for(self.pending_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            self.running_jobs[job.job_id] = job

            try:
                logger.debug(f"Worker {worker_id}: executing {job.job_id}")

                # Execute the task with optional timeout
                try:
                    if job.timeout_seconds:
                        await asyncio.wait_for(
                            job.task_func(*job.task_args, **job.task_kwargs),
                            timeout=job.timeout_seconds,
                        )
                    else:
                        await job.task_func(*job.task_args, **job.task_kwargs)

                    # Mark as succeeded
                    job.status = JobStatus.SUCCEEDED
                    job.completed_at = datetime.now(timezone.utc)
                    self.completed_jobs[job.job_id] = job
                    self.jobs_succeeded += 1

                    logger.debug(f"Worker {worker_id}: job {job.job_id} succeeded")

                except asyncio.TimeoutError:
                    # Handle timeout with fallback
                    timeout_error = (
                        f"Job execution timeout after {job.timeout_seconds}s"
                    )
                    logger.warning(
                        f"Worker {worker_id}: job {job.job_id} timed out: {timeout_error}"
                    )

                    # Try fallback if available
                    if job.fallback_func:
                        try:
                            logger.info(
                                f"Worker {worker_id}: executing fallback for {job.job_id}"
                            )
                            await job.fallback_func(
                                *job.task_args, **job.task_kwargs
                            )
                            job.status = JobStatus.SUCCEEDED
                            job.completed_at = datetime.now(timezone.utc)
                            job.error = timeout_error + " (fallback executed)"
                            self.completed_jobs[job.job_id] = job
                            logger.info(
                                f"Worker {worker_id}: fallback for {job.job_id} succeeded"
                            )
                        except Exception as fallback_error:
                            logger.error(
                                f"Worker {worker_id}: fallback for {job.job_id} failed: {fallback_error}"
                            )
                            raise TimeoutError(timeout_error) from fallback_error
                    else:
                        raise TimeoutError(timeout_error)

            except Exception as e:
                logger.error(
                    f"Worker {worker_id}: job {job.job_id} failed: {e}", exc_info=True
                )

                # Retry if attempts remaining
                if job.retry_count < job.max_retries:
                    job.retry_count += 1
                    job.status = JobStatus.RETRYING
                    job.error = str(e)
                    self.jobs_retried += 1

                    # Calculate backoff with jitter to prevent thundering herd
                    backoff_seconds = 0.5 * (2**job.retry_count)
                    logger.warning(
                        f"Worker {worker_id}: job {job.job_id} failed, "
                        f"retrying after {backoff_seconds:.2f}s "
                        f"({job.retry_count}/{job.max_retries}): {e}"
                    )

                    # Re-queue with exponential backoff
                    await asyncio.sleep(backoff_seconds)
                    await self.pending_queue.put(job)

                    logger.debug(
                        f"Worker {worker_id}: job {job.job_id} queued for retry "
                        f"({job.retry_count}/{job.max_retries})"
                    )
                else:
                    # Move to dead-letter queue - permanently failed job
                    job.status = JobStatus.FAILED
                    job.completed_at = datetime.now(timezone.utc)
                    job.error = str(e)

                    async with self._job_state_lock:
                        self.dead_letter_queue[job.job_id] = job
                        self.jobs_dead_lettered += 1

                    self.jobs_failed += 1

                    logger.error(
                        f"Worker {worker_id}: job {job.job_id} failed permanently "
                        f"after {job.retry_count} retries: {e}"
                    )

            finally:
                # Remove from running jobs
                self.running_jobs.pop(job.job_id, None)

    def get_metrics(self) -> Dict[str, Any]:
        """Get queue metrics and health status."""
        return {
            "jobs_queued": self.jobs_queued,
            "jobs_succeeded": self.jobs_succeeded,
            "jobs_failed": self.jobs_failed,
            "jobs_retried": self.jobs_retried,
            "jobs_dead_lettered": self.jobs_dead_lettered,
            "pending_jobs": self.pending_queue.qsize(),
            "running_jobs": len(self.running_jobs),
            "completed_jobs": len(self.completed_jobs),
            "failed_jobs": len(self.failed_jobs),
            "dead_letter_jobs": len(self.dead_letter_queue),
            "success_rate_percent": (
                self.jobs_succeeded / self.jobs_queued * 100
                if self.jobs_queued > 0
                else 0.0
            ),
        }

    def get_dead_letter_jobs(self) -> Dict[str, Job]:
        """Get all permanently failed jobs from dead-letter queue."""
        return dict(self.dead_letter_queue)

    def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        """Get the status of a job."""
        if job_id in self.running_jobs:
            return self.running_jobs[job_id].status
        if job_id in self.completed_jobs:
            return self.completed_jobs[job_id].status
        if job_id in self.failed_jobs:
            return self.failed_jobs[job_id].status
        if job_id in self.dead_letter_queue:
            return self.dead_letter_queue[job_id].status
        return None


# Global instance
_background_job_queue: Optional[BackgroundJobQueue] = None


def get_background_job_queue() -> BackgroundJobQueue:
    """Get or create the global BackgroundJobQueue instance."""
    global _background_job_queue
    if _background_job_queue is None:
        _background_job_queue = BackgroundJobQueue()
    return _background_job_queue


async def init_background_job_queue(max_workers: int = 3) -> BackgroundJobQueue:
    """Initialize the global BackgroundJobQueue with custom settings."""
    global _background_job_queue
    _background_job_queue = BackgroundJobQueue(max_workers=max_workers)
    await _background_job_queue.start()
    return _background_job_queue
