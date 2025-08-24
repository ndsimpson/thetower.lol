import subprocess
import datetime
import asyncio
import discord
from discord.ext import commands
from discord.ext.commands import Context
from thetower.bot.basecog import BaseCog
from pathlib import Path
from typing import Optional, List, Tuple


class GitManagement(BaseCog,
                    name="Git Management",
                    description="Manages Git repository operations and updates"):
    """Git repository management and automation.

    Provides commands for pulling updates, managing submodules,
    and monitoring repository status with automatic error handling
    and retries.
    """

    VALID_PULL_METHODS = {"rebase", "merge"}
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # seconds
    BUFFER_SIZE = 16384  # Increased buffer size for subprocess output

    def __init__(self, bot):
        # Initialize core instance variables
        self._last_operation_time = None
        self._active_process = None
        self._process_start_time = None
        self._last_error = None
        self._retry_count = 0
        self._submodule_status = {}
        self._pull_in_progress = asyncio.Lock()

        # Define settings with descriptions
        settings_config = {
            "git_directory": ("/tourney", "Git repository directory path"),
            "auto_rebase": (False, "Use rebase instead of merge for pulls"),
            "pull_timeout": (300, "Timeout for git operations in seconds"),
            "recurse_submodules": (True, "Include submodules in operations"),
            "max_output_length": (1950, "Maximum Discord message length")
        }

        # Initialize parent with settings
        super().__init__(bot)
        self.logger.info("Initializing Git Management")

        # Initialize settings
        for name, (value, description) in settings_config.items():
            if not self.has_setting(name):
                self.set_setting(name, value)

        # Load settings into instance variables
        self._load_settings()

        # Add standard pause commands to the git group
        self.create_pause_commands(self.git)

    def _load_settings(self) -> None:
        """Load settings into instance variables."""
        self.git_directory = self.get_setting("git_directory")
        self.auto_rebase = self.get_setting("auto_rebase")
        self.pull_timeout = self.get_setting("pull_timeout")
        self.recurse_submodules = self.get_setting("recurse_submodules")
        self.max_output_length = self.get_setting("max_output_length")

    async def cog_initialize(self) -> None:
        """Initialize cog-specific resources after bot is ready."""
        self.logger.info("Initializing Git Management cog")
        try:
            async with self.task_tracker.task_context("Initialization"):
                # Initialize parent
                await super().cog_initialize()

                # Verify git installation
                self.task_tracker.update_task_status("Initialization", "Checking Git")
                version = await self._get_git_version()
                self.logger.info(f"Git version: {version}")

                # Verify git directory
                self.task_tracker.update_task_status("Initialization", "Checking Repository")
                git_path = Path(self.git_directory)
                if not git_path.exists():
                    raise ValueError(f"Git directory does not exist: {self.git_directory}")
                if not (git_path / ".git").exists():
                    raise ValueError(f"Not a git repository: {self.git_directory}")

                # Check submodule status
                self.task_tracker.update_task_status("Initialization", "Checking Submodules")
                await self._update_submodule_status()

                # Start maintenance tasks
                self.task_tracker.update_task_status("Initialization", "Starting Tasks")
                self.bot.loop.create_task(self._check_git_status())
                self.bot.loop.create_task(self._cleanup_tasks())

                # Mark as ready
                self.set_ready(True)
                self.logger.info("Git Management cog initialized")

        except Exception as e:
            self._has_errors = True
            self._last_error = str(e)
            self.logger.error(f"Failed to initialize: {e}", exc_info=True)
            raise

    async def _get_git_version(self) -> str:
        """Get git version information."""
        result = await self._execute_git_command(
            ["git", "--version"],
            self.git_directory,
            timeout=10
        )
        return result.decode().strip()

    async def _check_git_status(self) -> None:
        """Periodically check git repository status."""
        while True:
            try:
                if not self.is_paused:
                    await self._execute_git_command(
                        ["git", "status", "--porcelain"],
                        self.git_directory,
                        timeout=30
                    )
            except Exception as e:
                self._has_errors = True
                self.logger.error(f"Git status check failed: {e}", exc_info=True)

            await asyncio.sleep(300)  # Check every 5 minutes

    async def _update_submodule_status(self) -> None:
        """Update submodule status information."""
        try:
            result = await self._execute_git_command(
                ["git", "submodule", "status"],
                self.git_directory,
                timeout=30
            )

            self._submodule_status = {}
            for line in result.decode("utf-8").splitlines():
                if line.strip():
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        status_char = line[0] if line[0] in ['+', '-', ' ', 'U'] else ' '
                        commit = parts[0].lstrip('+-U ')
                        name = parts[1]
                        self._submodule_status[name] = {
                            'commit': commit,
                            'status': self._parse_submodule_status(status_char)
                        }

            self.logger.debug(f"Updated submodule status: {len(self._submodule_status)} submodules found")
        except Exception as e:
            self.logger.error(f"Failed to update submodule status: {e}", exc_info=True)

    def _parse_submodule_status(self, status_char: str) -> str:
        """Parse submodule status character into a readable description."""
        statuses = {
            '+': 'Different commit checked out',
            '-': 'Not initialized',
            ' ': 'Up to date',
            'U': 'Merge conflicts'
        }
        return statuses.get(status_char, 'Unknown')

    async def _cleanup_tasks(self) -> None:
        """Periodically clean up stale tasks."""
        while True:
            try:
                # End tasks that have been running too long
                for task in self.task_tracker.get_active_tasks():
                    if task.elapsed_time > self.pull_timeout:
                        self.task_tracker.end_task(
                            task.name,
                            success=False,
                            status="Timed out"
                        )
            except Exception as e:
                self.logger.error(f"Task cleanup error: {e}", exc_info=True)
            await asyncio.sleep(60)

    def _build_git_command(self, method: Optional[str] = None) -> List[str]:
        """Build git pull command based on settings and method.

        Args:
            method: Optional pull method override ('rebase' or None)

        Returns:
            List of command components
        """
        cmd = ["git", "pull"]
        if self.recurse_submodules:
            cmd.append("--recurse-submodules")
        if method == "rebase" or self.auto_rebase:
            cmd.append("--rebase")
        return cmd

    @commands.group(name="git", invoke_without_command=True)
    async def git(self, ctx: Context) -> None:
        """Git repository management commands.

        Available commands:
        - status: Show current status and settings
        - pull [method]: Pull latest changes (method: rebase/merge)
        - submodules: Show submodule status
        - settings: View settings
        - set <setting> <value>: Change a setting
        - pause/resume/toggle: Control operation state

        Examples:
            $git status
            $git pull rebase
            $git set auto_rebase true
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @git.command(name="settings")
    async def settings_command(self, ctx: Context):
        """Display current git management settings.

        Shows all configurable settings and their current values.
        Use $git set <setting> <value> to change settings.

        Example:
            $git settings
        """
        settings = self.get_all_settings()

        embed = discord.Embed(
            title="Git Management Settings",
            description="Current configuration",
            color=discord.Color.blue()
        )

        for name, value in settings.items():
            # Format boolean values with emojis
            if isinstance(value, bool):
                value = "✅ Enabled" if value else "❌ Disabled"
            elif isinstance(value, (int, float)):
                # Add units for known settings
                if "timeout" in name:
                    value = f"{value} seconds"
                elif "length" in name:
                    value = f"{value} chars"

            embed.add_field(
                name=name.replace("_", " ").title(),
                value=str(value),
                inline=True
            )

        embed.set_footer(text="Use $git set <setting> <value> to change settings")
        await ctx.send(embed=embed)

    @git.command(name="set")
    async def set_setting_command(self, ctx: Context, setting: str, value: str):
        """Change a git management setting.

        Args:
            setting: Setting name to change
            value: New value to set

        Valid settings:
        - auto_rebase (true/false)
        - recurse_submodules (true/false)
        - pull_timeout (seconds)
        - max_output_length (chars)

        Examples:
            $git set auto_rebase true
            $git set pull_timeout 600
        """
        if not self.has_setting(setting):
            valid_settings = list(self.get_all_settings().keys())
            return await ctx.send(f"❌ Invalid setting. Valid options: {', '.join(valid_settings)}")

        try:
            current_value = self.get_setting(setting)

            # Convert value to correct type
            if isinstance(current_value, bool):
                value = value.lower() in ('true', '1', 'yes', 'on')
            elif isinstance(current_value, int):
                value = int(value)
            elif isinstance(current_value, float):
                value = float(value)

            # Update both setting storage and instance variable
            self.set_setting(setting, value)
            setattr(self, setting, value)

            # Format response based on type
            if isinstance(value, bool):
                status = "✅ enabled" if value else "❌ disabled"
            else:
                status = str(value)

            await ctx.send(f"Setting `{setting}` is now {status}")
            self.logger.info(f"Setting changed by {ctx.author}: {setting} = {value}")

        except ValueError:
            await ctx.send(f"❌ Invalid value format for {setting}")
        except Exception as e:
            self.logger.error(f"Error changing setting: {e}")
            await ctx.send(f"❌ An error occurred changing the setting: {str(e)}")

    # Move status under git group
    @git.command(name="status")
    async def status_command(self, ctx: Context) -> None:
        """Display current git operations status and settings.

        Shows:
        - Repository status
        - Configuration settings
        - Recent operations
        - Active tasks
        - Error state if any

        Example:
            $git status
        """
        # Determine overall status
        if not self.is_ready:
            status_emoji = "⏳"
            status_text = "Initializing"
            embed_color = discord.Color.orange()
        elif self.is_paused:
            status_emoji = "⏸️"
            status_text = "Paused"
            embed_color = discord.Color.orange()
        elif self._has_errors:
            status_emoji = "❌"
            status_text = "Error"
            embed_color = discord.Color.red()
        else:
            status_emoji = "✅"
            status_text = "Operational"
            embed_color = discord.Color.blue()

        embed = discord.Embed(
            title="Git Management Status",
            description=f"{status_emoji} Status: {status_text}",
            color=embed_color
        )

        # Add repository information
        embed.add_field(
            name="Repository",
            value=f"```\n{self.git_directory}\n```",
            inline=False
        )

        # Add settings information
        settings = {
            "Auto Rebase": self.auto_rebase,
            "Recurse Submodules": self.recurse_submodules,
            "Pull Timeout": f"{self.pull_timeout}s",
            "Max Output Length": f"{self.max_output_length} chars",
        }

        settings_text = []
        for name, value in settings.items():
            if isinstance(value, bool):
                value = "✅" if value else "❌"
            settings_text.append(f"**{name}:** {value}")

        embed.add_field(
            name="Settings",
            value="\n".join(settings_text),
            inline=False
        )

        # Add statistics
        if self._operation_count > 0:
            stats = [
                f"Operations completed: {self._operation_count}",
                f"Last operation: {self.format_relative_time(self._last_operation_time)}" if self._last_operation_time else "Never"
            ]
            embed.add_field(
                name="Statistics",
                value="\n".join(stats),
                inline=False
            )

        # Add last error if applicable
        if self._last_error:
            embed.add_field(
                name="Last Error",
                value=f"```{self._last_error[:1000]}```",
                inline=False
            )

        # Add task tracking info
        self.add_task_status_fields(embed)

        await ctx.send(embed=embed)

    @git.command(name="pull")
    async def pull_git(self, ctx: Context, method: Optional[str] = None) -> None:
        """Pull latest changes from git repository.

        Args:
            ctx: The command context
            method (str, optional): Pull method ('rebase' or None). Defaults to None.
        """
        # Command execution logging
        start_time = datetime.datetime.now()
        self.logger.info(f"Git pull requested by {ctx.author} with method: {method}")

        if not await self.wait_until_ready():
            await ctx.send("⏳ Still initializing, please try again later.")
            return

        if self.is_paused:
            await ctx.send("⏸️ Git operations are currently paused.")
            return

        if self._pull_in_progress.locked():
            await ctx.send("⏳ Another pull operation is in progress, please wait.")
            return

        # Validate pull method
        if method and method not in self.VALID_PULL_METHODS:
            await ctx.send(
                f"❌ Invalid pull method. Valid options: {', '.join(self.VALID_PULL_METHODS)}"
            )
            return

        async with self._pull_in_progress:
            async with self.task_tracker.task_context("Git Pull", "Initiating git pull operation") as task:
                try:
                    task.update_status("Building command...")
                    cmd = self._build_git_command(method)

                    task.update_status("Executing git command...")
                    response, success = await self._execute_git_command_with_retry(
                        cmd,
                        self.git_directory,
                        self.pull_timeout
                    )

                    if not success:
                        raise RuntimeError("Git operation failed after retries")

                    # Update submodule status after pull
                    task.update_status("Updating submodule status...")
                    await self._update_submodule_status()

                    # Format the output for sending
                    output = response.decode("utf-8", errors="replace")
                    if len(output) > self.max_output_length:
                        output = output[:self.max_output_length] + "\n... [output truncated]"

                    await ctx.send(output)
                    self._operation_count += 1
                    self._last_operation_time = datetime.datetime.now()

                    # Log completion
                    elapsed = (datetime.datetime.now() - start_time).total_seconds()
                    self.logger.info(f"Git pull completed in {elapsed:.2f}s")

                except subprocess.CalledProcessError as e:
                    self._has_errors = True
                    error_output = e.output.decode("utf-8", errors="replace")

                    # Check for known submodule errors
                    if "fatal: unable to access" in error_output or "Could not resolve host" in error_output:
                        error_output = "Network error accessing submodule. Check your internet connection.\n\n" + error_output

                    if len(error_output) > self.max_output_length:
                        error_output = error_output[:self.max_output_length] + "\n... [error output truncated]"

                    self._last_error = error_output
                    self.logger.error(f"Git pull failed: {error_output}")
                    await ctx.send(f"Git pull failed: {error_output}")
                    raise
                except Exception as e:
                    self._has_errors = True
                    elapsed = (datetime.datetime.now() - start_time).total_seconds()
                    error_message = str(e)
                    self._last_error = error_message
                    self.logger.error(
                        f"Git pull failed after {elapsed:.2f}s: {error_message}",
                        exc_info=True
                    )
                    await ctx.send(f"An error occurred: {error_message}")
                    raise

    @git.command(name="submodules")
    async def submodules_command(self, ctx: Context) -> None:
        """Display submodule status information."""
        if not await self.wait_until_ready():
            await ctx.send("⏳ Still initializing, please try again later.")
            return

        async with self.task_tracker.task_context("Submodule Status", "Checking submodule status") as task:
            try:
                # Refresh submodule status
                task.update_status("Updating submodule status...")
                await self._update_submodule_status()

                if not self._submodule_status:
                    await ctx.send("No submodules found in the repository.")
                    return

                embed = discord.Embed(
                    title="Git Submodule Status",
                    description=f"Found {len(self._submodule_status)} submodules",
                    color=discord.Color.blue()
                )

                # Add each submodule to the embed
                for name, info in self._submodule_status.items():
                    status_emoji = "✅" if info['status'] == "Up to date" else "⚠️"
                    embed.add_field(
                        name=f"{status_emoji} {name}",
                        value=f"Status: {info['status']}\nCommit: `{info['commit'][:7]}`",
                        inline=False
                    )

                await ctx.send(embed=embed)

            except Exception as e:
                self._has_errors = True
                self._last_error = str(e)
                self.logger.error(f"Failed to check submodule status: {e}", exc_info=True)
                await ctx.send(f"An error occurred while checking submodules: {str(e)}")
                raise

    async def _execute_git_command(self, cmd: list[str], cwd: str, timeout: int) -> bytes:
        """Execute a git command asynchronously and return its output.

        Args:
            cmd: List of command components
            cwd: Working directory for the command
            timeout: Command timeout in seconds

        Returns:
            bytes: Command output

        Raises:
            subprocess.CalledProcessError: If the command returns non-zero exit status
            asyncio.TimeoutError: If the command exceeds the timeout
        """
        # Get current task if running within task context
        current_task = None
        if hasattr(self.task_tracker, 'current_task'):
            current_task = self.task_tracker.current_task

        async def _run_process():
            # Create process
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )

            if current_task:
                self.task_tracker.update_status(current_task, f"Running command: {' '.join(cmd)}")

            # Start reading outputs
            stdout_chunks = []
            stderr_chunks = []

            while True:
                # Read chunks from stdout/stderr
                stdout_chunk = await process.stdout.read(self.BUFFER_SIZE)
                stderr_chunk = await process.stderr.read(self.BUFFER_SIZE)

                if not stdout_chunk and not stderr_chunk:
                    break

                # Store chunks
                if stdout_chunk:
                    stdout_chunks.append(stdout_chunk)
                    if current_task:
                        self.task_tracker.update_status(current_task, f"Processing output ({len(stdout_chunks)} chunks)...")
                if stderr_chunk:
                    stderr_chunks.append(stderr_chunk)

            # Wait for process to complete
            await process.wait()

            # Combine outputs
            stdout = b''.join(stdout_chunks)
            stderr = b''.join(stderr_chunks)

            # Check return code
            if process.returncode != 0:
                # Create custom exception with output
                error = subprocess.CalledProcessError(process.returncode, cmd)
                error.output = stderr if stderr else stdout
                if current_task:
                    self.task_tracker.update_status(current_task, f"Command failed with exit code {process.returncode}")
                raise error

            # Return combined output
            return stdout

        # Run with timeout
        try:
            if current_task:
                self.task_tracker.update_status(current_task, "Starting git operation...")
            result = await asyncio.wait_for(_run_process(), timeout=timeout)
            if current_task:
                self.task_tracker.update_status(current_task, "Git operation completed successfully")
            return result
        except asyncio.TimeoutError:
            if current_task:
                self.task_tracker.update_status(current_task, f"Command timed out after {timeout}s")
            self.logger.error(f"Command timed out after {timeout}s: {' '.join(cmd)}")
            raise
        except Exception as e:
            if current_task:
                self.task_tracker.update_status(current_task, f"Command failed: {str(e)}")
            raise

    async def _execute_git_command_with_retry(
        self, cmd: List[str], cwd: str, timeout: int
    ) -> Tuple[bytes, bool]:
        """Execute git command with retry logic."""
        current_task = self.task_tracker.get_current_task()

        for attempt in range(self.MAX_RETRIES):
            try:
                if attempt > 0:
                    if current_task:
                        current_task.update_status(f"Retry attempt {attempt + 1}/{self.MAX_RETRIES}...")
                    self.logger.warning(f"Retry attempt {attempt + 1} for command: {' '.join(cmd)}")
                    await asyncio.sleep(self.RETRY_DELAY)

                self.logger.debug(f"Executing git command: {' '.join(cmd)}")
                result = await self._execute_git_command(cmd, cwd, timeout)
                return result, True

            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed: {e}", exc_info=True)
                if attempt == self.MAX_RETRIES - 1:
                    if current_task:
                        current_task.update_status(f"All retry attempts failed: {str(e)}")
                    raise

        return b"", False

    @commands.command(name="toggle")
    async def toggle_command(self, ctx: Context, setting_name: str) -> None:
        """Toggle a boolean setting.

        Valid settings: auto_rebase, recurse_submodules

        Args:
            setting_name: Name of setting to toggle
        """
        valid_toggles = {"auto_rebase", "recurse_submodules"}

        if setting_name not in valid_toggles:
            await ctx.send(f"Invalid setting. Valid options: {', '.join(valid_toggles)}")
            return

        new_state = not getattr(self, setting_name)
        setattr(self, setting_name, new_state)
        self.set_setting(setting_name, new_state)

    async def cog_unload(self) -> None:
        """Clean up resources when cog is unloaded."""
        self.logger.info("Unloading Git Management cog")
        # Cancel any active tasks
        active_tasks = self.task_tracker.get_active_tasks()
        if active_tasks:
            self.logger.warning(f"Cancelling {len(active_tasks)} active tasks")
            for task in active_tasks:
                self.task_tracker.end_task(task, success=False, status="Cog unloaded")


async def setup(bot) -> None:
    await bot.add_cog(GitManagement(bot))
