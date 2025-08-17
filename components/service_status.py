"""
Service Status component for Streamlit hidden site.

Shows the status of various systemd services used by the Tower system.
Gracefully handles Windows development environments.
"""

import subprocess
import streamlit as st
import platform
from datetime import datetime
from typing import Tuple


def is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system().lower() == 'windows'


def get_service_status(service_name: str) -> Tuple[str, str, str]:
    """
    Get the status of a systemd service.

    Returns:
        tuple: (status, active_state, sub_state)
    """
    if is_windows():
        # On Windows, return mock status for development
        return ('not-available', 'unknown', 'windows-dev')

    try:
        # Get service status
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        active_state = result.stdout.strip()

        # Get more detailed status
        result = subprocess.run(
            ["systemctl", "show", service_name, "--property=SubState,ActiveState,LoadState"],
            capture_output=True,
            text=True,
            timeout=5
        )

        properties = {}
        for line in result.stdout.strip().split('\n'):
            if '=' in line:
                key, value = line.split('=', 1)
                properties[key] = value

        return (
            properties.get('LoadState', 'unknown'),
            properties.get('ActiveState', active_state),
            properties.get('SubState', 'unknown')
        )

    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        return ('not-found', 'inactive', 'dead')


def get_status_color(active_state: str, sub_state: str) -> str:
    """Get the appropriate color for service status."""
    if active_state == 'active' and sub_state == 'running':
        return 'green'
    elif active_state == 'active':
        return 'orange'
    elif active_state == 'inactive':
        return 'gray'
    elif active_state == 'failed':
        return 'red'
    else:
        return 'yellow'


def get_status_emoji(active_state: str, sub_state: str) -> str:
    """Get the appropriate emoji for service status."""
    if is_windows() and sub_state == 'windows-dev':
        return '🖥️'
    elif active_state == 'active' and sub_state == 'running':
        return '🟢'
    elif active_state == 'active':
        return '🟡'
    elif active_state == 'inactive':
        return '⚪'
    elif active_state == 'failed':
        return '🔴'
    else:
        return '🟡'


def restart_service(service_name: str) -> bool:
    """
    Restart a systemd service.

    Returns:
        bool: True if restart was successful, False otherwise
    """
    if is_windows():
        # On Windows, simulate restart for development
        return True

    try:
        result = subprocess.run(
            ["systemctl", "restart", service_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return False


def start_service(service_name: str) -> bool:
    """
    Start a systemd service.

    Returns:
        bool: True if start was successful, False otherwise
    """
    if is_windows():
        # On Windows, simulate start for development
        return True

    try:
        result = subprocess.run(
            ["systemctl", "start", service_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return False


def service_status_page():
    """Main service status page component."""
    st.title("🔧 Service Status")

    # Show environment info
    if is_windows():
        st.info("🖥️ **Development Mode**: Running on Windows - service status simulated for development")
    else:
        st.markdown("Monitor and manage Tower system services")

    # Warning about restarting services
    st.warning("⚠️ **Important**: Do not restart services without talking to **thedisasterfish** first! Service restarts can affect live users and ongoing tournaments.")

    # Define services to monitor (from admin.py restart actions)
    services = {
        'tower-public_site': {
            'name': 'Public Site',
            'description': 'Main public website (thetower.lol)',
            'service': 'tower-public_site',
            'restart_allowed': True
        },
        'tower-hidden_site': {
            'name': 'Hidden Site',
            'description': 'Internal analytics site (hidden.thetower.lol)',
            'service': 'tower-hidden_site',
            'restart_allowed': True
        },
        'tower-admin_site': {
            'name': 'Admin Site',
            'description': 'Admin interface (admin.thetower.lol)',
            'service': 'tower-admin_site',
            'restart_allowed': True
        },
        'fish_bot': {
            'name': 'Fish Bot',
            'description': 'Discord bot for game interactions',
            'service': 'fish_bot',
            'restart_allowed': True
        },
        'import_results': {
            'name': 'Import Results',
            'description': 'Service that imports tournament results (start-only)',
            'service': 'import_results',
            'restart_allowed': False
        },
        'get_results': {
            'name': 'Get Results',
            'description': 'Service that fetches tournament data (start-only)',
            'service': 'get_results',
            'restart_allowed': False
        },
        'tower-recalc_worker': {
            'name': 'Recalc Worker',
            'description': 'Background tournament recalculation queue worker',
            'service': 'tower-recalc_worker',
            'restart_allowed': True
        }
    }

    # Refresh controls
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🔄 Refresh Now"):
            st.rerun()
    with col2:
        utc_time = datetime.utcnow().strftime('%H:%M:%S')
        st.markdown(f"*Last updated: {utc_time} UTC*")

    st.markdown("---")

    # Service status grid
    for service_id, config in services.items():
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

            # Get service status
            load_state, active_state, sub_state = get_service_status(config['service'])
            status_emoji = get_status_emoji(active_state, sub_state)

            with col1:
                st.markdown(f"**{status_emoji} {config['name']}**")
                st.caption(config['description'])

            with col2:
                if is_windows() and sub_state == 'windows-dev':
                    st.info("Development Mode")
                elif active_state == 'active' and sub_state == 'running':
                    st.success(f"Running ({sub_state})")
                elif active_state == 'active':
                    st.warning(f"Active ({sub_state})")
                elif active_state == 'failed':
                    st.error(f"Failed ({sub_state})")
                elif active_state == 'inactive':
                    st.info(f"Stopped ({sub_state})")
                else:
                    st.warning(f"{active_state} ({sub_state})")

            with col3:
                if is_windows():
                    st.markdown("🖥️ Windows Dev")
                elif load_state == 'loaded':
                    st.markdown("✅ Loaded")
                elif load_state == 'not-found':
                    st.markdown("❌ Not Found")
                else:
                    st.markdown(f"⚠️ {load_state}")

            with col4:
                # Action button logic
                if load_state == 'loaded' or is_windows():
                    restart_allowed = config.get('restart_allowed', True)

                    # Determine button state and text
                    if not restart_allowed:
                        # Start-only services (import_results, get_results)
                        if is_windows() or (active_state != 'active' or sub_state != 'running'):
                            # Show start button if stopped or in dev mode
                            button_icon = "▶️"
                            button_help = f"Start {config['name']}" if not is_windows() else f"Simulate start {config['name']} (dev mode)"
                            action_text = "start"
                        else:
                            # Service is running, no button for start-only services
                            st.markdown("🔒 Start-only")
                            button_icon = None
                    else:
                        # Regular restart services
                        button_icon = "🔄"
                        button_help = f"Restart {config['name']}" if not is_windows() else f"Simulate restart {config['name']} (dev mode)"
                        action_text = "restart"

                    # Show button if we have an icon
                    if button_icon:
                        restart_key = f"action_{service_id}"
                        if st.button(button_icon, key=restart_key, help=button_help):
                            action_word = "Simulating" if is_windows() else action_text.title() + "ing"
                            with st.spinner(f"{action_word} {config['name']}..."):
                                # Use appropriate service function
                                if action_text == "start":
                                    success = start_service(config['service'])
                                else:
                                    success = restart_service(config['service'])

                                if success:
                                    past_tense = f"{action_text}ed" if action_text.endswith('t') else f"{action_text}ed"
                                    sim_text = f" ({action_text} simulated)" if is_windows() else f" {past_tense}"
                                    msg = f"✅ {config['name']}{sim_text} successfully!"
                                    st.success(msg)
                                    # Small delay to let service start, then refresh
                                    import time
                                    time.sleep(1 if is_windows() else 2)
                                    st.rerun()
                                else:
                                    st.error(f"❌ Failed to {action_text} {config['name']}")

        st.markdown("---")

    # Summary section
    st.markdown("### 📊 Service Summary")

    # Count services by status
    if is_windows():
        status_counts = {'dev_mode': len(services), 'running': 0, 'stopped': 0, 'failed': 0, 'other': 0}
    else:
        status_counts = {'running': 0, 'stopped': 0, 'failed': 0, 'other': 0}

        for service_id, config in services.items():
            load_state, active_state, sub_state = get_service_status(config['service'])
            if active_state == 'active' and sub_state == 'running':
                status_counts['running'] += 1
            elif active_state == 'inactive':
                status_counts['stopped'] += 1
            elif active_state == 'failed':
                status_counts['failed'] += 1
            else:
                status_counts['other'] += 1

    if is_windows():
        col1, col2 = st.columns(2)
        with col1:
            st.metric("🖥️ Dev Mode", status_counts['dev_mode'])
        with col2:
            st.info("Service monitoring available in Linux production environment")
    else:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("🟢 Running", status_counts['running'])
        with col2:
            st.metric("⚪ Stopped", status_counts['stopped'])
        with col3:
            st.metric("🔴 Failed", status_counts['failed'])
        with col4:
            st.metric("🟡 Other", status_counts['other'])

    # Queue status (if recalc worker exists)
    st.markdown("### 🔄 Queue Status")
    try:
        # Try to get queue status using Django management command
        import os
        import sys

        # Add Django project to path
        django_path = os.path.join(os.path.dirname(__file__), '..', 'thetower', 'dtower')
        if django_path not in sys.path:
            sys.path.insert(0, django_path)

        # Try to import and run queue status
        try:
            os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dtower.settings')
            import django
            django.setup()

            from dtower.tourney_results.models import TourneyResult
            from django.utils import timezone
            from datetime import timedelta

            # Get queue statistics
            pending_count = TourneyResult.objects.filter(needs_recalc=True).count()
            failed_count = TourneyResult.objects.filter(
                needs_recalc=True,
                recalc_retry_count__gte=3
            ).count()

            # Get recent processing stats (last 24h)
            yesterday = timezone.now() - timedelta(days=1)
            recent_processed = TourneyResult.objects.filter(
                last_recalc_at__gte=yesterday
            ).count()

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("📋 Pending", pending_count)
            with col2:
                st.metric("❌ Failed", failed_count)
            with col3:
                st.metric("✅ Processed (24h)", recent_processed)

        except Exception:
            st.warning("Could not load queue status")

    except Exception:
        st.warning("Queue status unavailable")

    # Instructions
    with st.expander("ℹ️ About Service Status"):
        st.markdown("""
        **Service States:**
        - 🟢 **Running**: Service is active and working normally
        - 🟡 **Active**: Service is loaded but may not be running (e.g., one-shot services)
        - ⚪ **Stopped**: Service is inactive but loaded
        - 🔴 **Failed**: Service has failed and needs attention
        
        **Actions:**
        - 🔄 **Restart button**: Restart services (most services)
        - ▶️ **Start button**: Start stopped services (import_results, get_results only)
        - 🔒 **Start-only**: Some services can only be started when stopped, not restarted when running
        - Use manual refresh to monitor services
        - Check the Queue Status for tournament recalculation progress
        
        **Services:**
        - **Public/Hidden/Admin Sites**: Web applications serving different interfaces
        - **Fish Bot**: Discord bot for game interactions
        - **Import/Get Results**: Background services that fetch tournament data (start-only)
        - **Recalc Worker**: Processes tournament position recalculations
        
        **Development Note:**
        - On Windows: Service status is simulated for development purposes
        - On Linux: Actual systemctl service status is displayed
        """)


if __name__ == "__main__":
    service_status_page()
