import datetime
import secrets

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q
from django.utils import timezone
from simple_history.models import HistoricalRecords


class ApiKey(models.Model):
    user = models.ForeignKey("auth.User", on_delete=models.CASCADE, related_name="api_keys")
    key = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = self.generate_key()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_key():
        return secrets.token_urlsafe(48)

    def invalidate(self):
        self.active = False
        self.invalidated_at = timezone.now()
        self.save()

    def key_suffix(self):
        return self.key[-8:] if self.key else ""

    def __str__(self):
        return f"API Key for {self.user.username} (…{self.key_suffix()})"


class KnownPlayer(models.Model):
    name = models.CharField(max_length=100, blank=True, null=True, help_text="Player's friendly name, e.g. common discord handle")
    discord_id = models.CharField(max_length=50, blank=True, null=True, help_text="Discord numeric id")
    creator_code = models.CharField(max_length=50, blank=True, null=True, help_text="Creator/supporter code to promote in shop")
    approved = models.BooleanField(blank=False, null=False, default=True, help_text="Has this entry been validated?")

    def __str__(self):
        return f"{self.name} ({self.ids.filter(primary=True).first().id if self.ids.filter(primary=True).first() else ''})"

    def save(self, *args, **kwargs):
        self.nname = self.name.strip()
        super().save(*args, **kwargs)

    history = HistoricalRecords()


class PlayerId(models.Model):
    id = models.CharField(max_length=32, primary_key=True, help_text="Player id from The Tower, pk")
    player = models.ForeignKey(KnownPlayer, null=False, blank=False, related_name="ids", on_delete=models.CASCADE, help_text="Player")
    primary = models.BooleanField(default=False)
    notes = models.TextField(null=True, blank=True, max_length=1000, help_text="Documentation about this Tower ID (e.g., ID change notes)")

    def __str__(self):
        return f"{self.id}"

    def save_base(self, *args, force_insert=False, **kwargs):
        if force_insert and self.primary:
            self.player.ids.filter(~Q(id=self.id), primary=True).update(primary=False)

        return super().save_base(*args, **kwargs)

    history = HistoricalRecords()


class ModerationRecord(models.Model):
    """
    New unified moderation system.
    - For verified players: links to KnownPlayer AND stores tower_id
    - For unverified players: stores only tower_id (known_player=null)
    - Auto-linking: when unverified player links Discord, existing moderation follows
    """

    # Moderation Types
    class ModerationType(models.TextChoices):
        SUS = 'sus', 'Suspicious'
        BAN = 'ban', 'Banned'
        SHUN = 'shun', 'Shunned (Discord)'
        SOFT_BAN = 'soft_ban', 'Soft Banned'

    # Moderation Sources
    class ModerationSource(models.TextChoices):
        MANUAL = 'manual', 'Manual (Admin)'
        API = 'api', 'API'
        BOT = 'bot', 'Discord Bot'
        AUTOMATED = 'automated', 'Automated System'

    # Moderation Status
    class ModerationStatus(models.TextChoices):
        ACTIVE = 'active', 'Active'
        RESOLVED = 'resolved', 'Resolved'
        SUPERSEDED = 'superseded', 'Superseded'

    # Core identification - hybrid linking approach
    known_player = models.ForeignKey(
        KnownPlayer,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="moderation_records",
        help_text="Linked KnownPlayer (null for unverified players)"
    )
    tower_id = models.CharField(
        max_length=32,
        db_index=True,
        help_text="Tower ID being moderated (always stored regardless of verification status)"
    )

    # Moderation details
    moderation_type = models.CharField(
        max_length=20,
        choices=ModerationType.choices,
        help_text="Type of moderation action"
    )
    source = models.CharField(
        max_length=20,
        choices=ModerationSource.choices,
        default=ModerationSource.MANUAL,
        help_text="Source of the moderation action"
    )
    status = models.CharField(
        max_length=20,
        choices=ModerationStatus.choices,
        default=ModerationStatus.ACTIVE,
        help_text="Current status of this moderation action"
    )

    # Audit trail - dual attribution system
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # Admin interface attribution
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_moderation_records",
        help_text="Django admin user who created this moderation record"
    )

    # Bot/Discord attribution
    created_by_discord_id = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="Discord ID of user who created this record via bot command"
    )

    # API attribution
    created_by_api_key = models.ForeignKey(
        ApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_moderation_records",
        help_text="API key used to create this record"
    )

    # Resolution audit trail
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this moderation was resolved"
    )

    # Admin interface resolution
    resolved_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_moderation_records",
        help_text="Django admin user who resolved this moderation record"
    )

    # Bot/Discord resolution
    resolved_by_discord_id = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="Discord ID of user who resolved this record via bot command"
    )

    # API resolution
    resolved_by_api_key = models.ForeignKey(
        ApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_moderation_records",
        help_text="API key used to resolve this record"
    )

    # Notes and context
    reason = models.TextField(
        null=True,
        blank=True,
        max_length=1000,
        help_text="Reason for this moderation action"
    )
    resolution_note = models.TextField(
        null=True,
        blank=True,
        max_length=1000,
        help_text="Note explaining the resolution"
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # Fast tower_id lookups for tournament filtering
            models.Index(fields=['tower_id', 'status']),
            models.Index(fields=['tower_id', 'moderation_type', 'status']),
            # Known player lookups
            models.Index(fields=['known_player', 'status']),
            # Source and type filtering
            models.Index(fields=['source', 'moderation_type']),
            # Time-based queries
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        player_info = f"{self.known_player.name}" if self.known_player else f"Tower ID {self.tower_id}"
        return f"{self.get_moderation_type_display()} - {player_info} ({self.get_status_display()})"

    def resolve(self, resolved_by_user=None, resolved_by_discord_id=None, resolved_by_api_key=None, resolution_note=None):
        """Mark this moderation record as resolved"""
        self.status = self.ModerationStatus.RESOLVED
        self.resolved_at = timezone.now()
        self.resolved_by = resolved_by_user
        self.resolved_by_discord_id = resolved_by_discord_id
        self.resolved_by_api_key = resolved_by_api_key
        if resolution_note:
            self.resolution_note = resolution_note
        self.save()

    @property
    def created_by_display(self):
        """Human-readable string showing who created this record"""
        if self.created_by:
            return f"Admin: {self.created_by.username}"
        elif self.created_by_discord_id:
            return f"Discord: {self.created_by_discord_id}"
        elif self.created_by_api_key:
            return f"API: {self.created_by_api_key.user.username} (…{self.created_by_api_key.key_suffix()})"
        return "System"

    @property
    def resolved_by_display(self):
        """Human-readable string showing who resolved this record"""
        if not self.resolved_at:
            return "-"
        if self.resolved_by:
            return f"Admin: {self.resolved_by.username}"
        elif self.resolved_by_discord_id:
            return f"Discord: {self.resolved_by_discord_id}"
        elif self.resolved_by_api_key:
            return f"API: {self.resolved_by_api_key.user.username} (…{self.resolved_by_api_key.key_suffix()})"
        return "System"

    @classmethod
    def create_for_admin(cls, tower_id, moderation_type, admin_user, reason=None, **kwargs):
        """Create a moderation record from admin interface"""
        return cls.objects.create(
            tower_id=tower_id,
            moderation_type=moderation_type,
            source=cls.ModerationSource.MANUAL,
            created_by=admin_user,
            reason=reason,
            **kwargs
        )

    @classmethod
    def create_for_bot(cls, tower_id, moderation_type, discord_id, reason=None, **kwargs):
        """Create a moderation record from Discord bot"""
        return cls.objects.create(
            tower_id=tower_id,
            moderation_type=moderation_type,
            source=cls.ModerationSource.BOT,
            created_by_discord_id=discord_id,
            reason=reason,
            **kwargs
        )

    @classmethod
    def create_for_api(cls, tower_id, moderation_type, api_key, reason=None, **kwargs):
        """Create a moderation record from API"""
        return cls.objects.create(
            tower_id=tower_id,
            moderation_type=moderation_type,
            source=cls.ModerationSource.API,
            created_by_api_key=api_key,
            reason=reason,
            **kwargs
        )

    @classmethod
    def get_active_moderation_ids(cls, moderation_type):
        """Get tower_ids with active moderation of specified type"""
        return set(cls.objects.filter(
            moderation_type=moderation_type,
            status=cls.ModerationStatus.ACTIVE
        ).values_list('tower_id', flat=True))

    history = HistoricalRecords()


class SusPerson(models.Model):
    player_id = models.CharField(max_length=32, primary_key=True, help_text="Player id from The Tower, pk")
    name = models.CharField(max_length=100, blank=True, null=True, help_text="Player's friendly name, e.g. common discord handle")
    notes = models.TextField(null=True, blank=True, max_length=1000, help_text="Additional comments")
    shun = models.BooleanField(
        null=False,
        blank=False,
        default=False,
        help_text="Are they shunned from the Discord? If checked, user won't appear in leaderboards or earn tourney roles.",
    )
    sus = models.BooleanField(
        null=False, blank=False, default=True, help_text="Is the person sus? If checked, they will be removed from the results on the public website."
    )
    soft_banned = models.BooleanField(null=False, blank=False, default=False, help_text="Soft-banned by Pog. For internal use.")
    banned = models.BooleanField(null=False, blank=False, default=False, help_text="Banned by support. For internal use.")
    # Mark whether this ban/sus was set by the API. These are provenance flags only.
    api_ban = models.BooleanField(null=False, blank=False, default=False, help_text="Was the ban set by the API?")
    api_sus = models.BooleanField(null=False, blank=False, default=False, help_text="Was the sus flag set by the API?")

    created = models.DateTimeField(auto_now_add=datetime.datetime.now, null=False, editable=False, db_index=True)
    modified = models.DateTimeField(auto_now=datetime.datetime.now, null=False, editable=False)

    class Meta:
        ordering = ("-modified",)

    history = HistoricalRecords()

    # Transient flag used to allow internal API-driven saves to bypass save-time protections
    _allow_api_save = False

    def mark_banned_by_api(self, api_user, api_key_obj=None, note=None):
        """Set banned and provenance, append note with user and key suffix, and save."""
        from django.utils import timezone

        # Store original sus/shun status for recalculation check
        original_sus = self.sus
        original_shun = self.shun

        self.banned = True
        self.api_ban = True
        # For API bans, explicitly set sus=False (override model default)
        # unless sus was already explicitly set by API
        if not self.api_sus:
            self.sus = False
        ts = timezone.now().astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        suffix = f" (API key …{api_key_obj.key_suffix()})" if api_key_obj else ""
        who = getattr(api_user, "username", str(api_user))
        action_note = f"API BANNED by {who}{suffix} at {ts}"
        if note:
            action_note += f" | {note}"
        self.notes = (self.notes or "") + f"\n{action_note}"
        self._allow_api_save = True
        # Set history user for simple_history tracking
        self._history_user = api_user
        try:
            self.save()
            # Queue recalculation if sus or shun status changed
            if original_sus != self.sus or original_shun != self.shun:
                self._queue_recalculation()
        finally:
            self._allow_api_save = False

    def unban_by_api(self, api_user, api_key_obj=None, note=None):
        """Clear banned and provenance when performed by API; append unban note."""
        from django.utils import timezone

        # Only allow unban via API if api_ban was previously set
        if not self.api_ban:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Cannot unban: ban was not created by the API.")

        # Store original sus/shun status for recalculation check
        original_sus = self.sus
        original_shun = self.shun

        self.banned = False
        self.api_ban = False
        ts = timezone.now().astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        suffix = f" (API key …{api_key_obj.key_suffix()})" if api_key_obj else ""
        who = getattr(api_user, "username", str(api_user))
        action_note = f"API UNBANNED by {who}{suffix} at {ts}"
        if note:
            action_note += f" | {note}"
        self.notes = (self.notes or "") + f"\n{action_note}"
        self._allow_api_save = True
        # Set history user for simple_history tracking
        self._history_user = api_user
        try:
            self.save()
            # Queue recalculation if sus or shun status changed
            if original_sus != self.sus or original_shun != self.shun:
                self._queue_recalculation()
        finally:
            self._allow_api_save = False

    def mark_sus_by_api(self, api_user, api_key_obj=None, note=None):
        from django.utils import timezone

        # Store original sus/shun status for recalculation check
        original_sus = self.sus
        original_shun = self.shun

        self.sus = True
        self.api_sus = True
        ts = timezone.now().astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        suffix = f" (API key …{api_key_obj.key_suffix()})" if api_key_obj else ""
        who = getattr(api_user, "username", str(api_user))
        action_note = f"API SUSSED by {who}{suffix} at {ts}"
        if note:
            action_note += f" | {note}"
        self.notes = (self.notes or "") + f"\n{action_note}"
        self._allow_api_save = True
        # Set history user for simple_history tracking
        self._history_user = api_user
        try:
            self.save()
            # Queue recalculation if sus or shun status changed
            if original_sus != self.sus or original_shun != self.shun:
                self._queue_recalculation()
        finally:
            self._allow_api_save = False

    def unsus_by_api(self, api_user, api_key_obj=None, note=None):
        from django.core.exceptions import PermissionDenied
        from django.utils import timezone

        if not self.api_sus:
            raise PermissionDenied("Cannot unsus: sus was not created by the API.")

        # Store original sus/shun status for recalculation check
        original_sus = self.sus
        original_shun = self.shun

        self.sus = False
        self.api_sus = False
        ts = timezone.now().astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        suffix = f" (API key …{api_key_obj.key_suffix()})" if api_key_obj else ""
        who = getattr(api_user, "username", str(api_user))
        action_note = f"API UNSUSSED by {who}{suffix} at {ts}"
        if note:
            action_note += f" | {note}"
        self.notes = (self.notes or "") + f"\n{action_note}"
        self._allow_api_save = True
        # Set history user for simple_history tracking
        self._history_user = api_user
        try:
            self.save()
            # Queue recalculation if sus or shun status changed
            if original_sus != self.sus or original_shun != self.shun:
                self._queue_recalculation()
        finally:
            self._allow_api_save = False

    def save(self, *args, **kwargs):
        # Prevent manual unsetting of banned/sus when api_ban/api_sus is set.
        if self.pk:
            try:
                original = SusPerson.objects.get(pk=self.pk)
            except SusPerson.DoesNotExist:
                original = None

            if original is not None and not getattr(self, "_allow_api_save", False):
                # If original was api-banned and still marked banned, but new instance clears banned => disallow
                if original.api_ban and original.banned and (not self.banned):
                    from django.core.exceptions import ValidationError

                    raise ValidationError("Cannot manually unban a record created by the API.")
                if original.api_sus and original.sus and (not self.sus):
                    from django.core.exceptions import ValidationError

                    raise ValidationError("Cannot manually unsus a record created by the API.")

        return super().save(*args, **kwargs)

    def _queue_recalculation(self):
        """Queue recalculation for tournaments involving this player."""
        try:
            from ..tourney_results.models import TourneyResult
            TourneyResult.objects.filter(rows__player_id=self.player_id).update(
                needs_recalc=True, recalc_retry_count=0
            )
        except Exception:
            # Swallow exceptions - recalculation queuing should not block API operations
            pass
