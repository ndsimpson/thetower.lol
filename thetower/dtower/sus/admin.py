import logging
import os

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from simple_history.admin import SimpleHistoryAdmin
from tqdm import tqdm


from dtower.sus.models import KnownPlayer, PlayerId, SusPerson
from .models import ApiKey

# Admin for ApiKey
from django.contrib import messages

from django.utils.translation import gettext_lazy as _


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
    def _link(self, obj):
        return format_html(f"<a href='https://{BASE_HIDDEN_URL}/player?player={obj.player_id}' target='_new'>https://{BASE_HIDDEN_URL}/player?player={obj.player_id}</a>")

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
        "notes",
    )

    def _created(self, obj):
        return mark_safe(obj.created.strftime("%Y-%m-%d<br>%H:%M:%S"))

    def _modified(self, obj):
        return mark_safe(obj.modified.strftime("%Y-%m-%d<br>%H:%M:%S"))

    def save_model(self, request, obj, form, change):
        player_id = obj.player_id

        # Check if sus or shun status changed (only these affect tournament positions)
        should_recalc = False
        if change:
            # Get the original object to compare values
            try:
                original = SusPerson.objects.get(pk=obj.pk)
                should_recalc = (original.sus != obj.sus or original.shun != obj.shun)
            except SusPerson.DoesNotExist:
                # Shouldn't happen in change mode, but be safe
                should_recalc = True
        else:
            # New object - always recalculate if sus or shun is True
            should_recalc = (obj.sus or obj.shun)

        obj = super().save_model(request, obj, form, change)

        # Only queue tournaments for recalculation if sus/shun status changed
        if should_recalc:
            queue_recalculation_for_player(player_id)
        return obj


def queue_recalculation_for_player(player_id):
    """Mark all tournaments involving this player for recalculation"""
    from dtower.tourney_results.models import TourneyResult

    # Mark affected tournaments as needing recalculation - FAST operation
    affected_count = TourneyResult.objects.filter(
        rows__player_id=player_id
    ).update(
        needs_recalc=True,
        recalc_retry_count=0  # Reset retry count
    )

    logging.info(f"Queued {affected_count} tournaments for recalculation (player: {player_id})")


def recalc_all(player_id):
    """Legacy function - kept for backwards compatibility but not used"""
    from dtower.tourney_results.models import TourneyResult, TourneyRow
    from dtower.tourney_results.tourney_utils import reposition

    all_results = TourneyResult.objects.filter(id__in=TourneyRow.objects.filter(player_id=player_id).values_list("result", flat=True))

    for res in tqdm(all_results):
        reposition(res)

    logging.info(f"Updated {player_id=}")


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
