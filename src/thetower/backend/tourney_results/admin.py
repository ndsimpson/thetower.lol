import logging
import os
import subprocess
import threading

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from simple_history.admin import SimpleHistoryAdmin

from ..sus.models import PlayerId
from .models import BattleCondition, Injection, NameDayWinner, PatchNew, PositionRole, PromptTemplate, RainPeriod, Role, TourneyResult, TourneyRow


class PatchFilter(admin.SimpleListFilter):
    title = 'patch'
    parameter_name = 'patch'

    def lookups(self, request, model_admin):
        """Return a list of tuples for the filter sidebar."""
        patches = PatchNew.objects.all().order_by('-version_minor', '-version_patch')
        return [(patch.pk, str(patch)) for patch in patches]

    def queryset(self, request, queryset):
        """Filter the queryset based on the selected patch."""
        if self.value():
            try:
                patch = PatchNew.objects.get(pk=self.value())
                return queryset.filter(
                    date__gte=patch.start_date,
                    date__lte=patch.end_date
                )
            except PatchNew.DoesNotExist:
                return queryset
        return queryset


BASE_ADMIN_URL = os.getenv("BASE_ADMIN_URL")

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


@admin.action(description="Restart public site (thetower.lol)")
def restart_public_site(modeladmin, request, queryset):
    subprocess.call("systemctl restart tower-public_site", shell=True)


@admin.action(description="Restart hidden site (hidden.thetower.lol)")
def restart_hidden_site(modeladmin, request, queryset):
    subprocess.call("systemctl restart tower-hidden_site", shell=True)


@admin.action(description="Restart admin site (admin.thetower.lol)")
def restart_admin_site(modeladmin, request, queryset):
    subprocess.call("systemctl restart tower-admin_site", shell=True)


@admin.action(description="Restart thetower bot")
def restart_thetower_bot(modeladmin, request, queryset):
    subprocess.call("systemctl restart thetower-bot", shell=True)


@admin.action(description="Restart verification bot")
def restart_verify_bot(modeladmin, request, queryset):
    subprocess.call("systemctl restart validation_bot", shell=True)


@admin.action(description="Restart import results (run me if you don't see TourneyResult objects from previous tourney when it should be there)")
def restart_import_results(modeladmin, request, queryset):
    subprocess.call("systemctl restart import_results", shell=True)


@admin.action(description="Restart get results (run me if import results is failing?)")
def restart_get_results(modeladmin, request, queryset):
    subprocess.call("systemctl restart get_results", shell=True)


@admin.action(description="Publicize")
def publicize(modeladmin, request, queryset):
    for item in queryset:
        item.public = True
        item.save()
        # queryset.update(public=True)


def update_summary(queryset):
    from .tourney_utils import get_summary

    last_date = sorted(queryset.values_list("date", flat=True))[-1]
    summary = get_summary(last_date)
    queryset.update(overview=summary)


@admin.action(description="Generate summary with the help of AI")
def generate_summary(modeladmin, request, queryset):
    thread = threading.Thread(target=update_summary, args=(queryset,))
    thread.start()


@admin.register(TourneyRow)
class TourneyRowAdmin(SimpleHistoryAdmin):
    list_display = (
        "player_id",
        "position",
        "nickname",
        "_known_player",
        "result",
        "wave",
        "avatar_id",
        "relic_id",
    )

    search_fields = (
        "player_id",
        "nickname",
        "wave",
    )

    def _known_player(self, obj):
        player_pk = PlayerId.objects.get(id=obj.player_id).player.id
        return format_html(f"<a href='{BASE_ADMIN_URL}sus/knownplayer/{player_pk}/change/'>{BASE_ADMIN_URL}<br>sus/<br>knownplayer/{player_pk}/change/</a>")

    list_filter = ["result__league", "result__date", "result__public", "avatar_id", "relic_id"]


@admin.register(TourneyResult)
class TourneyResultAdmin(SimpleHistoryAdmin):
    list_display = (
        "id",
        "league",
        "date",
        "_patch",
        "_conditions",
        "needs_recalc",
        "last_recalc_at",
        "recalc_retry_count",
        "result_file",
        "public",
        "_overview",
    )

    search_fields = (
        "id",
        "league",
        "date",
        "result_file",
        "public",
    )

    list_filter = ["needs_recalc", "date", "league", "public", "conditions", PatchFilter]

    def _overview(self, obj):
        return obj.overview[:500] + "..." if obj.overview else ""

    def _conditions(self, obj):
        return mark_safe("<br>".join([str(condition) for condition in obj.conditions.all()]))

    def _patch(self, obj):
        """Display the patch version for this tournament."""
        patch = obj.patch
        return str(patch) if patch else "Unknown"
    _patch.short_description = "Patch"
    _patch.admin_order_field = 'date'  # Allow sorting by date as proxy for patch

    def mark_for_recalc(self, request, queryset):
        """Mark selected tournaments for recalculation"""
        count = queryset.update(needs_recalc=True, recalc_retry_count=0)
        self.message_user(request, f"Marked {count} tournaments for recalculation")
    mark_for_recalc.short_description = "Mark selected tournaments for recalculation"
    _conditions.short_description = "Battle Conditions"

    filter_horizontal = ("conditions",)

    actions = [
        "mark_for_recalc",
        publicize,
        restart_public_site,
        restart_hidden_site,
        restart_admin_site,
        restart_thetower_bot,
        restart_verify_bot,
        restart_import_results,
        restart_get_results,
        generate_summary,
    ]


@admin.register(PatchNew)
class PatchNewAdmin(SimpleHistoryAdmin):
    list_display = (
        "version_minor",
        "version_patch",
        "interim",
        "start_date",
        "end_date",
    )

    search_fields = (
        "version_minor",
        "version_patch",
        "start_date",
        "end_date",
    )


@admin.register(Role)
class RoleAdmin(SimpleHistoryAdmin):
    def _color_preview(self, obj):
        return mark_safe(f"""<div style="width: 120px; height: 40px; background: {obj.color};">&nbsp;</div>""")

    _color_preview.short_description = "Color"

    list_display = (
        "wave_bottom",
        "wave_top",
        "patch",
        "league",
        "_color_preview",
        "color",
    )

    search_fields = (
        "wave_bottom",
        "wave_top",
        "patch",
        "league",
        "color",
    )

    list_filter = ["patch", "wave_bottom", "wave_top", "color", "league"]


@admin.register(PositionRole)
class PositionRoleAdmin(SimpleHistoryAdmin):
    def _color_preview(self, obj):
        return mark_safe(f"""<div style="width: 120px; height: 40px; background: {obj.color};">&nbsp;</div>""")

    _color_preview.short_description = "Color"

    list_display = (
        "position",
        "patch",
        "league",
        "_color_preview",
        "color",
    )

    search_fields = (
        "position",
        "patch",
        "league",
        "color",
    )

    list_filter = ["patch", "position", "color", "league"]


@admin.register(BattleCondition)
class BattleConditionAdmin(SimpleHistoryAdmin):
    list_display = (
        "name",
        "shortcut",
    )

    search_fields = (
        "name",
        "shortcut",
    )


@admin.register(NameDayWinner)
class NameDayWinnerAdmin(SimpleHistoryAdmin):
    list_display = (
        "winner",
        "tourney",
        "winning_nickname",
        "nameday_theme",
    )

    search_fields = (
        "winning_nickname",
        "winner__name",
        "winner__discord_id",
        "nameday_theme",
    )


@admin.register(Injection)
class InjectionAdmin(SimpleHistoryAdmin):
    list_display = (
        "text",
        "user",
    )

    search_fields = (
        "text",
        "user",
    )


@admin.register(PromptTemplate)
class PromptTemplateAdmin(SimpleHistoryAdmin):
    list_display = ("text",)
    search_fields = ("text",)


@admin.register(RainPeriod)
class RainPeriodAdmin(SimpleHistoryAdmin):
    list_display = (
        "emoji",
        "start_date",
        "end_date",
        "enabled",
        "description",
    )

    search_fields = (
        "emoji",
        "description",
    )

    list_filter = ["enabled", "start_date", "end_date"]
