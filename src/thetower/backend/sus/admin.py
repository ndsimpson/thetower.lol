import os

# Admin for ApiKey
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import path
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from simple_history.admin import SimpleHistoryAdmin

from ..sus.models import KnownPlayer, PlayerId, SusPerson

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
    change_form_template = "admin/sus/susperson/change_form.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("<path:object_id>/requeue/", self.admin_site.admin_view(self.requeue_view), name="sus_susperson_requeue"),
        ]
        return custom_urls + urls

    def requeue_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj is None:
            self.message_user(request, _("Object not found."), level=messages.ERROR)
            return redirect("..")

        res = queue_recalculation_for_player(obj.player_id)
        if res is None:
            messages.warning(request, _(f"Failed to queue recalculation for player {obj.player_id}; please try the action on the list view."))
        else:
            messages.success(request, _(f"Queued recalculation for player {obj.player_id}."))

        return redirect("..")

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

    list_editable = (
        "name",
        "notes",
        "shun",
        "sus",
        "soft_banned",
        "banned",
    )

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
        # If this object was flagged by the API, prevent editing the canonical fields from the admin UI
        ro = list(getattr(self, 'readonly_fields', []))
        if obj is not None:
            if getattr(obj, "api_ban", False):
                ro.append("banned")
            if getattr(obj, "api_sus", False):
                ro.append("sus")
            # Always make api_ban and api_sus readonly (only API should change these)
            ro.extend(["api_ban", "api_sus"])
        return ro

    def save_model(self, request, obj, form, change):
        player_id = obj.player_id

        # debug logging removed

        # Check if sus or shun status changed (only these affect tournament positions)
        should_recalc = False
        if change:
            # Get the original object to compare values
            try:
                original = SusPerson.objects.get(pk=obj.pk)
                should_recalc = original.sus != obj.sus or original.shun != obj.shun
            except SusPerson.DoesNotExist:
                # Shouldn't happen in change mode, but be safe
                should_recalc = True
        else:
            # New object - always recalculate if sus or shun is True
            should_recalc = obj.sus or obj.shun

        try:
            obj = super().save_model(request, obj, form, change)
        except Exception:
            # Re-raise so admin shows the 500 as before
            raise

        # Only queue tournaments for recalculation if sus/shun status changed
        if should_recalc:
            affected = queue_recalculation_for_player(player_id)
            # queue_recalculation_for_player returns None on failure
            if affected is None:
                messages.warning(request, _(f"Failed to queue recalculation for player {player_id}; please requeue manually."))

        return obj


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
SusPersonAdmin.actions = [queue_recalculation_for_selected]
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
