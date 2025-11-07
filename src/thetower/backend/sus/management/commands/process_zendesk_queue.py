"""
Management command to process Zendesk ticket creation queue.

This worker continuously processes moderation records that need Zendesk tickets
created in the background, preventing admin interface blocking.

Usage:
    python manage.py process_zendesk_queue [--max-retries 3] [--delay 0.5]
"""

import logging
import time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

# Import Zendesk utilities from backend module
from thetower.backend.zendesk_utils import ZendeskError, create_sus_report_ticket

from ...models import ModerationRecord

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process Zendesk ticket creation queue"

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-retries",
            type=int,
            default=3,
            help="Maximum number of retry attempts (default: 3)"
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=0.5,
            help="Delay between processing attempts in seconds (default: 0.5)"
        )
        parser.add_argument(
            "--one-shot",
            action="store_true",
            help="Process queue once and exit (useful for testing)"
        )

    def handle(self, *args, **options):
        max_retries = options["max_retries"]
        delay = options["delay"]
        one_shot = options["one_shot"]

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting Zendesk ticket creation worker "
                f"(max_retries={max_retries}, delay={delay}s)"
            )
        )

        if one_shot:
            self.stdout.write("Running in one-shot mode")
            processed = self.process_next_record(max_retries)
            if processed:
                self.stdout.write(self.style.SUCCESS("Processed 1 moderation record"))
            else:
                self.stdout.write("No moderation records to process")
            return

        # Continuous processing
        while True:
            try:
                processed = self.process_next_record(max_retries)
                if not processed:
                    time.sleep(delay)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("\nShutting down worker..."))
                break
            except Exception as e:
                logger.error(f"Worker error: {e}")
                self.stdout.write(self.style.ERROR(f"Worker error: {e}"))
                time.sleep(5)  # Wait before retrying after error

    def process_next_record(self, max_retries):
        """
        Process the next moderation record in the queue.

        Returns:
            bool: True if a record was processed, False if queue is empty
        """
        with transaction.atomic():
            # Get next record needing Zendesk ticket with pessimistic lock
            # Prioritize by: 1) Moderation type severity, 2) Newest first
            record = (
                ModerationRecord.objects.select_for_update()
                .filter(
                    needs_zendesk_ticket=True,
                    zendesk_ticket_id__isnull=True,
                    zendesk_retry_count__lt=max_retries
                )
                .extra(
                    select={
                        "type_priority": """
                        CASE moderation_type
                            WHEN 'ban' THEN 1
                            WHEN 'soft_ban' THEN 2
                            WHEN 'sus' THEN 3
                            WHEN 'shun' THEN 4
                            ELSE 5
                        END
                    """
                    }
                )
                .order_by("type_priority", "-created_at")
                .first()
            )

            if not record:
                return False

            # Mark as processing (prevent other workers from picking it up)
            record.needs_zendesk_ticket = False
            record.zendesk_last_attempt = timezone.now()
            record.save()

        # Process outside the lock transaction
        try:
            self.stdout.write(
                f"Processing moderation record {record.id} "
                f"({record.get_moderation_type_display()} - {record.tower_id})"
            )

            # Determine reporter based on source
            if record.created_by:
                reporter = f"Admin: {record.created_by.username}"
            elif record.created_by_discord_id:
                reporter = f"Discord: {record.created_by_discord_id}"
            elif record.created_by_api_key:
                reporter = f"API: {record.created_by_api_key.user.username}"
            else:
                reporter = "System"

            # Create the Zendesk ticket
            ticket_response = create_sus_report_ticket(
                player_id=record.tower_id,
                reporter=reporter,
                reason=record.get_moderation_type_display(),
                details=record.reason or "No additional details provided"
            )

            # Extract ticket ID
            ticket_id = ticket_response.get('ticket', {}).get('id')

            # Mark successful completion
            with transaction.atomic():
                record.zendesk_ticket_id = ticket_id
                record.zendesk_retry_count = 0
                record.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"[SUCCESS] Completed moderation record {record.id}: "
                    f"Zendesk ticket {ticket_id} created"
                )
            )
            logger.info(
                f"Created Zendesk ticket {ticket_id} for moderation record {record.id}"
            )
            return True

        except (ZendeskError, ValueError) as e:
            # Handle failure - mark for retry
            with transaction.atomic():
                record.needs_zendesk_ticket = True
                record.zendesk_retry_count += 1
                record.save()

            self.stdout.write(
                self.style.ERROR(
                    f"[FAILED] Failed to create Zendesk ticket for record {record.id} "
                    f"(attempt {record.zendesk_retry_count}/{max_retries}): {e}"
                )
            )
            logger.error(
                f"Failed to create Zendesk ticket for record {record.id}: {e}"
            )

            if record.zendesk_retry_count >= max_retries:
                self.stdout.write(
                    self.style.WARNING(
                        f"Record {record.id} exceeded max retries "
                        f"and will not be retried automatically"
                    )
                )

            return True  # We did process something, even if it failed

        except Exception as e:
            # Unexpected error - mark for retry
            with transaction.atomic():
                record.needs_zendesk_ticket = True
                record.zendesk_retry_count += 1
                record.save()

            self.stdout.write(
                self.style.ERROR(
                    f"[UNEXPECTED] Unexpected error for record {record.id}: {e}"
                )
            )
            logger.error(f"Unexpected error for record {record.id}: {e}", exc_info=True)
            return True
