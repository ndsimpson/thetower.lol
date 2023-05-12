import subprocess

from django.contrib import admin
from django.utils.safestring import mark_safe
from simple_history.admin import SimpleHistoryAdmin

from dtower.tourney_results.models import Patch, Role, TourneyResult


@admin.action(description="Restart the public app")
def restart_public_app(modeladmin, request, queryset):
    subprocess.call("systemctl restart streamlit2", shell=True)


@admin.action(description="Restart the hidden app instance (thetower.lol:8502)")
def restart_hidden_app(modeladmin, request, queryset):
    subprocess.call("systemctl restart streamlit", shell=True)


@admin.register(TourneyResult)
class TourneyResultAdmin(SimpleHistoryAdmin):
    list_display = (
        "id",
        "league",
        "date",
        "result_file",
        "public",
    )

    search_fields = (
        "id",
        "league",
        "date",
        "result_file",
        "public",
    )

    list_filter = ["date", "league", "public"]

    actions = [restart_public_app, restart_hidden_app]


@admin.register(Patch)
class PatchAdmin(SimpleHistoryAdmin):
    list_display = (
        "version_minor",
        "start_date",
        "end_date",
    )

    search_fields = (
        "version_minor",
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