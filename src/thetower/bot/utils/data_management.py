"""
Data Management Utilities

This module contains utility functions for managing data persistence, tracking
modifications, and handling serialization/deserialization across the bot.
"""

import asyncio
import json
import logging
import pickle
from pathlib import Path
from typing import Any, Callable, Optional, Union

logger = logging.getLogger(__name__)


class DataManager:
    """
    Manages data persistence with modification tracking.

    This class provides methods to track data modifications, save data when needed,
    and load data from files. It supports different serialization formats based on file extension.

    Usage:
        data_manager = DataManager()
        data_manager.mark_modified()
        await data_manager.save_if_modified(data, file_path)
    """

    def __init__(self):
        """Initialize the data manager."""
        self._modified = False
        self._save_lock = asyncio.Lock()

    def mark_modified(self) -> None:
        """Mark the data as modified, needing to be saved."""
        self._modified = True

    def is_modified(self) -> bool:
        """Check if the data has been modified since last save."""
        return self._modified

    def reset_modified(self) -> None:
        """Reset the modified flag after a successful save."""
        self._modified = False

    async def save_if_modified(self, data: Any, file_path: Union[str, Path], force: bool = False) -> bool:
        """
        Save data to file if it has been modified or if forced.

        Args:
            data: The data to save (must be JSON/pickle serializable)
            file_path: Path where the data should be saved
            force: Whether to save even if not modified

        Returns:
            bool: True if save was successful, False otherwise
        """
        # Skip saving if nothing has changed and not forced
        if not force and not self._modified:
            return True

        # Use a lock to prevent multiple simultaneous saves
        async with self._save_lock:
            return await self.save_data(data, file_path)

    @staticmethod
    def load_json_sync(file_path: Union[str, Path], default: Any = None, create_default: bool = False) -> Any:
        """
        Synchronously load data from a JSON file.

        Args:
            file_path: Path to the JSON file
            default: Default value to return if file doesn't exist or loading fails
            create_default: Whether to create the file with default value if it doesn't exist

        Returns:
            The loaded data or default value
        """
        file_path = Path(file_path)

        if not file_path.exists():
            logger.info(f"No data file found at {file_path}, using default")
            if create_default and default is not None:
                logger.info(f"Creating default file at {file_path}")
                DataManager.save_json_sync(default, file_path)
            return default

        try:
            with open(file_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load JSON from {file_path}: {str(e)}")
            return default

    @staticmethod
    def save_json_sync(data: Any, file_path: Union[str, Path]) -> bool:
        """
        Synchronously save data to a JSON file.

        Args:
            data: The data to save (must be JSON serializable)
            file_path: Path where the data should be saved

        Returns:
            bool: True if save was successful, False otherwise
        """
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save JSON to {file_path}: {str(e)}")
            return False

    @staticmethod
    def load_pickle_sync(file_path: Union[str, Path], default: Any = None, create_default: bool = False) -> Any:
        """
        Synchronously load data from a pickle file.

        Args:
            file_path: Path to the pickle file
            default: Default value to return if file doesn't exist or loading fails
            create_default: Whether to create the file with default value if it doesn't exist

        Returns:
            The loaded data or default value
        """
        file_path = Path(file_path)

        if not file_path.exists():
            logger.info(f"No data file found at {file_path}, using default")
            if create_default and default is not None:
                logger.info(f"Creating default file at {file_path}")
                DataManager.save_pickle_sync(default, file_path)
            return default

        try:
            with open(file_path, "rb") as f:
                return pickle.load(f)
        except ModuleNotFoundError as e:
            # Handle legacy pickle files with old module references
            logger.warning(
                f"Legacy pickle file {file_path} contains references to missing modules ({e}). Using default value and will recreate file."
            )
            if create_default and default is not None:
                logger.info(f"Recreating pickle file {file_path} with default data")
                DataManager.save_pickle_sync(default, file_path)
            return default
        except Exception as e:
            logger.error(f"Failed to load pickle from {file_path}: {str(e)}")
            return default

    @staticmethod
    def save_pickle_sync(data: Any, file_path: Union[str, Path]) -> bool:
        """
        Synchronously save data to a pickle file.

        Args:
            data: The data to save (must be pickle serializable)
            file_path: Path where the data should be saved

        Returns:
            bool: True if save was successful, False otherwise
        """
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(file_path, "wb") as f:
                pickle.dump(data, f)
            return True
        except Exception as e:
            logger.error(f"Failed to save pickle to {file_path}: {str(e)}")
            return False

    @staticmethod
    def load_data_sync(file_path: Union[str, Path], default: Any = None, format_type: str = None, create_default: bool = False) -> Any:
        """
        Synchronously load data from a file in either JSON or pickle format.

        Args:
            file_path: Path to the data file
            default: Default value to return if file doesn't exist or loading fails
            format_type: Format type ('json' or 'pickle'), if None will be determined from file extension
            create_default: Whether to create the file with default value if it doesn't exist

        Returns:
            The loaded data or default value
        """
        file_path = Path(file_path)

        if not file_path.exists():
            logger.info(f"No data file found at {file_path}, using default")
            if create_default and default is not None:
                logger.info(f"Creating default file at {file_path}")
                DataManager.save_data_sync(default, file_path, format_type)
            return default

        # Determine format from extension if not explicitly provided
        if format_type is None:
            extension = file_path.suffix.lower()
            if extension == ".json":
                format_type = "json"
            elif extension in (".pkl", ".pickle"):
                format_type = "pickle"
            else:
                logger.warning(f"Couldn't determine format from extension {extension}, defaulting to JSON")
                format_type = "json"

        try:
            if format_type.lower() == "json":
                with open(file_path, "r") as f:
                    return json.load(f)
            elif format_type.lower() in ("pickle", "pkl"):
                with open(file_path, "rb") as f:
                    return pickle.load(f)
            else:
                logger.error(f"Unsupported format type: {format_type}")
                return default
        except ModuleNotFoundError as e:
            # Handle legacy pickle files with old module references
            logger.warning(
                f"Legacy pickle file {file_path} contains references to missing modules ({e}). Using default value and will recreate file."
            )
            if create_default and default is not None:
                logger.info(f"Recreating file {file_path} with default data")
                DataManager.save_data_sync(default, file_path, format_type)
            return default
        except Exception as e:
            logger.error(f"Failed to load data from {file_path} as {format_type}: {str(e)}")
            return default

    @staticmethod
    def save_data_sync(data: Any, file_path: Union[str, Path], format_type: str = None) -> bool:
        """
        Synchronously save data to a file in either JSON or pickle format.

        Args:
            data: The data to save
            file_path: Path where the data should be saved
            format_type: Format type ('json' or 'pickle'), if None will be determined from file extension

        Returns:
            bool: True if save was successful, False otherwise
        """
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Determine format from extension if not explicitly provided
        if format_type is None:
            extension = file_path.suffix.lower()
            if extension == ".json":
                format_type = "json"
            elif extension in (".pkl", ".pickle"):
                format_type = "pickle"
            else:
                logger.warning(f"Couldn't determine format from extension {extension}, defaulting to JSON")
                format_type = "json"

        try:
            if format_type.lower() == "json":
                with open(file_path, "w") as f:
                    json.dump(data, f, indent=2)
                return True
            elif format_type.lower() in ("pickle", "pkl"):
                with open(file_path, "wb") as f:
                    pickle.dump(data, f)
                return True
            else:
                logger.error(f"Unsupported format type: {format_type}")
                return False
        except Exception as e:
            logger.error(f"Failed to save data to {file_path} as {format_type}: {str(e)}")
            return False

    @staticmethod
    async def _save_json(data: Any, file_path: Path) -> None:
        """Save data as JSON."""
        # Use run_in_executor for file IO to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: file_path.write_text(json.dumps(data, indent=2)))

    @staticmethod
    async def _save_pickle(data: Any, file_path: Path) -> None:
        """Save data as pickle."""
        # Use run_in_executor for file IO to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: file_path.write_bytes(pickle.dumps(data)))

    @staticmethod
    async def load_data(
        file_path: Union[str, Path],
        default: Any = None,
        post_process: Optional[Callable] = None,
        format_type: str = None,
        create_default: bool = False,
    ) -> Any:
        """
        Load data from a file with fallback to default if file doesn't exist.

        Args:
            file_path: Path to the data file
            default: Default value to return if file doesn't exist
            post_process: Optional function to process data after loading
            format_type: Format type ('json' or 'pickle'), if None will be determined from file extension
            create_default: Whether to create the file with default value if it doesn't exist

        Returns:
            The loaded data or default value
        """
        file_path = Path(file_path)

        if not file_path.exists():
            logger.info(f"No data file found at {file_path}, using default")
            if create_default and default is not None:
                logger.info(f"Creating default file at {file_path}")
                await DataManager.save_data(default, file_path, format_type)
            return default

        try:
            loop = asyncio.get_event_loop()

            # Determine format from extension if not explicitly provided
            if format_type is None:
                extension = file_path.suffix.lower()
                if extension == ".json":
                    format_type = "json"
                elif extension in (".pkl", ".pickle"):
                    format_type = "pickle"
                else:
                    logger.warning(f"Couldn't determine format from extension {extension}, defaulting to JSON")
                    format_type = "json"

            # Load data based on format type
            if format_type.lower() == "json":
                data = await loop.run_in_executor(None, lambda: json.loads(file_path.read_text()))
            elif format_type.lower() in ("pickle", "pkl"):
                data = await loop.run_in_executor(None, lambda: pickle.loads(file_path.read_bytes()))
            else:
                raise ValueError(f"Unsupported format type: {format_type}")

            # Apply post-processing if provided
            if post_process is not None:
                data = post_process(data)

            logger.info(f"Loaded data from {file_path}")
            return data
        except ModuleNotFoundError as e:
            # Handle legacy pickle files with old module references
            logger.warning(
                f"Legacy pickle file {file_path} contains references to missing modules ({e}). Using default value and will recreate file."
            )
            if create_default and default is not None:
                logger.info(f"Recreating file {file_path} with default data")
                await DataManager.save_data(default, file_path, format_type)
            return default
        except Exception as e:
            logger.error(f"Failed to load data from {file_path} as {format_type}: {str(e)}")
            return default

    async def save_data(self, data: Any, file_path: Union[str, Path], format_type: str = None) -> bool:
        """
        Save data to a file in either JSON or pickle format.

        Args:
            data: The data to save
            file_path: Path where the data should be saved
            format_type: Format type ('json' or 'pickle'), if None will be determined from file extension

        Returns:
            bool: True if save was successful, False otherwise
        """
        try:
            # Ensure directory exists
            file_path = Path(file_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Determine format from extension if not explicitly provided
            if format_type is None:
                extension = file_path.suffix.lower()
                if extension == ".json":
                    format_type = "json"
                elif extension in (".pkl", ".pickle"):
                    format_type = "pickle"
                else:
                    logger.warning(f"Couldn't determine format from extension {extension}, defaulting to JSON")
                    format_type = "json"

            # Save based on format type
            if format_type.lower() == "json":
                await self._save_json(data, file_path)
            elif format_type.lower() in ("pickle", "pkl"):
                await self._save_pickle(data, file_path)
            else:
                raise ValueError(f"Unsupported format type: {format_type}")

            self.reset_modified()
            logger.info(f"Saved data to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save data to {file_path} as {format_type}: {str(e)}")
            return False


class PeriodicTask:
    """
    Manages periodic tasks like data saving.

    This class wraps common patterns for creating and managing periodic
    background tasks in the bot.

    Usage:
        task_manager = PeriodicTask(bot)
        task = await task_manager.create_periodic_save_task(
            data_manager.save_if_modified,
            data_object,
            file_path,
            interval=3600
        )
    """

    def __init__(self, bot):
        """
        Initialize the task manager.

        Args:
            bot: The bot instance
        """
        self.bot = bot
        self.tasks = {}

    async def create_periodic_task(self, coroutine_func: Callable, interval: int, name: Optional[str] = None, *args, **kwargs) -> asyncio.Task:
        """
        Create a task that runs periodically.

        Args:
            coroutine_func: Async function to call periodically
            interval: How often to run the task (in seconds)
            name: Optional name for the task (for tracking)
            *args, **kwargs: Arguments to pass to the coroutine function

        Returns:
            asyncio.Task: The created task
        """

        async def periodic_runner():
            await self.bot.wait_until_ready()
            while not self.bot.is_closed():
                try:
                    await coroutine_func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Error in periodic task {name or coroutine_func.__name__}: {e}")
                await asyncio.sleep(interval)

        task = self.bot.loop.create_task(periodic_runner())

        if name:
            self.tasks[name] = task

        return task

    async def create_periodic_save_task(
        self, data_manager: DataManager, data_object: Any, file_path: Union[str, Path], interval: int = 3600, name: Optional[str] = None
    ) -> asyncio.Task:
        """
        Create a task that periodically saves data.

        Args:
            data_manager: DataManager instance
            data_object: The data to save
            file_path: Path where to save the data
            interval: How often to save (in seconds)
            name: Optional name for the task

        Returns:
            asyncio.Task: The created task
        """
        return await self.create_periodic_task(
            data_manager.save_if_modified, interval, name or f"save_task_{Path(file_path).name}", data_object, file_path
        )

    def cancel_task(self, name: str) -> bool:
        """
        Cancel a task by name.

        Args:
            name: Name of the task to cancel

        Returns:
            bool: True if task was found and cancelled, False otherwise
        """
        if name in self.tasks:
            self.tasks[name].cancel()
            del self.tasks[name]
            return True
        return False

    def cancel_all_tasks(self) -> int:
        """
        Cancel all managed tasks.

        Returns:
            int: Number of tasks cancelled
        """
        count = 0
        for task in self.tasks.values():
            task.cancel()
            count += 1
        self.tasks.clear()
        return count


# Singleton instances for easy access
data_manager = DataManager()

# Helper functions


def sort_dictionary(d):
    """Sort a dictionary by keys alphabetically.

    Works recursively on nested dictionaries.

    Args:
        d: Dictionary to sort

    Returns:
        OrderedDict with alphabetically sorted keys
    """
    from collections import OrderedDict

    # Handle non-dict types
    if not isinstance(d, dict):
        return d

    # Create a new OrderedDict with sorted keys
    result = OrderedDict()
    for key in sorted(d.keys()):
        # Recursively sort any nested dictionaries
        result[key] = sort_dictionary(d[key]) if isinstance(d[key], dict) else d[key]

    return result


def sort_list_alphabetically(lst):
    """Sort a list alphabetically.

    Args:
        lst: List to sort

    Returns:
        Alphabetically sorted list
    """
    if not isinstance(lst, list):
        return lst

    return sorted(lst)


def mark_modified():
    """Mark the global data manager as modified."""
    data_manager.mark_modified()


async def save_data(data: Any, file_path: Union[str, Path], force: bool = False) -> bool:
    """
    Save data to file using the global data manager.

    Args:
        data: Data to save
        file_path: Where to save the data
        force: Whether to force save even if not modified

    Returns:
        bool: Whether the save was successful
    """
    return await data_manager.save_if_modified(data, file_path, force)


async def load_data(file_path: Union[str, Path], default: Any = None) -> Any:
    """
    Load data from file with fallback to default.

    Args:
        file_path: Path to the data file
        default: Default value if file doesn't exist

    Returns:
        The loaded data or default
    """
    return await DataManager.load_data(file_path, default)
