"""
Zendesk API utilities for creating support tickets.
"""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def _get_zendesk_base_url() -> str:
    """Get Zendesk base URL from environment variable."""
    base_url = os.getenv("ZENDESK_BASE_URL")
    if not base_url:
        raise ValueError(
            "ZENDESK_BASE_URL environment variable is not set. "
            "Please set it to your Zendesk instance URL (e.g., https://yourcompany.zendesk.com)"
        )
    return base_url.rstrip('/')  # Remove trailing slash if present


def get_zendesk_ticket_url(ticket_id: int) -> str:
    """Get the API URL for a Zendesk ticket."""
    base_url = _get_zendesk_base_url()
    return f"{base_url}/api/v2/tickets/{ticket_id}.json"


def get_zendesk_ticket_web_url(ticket_id: int) -> str:
    """Get the web interface URL for a Zendesk ticket."""
    base_url = _get_zendesk_base_url()
    return f"{base_url}/agent/tickets/{ticket_id}"


class ZendeskError(Exception):
    """Exception raised for Zendesk API errors."""
    pass


def create_zendesk_ticket(
    subject: str,
    body: str,
    priority: str = "normal",
    tags: Optional[list[str]] = None,
    requester_name: str = "Tower.lol",
    requester_email: str = "bot@tower.lol",
    external_id: Optional[str] = None
) -> dict:
    """
    Create a Zendesk support ticket.

    Args:
        subject: The subject line of the ticket
        body: The main body content of the ticket
        priority: Ticket priority (urgent, high, normal, low)
        tags: List of tags to add to the ticket
        requester_name: Name of the requester
        requester_email: Email of the requester
        external_id: Optional external ID for deduplication

    Returns:
        dict: The created ticket data from Zendesk API

    Raises:
        ZendeskError: If the ticket creation fails
        ValueError: If ZENDESK_AUTH_TOKEN is not set
    """
    # Get authorization token from environment variable
    auth_token = os.getenv("ZENDESK_AUTH_TOKEN")
    if not auth_token:
        raise ValueError(
            "ZENDESK_AUTH_TOKEN environment variable is not set. "
            "Please set it to your Zendesk API token."
        )

    # Zendesk API endpoint
    base_url = _get_zendesk_base_url()
    zendesk_url = f"{base_url}/api/v2/tickets.json"

    # Construct the ticket payload
    ticket_data = {
        "ticket": {
            "subject": subject,
            "comment": {
                "body": body
            },
            "priority": priority,
            "tags": tags or [],
            "requester": {
                "name": requester_name,
                "email": requester_email
            }
        }
    }

    # Add external_id if provided (for deduplication)
    if external_id:
        ticket_data["ticket"]["external_id"] = external_id

    # Prepare headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_token}"
    }

    try:
        # Make the API request
        response = requests.post(
            zendesk_url,
            json=ticket_data,
            headers=headers,
            timeout=30
        )

        # Check if request was successful
        if not response.ok:
            error_message = f"Zendesk API error: {response.status_code} - {response.text}"
            logger.error(error_message)
            raise ZendeskError(error_message)

        # Return the created ticket data
        ticket_response = response.json()
        ticket_id = ticket_response.get('ticket', {}).get('id')
        logger.info(f"Successfully created Zendesk ticket: {ticket_id}")

        # Add constructed URLs to the response
        if ticket_id:
            ticket_response['ticket']['url'] = get_zendesk_ticket_url(ticket_id)
            ticket_response['ticket']['web_url'] = get_zendesk_ticket_web_url(ticket_id)

        return ticket_response

    except requests.RequestException as e:
        error_message = f"Failed to create Zendesk ticket: {str(e)}"
        logger.error(error_message)
        raise ZendeskError(error_message) from e


def create_sus_report_ticket(
    player_id: str,
    reporter: str,
    reason: str,
    details: str,
    external_id: Optional[str] = None
) -> dict:
    """
    Create a SUS report ticket in Zendesk.

    This is a convenience function specifically for creating SUS player reports.

    Args:
        player_id: The ID of the player being reported
        reporter: The username/ID of the person reporting
        reason: The reason for the report
        details: Additional details about the report
        external_id: Optional external ID for deduplication (auto-generated if not provided)

    Returns:
        dict: The created ticket data from Zendesk API

    Raises:
        ZendeskError: If the ticket creation fails
        ValueError: If ZENDESK_AUTH_TOKEN is not set
    """
    import time

    # Generate external_id if not provided (for deduplication)
    if not external_id:
        timestamp = int(time.time() * 1000)  # milliseconds
        external_id = f"sus_report_{timestamp}_{player_id}"

    subject = f"[SUS REPORT] Player {player_id}"
    body = (
        f"New SUS report submitted:\n\n"
        f"Player ID: {player_id}\n"
        f"Reported by: {reporter}\n"
        f"Reason: {reason}\n"
        f"Details: {details}"
    )

    return create_zendesk_ticket(
        subject=subject,
        body=body,
        priority="normal",
        tags=["sus_report", "no_merge"],
        requester_name="Tower.lol",
        requester_email="bot@tower.lol",
        external_id=external_id
    )
