#!/usr/bin/env python3
"""
Bytecode cache management script for Python projects.

This script provides comprehensive bytecode cache management:
- Setup: Install sitecustomize.py for centralized bytecode caching
- Cleanup: Remove scattered __pycache__ directories
- Status: Check current bytecode cache configuration

Usage:
    python scripts/manage_bytecode.py setup    # Install sitecustomize.py
    python scripts/manage_bytecode.py cleanup  # Remove __pycache__ directories
    python scripts/manage_bytecode.py status   # Show current configuration
    python scripts/manage_bytecode.py --help   # Show this help
"""

import argparse
import os
import shutil
import sys
from pathlib import Path


def get_venv_site_packages():
    """Get the site-packages directory of the active virtual environment."""
    # Check if we're in a virtual environment
    if not (hasattr(sys, 'real_prefix') or
            (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)):
        print("❌ Error: No virtual environment detected!")
        print("   Please activate your virtual environment first:")
        print("   .venv\\Scripts\\Activate.ps1  # Windows")
        print("   source .venv/bin/activate     # Unix/macOS")
        return None

    # Get site-packages directory
    import site
    site_packages = site.getsitepackages()

    # Find the one in the current virtual environment
    venv_site_packages = None
    for path in site_packages:
        if sys.prefix in path and 'site-packages' in path:
            venv_site_packages = path
            break

    if not venv_site_packages:
        print("❌ Error: Could not find virtual environment site-packages directory")
        return None

    return Path(venv_site_packages)


def cleanup_pycache(start_path=None, verbose=True):
    """Remove all __pycache__ directories recursively."""
    if start_path is None:
        start_path = Path.cwd()
    else:
        start_path = Path(start_path)

    removed_count = 0
    errors = []

    if verbose:
        print(f"🧹 Cleaning up __pycache__ directories from: {start_path}")

    try:
        for item in start_path.rglob('__pycache__'):
            if item.is_dir():
                try:
                    shutil.rmtree(item)
                    removed_count += 1
                    if verbose:
                        print(f"   Removed: {item.relative_to(start_path)}")
                except Exception as e:
                    errors.append(f"Error removing {item}: {e}")
    except Exception as e:
        errors.append(f"Error scanning directory {start_path}: {e}")

    if verbose:
        if removed_count > 0:
            print(f"✅ Removed {removed_count} __pycache__ directories")
        else:
            print("✅ No __pycache__ directories found")

        if errors:
            print("⚠️  Errors encountered:")
            for error in errors:
                print(f"   {error}")

    return removed_count, errors


def show_status():
    """Show current bytecode cache configuration."""
    print("🔍 Bytecode Cache Status")
    print("=" * 40)

    # Check if in virtual environment
    in_venv = (hasattr(sys, 'real_prefix') or
               (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))

    print(f"Virtual Environment: {'✅ Active' if in_venv else '❌ Not detected'}")

    if in_venv:
        # Get site-packages directory
        import site
        site_packages = site.getsitepackages()
        venv_site_packages = None
        for path in site_packages:
            if sys.prefix in path and 'site-packages' in path:
                venv_site_packages = Path(path)
                break

        if venv_site_packages:
            sitecustomize_path = venv_site_packages / "sitecustomize.py"
            sitecustomize_installed = sitecustomize_path.exists()
            print(f"sitecustomize.py: {'✅ Installed' if sitecustomize_installed else '❌ Not installed'}")
            if sitecustomize_installed:
                print(f"   Location: {sitecustomize_path}")
        else:
            print("sitecustomize.py: ❌ Could not determine site-packages location")

    # Check pycache_prefix
    cache_prefix = getattr(sys, 'pycache_prefix', None)
    if cache_prefix:
        print(f"Cache Location: ✅ {cache_prefix}")
        cache_exists = Path(cache_prefix).exists()
        print(f"Cache Directory: {'✅ Exists' if cache_exists else '❌ Not created yet'}")
    else:
        print("Cache Location: ❌ Not configured (using default __pycache__)")

    # Count existing __pycache__ directories
    project_root = Path.cwd()
    pycache_dirs = list(project_root.rglob('__pycache__'))
    # Filter out virtual environment pycache dirs
    pycache_dirs = [d for d in pycache_dirs if '.venv' not in str(d)]

    print(f"__pycache__ directories: {len(pycache_dirs)} found in project")
    if len(pycache_dirs) > 0:
        print("   (These can be cleaned up with: manage_bytecode.py cleanup)")


def install_sitecustomize():
    """Install sitecustomize.py to the virtual environment."""
    # Get project root (parent of the scripts directory)
    project_root = Path(__file__).parent.parent
    source_file = project_root / "scripts" / "templates" / "sitecustomize.py"

    # Check if source file exists
    if not source_file.exists():
        print(f"❌ Error: sitecustomize.py not found at {source_file}")
        return False

    # Get virtual environment site-packages directory
    site_packages_dir = get_venv_site_packages()
    if not site_packages_dir:
        return False

    target_file = site_packages_dir / "sitecustomize.py"

    try:
        # Copy the file
        shutil.copy2(source_file, target_file)
        print("✅ Successfully installed sitecustomize.py")
        print(f"   Source: {source_file}")
        print(f"   Target: {target_file}")

        # Test if it's working
        print("\n🔍 Testing installation...")
        import importlib

        # Force reload of sitecustomize module
        if 'sitecustomize' in sys.modules:
            importlib.reload(sys.modules['sitecustomize'])
        else:
            importlib.import_module('sitecustomize')

        cache_prefix = getattr(sys, 'pycache_prefix', None)
        if cache_prefix:
            print(f"✅ Bytecode cache configured: {cache_prefix}")

            # Create cache directory to verify it works
            os.makedirs(cache_prefix, exist_ok=True)
            print(f"✅ Cache directory created: {cache_prefix}")
        else:
            print("⚠️  Warning: pycache_prefix not set - sitecustomize may not be working")

        return True

    except Exception as e:
        print(f"❌ Error installing sitecustomize.py: {e}")
        return False


def main():
    """Main function with command-line argument parsing."""
    parser = argparse.ArgumentParser(
        description="Bytecode cache management for Python projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/manage_bytecode.py setup    # Install bytecode cache management
  python scripts/manage_bytecode.py cleanup  # Remove __pycache__ directories
  python scripts/manage_bytecode.py status   # Show current configuration
        """
    )

    parser.add_argument(
        'command',
        choices=['setup', 'cleanup', 'status'],
        help='Command to execute'
    )

    parser.add_argument(
        '--path',
        type=str,
        help='Path to clean (for cleanup command, defaults to current directory)'
    )

    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress verbose output'
    )

    args = parser.parse_args()

    if args.command == 'setup':
        print("🔧 Setting up bytecode cache management...")
        print("=" * 50)

        if install_sitecustomize():
            print("\n🎉 Setup complete!")
            print("\nBenefits:")
            print("  • No more __pycache__ folders in your project")
            print("  • Centralized bytecode cache in .cache/python/")
            print("  • Cache survives virtual environment recreation")
            print("  • Cleaner project structure for version control")
            print("\nOptional: Run 'python scripts/manage_bytecode.py cleanup' to remove existing __pycache__ directories")
        else:
            print("\n❌ Setup failed!")
            sys.exit(1)

    elif args.command == 'cleanup':
        start_path = args.path if args.path else None
        removed_count, errors = cleanup_pycache(start_path, verbose=not args.quiet)

        if errors:
            sys.exit(1)

    elif args.command == 'status':
        show_status()


def legacy_main():
    """Legacy main function for backward compatibility."""
    print("🔧 Setting up bytecode cache management...")
    print("=" * 50)

    if install_sitecustomize():
        print("\n🎉 Setup complete!")
        print("\nBenefits:")
        print("  • No more __pycache__ folders in your project")
        print("  • Centralized bytecode cache in .cache/python/")
        print("  • Cache survives virtual environment recreation")
        print("  • Cleaner project structure for version control")
    else:
        print("\n❌ Setup failed!")
        sys.exit(1)


if __name__ == "__main__":
    # If no arguments provided, run legacy behavior for backward compatibility
    if len(sys.argv) == 1:
        legacy_main()
    else:
        main()
