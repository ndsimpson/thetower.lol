"""
Codebase Status component for Streamlit hidden site.

Shows the status of git repositories and external packages, allows pulling updates.
Gracefully handles Windows development environments.
"""

import os
import platform
import subprocess
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import streamlit as st

from thetower.web.admin.package_updates import check_package_updates_sync, get_thetower_packages, update_package_sync


@st.dialog("Operation Result", width="large")
def show_operation_result(success: bool, title: str, message: str):
    """Display operation result in a modal dialog."""
    if success:
        st.success(title)
    else:
        st.error(title)

    st.code(message, language="bash")

    if st.button("✅ Close & Refresh", use_container_width=True, type="primary"):
        st.rerun()


def is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system().lower() == "windows"


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
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, cwd=cwd)
        return (result.returncode == 0, result.stdout.rstrip("\n\r"), result.stderr.strip())
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as e:
        return (False, "", str(e))


def get_git_status(repo_path: str) -> Dict[str, any]:
    """
    Get comprehensive git status for a repository.

    Returns:
        dict: Repository status information
    """
    status_info = {
        "path": repo_path,
        "exists": False,
        "branch": "unknown",
        "remote_url": "unknown",
        "ahead": 0,
        "behind": 0,
        "modified": [],
        "untracked": [],
        "staged": [],
        "last_commit": "unknown",
        "last_commit_date": "unknown",
        "has_changes": False,
        "can_pull": True,
        "error": None,
    }

    # Check if directory exists and is a git repo
    if not os.path.exists(repo_path):
        status_info["error"] = "Directory does not exist"
        return status_info

    # Check if it's a git repository by trying a git command
    # This works for both regular repos (.git directory) and submodules (.git file)
    success, _, _ = run_git_command(["git", "rev-parse", "--git-dir"], repo_path)
    if not success:
        status_info["error"] = "Not a git repository"
        return status_info

    status_info["exists"] = True

    # Get current branch
    success, branch, error = run_git_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    if success:
        status_info["branch"] = branch
    else:
        status_info["error"] = f"Could not get branch: {error}"
        return status_info

    # Get remote URL
    success, remote_url, _ = run_git_command(["git", "config", "--get", "remote.origin.url"], repo_path)
    if success:
        status_info["remote_url"] = remote_url

    # Get last commit info
    success, commit_info, _ = run_git_command(["git", "log", "-1", "--pretty=format:%h|%s|%ci"], repo_path)
    if success and commit_info:
        parts = commit_info.split("|", 2)
        if len(parts) >= 3:
            status_info["last_commit"] = f"{parts[0]} - {parts[1]}"
            status_info["last_commit_date"] = parts[2]

    # Get ahead/behind info (fetch from remote first for accurate info)
    try:
        # Fetch from remote to get updated refs (but don't output progress)
        run_git_command(["git", "fetch", "origin", "--quiet"], repo_path)

        success, ahead_behind, _ = run_git_command(["git", "rev-list", "--left-right", "--count", f"{branch}...origin/{branch}"], repo_path)
        if success and ahead_behind:
            parts = ahead_behind.split("\t")
            if len(parts) == 2:
                status_info["ahead"] = int(parts[0])
                status_info["behind"] = int(parts[1])
    except Exception:
        # If we can't check ahead/behind, that's okay - might be offline or no remote
        pass

    # Get working directory status
    success, porcelain, _ = run_git_command(["git", "status", "--porcelain"], repo_path)
    if success:
        for line in porcelain.split("\n"):
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
            if index_status in ["M", "A", "D", "R", "C"]:
                status_info["staged"].append(filename)

            # Check working tree changes
            if worktree_status in ["M", "D"]:
                status_info["modified"].append(filename)
            elif worktree_status == "?":
                status_info["untracked"].append(filename)

    status_info["has_changes"] = bool(status_info["modified"] or status_info["untracked"] or status_info["staged"])

    return status_info


def pull_repository(repo_path: str, pull_mode: str = "normal") -> Tuple[bool, str]:
    """
    Pull updates for a repository with different strategies.

    Args:
        repo_path: Path to the repository
        pull_mode: "normal", "rebase", "autostash", or "force"

    Returns:
        tuple: (success, message)
    """
    if pull_mode == "rebase":
        success, stdout, stderr = run_git_command(["git", "pull", "--rebase"], repo_path)
    elif pull_mode == "autostash":
        success, stdout, stderr = run_git_command(["git", "pull", "--autostash"], repo_path)
    elif pull_mode == "force":
        # Force pull by resetting to remote
        # First fetch to get latest remote refs
        success1, stdout1, stderr1 = run_git_command(["git", "fetch", "origin"], repo_path)
        if success1:
            success, stdout2, stderr2 = run_git_command(["git", "reset", "--hard", "origin/HEAD"], repo_path)
            stdout = f"Fetch:\n{stdout1}\n\nReset:\n{stdout2}"
            stderr = f"{stderr1}\n{stderr2}".strip()
        else:
            success, stdout, stderr = success1, stdout1, stderr1
    else:  # normal
        success, stdout, stderr = run_git_command(["git", "pull"], repo_path)

    if success:
        return True, stdout if stdout else "Pull completed successfully"
    else:
        return False, stderr if stderr else "Pull failed"


def get_status_emoji(repo_info: Dict[str, any]) -> str:
    """Get emoji representing repository status."""
    if not repo_info["exists"]:
        return "❌"
    elif repo_info["error"]:
        return "⚠️"
    elif repo_info["behind"] > 0:
        return "⬇️"
    elif repo_info["ahead"] > 0:
        return "⬆️"
    elif repo_info["ahead"] == 0 and repo_info["behind"] == 0:
        return "✅"  # Up to date with remote (regardless of local changes)
    elif repo_info["has_changes"]:
        return "📝"
    else:
        return "✅"


def is_development_mode() -> bool:
    """Check if running in development mode (git repository available)."""
    cwd = os.getcwd()
    # Check if current directory or parent has .git
    return os.path.exists(os.path.join(cwd, ".git")) or os.path.exists(os.path.join(os.path.dirname(cwd), ".git"))


def codebase_status_page():
    """Main codebase status page component."""
    st.title("📋 Codebase Status")

    cwd = os.getcwd()
    dev_mode = is_development_mode()

    # Show environment info
    if is_windows():
        st.info("🖥️ **Development Mode**: Running on Windows with git repository")
    elif dev_mode:
        st.info("🔧 **Development Mode**: Git repository available")
    else:
        st.info("🚀 **Production Mode**: Running from pip-installed package")

    if dev_mode:
        st.markdown(f"**Repository Path:** `{cwd}`")
    else:
        st.markdown(f"**Working Directory:** `{cwd}`")

    # Refresh controls
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🔄 Refresh Status"):
            st.rerun()
    with col2:
        utc_time = datetime.now(timezone.utc).strftime("%H:%M:%S")
        st.markdown(f"*Last updated: {utc_time} UTC*")

    st.markdown("---")

    # Main Package/Repository Section
    if dev_mode:
        # Development mode: show git repository status
        main_repo = get_git_status(cwd)

        st.markdown("## 🏠 Main Repository")

        with st.container():
            col1, col2 = st.columns([1, 1])

            with col1:
                # Repository Info Card
                with st.container():
                    st.markdown("**Repository Info**")

                    emoji = get_status_emoji(main_repo)
                    st.markdown(f"**{emoji} thetower.lol**")

                    if main_repo["exists"]:
                        st.caption(f"Branch: `{main_repo['branch']}`")

                        # Last commit info
                        if main_repo["last_commit"] != "unknown":
                            commit_parts = main_repo["last_commit"].split(" - ", 1)
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

                    if main_repo["error"]:
                        st.error(f"Error: {main_repo['error']}")
                    else:
                        # Git status
                        if main_repo["behind"] > 0:
                            st.warning(f"Git Status: {main_repo['behind']} commits behind")
                        elif main_repo["ahead"] > 0:
                            st.info(f"Git Status: {main_repo['ahead']} commits ahead")
                        else:
                            st.success("Git Status: ✅ Up to date")

                        # Local changes
                        if main_repo["has_changes"]:
                            changes = len(main_repo["modified"]) + len(main_repo["untracked"]) + len(main_repo["staged"])
                            st.warning(f"Local Changes: 📝 {changes} changes")
                        else:
                            st.success("Local Changes: No changes")

                    st.markdown("")  # Add some spacing

                    # Action buttons
                    if main_repo["exists"] and not main_repo["error"]:
                        col_a, col_b, col_c = st.columns(3)

                        with col_a:
                            if st.button("⬇️ Pull", key="pull_main_normal", help="Normal git pull"):
                                with st.spinner("Pulling main repository..."):
                                    success, message = pull_repository(cwd, pull_mode="normal")
                                    show_operation_result(
                                        success=success,
                                        title="✅ Main repository updated" if success else "❌ Failed to pull main repository",
                                        message=message,
                                    )

                        with col_b:
                            if st.button("🔄 Rebase", key="pull_main_rebase", help="Pull with rebase (git pull --rebase)"):
                                with st.spinner("Pulling main repository (rebase)..."):
                                    success, message = pull_repository(cwd, pull_mode="rebase")
                                    show_operation_result(
                                        success=success,
                                        title="✅ Main repository rebased" if success else "❌ Failed to rebase main repository",
                                        message=message,
                                    )

                        with col_c:
                            if st.button("💾 Stash", key="pull_main_autostash", help="Pull with autostash (git pull --autostash)"):
                                with st.spinner("Pulling main repository (autostash)..."):
                                    success, message = pull_repository(cwd, pull_mode="autostash")
                                    show_operation_result(
                                        success=success,
                                        title="✅ Main repository updated (autostash)" if success else "❌ Failed to autostash pull main repository",
                                        message=message,
                                    )

        # Show detailed main repo info if there are changes
        if main_repo["exists"] and main_repo["has_changes"]:
            with st.expander("📝 Main Repository - Local Changes", expanded=False):
                if main_repo["staged"]:
                    st.markdown("**Staged changes:**")
                    for file in main_repo["staged"][:10]:  # Limit to first 10
                        st.markdown(f"- `{file}`")
                    if len(main_repo["staged"]) > 10:
                        st.markdown(f"... and {len(main_repo['staged']) - 10} more")

                if main_repo["modified"]:
                    st.markdown("**Modified files:**")
                    for file in main_repo["modified"][:10]:  # Limit to first 10
                        st.markdown(f"- `{file}`")
                    if len(main_repo["modified"]) > 10:
                        st.markdown(f"... and {len(main_repo['modified']) - 10} more")

                if main_repo["untracked"]:
                    st.markdown("**Untracked files:**")
                    for file in main_repo["untracked"][:10]:  # Limit to first 10
                        st.markdown(f"- `{file}`")
                    if len(main_repo["untracked"]) > 10:
                        st.markdown(f"... and {len(main_repo['untracked']) - 10} more")

        st.markdown("---")

    else:
        # Production mode: show pip package status for main thetower package
        st.markdown("## 🏠 Main Package (thetower)")

        # Get thetower packages (will include the main package)
        all_packages = get_thetower_packages()
        main_pkg = next((pkg for pkg in all_packages if pkg["name"] == "thetower"), None)

        if not main_pkg:
            st.warning("⚠️ Main thetower package not found. Is it installed?")
        else:
            with st.container():
                col1, col2 = st.columns([1, 1])

                with col1:
                    # Package Info Card
                    with st.container():
                        st.markdown("**Package Info**")

                        # Install type badge
                        install_badge = "📝 Editable" if main_pkg.get("install_type") == "editable" else "📦 Regular"

                        st.markdown(f"**🏠 {main_pkg['name']}**")
                        st.caption(f"Type: Main Package | Install: {install_badge}")
                        st.caption(f"Version: v{main_pkg['version']}")

                        if main_pkg["repository_url"]:
                            # Convert SSH URLs to GitHub HTTPS URLs for display
                            repo_display = main_pkg["repository_url"]
                            if "git@" in repo_display or repo_display.startswith("ssh://"):
                                # ssh://git@alias/owner/repo.git → https://github.com/owner/repo
                                parts = repo_display.rstrip("/").replace(".git", "").split("/")
                                if len(parts) >= 2:
                                    owner_repo = "/".join(parts[-2:])
                                else:
                                    owner_repo = parts[-1]
                                repo_display = f"https://github.com/{owner_repo}"
                            st.caption(f"Repository: {repo_display}")

                with col2:
                    # Status & Actions Card
                    with st.container():
                        st.markdown("**Status & Actions**")

                        if main_pkg["repository_url"]:
                            # Check for updates
                            update_info = check_package_updates_sync(main_pkg["name"], main_pkg["repository_url"])

                            if update_info.get("error"):
                                st.warning(f"Status: ⚠️ {update_info['error'][:50]}...")
                            elif update_info["update_available"]:
                                st.warning(f"Status: 🔄 Update available ({update_info['latest_version']})")
                            else:
                                st.success("Status: ✅ Up to date")

                            st.info("⚠️ Service restart required after updating")
                            st.caption("Streamlit pages will be re-extracted automatically")

                            st.markdown("")  # Add spacing

                            # Action buttons
                            col_a, col_b = st.columns(2)

                            with col_a:
                                if st.button("🔄 Update", key="update_main_package", help="Update main thetower package to latest version"):
                                    with st.spinner("Updating main thetower package..."):
                                        result = update_package_sync(main_pkg["name"], repo_url=main_pkg["repository_url"])
                                        title = (
                                            f"✅ {main_pkg['name']} updated to {result['new_version']}\n🔄 Please restart services for changes to take effect"
                                            if result["success"]
                                            else f"❌ Failed to update {main_pkg['name']}"
                                        )
                                        show_operation_result(success=result["success"], title=title, message=result["message"])

                            with col_b:
                                if st.button("⚡ Force", key="force_main_package", help="Force reinstall main package from main branch"):
                                    with st.spinner("Force installing main thetower package..."):
                                        result = update_package_sync(main_pkg["name"], target_version="main", repo_url=main_pkg["repository_url"])
                                        title = (
                                            f"✅ {main_pkg['name']} force installed\n🔄 Please restart services for changes to take effect"
                                            if result["success"]
                                            else f"❌ Failed to force install {main_pkg['name']}"
                                        )
                                        show_operation_result(success=result["success"], title=title, message=result["message"])
                        else:
                            st.info("Status: ℹ️ No repository URL configured")

        st.markdown("---")

    # External Packages Section
    st.markdown("## 📦 External Packages")

    # Scan for all thetower-project packages
    thetower_packages = get_thetower_packages()

    if not thetower_packages:
        st.info("No external thetower-project packages found.")
    else:
        for idx, pkg in enumerate(thetower_packages):
            # Skip the main thetower package itself
            if pkg["name"] == "thetower":
                continue

            with st.container():
                col1, col2 = st.columns([1, 1])

                with col1:
                    # Package Info Card
                    with st.container():
                        st.markdown("**Package Info**")

                        # Package type emoji
                        type_emoji = {"cog": "🔌", "module": "📦", "main": "🏠", "unknown": "❓"}.get(pkg["type"], "❓")

                        # Install type badge
                        install_badge = "📝 Editable" if pkg.get("install_type") == "editable" else "📦 Regular"

                        st.markdown(f"**{type_emoji} {pkg['name']}**")
                        st.caption(f"Type: {pkg['type']} | Install: {install_badge}")
                        st.caption(f"Current: v{pkg['version']}")

                        if pkg["repository_url"]:
                            # Convert SSH URLs to GitHub HTTPS URLs for display
                            repo_display = pkg["repository_url"]
                            if "git@" in repo_display or repo_display.startswith("ssh://"):
                                # ssh://git@alias/owner/repo.git → https://github.com/owner/repo
                                parts = repo_display.rstrip("/").replace(".git", "").split("/")
                                if len(parts) >= 2:
                                    owner_repo = "/".join(parts[-2:])
                                else:
                                    owner_repo = parts[-1]
                                repo_display = f"https://github.com/{owner_repo}"
                            st.caption(f"Repo: {repo_display}")

                with col2:
                    # Status & Actions Card
                    with st.container():
                        st.markdown("**Status & Actions**")

                        if pkg["repository_url"]:
                            # Check for updates
                            update_info = check_package_updates_sync(pkg["name"], pkg["repository_url"])

                            if update_info.get("error"):
                                st.warning(f"Status: ⚠️ {update_info['error'][:40]}...")
                            elif update_info["update_available"]:
                                st.warning(f"Status: 🔄 Update available ({update_info['latest_version']})")
                            else:
                                st.success("Status: ✅ Up to date")
                        else:
                            st.info("Status: ℹ️ No repository URL")

                        # Show info for cogs
                        if pkg["type"] == "cog":
                            st.info("🤖 Cog reload or bot restart may be needed after updating")

                        st.markdown("")  # Add spacing

                        # Action buttons
                        if pkg["repository_url"]:
                            col_a, col_b = st.columns(2)

                            with col_a:
                                update_key = f"update_{idx}_{pkg['name'].replace('-', '_')}"
                                if st.button("🔄 Update", key=update_key, help=f"Update {pkg['name']} to latest version"):
                                    with st.spinner(f"Updating {pkg['name']}..."):
                                        result = update_package_sync(pkg["name"], repo_url=pkg["repository_url"])
                                        title = (
                                            f"✅ {pkg['name']} updated to {result['new_version']}"
                                            if result["success"]
                                            else f"❌ Failed to update {pkg['name']}"
                                        )
                                        show_operation_result(success=result["success"], title=title, message=result["message"])

                            with col_b:
                                force_key = f"force_{idx}_{pkg['name'].replace('-', '_')}"
                                if st.button("⚡ Force", key=force_key, help=f"Force reinstall {pkg['name']} (main branch)"):
                                    with st.spinner(f"Force installing {pkg['name']}..."):
                                        # Force install uses main branch instead of a tag
                                        result = update_package_sync(pkg["name"], target_version="main", repo_url=pkg["repository_url"])
                                        title = (
                                            f"✅ {pkg['name']} force installed" if result["success"] else f"❌ Failed to force install {pkg['name']}"
                                        )
                                        show_operation_result(success=result["success"], title=title, message=result["message"])

                st.markdown("---")

    # Instructions
    with st.expander("ℹ️ About Codebase Status"):
        st.markdown(
            """
        **Environment Detection:**
        - **Development Mode**: Detects git repository, shows git status and controls
        - **Production Mode**: Pip-installed package, shows version and pip update controls
        - Mode is automatically detected based on presence of .git directory

        **Development Mode (Git-based):**
        - Shows git status: synchronization with remote (ahead/behind/up to date)
        - Shows local changes: uncommitted modifications, additions, deletions
        - Git pull operations: normal, rebase, autostash
        - Status indicators: ✅ up to date | ⬇️ behind | ⬆️ ahead | 📝 changes | ⚠️ error

        **Production Mode (Pip-based):**
        - Shows installed package version
        - Checks for updates from git repository tags
        - Update to latest tagged version or force install from HEAD
        - ⚠️ Service restart required after main package updates
        - Streamlit pages are automatically re-extracted via `thetower-init-streamlit`

        **Repository Status Indicators (Development Mode):**
        - ✅ **Up to date**: Repository is up to date with remote
        - ⬇️ **Behind**: Local repository is behind remote (can pull updates)
        - ⬆️ **Ahead**: Local repository has unpushed commits
        - 📝 **Changes**: Local repository has uncommitted changes (shown in expandable sections)
        - ⚠️ **Error**: There's an issue with the repository
        - ❌ **Not found**: Repository directory doesn't exist

        **Pull Options (Development Mode):**
        - ⬇️ **Pull**: Normal `git pull` - merges remote changes
        - 🔄 **Rebase**: `git pull --rebase` - replays local commits on top of remote
        - 💾 **Autostash**: `git pull --autostash` - temporarily stashes uncommitted changes

        **External Packages (Both Modes):**
        - Shows status of all installed packages with `Private::thetower-project` classifier
        - Automatically detects package type (cog/module/main) from classifiers
        - Version checking and updates handled via git repository tags
        - Works with SSH deploy keys via git+ssh:// URLs

        **Package Types:**
        - 🔌 **Cog**: External Discord bot cog (`Private::thetower.cog`)
        - 📦 **Module**: External Python module (`Private::thetower.module`)
        - 🏠 **Main**: Main thetower application (`Private::thetower.main`)

        **Package Update Options:**
        - 🔄 **Update**: Update to latest tagged version
        - ⚡ **Force**: Force reinstall from HEAD (latest commit, bypasses tags)

        **Update Process:**
        - Uses git ls-remote to check for new tags without cloning
        - Updates via pip install git+<url>@<tag>
        - Works with SSH URLs via configured deploy keys in ~/.ssh/config
        - Preserves existing dependencies (uses --no-deps)

        **Console Output:**
        - All commands show their console output in expandable sections
        - Successful operations show output collapsed by default
        - Failed operations show error output expanded by default
        - This helps with debugging and understanding what happened

        **Safety Notes:**
        - Always review changes before pulling in production environments
        - Package updates may require service restart to take effect
        - In production, main package updates require restarting all services (bot, web, workers)
        - External cog packages require bot restart or cog reload
        """
        )


if __name__ == "__main__":
    codebase_status_page()
