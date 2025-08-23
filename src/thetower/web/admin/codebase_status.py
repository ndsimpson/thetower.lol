"""
Codebase Status component for Streamlit hidden site.

Shows the status of git repositories and external packages, allows pulling updates.
Gracefully handles Windows development environments.
"""

import subprocess
import streamlit as st
import platform
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from importlib.metadata import version, PackageNotFoundError


def get_external_package_status(package_name: str) -> Dict[str, any]:
    """
    Get status information for an external Python package.

    Args:
        package_name: Name of the package to check

    Returns:
        dict: Package status information
    """
    status_info = {
        'name': package_name,
        'installed': False,
        'version': 'unknown',
        'location': 'unknown',
        'error': None
    }

    try:
        # Check if package is installed and get version
        pkg_version = version(package_name)
        status_info['installed'] = True
        status_info['version'] = pkg_version

        # Try to get package location
        try:
            import importlib.util
            spec = importlib.util.find_spec(package_name)
            if spec and spec.origin:
                status_info['location'] = os.path.dirname(spec.origin)
        except Exception:
            pass

    except PackageNotFoundError:
        status_info['error'] = 'Package not installed'
    except Exception as e:
        status_info['error'] = f'Error checking package: {str(e)}'

    return status_info


def check_towerbcs_updates() -> Tuple[bool, str, str]:
    """
    Check for towerbcs updates using direct import of the fast functions.

    Returns:
        tuple: (success, current_version, latest_version)
    """
    try:
        # Import the fast functions directly from update_towerbcs
        from thetower.scripts.install_towerbcs import get_installed_version, get_latest_version

        # Get versions quickly
        current_version = get_installed_version('towerbcs')
        latest_version = get_latest_version()  # Uses default repo URL

        return True, current_version, latest_version

    except ImportError:
        # Fallback to subprocess if import fails
        try:
            # Get current environment and ensure TOWERBCS_REPO_URL is available
            env = os.environ.copy()
            if 'TOWERBCS_REPO_URL' not in env:
                env['TOWERBCS_REPO_URL'] = 'https://github.com/ndsimpson/thetower.lol-bc-generator.git'

            result = subprocess.run(
                [sys.executable, 'src/thetower/scripts/install_towerbcs.py', '--version-only'],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=os.getcwd(),
                env=env
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                lines = output.split('\n')

                current_version = None
                latest_version = None

                for line in lines:
                    if line.startswith('current:'):
                        current_version = line.split('current:', 1)[1]
                        if current_version == 'not_installed':
                            current_version = None
                    elif line.startswith('latest:'):
                        latest_version = line.split('latest:', 1)[1]
                        if latest_version == 'unknown':
                            latest_version = None

                return True, current_version, latest_version
            else:
                return False, 'check_failed', None
        except Exception:
            return False, 'subprocess_failed', None

    except Exception:
        return False, 'import_failed', None


def update_towerbcs_package() -> Tuple[bool, str]:
    """
    Update towerbcs package using the install_towerbcs.py script.

    Returns:
        tuple: (success, message)
    """
    try:
        # Get current environment and ensure TOWERBCS_REPO_URL is available
        env = os.environ.copy()
        if 'TOWERBCS_REPO_URL' not in env:
            env['TOWERBCS_REPO_URL'] = 'https://github.com/ndsimpson/thetower.lol-bc-generator.git'

        result = subprocess.run(
            [sys.executable, 'src/thetower/scripts/install_towerbcs.py', '--auto'],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=os.getcwd(),
            env=env
        )

        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            return False, result.stderr.strip() or result.stdout.strip()

    except Exception as e:
        return False, str(e)


def force_install_towerbcs_package() -> Tuple[bool, str]:
    """
    Force install towerbcs package using the install_towerbcs.py script with --force flag.

    Returns:
        tuple: (success, message)
    """
    try:
        # Get current environment and ensure TOWERBCS_REPO_URL is available
        env = os.environ.copy()
        if 'TOWERBCS_REPO_URL' not in env:
            env['TOWERBCS_REPO_URL'] = 'https://github.com/ndsimpson/thetower.lol-bc-generator.git'

        result = subprocess.run(
            [sys.executable, 'src/thetower/scripts/install_towerbcs.py', '--force'],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=os.getcwd(),
            env=env
        )

        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            return False, result.stderr.strip() or result.stdout.strip()

    except Exception as e:
        return False, str(e)


def is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system().lower() == 'windows'


def run_git_command(command: List[str], cwd: str = None) -> Tuple[bool, str, str]:
    """
    Run a git command and return success status, stdout, and stderr.

    Args:
        command: List of command parts (e.g., ['git', 'status', '--porcelain'])
        cwd: Working directory for the command

    Returns:
        tuple: (success, stdout, stderr)
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd
        )
        return (result.returncode == 0, result.stdout.rstrip('\n\r'), result.stderr.strip())
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as e:
        return (False, "", str(e))


def get_git_status(repo_path: str) -> Dict[str, any]:
    """
    Get comprehensive git status for a repository.

    Returns:
        dict: Repository status information
    """
    status_info = {
        'path': repo_path,
        'exists': False,
        'branch': 'unknown',
        'remote_url': 'unknown',
        'ahead': 0,
        'behind': 0,
        'modified': [],
        'untracked': [],
        'staged': [],
        'last_commit': 'unknown',
        'last_commit_date': 'unknown',
        'has_changes': False,
        'can_pull': True,
        'error': None
    }

    # Check if directory exists and is a git repo
    if not os.path.exists(repo_path):
        status_info['error'] = 'Directory does not exist'
        return status_info

    # Check if it's a git repository by trying a git command
    # This works for both regular repos (.git directory) and submodules (.git file)
    success, _, _ = run_git_command(['git', 'rev-parse', '--git-dir'], repo_path)
    if not success:
        status_info['error'] = 'Not a git repository'
        return status_info

    status_info['exists'] = True

    # Get current branch
    success, branch, error = run_git_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], repo_path)
    if success:
        status_info['branch'] = branch
    else:
        status_info['error'] = f'Could not get branch: {error}'
        return status_info

    # Get remote URL
    success, remote_url, _ = run_git_command(['git', 'config', '--get', 'remote.origin.url'], repo_path)
    if success:
        status_info['remote_url'] = remote_url

    # Get last commit info
    success, commit_info, _ = run_git_command(
        ['git', 'log', '-1', '--pretty=format:%h|%s|%ci'], repo_path
    )
    if success and commit_info:
        parts = commit_info.split('|', 2)
        if len(parts) >= 3:
            status_info['last_commit'] = f"{parts[0]} - {parts[1]}"
            status_info['last_commit_date'] = parts[2]

    # Get ahead/behind info (fetch from remote first for accurate info)
    try:
        # Fetch from remote to get updated refs (but don't output progress)
        run_git_command(['git', 'fetch', 'origin', '--quiet'], repo_path)

        success, ahead_behind, _ = run_git_command(
            ['git', 'rev-list', '--left-right', '--count', f'{branch}...origin/{branch}'], repo_path
        )
        if success and ahead_behind:
            parts = ahead_behind.split('\t')
            if len(parts) == 2:
                status_info['ahead'] = int(parts[0])
                status_info['behind'] = int(parts[1])
    except Exception:
        # If we can't check ahead/behind, that's okay - might be offline or no remote
        pass

    # Get working directory status
    success, porcelain, _ = run_git_command(['git', 'status', '--porcelain'], repo_path)
    if success:
        for line in porcelain.split('\n'):
            if not line.strip():
                continue

            # Git porcelain format: XY filename
            # X = index status, Y = working tree status
            # Position 0: index status (space = unchanged, A/M/D/etc = staged)
            # Position 1: working tree status (space = unchanged, M/D = modified, ? = untracked)
            # Position 2: space separator
            # Position 3+: filename
            if len(line) < 3:
                continue

            index_status = line[0]
            worktree_status = line[1]
            filename = line[3:]

            # Check index (staged) changes
            if index_status in ['M', 'A', 'D', 'R', 'C']:
                status_info['staged'].append(filename)

            # Check working tree changes
            if worktree_status in ['M', 'D']:
                status_info['modified'].append(filename)
            elif worktree_status == '?':
                status_info['untracked'].append(filename)

    status_info['has_changes'] = bool(
        status_info['modified'] or status_info['untracked'] or status_info['staged']
    )

    return status_info


def get_submodules_info(repo_path: str) -> List[Dict[str, any]]:
    """
    Get information about all submodules.

    Returns:
        list: List of submodule information dictionaries
    """
    submodules = []

    # Get submodule status
    success, submodule_status, _ = run_git_command(['git', 'submodule', 'status'], repo_path)
    if not success:
        return submodules

    for line in submodule_status.split('\n'):
        if not line.strip():
            continue

        # Parse submodule status line
        # Format: " commit_hash path (describe_output)"
        # Status prefixes: space=up-to-date, +=needs-update, -=not-initialized, U=merge-conflicts
        status_char = line[0] if line else ' '
        parts = line[1:].split(' ', 2)
        if len(parts) >= 2:
            commit_hash = parts[0]
            submodule_path = parts[1]
            describe = parts[2] if len(parts) > 2 else ''

            # Get full status for this submodule
            full_path = os.path.join(repo_path, submodule_path)
            submodule_info = get_git_status(full_path)
            submodule_info['submodule_path'] = submodule_path
            submodule_info['submodule_commit'] = commit_hash
            submodule_info['submodule_describe'] = describe.strip('()')
            submodule_info['submodule_status'] = status_char
            submodule_info['needs_update'] = status_char == '+'
            submodule_info['not_initialized'] = status_char == '-'
            submodule_info['has_conflicts'] = status_char == 'U'

            submodules.append(submodule_info)

    return submodules


def pull_repository(repo_path: str, is_submodule: bool = False, pull_mode: str = "normal") -> Tuple[bool, str]:
    """
    Pull updates for a repository with different strategies.

    Args:
        repo_path: Path to the repository
        is_submodule: Whether this is a submodule
        pull_mode: "normal", "rebase", "autostash", or "force"

    Returns:
        tuple: (success, message)
    """
    if is_submodule:
        # For submodules, use git submodule update
        parent_path = os.path.dirname(repo_path)
        submodule_name = os.path.basename(repo_path)
        success, stdout, stderr = run_git_command(
            ['git', 'submodule', 'update', '--remote', '--merge', submodule_name],
            parent_path
        )
    else:
        # For main repo, use different pull strategies
        if pull_mode == "rebase":
            success, stdout, stderr = run_git_command(['git', 'pull', '--rebase'], repo_path)
        elif pull_mode == "autostash":
            success, stdout, stderr = run_git_command(['git', 'pull', '--autostash'], repo_path)
        elif pull_mode == "force":
            # Force pull by resetting to remote
            # First fetch to get latest remote refs
            success1, stdout1, stderr1 = run_git_command(['git', 'fetch', 'origin'], repo_path)
            if success1:
                success, stdout2, stderr2 = run_git_command(['git', 'reset', '--hard', 'origin/HEAD'], repo_path)
                stdout = f"Fetch:\n{stdout1}\n\nReset:\n{stdout2}"
                stderr = f"{stderr1}\n{stderr2}".strip()
            else:
                success, stdout, stderr = success1, stdout1, stderr1
        else:  # normal
            success, stdout, stderr = run_git_command(['git', 'pull'], repo_path)

    if success:
        return True, stdout if stdout else "Pull completed successfully"
    else:
        return False, stderr if stderr else "Pull failed"


def get_status_emoji(repo_info: Dict[str, any]) -> str:
    """Get emoji representing repository status."""
    if not repo_info['exists']:
        return '❌'
    elif repo_info['error']:
        return '⚠️'
    elif repo_info.get('has_conflicts'):
        return '🔴'
    elif repo_info.get('needs_update'):
        return '🟡'
    elif repo_info['behind'] > 0:
        return '⬇️'
    elif repo_info['ahead'] > 0:
        return '⬆️'
    elif repo_info['ahead'] == 0 and repo_info['behind'] == 0:
        return '✅'  # Up to date with remote (regardless of local changes)
    elif repo_info['has_changes']:
        return '📝'
    else:
        return '✅'


def codebase_status_page():
    """Main codebase status page component."""
    st.title("📋 Codebase Status")

    # Get current working directory (should be the repo root)
    repo_root = os.getcwd()

    # Show environment info
    if is_windows():
        st.info("🖥️ **Development Mode**: Running on Windows")

    st.markdown(f"**Repository Path:** `{repo_root}`")

    # Refresh controls
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🔄 Refresh Status"):
            st.rerun()
    with col2:
        utc_time = datetime.now(timezone.utc).strftime('%H:%M:%S')
        st.markdown(f"*Last updated: {utc_time} UTC*")

    st.markdown("---")

    # Get main repository status
    main_repo = get_git_status(repo_root)
    submodules = get_submodules_info(repo_root)

    # Get external package status
    towerbcs_info = get_external_package_status('towerbcs')

    # Main Repository Section
    st.markdown("## 🏠 Main Repository")

    with st.container():
        col1, col2 = st.columns([1, 1])

        with col1:
            # Repository Info Card
            with st.container():
                st.markdown("**Repository Info**")

                emoji = get_status_emoji(main_repo)
                st.markdown(f"**{emoji} thetower.lol**")

                if main_repo['exists']:
                    st.caption(f"Branch: `{main_repo['branch']}`")

                    # Last commit info
                    if main_repo['last_commit'] != 'unknown':
                        commit_parts = main_repo['last_commit'].split(' - ', 1)
                        if len(commit_parts) == 2:
                            commit_hash, commit_msg = commit_parts
                            st.caption(f"Last: {commit_hash} - {commit_msg[:30]}{'...' if len(commit_msg) > 30 else ''}")
                        else:
                            st.caption(f"Last: {main_repo['last_commit']}")
                else:
                    st.caption("Repository not found")

        with col2:
            # Status & Actions Card
            with st.container():
                st.markdown("**Status & Actions**")

                if main_repo['error']:
                    st.error(f"Error: {main_repo['error']}")
                else:
                    # Git status
                    if main_repo['behind'] > 0:
                        st.warning(f"Git Status: {main_repo['behind']} commits behind")
                    elif main_repo['ahead'] > 0:
                        st.info(f"Git Status: {main_repo['ahead']} commits ahead")
                    else:
                        st.success("Git Status: ✅ Up to date")

                    # Local changes
                    if main_repo['has_changes']:
                        changes = len(main_repo['modified']) + len(main_repo['untracked']) + len(main_repo['staged'])
                        st.warning(f"Local Changes: 📝 {changes} changes")
                    else:
                        st.success("Local Changes: No changes")

                st.markdown("")  # Add some spacing

                # Action buttons
                if main_repo['exists'] and not main_repo['error']:
                    col_a, col_b, col_c = st.columns(3)

                    with col_a:
                        if st.button("⬇️ Pull", key="pull_main_normal", help="Normal git pull"):
                            with st.spinner("Pulling main repository..."):
                                success, message = pull_repository(repo_root, pull_mode="normal")
                                if success:
                                    st.success("✅ Main repository updated")
                                    with st.expander("📋 Pull Output", expanded=False):
                                        st.code(message, language="bash")
                                    import time
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error("❌ Failed to pull main repository")
                                    with st.expander("📋 Error Output", expanded=True):
                                        st.code(message, language="bash")

                    with col_b:
                        if st.button("🔄 Rebase", key="pull_main_rebase", help="Pull with rebase (git pull --rebase)"):
                            with st.spinner("Pulling main repository (rebase)..."):
                                success, message = pull_repository(repo_root, pull_mode="rebase")
                                if success:
                                    st.success("✅ Main repository rebased")
                                    with st.expander("📋 Rebase Output", expanded=False):
                                        st.code(message, language="bash")
                                    import time
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error("❌ Failed to rebase main repository")
                                    with st.expander("📋 Error Output", expanded=True):
                                        st.code(message, language="bash")

                    with col_c:
                        if st.button("💾 Stash", key="pull_main_autostash", help="Pull with autostash (git pull --autostash)"):
                            with st.spinner("Pulling main repository (autostash)..."):
                                success, message = pull_repository(repo_root, pull_mode="autostash")
                                if success:
                                    st.success("✅ Main repository updated (autostash)")
                                    with st.expander("📋 Autostash Output", expanded=False):
                                        st.code(message, language="bash")
                                    import time
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error("❌ Failed to autostash pull main repository")
                                    with st.expander("📋 Error Output", expanded=True):
                                        st.code(message, language="bash")    # Show detailed main repo info if there are changes
    if main_repo['exists'] and main_repo['has_changes']:
        with st.expander("📝 Main Repository - Local Changes", expanded=False):
            if main_repo['staged']:
                st.markdown("**Staged changes:**")
                for file in main_repo['staged'][:10]:  # Limit to first 10
                    st.markdown(f"- `{file}`")
                if len(main_repo['staged']) > 10:
                    st.markdown(f"... and {len(main_repo['staged']) - 10} more")

            if main_repo['modified']:
                st.markdown("**Modified files:**")
                for file in main_repo['modified'][:10]:  # Limit to first 10
                    st.markdown(f"- `{file}`")
                if len(main_repo['modified']) > 10:
                    st.markdown(f"... and {len(main_repo['modified']) - 10} more")

            if main_repo['untracked']:
                st.markdown("**Untracked files:**")
                for file in main_repo['untracked'][:10]:  # Limit to first 10
                    st.markdown(f"- `{file}`")
                if len(main_repo['untracked']) > 10:
                    st.markdown(f"... and {len(main_repo['untracked']) - 10} more")

    st.markdown("---")

    # Submodules Section
    if submodules:
        st.markdown("## 📦 Submodules")

        for submodule in submodules:
            with st.container():
                col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

                with col1:
                    emoji = get_status_emoji(submodule)
                    st.markdown(f"**{emoji} {submodule['submodule_path']}**")
                    if submodule['exists']:
                        st.caption(f"Branch: `{submodule['branch']}`")
                    else:
                        st.caption("Submodule not initialized")

                with col2:
                    if submodule['not_initialized']:
                        st.warning("Not initialized")
                    elif submodule['has_conflicts']:
                        st.error("Has conflicts")
                    elif submodule['needs_update']:
                        st.warning("Needs update")
                    elif submodule['error']:
                        st.error(f"Error: {submodule['error']}")
                    else:
                        # Git status (remote tracking)
                        if submodule['behind'] > 0:
                            st.warning(f"Git status: {submodule['behind']} behind")
                        elif submodule['ahead'] > 0:
                            st.info(f"Git status: {submodule['ahead']} ahead")
                        else:
                            st.success("Git status: up to date")

                        # Local changes (separate line)
                        if submodule['has_changes']:
                            changes = len(submodule['modified']) + len(submodule['untracked']) + len(submodule['staged'])
                            st.caption(f"Local changes: {changes} changes")
                        else:
                            st.caption("Local changes: none")

                with col3:
                    if submodule['exists'] and not submodule['error']:
                        st.markdown("**Last commit:**")
                        st.caption(submodule['last_commit'])
                    else:
                        st.markdown("—")

                with col4:
                    if submodule['exists'] and not submodule['error']:
                        pull_key = f"pull_{submodule['submodule_path']}"
                        if st.button("⬇️", key=pull_key, help=f"Pull {submodule['submodule_path']} submodule"):
                            with st.spinner(f"Pulling {submodule['submodule_path']} submodule..."):
                                success, message = pull_repository(
                                    os.path.join(repo_root, submodule['submodule_path']),
                                    is_submodule=True
                                )
                                if success:
                                    st.success(f"✅ {submodule['submodule_path']} updated")
                                    with st.expander("📋 Pull Output", expanded=False):
                                        st.code(message, language="bash")
                                    import time
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"❌ Failed to pull {submodule['submodule_path']}")
                                    with st.expander("📋 Error Output", expanded=True):
                                        st.code(message, language="bash")

            # Show detailed submodule info if there are changes
            if submodule['exists'] and submodule['has_changes']:
                with st.expander(f"📝 {submodule['submodule_path']} - Local Changes", expanded=False):
                    if submodule['staged']:
                        st.markdown("**Staged changes:**")
                        for file in submodule['staged'][:5]:  # Limit to first 5 for submodules
                            st.markdown(f"- `{file}`")
                        if len(submodule['staged']) > 5:
                            st.markdown(f"... and {len(submodule['staged']) - 5} more")

                    if submodule['modified']:
                        st.markdown("**Modified files:**")
                        for file in submodule['modified'][:5]:
                            st.markdown(f"- `{file}`")
                        if len(submodule['modified']) > 5:
                            st.markdown(f"... and {len(submodule['modified']) - 5} more")

                    if submodule['untracked']:
                        st.markdown("**Untracked files:**")
                        for file in submodule['untracked'][:5]:
                            st.markdown(f"- `{file}`")
                        if len(submodule['untracked']) > 5:
                            st.markdown(f"... and {len(submodule['untracked']) - 5} more")

            st.markdown("---")

    # External Packages Section
    st.markdown("## 📦 External Packages")

    with st.container():
        col1, col2 = st.columns([1, 1])

        with col1:
            # Package Info Card
            with st.container():
                st.markdown("**Package Info**")

                if towerbcs_info['installed']:
                    st.markdown("**✅ towerbcs**")
                else:
                    st.markdown("**❌ towerbcs**")

                st.caption("Battle Conditions Predictor")

                if towerbcs_info['installed']:
                    st.caption("📦 Python Package")
                else:
                    st.caption("Not installed")

        with col2:
            # Status & Actions Card
            with st.container():
                st.markdown("**Status & Actions**")

                if towerbcs_info['installed']:
                    # Check for updates
                    success, current_ver, latest_ver = check_towerbcs_updates()

                    st.caption(f"Current: v{towerbcs_info['version']}")

                    if success and current_ver and latest_ver:
                        if current_ver == latest_ver:
                            st.success("Status: ✅ Up to date")
                        else:
                            st.warning(f"Status: 🔄 Update available (v{latest_ver})")
                    elif success and not current_ver:
                        st.error("Status: ❌ Not installed")
                    else:
                        st.info("Status: ℹ️ Update check failed")

                else:
                    st.error(f"Error: {towerbcs_info['error']}")

                st.markdown("")  # Add spacing

                # Action buttons
                col_a, col_b, col_c = st.columns(3)

                with col_a:
                    if towerbcs_info['installed']:
                        if st.button("🔄 Update", key="update_towerbcs", help="Update towerbcs package"):
                            with st.spinner("Updating towerbcs..."):
                                success, message = update_towerbcs_package()
                                if success:
                                    st.success("✅ towerbcs updated")
                                    with st.expander("📋 Update Output", expanded=False):
                                        st.code(message, language="bash")
                                    import time
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error("❌ Failed to update towerbcs")
                                    with st.expander("📋 Error Output", expanded=True):
                                        st.code(message, language="bash")
                    else:
                        if st.button("📥 Install", key="install_towerbcs", help="Install towerbcs package"):
                            with st.spinner("Installing towerbcs..."):
                                success, message = update_towerbcs_package()
                                if success:
                                    st.success("✅ towerbcs installed")
                                    with st.expander("📋 Install Output", expanded=False):
                                        st.code(message, language="bash")
                                    import time
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error("❌ Failed to install towerbcs")
                                    with st.expander("📋 Error Output", expanded=True):
                                        st.code(message, language="bash")

                with col_b:
                    if st.button("⚡ Force", key="force_towerbcs", help="Force reinstall towerbcs package (ignores version checks)"):
                        with st.spinner("Force installing towerbcs..."):
                            success, message = force_install_towerbcs_package()
                            if success:
                                st.success("✅ towerbcs force installed")
                                with st.expander("📋 Force Install Output", expanded=False):
                                    st.code(message, language="bash")
                                import time
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("❌ Failed to force install towerbcs")
                                with st.expander("📋 Error Output", expanded=True):
                                    st.code(message, language="bash")

    # Instructions
    with st.expander("ℹ️ About Codebase Status"):
        st.markdown("""
        **Codebase Status Display:**
        - **Git status**: Shows synchronization with remote (ahead/behind/up to date)
        - **Local changes**: Shows number of uncommitted local changes
        - Both statuses are displayed independently for clear visibility

        **Repository Status Indicators:**
        - ✅ **Up to date**: Repository is up to date with remote
        - ⬇️ **Behind**: Local repository is behind remote (can pull updates)
        - ⬆️ **Ahead**: Local repository has unpushed commits
        - 📝 **Changes**: Local repository has uncommitted changes (shown in expandable sections)
        - 🟡 **Needs update**: Submodule needs to be updated
        - ⚠️ **Error**: There's an issue with the repository
        - ❌ **Not found**: Repository directory doesn't exist

        **Display Format:**
        - Git status and local changes are shown as separate, clear indicators
        - Click the expandable "Local Changes" sections to see detailed file lists
        - This helps distinguish between remote sync status and local work progress

        **Pull Options:**
        - ⬇️ **Pull**: Normal `git pull` - merges remote changes
        - 🔄 **Rebase**: `git pull --rebase` - replays local commits on top of remote
        - 💾 **Autostash**: `git pull --autostash` - temporarily stashes uncommitted changes

        **Console Output:**
        - All git commands show their console output in expandable sections
        - Successful operations show output collapsed by default
        - Failed operations show error output expanded by default
        - This helps with debugging and understanding what happened

        **Submodules:**
        - The page automatically detects and monitors git submodules
        - Submodule updates use `git submodule update --remote --merge`
        - Each submodule can be updated individually or as part of bulk operations

        **External Packages:**
        - Shows status of external Python packages (like towerbcs)
        - Version checking and updates are handled via dedicated update scripts
        - Package installation status is monitored independently from git repositories
        - Uses `install_towerbcs.py` script for towerbcs management

        **Package Update Options:**
        - 🔄 **Update**: Normal update (checks versions, installs if newer available)
        - 📥 **Install**: Install package if not currently installed
        - ⚡ **Force**: Force reinstall package (ignores version checks, uses --force-reinstall and --no-cache-dir)

        **Force Install Details:**
        - The force option bypasses version checking and forces a fresh installation
        - Uses pip's `--force-reinstall` and `--no-cache-dir` flags for clean install
        - Useful when package installation is corrupted or you want to ensure latest code
        - Always installs from the latest version available in the repository

        **Safety Notes:**
        - Console output helps diagnose issues
        - Always review changes before pulling in production environments
        - External package updates may require additional dependencies
        """)


if __name__ == "__main__":
    codebase_status_page()
