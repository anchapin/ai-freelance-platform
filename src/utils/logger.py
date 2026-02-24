"""
Robust Logging Configuration

Provides centralized logging with:
- Rotating file handler (prevents huge log files)
- Console handler for development
- Timestamps and severity levels
- Module-specific loggers

Usage:
    from src.utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Task processing started")
    logger.warning("Task failed, escalating")
    logger.error("Critical error occurred")
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(
    log_dir: str = "logs",
    log_file: str = "app.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
    log_level: int = logging.INFO
) -> logging.Logger:
    """
    Setup logging with rotating file handler and console output.
    
    Args:
        log_dir: Directory for log files
        log_file: Name of the log file
        max_bytes: Maximum size of log file before rotation
        backup_count: Number of backup files to keep
        log_level: Minimum log level to record
        
    Returns:
        Configured root logger
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler - rotates at 10MB, keeps 5 backups
    file_handler = RotatingFileHandler(
        filename=log_path / log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(detailed_formatter)
    
    # Console handler for development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(simple_formatter)
    
    # Add handlers to root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for the specified module.
    
    Args:
        name: Usually __name__ from the calling module
        
    Returns:
        Logger instance
    """
    # Ensure logging is configured (lazy initialization)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        setup_logging()
    
    return logging.getLogger(name)


# Initialize logging on module import
# This ensures logging is ready when other modules import this
_root_logger = setup_logging()


class TaskLogger:
    """
    Specialized logger for task processing with structured logging.
    
    Provides convenient methods for common task operations.
    """
    
    def __init__(self, task_id: str = None):
        self.logger = get_logger("task_processor")
        self.task_id = task_id
    
    def _format_message(self, message: str) -> str:
        """Add task ID prefix to message if available."""
        if self.task_id:
            return f"Task {self.task_id}: {message}"
        return message
    
    def info(self, message: str):
        """Log info level message."""
        self.logger.info(self._format_message(message))
    
    def warning(self, message: str):
        """Log warning level message."""
        self.logger.warning(self._format_message(message))
    
    def error(self, message: str):
        """Log error level message."""
        self.logger.error(self._format_message(message))
    
    def debug(self, message: str):
        """Log debug level message."""
        self.logger.debug(self._format_message(message))
    
    def task_started(self, workflow: str = "Research & Plan"):
        """Log task processing start."""
        self.info(f"Starting task processing with {workflow} workflow")
    
    def task_completed(self, output_format: str = None):
        """Log task completion."""
        msg = "Task completed successfully"
        if output_format:
            msg += f" (output: {output_format})"
        self.info(msg)
    
    def task_failed(self, error: str):
        """Log task failure."""
        self.error(f"Task failed - {error}")
    
    def task_escalated(self, reason: str, error: str = None):
        """Log task escalation to human review."""
        msg = f"ESCALATED for human review - {reason}"
        if error:
            msg += f" | Error: {error[:200]}..."
        self.warning(msg)
    
    def plan_generated(self, title: str):
        """Log work plan generation."""
        self.info(f"Work plan generated - {title}")
    
    def plan_failed(self, error: str):
        """Log plan generation failure."""
        self.warning(f"Plan generation failed - {error}")
    
    def arena_started(self, competition_type: str, agent_a: str, agent_b: str):
        """Log arena competition start."""
        self.logger.info(
            f"🏟️ Starting Arena Competition: {competition_type} | "
            f"Agent A: {agent_a} | Agent B: {agent_b}"
        )
    
    def arena_completed(self, agent: str, execution_time: float):
        """Log arena agent completion."""
        self.info(f"Agent {agent} completed in {execution_time:.1f}s")
    
    def arena_winner(self, winner: str, reason: str):
        """Log arena winner determination."""
        self.logger.info(f"🏆 Winner: {winner} | Reason: {reason}")
    
    def learning_logged(self, system: str, success: bool = True):
        """Log learning system operation."""
        status = "✓" if success else "✗"
        self.logger.info(f"   {status} Logged to {system}")


class ArenaLogger:
    """
    Specialized logger for arena operations.
    """
    
    def __init__(self):
        self.logger = get_logger("arena")
    
    def competition_start(self, competition_type: str, agent_a: str, agent_b: str):
        """Log competition start."""
        self.logger.info(
            f"🏟️ Starting Arena Competition: {competition_type}\n"
            f"   Agent A: {agent_a}\n"
            f"   Agent B: {agent_b}"
        )
    
    def agent_complete(self, agent_name: str, execution_time: float):
        """Log agent completion."""
        self.logger.info(f"   Agent {agent_name} completed in {execution_time:.1f}s")
    
    def winner_determined(self, winner: str, reason: str):
        """Log winner determination."""
        self.logger.info(f"   🏆 Winner: {winner}")
        self.logger.info(f"   Reason: {reason}")
    
    def learning_error(self, system: str, error: str):
        """Log learning system error."""
        self.logger.warning(f"   ✗ Failed to log to {system}: {error}")
