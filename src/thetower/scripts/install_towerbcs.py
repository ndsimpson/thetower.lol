#!/usr/bin/env python3
"""
Complete script to check and update towerbcs package from git repository.
Usage: python install_towerbcs.py [--auto] [--check-only] [--repo-url URL]

Repository URL priority:
1. Command line: --repo-url (highest priority)
2. Environment: TOWERBCS_REPO_URL (optional)
3. Default: Built-in repository URL (lowest priority)
"""

import subprocess
import sys
import re
import argparse
import os
from packaging import version
import importlib.metadata


def get_latest_version(repo_url=None):
    """
    Quickly fetch the latest version tag from remote git repository.

    Args:
        repo_url: Git repository URL (optional, uses default if not provided)

    Returns:
        str or None: Latest version string (e.g., "1.0.0") or None if error
    """
    if repo_url is None:
        repo_url = os.getenv('TOWERBCS_REPO_URL', 'https://github.com/ndsimpson/thetower.lol-bc-generator.git')

    try:
        # Quick git ls-remote call with minimal output
        result = subprocess.run(
            ['git', 'ls-remote', '--tags', '--refs', repo_url],
            capture_output=True,
            text=True,
            timeout=10,  # Fast timeout for quick response
            check=True
        )

        # Extract and parse version tags
        tags = []
        for line in result.stdout.strip().split('\n'):
            if line:
                tag = line.split('/')[-1]  # Get tag name after refs/tags/
                # Filter for semantic version tags (v1.2.3 or 1.2.3)
                if re.match(r'^v?\d+\.\d+\.\d+.*', tag):
                    clean_tag = tag.lstrip('v')  # Remove 'v' prefix if present
                    tags.append(clean_tag)

        # Sort by version and return latest
        if tags:
            from packaging import version
            latest = max(tags, key=lambda x: version.parse(x))
            return latest
        else:
            return None

    except subprocess.CalledProcessError:
        # Git command failed
        return None
    except subprocess.TimeoutExpired:
        # Git command timed out
        return None
    except ImportError:
        # packaging module not available - fallback to simple string comparison
        if tags:
            return max(tags)  # Simple string max as fallback
        return None
    except Exception:
        # Any other error
        return None


def get_installed_version(package_name='towerbcs'):
    """
    Quickly get the installed version of a package.

    Args:
        package_name: Name of the package to check

    Returns:
        str or None: Installed version string or None if not installed
    """
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


class TowerBCSUpdater:
    def __init__(self, repo_url, package_name):
        self.repo_url = repo_url
        self.package_name = package_name

    def get_remote_latest_tag(self):
        """Get the latest semantic version tag from remote git repository."""
        try:
            print(f"Checking remote tags for {self.repo_url}...")
            latest = get_latest_version(self.repo_url)
            if latest:
                print(f"Latest remote tag: v{latest}")
                return latest
            else:
                print("No version tags found in repository")
                return None
        except Exception as e:
            print(f"Error checking remote tags: {e}")
            print("Make sure you have git access to the repository")
            return None

    def get_installed_version(self):
        """Get currently installed package version."""
        try:
            installed_version = get_installed_version(self.package_name)
            if installed_version:
                print(f"Installed version: {installed_version}")
                return installed_version
            else:
                print(f"Package '{self.package_name}' is not installed")
                return None
        except Exception as e:
            print(f"Error checking installed version: {e}")
            return None

    def needs_update(self, current_version, latest_version):
        """Check if package needs updating."""
        if not current_version:
            return True, "Package not installed"

        if not latest_version:
            return False, "Cannot determine latest version"

        try:
            current_parsed = version.parse(current_version)
            latest_parsed = version.parse(latest_version)

            if current_parsed < latest_parsed:
                return True, f"Update available: {current_version} -> {latest_version}"
            elif current_parsed > latest_parsed:
                return False, f"Installed version is newer: {current_version} > {latest_version}"
            else:
                return False, "Package is up to date"
        except Exception as e:
            print(f"Error comparing versions: {e}")
            return False, "Version comparison failed"

    def update_package(self, target_version=None, force=False):
        """Update package from git repository."""
        url = f"git+{self.repo_url}"
        if target_version:
            url += f"@v{target_version}"

        if force:
            print(f"Force installing from: {url}")
        else:
            print(f"Installing/updating from: {url}")

        try:
            # First uninstall if already installed
            subprocess.run([
                sys.executable, '-m', 'pip', 'uninstall',
                self.package_name, '-y'
            ], capture_output=True)

            # Install from git with force options if specified
            install_cmd = [sys.executable, '-m', 'pip', 'install', url]
            if force:
                install_cmd.extend(['--force-reinstall', '--no-cache-dir'])

            result = subprocess.run(
                install_cmd, capture_output=True, text=True, check=True
            )

            if force:
                print("Package force installed successfully!")
            else:
                print("Package updated successfully!")
            print("Installation output:")
            print(result.stdout)
            return True

        except subprocess.CalledProcessError as e:
            print(f"Error updating package: {e}")
            if e.stderr:
                print("Error details:")
                print(e.stderr)
            return False

    def verify_installation(self):
        """Verify the package can be imported after installation."""
        try:
            print("Verifying installation...")
            result = subprocess.run([
                sys.executable, '-c',
                f'import {self.package_name}; print(f"[OK] {self.package_name} imported successfully"); print(f"Version: {{{self.package_name}.__version__}}")'
            ], capture_output=True, text=True, check=True, encoding='utf-8')

            print(result.stdout)
            return True

        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to import {self.package_name}: {e}")
            if e.stderr:
                print(e.stderr)
            return False

    def run_update_check(self, auto_update=False, check_only=False, force=False):
        """Main update check and update process."""
        print("=" * 50)
        if force and check_only:
            print(f"Force check-only (dry-run) for {self.package_name}")
        elif force:
            print(f"Force installing {self.package_name}")
        else:
            print(f"Checking updates for {self.package_name}")
        print("=" * 50)

        if force and check_only:
            # Force check-only mode - show what would be force installed
            print("Force dry-run mode: Showing what would be force installed...")
            latest_version = self.get_remote_latest_tag()
            current_version = self.get_installed_version()

            if latest_version:
                url = f"git+{self.repo_url}@v{latest_version}"
                print(f"\nWould force install from: {url}")
                print("Force install would use: pip install --force-reinstall --no-cache-dir")
                print("✓ Dry-run completed - no actual installation performed")
                return True
            else:
                print("Cannot determine what would be installed (no version info)")
                return False

        elif force:
            # Force install mode - skip version checks
            print("Force mode: Skipping version checks and installing directly...")
            latest_version = self.get_remote_latest_tag()
            if not latest_version:
                print("Warning: Cannot determine latest version, installing from HEAD")
                latest_version = None

            print("\nStarting force installation...")
            if self.update_package(latest_version, force=True):
                return self.verify_installation()
            else:
                print("Force installation failed!")
                return False

        # Get current and latest versions
        current_version = self.get_installed_version()
        latest_version = self.get_remote_latest_tag()

        if not latest_version:
            print("Cannot proceed without latest version information")
            return False

        # Check if update is needed
        needs_update, reason = self.needs_update(current_version, latest_version)
        print(f"\nStatus: {reason}")

        if not needs_update:
            print("No update needed!")
            return True

        if check_only:
            print("Check-only mode: Update available but not installing")
            return True

        # Ask user or auto-update
        if auto_update:
            do_update = True
            print("Auto-update mode: Proceeding with update...")
        else:
            response = input(f"\nUpdate to version {latest_version}? (y/N): ")
            do_update = response.lower() in ('y', 'yes')

        if do_update:
            print("\nStarting update process...")
            if self.update_package(latest_version):
                return self.verify_installation()
            else:
                print("Update failed!")
                return False
        else:
            print("Update cancelled by user")
            return True


def main():
    parser = argparse.ArgumentParser(
        description='Check and update towerbcs package',
        epilog='Repository URL priority: --repo-url > TOWERBCS_REPO_URL env > built-in default\n\n'
               'Special combinations:\n'
               '  --force --check-only : Dry-run mode - show what force install would do without installing',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--auto', action='store_true',
                        help='Automatically update without prompting')
    parser.add_argument('--check-only', action='store_true',
                        help='Only check for updates, do not install (combine with --force for dry-run)')
    parser.add_argument('--force', action='store_true',
                        help='Force reinstall package (skip version checks, combine with --check-only for dry-run)')
    parser.add_argument('--version-only', action='store_true',
                        help='Only get latest version (fast, minimal output)')
    parser.add_argument('--repo-url',
                        help='Git repository URL (overrides environment and default)')
    parser.add_argument('--package-name', default='towerbcs',
                        help='Package name')

    args = parser.parse_args()

    # Handle quick version-only mode
    if args.version_only:
        # Priority system for repo URL
        if args.repo_url:
            repo_url = args.repo_url
        elif os.getenv('TOWERBCS_REPO_URL'):
            repo_url = os.getenv('TOWERBCS_REPO_URL')
        else:
            repo_url = 'https://github.com/ndsimpson/thetower.lol-bc-generator.git'

        # Get versions quickly
        current_version = get_installed_version(args.package_name)
        latest_version = get_latest_version(repo_url)

        # Output in simple format for parsing
        print(f"current:{current_version or 'not_installed'}")
        print(f"latest:{latest_version or 'unknown'}")

        sys.exit(0 if latest_version else 1)

    # Priority system: command line > environment > hardcoded default
    if args.repo_url:
        # Command line specified (highest priority)
        repo_url = args.repo_url
        source = "command line"
    elif os.getenv('TOWERBCS_REPO_URL'):
        # Environment variable (medium priority)
        repo_url = os.getenv('TOWERBCS_REPO_URL')
        source = "environment variable"
    else:
        # Hardcoded default (lowest priority)
        repo_url = 'https://github.com/ndsimpson/thetower.lol-bc-generator.git'
        source = "default"

    print(f"Repository URL: {repo_url} (from {source})")

    # Configuration
    updater = TowerBCSUpdater(repo_url, args.package_name)

    try:
        success = updater.run_update_check(
            auto_update=args.auto,
            check_only=args.check_only,
            force=args.force
        )

        if success:
            print("\n[SUCCESS] Operation completed successfully!")
            sys.exit(0)
        else:
            print("\n[FAILED] Operation failed!")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
