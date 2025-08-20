"""
Git Repository Status component for Streamlit hidden site.

Shows the status of the main repository and submodules, allows pulling updates.
Gracefully handles Windows development environments.
"""

import subprocess
import streamlit as st
import platform
import os
from datetime import datetime
from typing import Dict, List, Tuple


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
        return (result.returncode == 0, result.stdout.strip(), result.stderr.strip())
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
            status_code = line[:2]
            filename = line[3:]

            if status_code[0] in ['M', 'A', 'D', 'R', 'C']:
                status_info['staged'].append(filename)
            if status_code[1] in ['M', 'D']:
                status_info['modified'].append(filename)
            elif status_code[1] == '?':
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


def git_status_page():
    """Main git repository status page component."""
    st.title("📦 Git Repository Status")

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
        utc_time = datetime.utcnow().strftime('%H:%M:%S')
        st.markdown(f"*Last updated: {utc_time} UTC*")

    st.markdown("---")

    # Get main repository status
    main_repo = get_git_status(repo_root)
    submodules = get_submodules_info(repo_root)

    # Main Repository Section
    st.markdown("## 🏠 Main Repository")

    with st.container():
        col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

        with col1:
            emoji = get_status_emoji(main_repo)
            st.markdown(f"**{emoji} thetower.lol**")
            if main_repo['exists']:
                st.caption(f"Branch: `{main_repo['branch']}`")
            else:
                st.caption("Repository not found")

        with col2:
            if main_repo['error']:
                st.error(f"Error: {main_repo['error']}")
            else:
                # Git status (remote tracking)
                if main_repo['behind'] > 0:
                    st.warning(f"Git status: {main_repo['behind']} behind")
                elif main_repo['ahead'] > 0:
                    st.info(f"Git status: {main_repo['ahead']} ahead")
                else:
                    st.success("Git status: up to date")

                # Local changes (separate line)
                if main_repo['has_changes']:
                    changes = len(main_repo['modified']) + len(main_repo['untracked']) + len(main_repo['staged'])
                    st.caption(f"Local changes: {changes} changes")
                else:
                    st.caption("Local changes: none")

        with col3:
            if main_repo['exists'] and not main_repo['error']:
                st.markdown("**Last commit:**")
                st.caption(main_repo['last_commit'])
            else:
                st.markdown("—")

        with col4:
            if main_repo['exists'] and not main_repo['error']:
                # Multiple pull options in a row
                st.markdown("**Pull Options:**")

                # Normal pull
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

                # Rebase pull
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

                # Autostash pull
                if st.button("💾 Autostash", key="pull_main_autostash", help="Pull with autostash (git pull --autostash)"):
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
                                st.code(message, language="bash")

    # Show detailed main repo info if there are changes
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

    # Bulk Actions Section
    st.markdown("## 🚀 Bulk Actions")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("⬇️ Pull All Repositories", help="Pull main repository and all submodules"):
            with st.spinner("Pulling all repositories..."):
                results = []

                # Pull main repository
                success, message = pull_repository(repo_root)
                results.append(("Main Repository", success, message))

                # Pull all submodules
                for submodule in submodules:
                    if submodule['exists'] and not submodule['error']:
                        success, message = pull_repository(
                            os.path.join(repo_root, submodule['submodule_path']),
                            is_submodule=True
                        )
                        results.append((submodule['submodule_path'], success, message))

                # Show results
                success_count = sum(1 for _, success, _ in results if success)
                total_count = len(results)

                if success_count == total_count:
                    st.success(f"✅ All {total_count} repositories updated successfully!")
                else:
                    st.warning(f"⚠️ {success_count}/{total_count} repositories updated successfully")

                # Show detailed results
                with st.expander("📋 Bulk Pull Results", expanded=True):
                    for name, success, message in results:
                        if success:
                            st.success(f"✅ {name}")
                            if message:
                                st.code(message, language="bash")
                        else:
                            st.error(f"❌ {name}")
                            if message:
                                st.code(message, language="bash")

                # Refresh after bulk operation
                import time
                time.sleep(2)
                st.rerun()

    with col2:
        # Show summary statistics
        total_repos = 1 + len(submodules)
        up_to_date = 0
        needs_update = 0
        has_issues = 0

        # Check main repo
        if main_repo['exists'] and not main_repo['error']:
            if main_repo['behind'] > 0 or main_repo['ahead'] > 0:
                needs_update += 1
            else:
                up_to_date += 1
        else:
            has_issues += 1

        # Check submodules
        for submodule in submodules:
            if submodule['exists'] and not submodule['error']:
                if (submodule['behind'] > 0 or submodule['ahead'] > 0 or
                        submodule['needs_update']):
                    needs_update += 1
                else:
                    up_to_date += 1
            else:
                has_issues += 1

        st.metric("📊 Repository Summary", f"{total_repos} total")
        st.metric("✅ Up to date", up_to_date)
        st.metric("⚠️ Needs attention", needs_update + has_issues)

    # Instructions
    with st.expander("ℹ️ About Git Repository Status"):
        st.markdown("""
        **Repository Status Display:**
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

        **Safety Notes:**
        - Console output helps diagnose issues
        - Always review changes before pulling in production environments
        """)


if __name__ == "__main__":
    git_status_page()
