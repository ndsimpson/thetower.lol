import logging
import sys
from typing import Any, Dict

import discord

logger = logging.getLogger(__name__)


class MemoryUtils:
    """Utility class for memory measurement and reporting."""

    @staticmethod
    def format_bytes(size_bytes: int) -> str:
        """Format bytes into a human-readable string"""
        if size_bytes < 1024:
            return f"{size_bytes} bytes"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    @classmethod
    def get_memory_usage(cls, obj=None, detailed=False) -> Dict[str, Any]:
        """
        Get memory usage statistics for an object or the current process

        Args:
            obj: Object to analyze (if None, analyzes current process)
            detailed: Whether to include detailed object type information

        Returns:
            Dictionary with memory usage information
        """
        result = {
            "success": False,
            "error": None,
            "total_size": 0,
            "total_size_formatted": "0 bytes",
            "process_rss": None,
            "process_vms": None,
            "type_summary": None
        }

        try:
            # Process memory from system
            try:
                import psutil
                process = psutil.Process()
                result["process_rss"] = process.memory_info().rss  # Resident Set Size
                result["process_vms"] = process.memory_info().vms  # Virtual Memory Size
                result["process_rss_formatted"] = cls.format_bytes(result["process_rss"])
                result["process_vms_formatted"] = cls.format_bytes(result["process_vms"])
            except ImportError:
                logger.warning("psutil not available for process memory information")

            # Object memory size using pympler (most accurate)
            try:
                from pympler import asizeof, muppy, summary

                if obj is not None:
                    # Measure specific object
                    result["total_size"] = asizeof.asizeof(obj)
                    result["total_size_formatted"] = cls.format_bytes(result["total_size"])

                    # If it's a complex object with components
                    if hasattr(obj, "__dict__") and detailed:
                        component_sizes = {}
                        for key, value in obj.__dict__.items():
                            if not key.startswith("_"):  # Skip private attributes
                                component_sizes[key] = {
                                    "size": asizeof.asizeof(value),
                                    "size_formatted": cls.format_bytes(asizeof.asizeof(value))
                                }
                        result["components"] = component_sizes

                # If detailed is requested or no specific object
                if detailed or obj is None:
                    all_objects = muppy.get_objects()
                    sum_output = summary.summarize(all_objects)
                    result["type_summary"] = summary.format_(sum_output, limit=20)  # Top 20 object types

                result["success"] = True

            except ImportError:
                # Fallback to sys.getsizeof (less accurate)
                logger.warning("pympler not available, using sys.getsizeof (less accurate)")

                # Define custom recursive size calculator
                seen = set()

                def get_size(obj):
                    obj_id = id(obj)
                    if obj_id in seen:
                        return 0
                    seen.add(obj_id)

                    size = sys.getsizeof(obj)

                    if isinstance(obj, dict):
                        size += sum(get_size(k) + get_size(v) for k, v in obj.items())
                    elif isinstance(obj, (list, tuple, set)):
                        size += sum(get_size(i) for i in obj)

                    return size

                if obj is not None:
                    result["total_size"] = get_size(obj)
                    result["total_size_formatted"] = cls.format_bytes(result["total_size"])

                    if hasattr(obj, "__dict__") and detailed:
                        component_sizes = {}
                        seen = set()  # Reset seen set for each component
                        for key, value in obj.__dict__.items():
                            if not key.startswith("_"):  # Skip private attributes
                                component_sizes[key] = {
                                    "size": get_size(value),
                                    "size_formatted": cls.format_bytes(get_size(value))
                                }
                        result["components"] = component_sizes

                result["success"] = True
                result["method"] = "sys.getsizeof (approximate)"

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Error measuring memory usage: {e}", exc_info=True)

        return result

    @classmethod
    async def send_memory_report(cls, ctx: discord.ext.commands.Context,
                                 obj=None,
                                 title: str = "Memory Usage Report",
                                 detailed: bool = False) -> None:
        """
        Generate and send a memory usage report to a Discord context

        Args:
            ctx: Discord command context
            obj: Object to analyze (if None, analyzes the bot)
            title: Title for the embed
            detailed: Whether to include detailed object type information
        """
        await ctx.typing()

        # Use the bot if no object specified
        if obj is None:
            obj = ctx.bot
            obj_name = "Bot"
        else:
            obj_name = obj.__class__.__name__

        mem_info = cls.get_memory_usage(obj, detailed)

        if not mem_info["success"]:
            await ctx.send(f"❌ Error measuring memory: {mem_info['error']}")
            return

        # Create main embed
        embed = discord.Embed(
            title=title,
            description=f"Memory analysis for {obj_name}",
            color=discord.Color.blue()
        )

        # Add object size
        embed.add_field(
            name=f"{obj_name} Size",
            value=mem_info["total_size_formatted"],
            inline=True
        )

        # Add process memory if available
        if mem_info.get("process_rss"):
            embed.add_field(
                name="Process Memory",
                value=f"RSS: {mem_info['process_rss_formatted']}\nVMS: {mem_info['process_vms_formatted']}",
                inline=True
            )

        # Add measurement method if available
        if "method" in mem_info:
            embed.add_field(
                name="Measurement Method",
                value=mem_info["method"],
                inline=True
            )

        # Add component breakdown if available
        if "components" in mem_info:
            # Sort components by size (largest first)
            sorted_components = sorted(
                mem_info["components"].items(),
                key=lambda x: x[1]["size"],
                reverse=True
            )

            # Format component list
            component_text = "\n".join([
                f"**{name}**: {data['size_formatted']}"
                for name, data in sorted_components[:10]  # Show top 10
            ])

            if len(sorted_components) > 10:
                component_text += f"\n... and {len(sorted_components) - 10} more"

            embed.add_field(
                name="Component Breakdown",
                value=component_text or "No components found",
                inline=False
            )

        # Send the main embed
        await ctx.send(embed=embed)

        # Send type summary if available (as code blocks)
        if mem_info.get("type_summary") and detailed:
            summary_text = mem_info["type_summary"]

            await ctx.send("**Object Type Summary**:")

            # Split into chunks if needed
            for i in range(0, len(summary_text), 1990):
                chunk = summary_text[i:i + 1990]
                await ctx.send(f"```\n{chunk}\n```")
