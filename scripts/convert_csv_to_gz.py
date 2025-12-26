#!/usr/bin/env python
"""
Convert existing .csv files to .csv.gz with data verification.

This script:
1. Finds all .csv files in the data directories
2. Reads each .csv file
3. Writes it as .csv.gz with gzip compression
4. Reads back the .csv.gz to verify data integrity
5. Only deletes the original .csv after successful verification
6. Logs all operations for safety
"""
import argparse
import logging
import os
import signal
import sys
from pathlib import Path

import pandas as pd

# Setup logging - file gets detailed logs, console gets progress
file_handler = logging.FileHandler("csv_conversion.log", encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.WARNING)  # Only warnings/errors to console
console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])
logger = logging.getLogger(__name__)


# Global stats tracking
class ConversionStats:
    def __init__(self):
        self.total_files = 0
        self.processed = 0
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.original_bytes = 0
        self.compressed_bytes = 0
        self.interrupted = False

    def format_bytes(self, bytes_val):
        """Format bytes as human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_val < 1024.0:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f} TB"

    def print_summary(self, dry_run=False, keep_original=False):
        """Print summary statistics."""
        print("\n" + "=" * 80)
        print("CONVERSION SUMMARY")
        print("=" * 80)
        print(f"Total files found:     {self.total_files}")
        print(f"Processed:             {self.processed}")
        print(f"  Successful:          {self.success}")
        print(f"  Failed:              {self.failed}")
        print(f"  Skipped (.gz exists): {self.skipped}")

        if self.original_bytes > 0 or self.compressed_bytes > 0:
            savings = self.original_bytes - self.compressed_bytes
            savings_pct = (savings / self.original_bytes * 100) if self.original_bytes > 0 else 0
            print("\nSpace usage:")
            print(f"  Original size:       {self.format_bytes(self.original_bytes)}")
            print(f"  Compressed size:     {self.format_bytes(self.compressed_bytes)}")
            print(f"  Space saved:         {self.format_bytes(savings)} ({savings_pct:.1f}%)")

        if dry_run:
            print("\n[DRY RUN] No files were actually modified")
        elif keep_original:
            print("\nOriginal .csv files were kept")

        if self.interrupted:
            print("\n[INTERRUPTED] Conversion was stopped by user")
        elif self.failed > 0:
            print(f"\n⚠ {self.failed} file(s) failed - see csv_conversion.log for details")
        elif self.success > 0:
            print("\n✓ All conversions completed successfully!")


stats = ConversionStats()


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    stats.interrupted = True
    logger.warning("\n\nConversion interrupted by user (Ctrl+C)")
    logger.info(f"Files processed: {stats.processed}/{stats.total_files}")
    logger.info(f"Successful: {stats.success}, Failed: {stats.failed}, Skipped: {stats.skipped}")

    if stats.original_bytes > 0 or stats.compressed_bytes > 0:
        savings = stats.original_bytes - stats.compressed_bytes
        savings_pct = (savings / stats.original_bytes * 100) if stats.original_bytes > 0 else 0
        logger.info(
            f"Space: Original {stats.format_bytes(stats.original_bytes)}, "
            f"Compressed {stats.format_bytes(stats.compressed_bytes)}, "
            f"Saved {stats.format_bytes(savings)} ({savings_pct:.1f}%)"
        )

    print("\n\nInterrupted by user. Showing summary of work completed so far...\n")
    stats.print_summary()
    sys.exit(130)  # Standard exit code for SIGINT


# Register signal handler
signal.signal(signal.SIGINT, signal_handler)


def verify_dataframes_equal(df1: pd.DataFrame, df2: pd.DataFrame) -> bool:
    """
    Verify two DataFrames are identical.

    Args:
        df1: First DataFrame
        df2: Second DataFrame

    Returns:
        True if DataFrames are equal, False otherwise
    """
    try:
        # Check shape first (fast check)
        if df1.shape != df2.shape:
            logger.error(f"Shape mismatch: {df1.shape} vs {df2.shape}")
            return False

        # Check column names
        if not df1.columns.equals(df2.columns):
            logger.error(f"Column mismatch: {df1.columns.tolist()} vs {df2.columns.tolist()}")
            return False

        # Check dtypes
        if not df1.dtypes.equals(df2.dtypes):
            logger.warning(f"Dtype mismatch (may be OK): {df1.dtypes.to_dict()} vs {df2.dtypes.to_dict()}")
            # Don't fail on dtype differences as compression can sometimes change them

        # Check values
        if not df1.equals(df2):
            # Try more lenient comparison for numeric columns
            try:
                pd.testing.assert_frame_equal(df1, df2, check_dtype=False, atol=1e-10)
                logger.info("DataFrames equal (with tolerance for floating point)")
                return True
            except AssertionError as e:
                logger.error(f"DataFrame content mismatch: {e}")
                return False

        return True

    except Exception as e:
        logger.error(f"Error comparing DataFrames: {e}")
        return False


def convert_file(csv_path: Path, dry_run: bool = False, keep_original: bool = False) -> bool:
    """
    Convert a single .csv file to .csv.gz with verification.

    Args:
        csv_path: Path to the .csv file
        dry_run: If True, don't actually write or delete files
        keep_original: If True, keep the original .csv file

    Returns:
        True if successful, False otherwise
    """
    gz_path = csv_path.with_suffix(".csv.gz")

    # If .gz already exists, verify it's valid and complete
    if gz_path.exists():
        logger.info(f"Found existing {gz_path}, verifying...")
        try:
            # Try to read the .gz file
            df_compressed = pd.read_csv(gz_path)
            # Try to read the original .csv file
            df_original = pd.read_csv(csv_path)

            # Verify they match
            if verify_dataframes_equal(df_original, df_compressed):
                logger.info(f"✓ Existing {gz_path} is valid and matches {csv_path}")

                # Ensure timestamps are correct
                original_stat = csv_path.stat()
                gz_stat = gz_path.stat()

                # If timestamps don't match, fix them
                if abs(gz_stat.st_mtime - original_stat.st_mtime) > 1:  # Allow 1 second tolerance
                    os.utime(gz_path, (original_stat.st_atime, original_stat.st_mtime))
                    logger.info("  Updated timestamps on .gz to match original")

                # Track the sizes
                stats.original_bytes += csv_path.stat().st_size
                stats.compressed_bytes += gz_path.stat().st_size

                # Delete the original .csv if not keeping originals
                if not keep_original and not dry_run:
                    logger.info(f"Deleting original {csv_path}")
                    csv_path.unlink()
                    logger.info(f"✓ Cleaned up {csv_path}")

                stats.skipped += 1
                return True
            else:
                logger.warning(f"Existing {gz_path} does not match {csv_path}, will regenerate")
                if not dry_run:
                    # Rename instead of delete to preserve data
                    backup_path = gz_path
                    counter = 1
                    while backup_path.exists():
                        backup_path = gz_path.with_suffix(f"{gz_path.suffix}.{counter:03d}")
                        counter += 1
                    gz_path.rename(backup_path)
                    logger.info(f"Renamed invalid {gz_path.name} to {backup_path.name}")
        except Exception as e:
            logger.warning(f"Existing {gz_path} is corrupt or unreadable: {e}")
            if not dry_run:
                # Rename instead of delete to preserve data
                backup_path = gz_path
                counter = 1
                while backup_path.exists():
                    backup_path = gz_path.with_suffix(f"{gz_path.suffix}.{counter:03d}")
                    counter += 1
                gz_path.rename(backup_path)
                logger.info(f"Renamed corrupt {gz_path.name} to {backup_path.name}")

        # Fall through to normal compression if verification failed

    try:
        # Read original CSV
        logger.info(f"Reading {csv_path}")
        df_original = pd.read_csv(csv_path)
        original_size = csv_path.stat().st_size
        original_stat = csv_path.stat()
        logger.info(f"  Original: {len(df_original)} rows, {original_size:,} bytes")

        stats.original_bytes += original_size

        if dry_run:
            logger.info(f"  [DRY RUN] Would write to {gz_path}")
            # Estimate compressed size for dry run (assume ~10% of original)
            stats.compressed_bytes += int(original_size * 0.1)
            return True

        # Write compressed version
        logger.info(f"Writing {gz_path}")
        df_original.to_csv(gz_path, index=False, compression="gzip")
        gz_size = gz_path.stat().st_size
        compression_ratio = (1 - gz_size / original_size) * 100
        logger.info(f"  Compressed: {gz_size:,} bytes ({compression_ratio:.1f}% savings)")

        stats.compressed_bytes += gz_size

        # Preserve original file timestamps
        os.utime(gz_path, (original_stat.st_atime, original_stat.st_mtime))
        logger.info("  Preserved timestamps from original file")

        # Read back compressed version for verification
        logger.info(f"Verifying {gz_path}")
        df_compressed = pd.read_csv(gz_path)

        # Verify data integrity
        if not verify_dataframes_equal(df_original, df_compressed):
            logger.error(f"VERIFICATION FAILED for {csv_path}")
            logger.error(f"Deleting potentially corrupt {gz_path}")
            gz_path.unlink()
            stats.compressed_bytes -= gz_size  # Revert size count
            return False

        logger.info(f"✓ Verification passed for {csv_path}")

        # Delete original if verification passed and not keeping
        if not keep_original:
            logger.info(f"Deleting original {csv_path}")
            csv_path.unlink()
            logger.info(f"✓ Successfully converted {csv_path}")
        else:
            logger.info(f"✓ Successfully converted {csv_path} (keeping original)")

        return True

    except Exception as e:
        logger.error(f"Error converting {csv_path}: {e}", exc_info=True)
        # Clean up partial .gz file if it exists
        if gz_path.exists() and not dry_run:
            logger.info(f"Cleaning up partial file {gz_path}")
            gz_path.unlink()
        return False


def find_csv_files(base_path: Path, pattern: str = "**/*.csv") -> list[Path]:
    """
    Find all .csv files in the given path.

    Args:
        base_path: Base directory to search
        pattern: Glob pattern for finding files

    Returns:
        List of Path objects for .csv files
    """
    csv_files = list(base_path.glob(pattern))
    logger.info(f"Found {len(csv_files)} .csv files in {base_path}")
    return csv_files


def main():
    parser = argparse.ArgumentParser(
        description="Convert .csv files to .csv.gz with verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (don't actually convert)
  python scripts/convert_csv_to_gz.py --dry-run

  # Convert with Windows path
  python scripts/convert_csv_to_gz.py --path c:\\data

  # Convert with Linux path
  python scripts/convert_csv_to_gz.py --path /data

  # Convert but keep originals
  python scripts/convert_csv_to_gz.py --keep-original

  # Convert specific pattern
  python scripts/convert_csv_to_gz.py --pattern "results_cache/**/*.csv"
        """,
    )
    parser.add_argument(
        "--path",
        type=str,
        help="Base path to search for .csv files (default: current OS data path)",
    )
    parser.add_argument("--pattern", type=str, default="**/*.csv", help="Glob pattern for finding CSV files (default: **/*.csv)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without actually doing it")
    parser.add_argument("--keep-original", action="store_true", help="Keep original .csv files after conversion")

    args = parser.parse_args()

    # Determine base path
    if args.path:
        base_path = Path(args.path)
    else:
        # Default to system-appropriate data path
        import os

        if os.name == "nt":  # Windows
            base_path = Path("c:/data")
        else:  # Linux/Mac
            base_path = Path("/data")

    if not base_path.exists():
        print(f"ERROR: Path does not exist: {base_path}")
        print("Use --path to specify a different directory")
        return 1

    print(f"Starting conversion in {base_path}")
    print(f"Pattern: {args.pattern}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    if args.keep_original:
        print("Keeping original files")
    print("=" * 80)
    print("Detailed logs written to: csv_conversion.log\n")

    # Log to file
    logger.info(f"Starting conversion in {base_path}")
    logger.info(f"Pattern: {args.pattern}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Keep original: {args.keep_original}")
    logger.info("-" * 80)

    # Find all CSV files
    csv_files = find_csv_files(base_path, args.pattern)

    if not csv_files:
        print("No .csv files found to convert")
        return 0

    stats.total_files = len(csv_files)

    # Convert each file
    print(f"Processing {stats.total_files} files...\n")

    for i, csv_path in enumerate(csv_files, 1):
        stats.processed = i
        # Show progress on console
        progress_pct = (i / stats.total_files) * 100
        print(f"[{i}/{stats.total_files}] ({progress_pct:.1f}%) {csv_path.name}...", end=" ", flush=True)

        logger.info(f"\n[{i}/{stats.total_files}] Processing {csv_path}")
        if convert_file(csv_path, dry_run=args.dry_run, keep_original=args.keep_original):
            stats.success += 1
            print("✓")
        else:
            stats.failed += 1
            print("✗ FAILED")

    # Summary
    stats.print_summary(dry_run=args.dry_run, keep_original=args.keep_original)

    if stats.failed > 0:
        return 1

    logger.info("\n✓ All conversions completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
