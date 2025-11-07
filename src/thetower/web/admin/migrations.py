"""
Django Migrations Management for Streamlit Admin.

This page provides a safe interface for checking and applying Django migrations.
"""

import os
import subprocess
import sys
from datetime import datetime, timezone

import streamlit as st


def get_django_migrations_status():
    """
    Get the status of Django migrations using showmigrations command.

    Returns:
        dict: Migration status by app with applied/unapplied migrations
    """
    try:
        # Add Django backend to Python path
        backend_path = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)

        # Set Django settings
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")

        # Run showmigrations command
        result = subprocess.run(
            [sys.executable, "manage.py", "showmigrations", "--plan"],
            cwd=backend_path,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return {"error": f"Migration check failed: {result.stderr}"}

        # Parse the output
        migrations = {}
        current_app = None

        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue

            # App header (no leading spaces/symbols)
            if not line.startswith(('[X]', '[ ]', '(no')):
                current_app = line.rstrip(':')
                if current_app not in migrations:
                    migrations[current_app] = {
                        'applied': [],
                        'unapplied': []
                    }
            else:
                # Migration entry
                if current_app and line.startswith('['):
                    is_applied = line.startswith('[X]')
                    migration_name = line[4:].strip()  # Remove [X] or [ ] prefix

                    if is_applied:
                        migrations[current_app]['applied'].append(migration_name)
                    else:
                        migrations[current_app]['unapplied'].append(migration_name)

        return migrations

    except subprocess.TimeoutExpired:
        return {"error": "Migration check timed out"}
    except Exception as e:
        return {"error": f"Error checking migrations: {str(e)}"}


def apply_migrations(app_name=None, migration_name=None):
    """
    Apply Django migrations.

    Args:
        app_name: Specific app to migrate (None for all apps)
        migration_name: Specific migration to apply (None for all unapplied)

    Returns:
        dict: Result of migration operation
    """
    try:
        backend_path = os.path.join(os.path.dirname(__file__), "..", "..", "backend")

        # Build migrate command
        cmd = [sys.executable, "manage.py", "migrate"]
        if app_name:
            cmd.append(app_name)
            if migration_name:
                cmd.append(migration_name)

        # Run migration
        result = subprocess.run(
            cmd,
            cwd=backend_path,
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes timeout for migrations
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": " ".join(cmd)
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Migration timed out after 5 minutes"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error applying migrations: {str(e)}"
        }


def migrations_page():
    """Main migrations management page."""
    st.title("🔄 Django Migrations Management")

    # Warning about migrations
    st.warning(
        "⚠️ **Important**: Migrations modify the database structure. "
        "Always backup the database before applying migrations in production!"
    )

    # Refresh button
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("🔄 Refresh Status"):
            st.rerun()
    with col2:
        utc_time = datetime.now(timezone.utc).strftime("%H:%M:%S")
        st.markdown(f"*Last updated: {utc_time} UTC*")

    st.markdown("---")

    # Get migration status
    with st.spinner("Checking migration status..."):
        migrations_status = get_django_migrations_status()

    # Handle errors
    if "error" in migrations_status:
        st.error(f"❌ {migrations_status['error']}")
        return

    # Calculate summary stats
    total_unapplied = sum(len(app_data.get('unapplied', [])) for app_data in migrations_status.values())
    total_applied = sum(len(app_data.get('applied', [])) for app_data in migrations_status.values())

    # Summary metrics
    st.markdown("### 📊 Migration Summary")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("✅ Applied Migrations", total_applied)
    with col2:
        st.metric("⏳ Pending Migrations", total_unapplied)
    with col3:
        apps_with_pending = sum(1 for app_data in migrations_status.values() if app_data.get('unapplied'))
        st.metric("📦 Apps with Pending", apps_with_pending)

    # Show status
    if total_unapplied == 0:
        st.success("🎉 All migrations are up to date!")
    else:
        st.info(f"ℹ️ {total_unapplied} migrations pending across {apps_with_pending} apps")

    st.markdown("---")

    # Apply all migrations button (if there are pending migrations)
    if total_unapplied > 0:
        st.markdown("### 🚀 Quick Actions")

        col1, col2 = st.columns([1, 2])
        with col1:
            if st.button("🔄 Apply All Migrations", type="primary"):
                with st.spinner("Applying all migrations..."):
                    result = apply_migrations()

                    if result["success"]:
                        st.success("✅ All migrations applied successfully!")
                        if result["stdout"]:
                            with st.expander("📝 Migration Output"):
                                st.code(result["stdout"])
                        st.rerun()  # Refresh the page
                    else:
                        st.error("❌ Migration failed!")
                        if result.get("stderr"):
                            st.error(result["stderr"])
                        if result.get("stdout"):
                            with st.expander("📝 Migration Output"):
                                st.code(result["stdout"])

        with col2:
            st.markdown("*Apply all pending migrations across all Django apps*")

        st.markdown("---")

    # Per-app migration details
    st.markdown("### 📱 Per-App Migration Status")

    for app_name, app_migrations in migrations_status.items():
        applied = app_migrations.get('applied', [])
        unapplied = app_migrations.get('unapplied', [])

        # Skip apps with no migrations
        if not applied and not unapplied:
            continue

        with st.expander(f"📦 {app_name} ({len(unapplied)} pending, {len(applied)} applied)"):

            # App-specific apply button
            if unapplied:
                col1, col2 = st.columns([1, 3])
                with col1:
                    if st.button("Apply All", key=f"apply_all_{app_name}"):
                        with st.spinner(f"Applying {app_name} migrations..."):
                            result = apply_migrations(app_name=app_name)

                            if result["success"]:
                                st.success(f"✅ {app_name} migrations applied!")
                                if result["stdout"]:
                                    st.code(result["stdout"])
                                st.rerun()
                            else:
                                st.error(f"❌ {app_name} migration failed!")
                                if result.get("stderr"):
                                    st.error(result["stderr"])

                with col2:
                    st.markdown(f"*Apply all {len(unapplied)} pending {app_name} migrations*")

            # Show unapplied migrations
            if unapplied:
                st.markdown("**⏳ Pending Migrations:**")
                for i, migration in enumerate(unapplied):
                    col1, col2, col3 = st.columns([2, 1, 1])
                    with col1:
                        st.markdown(f"• `{migration}`")
                    with col2:
                        # Individual migration apply button
                        if st.button("Apply", key=f"apply_{app_name}_{migration}"):
                            with st.spinner(f"Applying {migration}..."):
                                result = apply_migrations(app_name=app_name, migration_name=migration)

                                if result["success"]:
                                    st.success(f"✅ Applied {migration}")
                                    if result["stdout"]:
                                        st.code(result["stdout"])
                                    st.rerun()
                                else:
                                    st.error(f"❌ Failed to apply {migration}")
                                    if result.get("stderr"):
                                        st.error(result["stderr"])

            # Show applied migrations (collapsed by default)
            if applied:
                with st.expander(f"✅ Applied Migrations ({len(applied)})"):
                    for migration in applied:
                        st.markdown(f"• `{migration}`")

    # Instructions
    st.markdown("---")
    with st.expander("ℹ️ About Django Migrations"):
        st.markdown("""
        **Migration Management:**
        - **Apply All**: Runs `python manage.py migrate` to apply all pending migrations
        - **Per-App Apply**: Runs `python manage.py migrate <app_name>` for specific apps
        - **Individual Migration**: Runs `python manage.py migrate <app> <migration>` for specific migrations

        **Migration Status:**
        - **✅ Applied**: Migration has been applied to the database
        - **⏳ Pending**: Migration exists but hasn't been applied yet
        - **📦 App Name**: Shows count of pending and applied migrations per Django app

        **Safety Guidelines:**
        - Always backup your database before applying migrations in production
        - Test migrations in development environment first
        - Review migration files before applying them
        - Monitor the application after applying migrations

        **Common Django Apps:**
        - `sus`: Moderation and player management system
        - `tourney_results`: Tournament data and analytics
        - `auth`: Django authentication system
        - `contenttypes`: Django content types framework
        - `sessions`: Django session management
        """)


if __name__ == "__main__":
    migrations_page()
