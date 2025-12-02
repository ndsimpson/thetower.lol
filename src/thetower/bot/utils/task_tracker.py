"""
Utility for tracking task execution state, history and statistics.

This module provides a TaskTracker class that handles tracking of:
- Active tasks
- Task execution history
- Task success/failure statistics
- Error states
"""

import datetime
import logging
from collections import deque
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, Dict, List, Union


class TaskTracker:
    """
    Track tasks execution state, history, and statistics.

    This class provides methods to:
    - Begin and end task tracking
    - Update task status during execution
    - Get task history and statistics
    - Generate status reports

    It's designed to be used for tracking periodic tasks, command execution,
    and other operations where monitoring execution is important.
    """

    def __init__(self, logger=None, history_size: int = 10):
        """
        Initialize the task tracker.

        Args:
            logger: Optional logger instance to use for logging task events
            history_size: Maximum number of historical executions to keep per task
        """
        # Initialize state tracking
        self._active_tasks = {}  # name -> {'start_time': datetime, 'status': str}
        self._task_history = {}  # name -> deque of execution records
        self._task_stats = {}  # name -> {'count': int, 'success': int, 'failure': int, 'avg_time': float}
        self._task_history_size = history_size
        self._has_errors = False  # General error flag

        # Set up logging
        self.logger = logger or logging.getLogger(__name__)

    def begin_task(self, task_name: str, status: str = "Running") -> None:
        """
        Mark the beginning of a task execution.

        Args:
            task_name: Name of the task being executed
            status: Initial status message for the task
        """
        self._active_tasks[task_name] = {"start_time": datetime.datetime.now(), "status": status}

        # Initialize task stats if this is a new task
        if task_name not in self._task_stats:
            self._task_stats[task_name] = {"count": 0, "success": 0, "failure": 0, "total_time": 0, "avg_time": 0}

        # Initialize history queue if this is a new task
        if task_name not in self._task_history:
            self._task_history[task_name] = deque(maxlen=self._task_history_size)

        self.logger.debug(f"Task '{task_name}' started with status: {status}")

    def end_task(self, task_name: str, success: bool = True, status: str = None) -> None:
        """
        Mark the end of a task execution.

        Args:
            task_name: Name of the task that completed
            success: Whether the task completed successfully
            status: Final status message for the task
        """
        if task_name not in self._active_tasks:
            self.logger.warning(f"Attempted to end unknown task: {task_name}")
            return

        task_info = self._active_tasks.pop(task_name)
        end_time = datetime.datetime.now()
        execution_time = (end_time - task_info["start_time"]).total_seconds()

        # Update task statistics
        stats = self._task_stats.get(task_name, {"count": 0, "success": 0, "failure": 0, "total_time": 0, "avg_time": 0})

        stats["count"] += 1
        if success:
            stats["success"] += 1
        else:
            stats["failure"] += 1
            self._has_errors = True  # Set general error flag

        stats["total_time"] += execution_time
        stats["avg_time"] = stats["total_time"] / stats["count"]

        self._task_stats[task_name] = stats

        # Add to history
        history_record = {
            "start_time": task_info["start_time"],
            "end_time": end_time,
            "execution_time": execution_time,
            "success": success,
            "status": status or task_info["status"],
        }

        if task_name in self._task_history:
            self._task_history[task_name].append(history_record)
        else:
            self._task_history[task_name] = deque([history_record], maxlen=self._task_history_size)

        self.logger.debug(f"Task '{task_name}' ended with {'success' if success else 'failure'} " f"in {execution_time:.2f}s")

    def update_task_status(self, task_name: str, status: str) -> None:
        """
        Update the status of a running task.

        Args:
            task_name: Name of the task to update
            status: New status message
        """
        if task_name in self._active_tasks:
            self._active_tasks[task_name]["status"] = status
            self.logger.debug(f"Task '{task_name}' status updated to: {status}")
        else:
            self.logger.warning(f"Attempted to update status of unknown task: {task_name}")

    def get_active_tasks(self) -> Dict[str, Dict[str, Any]]:
        """
        Get information about all currently active tasks.

        Returns:
            Dictionary mapping task names to their current information including elapsed time
        """
        # Include elapsed time for each task
        now = datetime.datetime.now()
        result = {}

        for name, info in self._active_tasks.items():
            elapsed = (now - info["start_time"]).total_seconds()
            result[name] = {**info, "elapsed_seconds": elapsed}

        return result

    def get_task_stats(self, task_name: str = None) -> Union[Dict[str, Any], Dict[str, Dict[str, Any]]]:
        """
        Get statistics for a specific task or all tasks.

        Args:
            task_name: Name of the task to get statistics for, or None for all tasks

        Returns:
            Dictionary of task statistics
        """
        if task_name:
            return self._task_stats.get(task_name, {"count": 0, "success": 0, "failure": 0, "total_time": 0, "avg_time": 0})
        return self._task_stats

    def get_task_history(self, task_name: str = None, limit: int = None) -> Union[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """
        Get execution history for a task or all tasks.

        Args:
            task_name: Name of the task to get history for, or None for all tasks
            limit: Maximum number of history entries to return per task

        Returns:
            List of task execution records or dictionary mapping task names to lists of records
        """
        if task_name:
            history = list(self._task_history.get(task_name, []))
            if limit:
                return history[-limit:]
            return history

        if limit:
            return {name: list(records)[-limit:] for name, records in self._task_history.items()}
        return {name: list(records) for name, records in self._task_history.items()}

    def set_history_size(self, size: int) -> None:
        """
        Set the maximum number of execution records to keep per task.

        Args:
            size: Maximum number of records to keep
        """
        if size < 1:
            raise ValueError("History size must be at least 1")

        self._task_history_size = size

        # Update existing history queues
        for name, history in self._task_history.items():
            new_history = deque(list(history), maxlen=size)
            self._task_history[name] = new_history

    def clear_error_state(self) -> None:
        """Reset the error flag to indicate issues have been addressed."""
        self._has_errors = False
        self.logger.info("Task error state cleared")

    def has_errors(self) -> bool:
        """Check if there have been any task errors."""
        return self._has_errors

    def get_error_rate(self, task_name: str = None) -> Union[float, Dict[str, float]]:
        """
        Get the error rate for a task or all tasks.

        Args:
            task_name: Name of the task to get the error rate for, or None for all tasks

        Returns:
            Error rate as a float between 0 and 1, or dictionary of task error rates
        """
        if task_name:
            stats = self._task_stats.get(task_name)
            if not stats or stats["count"] == 0:
                return 0.0
            return stats["failure"] / stats["count"]

        return {name: (stats["failure"] / stats["count"]) if stats["count"] > 0 else 0.0 for name, stats in self._task_stats.items()}

    def get_status_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive status report of all task activity.

        Returns:
            Dictionary containing active tasks, recent history, and statistics
        """
        now = datetime.datetime.now()

        # Get active task information with elapsed time
        active_tasks = {}
        for name, info in self._active_tasks.items():
            elapsed = (now - info["start_time"]).total_seconds()
            active_tasks[name] = {"status": info["status"], "started_at": info["start_time"], "elapsed_seconds": elapsed}

        # Get the most recent execution of each task
        recent_activity = {}
        for name, history in self._task_history.items():
            if history:
                latest = history[-1]
                recent_activity[name] = {
                    "time": latest["end_time"],
                    "success": latest["success"],
                    "execution_time": latest["execution_time"],
                    "status": latest["status"],
                }

        # Get task statistics
        task_stats = {
            name: {
                "total": stats["count"],
                "success": stats["success"],
                "failure": stats["failure"],
                "success_rate": (stats["success"] / stats["count"]) if stats["count"] > 0 else 0,
                "avg_time": stats["avg_time"],
            }
            for name, stats in self._task_stats.items()
        }

        return {"active_tasks": active_tasks, "recent_activity": recent_activity, "statistics": task_stats, "has_errors": self._has_errors}

    @asynccontextmanager
    async def task_context(self, task_name: str, initial_status: str = "Starting"):
        """
        Context manager for tracking task execution.

        Args:
            task_name: Name of the task to track
            initial_status: Initial status message for the task

        Example:
            async with task_tracker.task_context("Data Refresh", "Starting refresh") as tracker:
                await do_something()
                tracker.update_status("Processing data")
                await do_more_things()
        """
        self.begin_task(task_name, initial_status)
        try:
            # Create a simple namespace for status updates
            tracker = SimpleNamespace(current_status=initial_status, update_status=lambda status: self.update_task_status(task_name, status))
            yield tracker
            self.end_task(task_name, success=True)
        except Exception as e:
            self.end_task(task_name, success=False, status=f"Error: {str(e)}")
            raise

    @staticmethod
    def format_task_time(seconds: float) -> str:
        """
        Format task execution time in a human-readable way.

        Args:
            seconds: Time in seconds

        Returns:
            Human-readable string representation of the time
        """
        if seconds < 0.001:
            return f"{seconds * 1000000:.2f} µs"
        elif seconds < 1:
            return f"{seconds * 1000:.2f} ms"
        elif seconds < 60:
            return f"{seconds:.2f} seconds"
        else:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}m {secs:.2f}s"
