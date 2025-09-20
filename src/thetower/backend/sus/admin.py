import os

# Admin for ApiKey
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import path
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from simple_history.admin import SimpleHistoryAdmin

from ..sus.models import KnownPlayer, ModerationRecord, PlayerId, SusPerson

# Import custom User admin
from . import user_admin  # noqa: F401 - This registers the custom User admin
from .models import ApiKey


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("user", "key_suffix", "created_at", "last_used_at", "active", "invalidated_at")
    list_filter = ("active", "created_at", "invalidated_at")
    search_fields = ("user__username", "key")
    readonly_fields = ("key_suffix", "created_at", "last_used_at", "invalidated_at")

    def key_suffix(self, obj):
        return f"…{obj.key_suffix()}" if obj.key else ""

    key_suffix.short_description = "Key Suffix"

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields

    def get_fields(self, request, obj=None):
        return ["user", "active", "key_suffix", "created_at", "last_used_at", "invalidated_at"]

    def save_model(self, request, obj, form, change):
        # Prevent reactivation if invalidated_at is set
        if obj.invalidated_at and obj.active:
            messages.add_message(request, messages.ERROR, _("Cannot reactivate an invalidated API key."))
            obj.active = False
        super().save_model(request, obj, form, change)
        if not change:
            # Show the key only at creation
            messages.add_message(request, messages.INFO, _(f"API Key created: {obj.key} (save this now; it will not be shown again)."))


BASE_HIDDEN_URL = os.getenv("BASE_HIDDEN_URL")


@admin.register(SusPerson)
class SusPersonAdmin(SimpleHistoryAdmin):
    """
    READ-ONLY admin for legacy SusPerson model.
    This model is deprecated - use ModerationRecord instead.
    """
    change_form_template = "admin/sus/susperson/change_form.html"

    def get_urls(self):
        # READ-ONLY: Remove requeue functionality since this model is deprecated
        return super().get_urls()

    def _link(self, obj):
        return format_html(
            f"<a href='https://{BASE_HIDDEN_URL}/player?player={obj.player_id}' target='_new'>https://{BASE_HIDDEN_URL}/player?player={obj.player_id}</a>"
        )

    _link.short_description = "link"

    list_display = (
        "_created",
        "player_id",
        "name",
        "notes",
        "shun",
        "sus",
        "soft_banned",
        "banned",
        "api_ban",
        "api_sus",
        "_link",
        "_modified",
    )

    list_editable = ()  # READ-ONLY: No inline editing allowed

    search_fields = (
        "player_id",
        "name",
        "notes",
    )

    list_filter = (
        "shun",
        "sus",
        "soft_banned",
        "banned",
        "api_ban",
        "api_sus",
        "notes",
    )

    def _created(self, obj):
        return mark_safe(obj.created.strftime("%Y-%m-%d<br>%H:%M:%S"))

    def _modified(self, obj):
        return mark_safe(obj.modified.strftime("%Y-%m-%d<br>%H:%M:%S"))

    def get_readonly_fields(self, request, obj=None):
        # READ-ONLY: Make all fields readonly - this model is deprecated
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        # READ-ONLY: Prevent adding new SusPerson records
        return False

    def has_delete_permission(self, request, obj=None):
        # READ-ONLY: Prevent deleting SusPerson records (preserve for reference)
        return False

    def has_change_permission(self, request, obj=None):
        # Allow viewing but not changing
        return True

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['deprecation_message'] = (
            "⚠️ SusPerson model is deprecated and read-only. "
            "For new moderation actions, please use the ModerationRecord admin."
        )
        return super().changelist_view(request, extra_context)

    def save_model(self, request, obj, form, change):
        # READ-ONLY: Prevent saving - this model is deprecated
        messages.error(request, "SusPerson model is read-only. Please use ModerationRecord instead.")
        return


def queue_recalculation_for_player(player_id):
    """Mark all tournaments involving this player for recalculation"""
    from ..tourney_results.models import TourneyResult

    # Testing switch: set FORCE_QUEUE_FAIL=1 in the environment to simulate a failure
    # (useful to exercise admin warning UI without breaking production logic)
    if os.environ.get("FORCE_QUEUE_FAIL") == "1":
        return None

    try:
        # Mark affected tournaments as needing recalculation - FAST operation
        affected_count = TourneyResult.objects.filter(rows__player_id=player_id).update(needs_recalc=True, recalc_retry_count=0)  # Reset retry count
        return affected_count
    except Exception:
        # Swallow exceptions - recalculation queuing should not block admin save
        return None


def queue_recalculation_for_selected(modeladmin, request, queryset):
    """Admin action: queue recalculation for selected SusPerson entries"""
    count = 0
    failed = []
    for obj in queryset:
        res = queue_recalculation_for_player(obj.player_id)
        if res is None:
            failed.append(obj.player_id)
        else:
            count += 1

    if count:
        messages.info(request, _("Queued recalculation for %d players.") % count)
    if failed:
        messages.warning(request, _("Failed to queue for: %s") % ", ".join(failed))


# Register the action so it appears in the Django admin actions dropdown
# REMOVED: SusPersonAdmin.actions - model is now read-only
queue_recalculation_for_selected.short_description = "Queue recalculation for selected players"


class IdInline(admin.TabularInline):
    model = PlayerId
    verbose_name = "The Tower Player ID"
    verbose_name_plural = "The Tower Player IDs"


@admin.register(KnownPlayer)
class KnownPlayerAdmin(SimpleHistoryAdmin):
    def _ids(self, obj):
        id_data = obj.ids.all().values_list("id", "primary")

        info = ""

        for id_, primary in id_data:
            primary_string = " primary" if primary else ""
            info += f"{id_}{primary_string}<br>"

        return mark_safe(info)

    _ids.short_description = "Ids"

    list_display = ("name", "approved", "discord_id", "creator_code", "_ids")
    list_editable = ("approved", "creator_code")
    search_fields = ("name", "discord_id", "creator_code", "ids__id")
    inlines = (IdInline,)


@admin.register(ModerationRecord)
class ModerationRecordAdmin(SimpleHistoryAdmin):
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("<path:object_id>/requeue/", self.admin_site.admin_view(self.requeue_view), name="sus_moderationrecord_requeue"),
        ]
        return custom_urls + urls

    def requeue_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj is None:
            self.message_user(request, _("Object not found."), level=messages.ERROR)
            return redirect("..")

        res = queue_recalculation_for_player(obj.tower_id)
        if res is None:
            messages.warning(request, _(f"Failed to queue recalculation for player {obj.tower_id}; please try the action on the list view."))
        else:
            messages.success(request, _(f"Queued recalculation for player {obj.tower_id} ({res} tournaments)."))

        return redirect("..")

    def _known_player_display(self, obj):
        if obj.known_player:
            return f"{obj.known_player.name} (ID: {obj.known_player.id})"
        return "Unverified Player"

    _known_player_display.short_description = "Known Player"

    def _created_by_display(self, obj):
        return obj.created_by_display

    _created_by_display.short_description = "Created By"

    def _resolved_by_display(self, obj):
        return obj.resolved_by_display

    _resolved_by_display.short_description = "Resolved By"

    def _status_display(self, obj):
        return "Active" if obj.is_active else "Resolved"

    _status_display.short_description = "Status"

    def _notes_display(self, obj):
        return obj.reason or "-"

    _notes_display.short_description = "Notes"

    list_display = (
        "tower_id",
        "_known_player_display",
        "moderation_type",
        "_status_display",
        "source",
        "created_at",
        "_created_by_display",
        "resolved_at",
        "_resolved_by_display",
    )

    list_filter = (
        "moderation_type",
        "source",
        "created_at",
        "resolved_at",
    )

    search_fields = (
        "tower_id",
        "known_player__name",
        "known_player__discord_id",
        "reason",
        "resolution_note",
    )

    readonly_fields = (
        "created_at",
        "known_player",  # Auto-linked, not directly editable
        "_created_by_display",  # Read-only combo field
        "_resolved_by_display",  # Read-only combo field
        "created_by_discord_id",  # Only set by bot
        "created_by_api_key",  # Only set by API
        "resolved_by_discord_id",  # Only set by bot
        "resolved_by_api_key",  # Only set by API
    )

    fieldsets = (
        ("Moderation Details", {
            "fields": ("tower_id", "known_player", "moderation_type", "source", "created_at", "_created_by_display", "resolved_at", "_resolved_by_display", "reason"),
            "description": "Enter the Tower ID. If this player is verified (has a Discord account), they will be auto-linked."
        }),
        ("Audit Trail", {
            "fields": (
                "created_by", "created_by_discord_id", "created_by_api_key",
                "resolved_by", "resolved_by_discord_id", "resolved_by_api_key"
            ),
            "classes": ("collapse",)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("known_player", "created_by", "resolved_by")

    def get_readonly_fields(self, request, obj=None):
        # Base readonly fields that are always readonly
        readonly = list(self.readonly_fields)

        # For non-superusers, make audit trail fields readonly
        if not request.user.is_superuser:
            audit_fields = [
                "created_by", "created_by_discord_id", "created_by_api_key",
                "resolved_by", "resolved_by_discord_id", "resolved_by_api_key"
            ]
            readonly.extend(audit_fields)

        return readonly

    def has_delete_permission(self, request, obj=None):
        # Restrict delete permissions - moderation records should be resolved, not deleted
        return request.user.is_superuser  # Only superusers can delete

    def delete_model(self, request, obj):
        # Trigger recalc before deletion if this was an active record affecting tournaments
        if obj.moderation_type in ['sus', 'shun', 'ban'] and obj.resolved_at is None:
            affected = queue_recalculation_for_player(obj.tower_id)
            if affected:
                messages.info(request, f"Triggered tournament recalculation before deleting record for {obj.tower_id}")

        super().delete_model(request, obj)

    def save_model(self, request, obj, form, change):
        # Store original state for comparison
        original_affects_tournaments = False
        if change and obj.pk:
            try:
                original = ModerationRecord.objects.get(pk=obj.pk)
                # Check if the original record affected tournaments (sus/shun/ban)
                original_affects_tournaments = (
                    original.moderation_type in ['sus', 'shun', 'ban'] and
                    original.resolved_at is None
                )
            except ModerationRecord.DoesNotExist:
                pass

        if not change:  # New object
            obj.created_by = request.user

            # Auto-link to KnownPlayer if one exists for this tower_id
            if obj.tower_id:
                try:
                    # Look for a KnownPlayer who has this tower_id
                    player_id_obj = PlayerId.objects.select_related('player').get(id=obj.tower_id)
                    obj.known_player = player_id_obj.player
                except PlayerId.DoesNotExist:
                    # No KnownPlayer has this tower_id - leave as unverified
                    obj.known_player = None

        super().save_model(request, obj, form, change)

        # Check if we need to trigger tournament recalculation
        # Sus, shun, and ban moderation types affect tournament positions
        current_affects_tournaments = (
            obj.moderation_type in ['sus', 'shun', 'ban'] and
            obj.resolved_at is None  # Active moderation
        )

        # Trigger recalc if:
        # 1. New active sus/shun/ban record, OR
        # 2. Existing record changed from affecting tournaments to not affecting (resolved), OR
        # 3. Existing record changed from not affecting to affecting (reactivated)
        should_recalc = (
            (not change and current_affects_tournaments) or  # New active sus/shun
            (change and original_affects_tournaments != current_affects_tournaments)  # Status change
        )

        if should_recalc:
            affected = queue_recalculation_for_player(obj.tower_id)
            if affected is None:
                messages.warning(request, _(f"Failed to queue recalculation for player {obj.tower_id}; please requeue manually."))
            else:
                messages.info(request, _(f"Queued tournament recalculation for {affected} tournaments involving player {obj.tower_id}."))


def queue_recalculation_for_moderation_records(modeladmin, request, queryset):
    """Admin action: queue recalculation for selected ModerationRecord entries"""
    count = 0
    failed = []
    processed_players = set()  # Avoid duplicate processing for same player

    for obj in queryset:
        # Only process each player once, even if multiple records selected
        if obj.tower_id in processed_players:
            continue
        processed_players.add(obj.tower_id)

        res = queue_recalculation_for_player(obj.tower_id)
        if res is None:
            failed.append(obj.tower_id)
        else:
            count += 1

    if count:
        messages.info(request, _("Queued recalculation for %d players.") % count)
    if failed:
        messages.warning(request, _("Failed to queue for: %s") % ", ".join(failed))


def resolve_moderation_records(modeladmin, request, queryset):
    """Admin action: resolve selected active ModerationRecord entries"""
    from django.utils import timezone

    resolved_count = 0
    already_resolved = 0
    players_to_recalc = set()

    for obj in queryset:
        if obj.resolved_at is None:  # Only resolve active records
            # Check if this record affects tournaments before resolving
            if obj.moderation_type in ['sus', 'shun', 'ban']:
                players_to_recalc.add(obj.tower_id)

            obj.resolved_at = timezone.now()
            obj.resolved_by = request.user
            obj.save()
            resolved_count += 1
        else:
            already_resolved += 1

    # Trigger recalculation for affected players
    recalc_success = 0
    recalc_failed = []
    for player_id in players_to_recalc:
        res = queue_recalculation_for_player(player_id)
        if res is None:
            recalc_failed.append(player_id)
        else:
            recalc_success += 1

    # User feedback
    if resolved_count:
        messages.success(request, _("Resolved %d moderation records.") % resolved_count)
    if already_resolved:
        messages.info(request, _("%d records were already resolved.") % already_resolved)
    if recalc_success:
        messages.info(request, _("Triggered tournament recalculation for %d players.") % recalc_success)
    if recalc_failed:
        messages.warning(request, _("Failed to queue recalculation for: %s") % ", ".join(recalc_failed))


# Register the actions for ModerationRecord admin
ModerationRecordAdmin.actions = [queue_recalculation_for_moderation_records, resolve_moderation_records]
queue_recalculation_for_moderation_records.short_description = "Queue tournament recalculation for selected players"
resolve_moderation_records.short_description = "Resolve selected moderation records"
