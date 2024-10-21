import logging
import os
import subprocess

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

#from dtower.status.models import Service

BASE_ADMIN_URL = os.getenv("BASE_ADMIN_URL")

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

handler = logging.FileHandler("app.log")
handler.setLevel(logging.DEBUG)

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

logger.addHandler(handler)


@admin.action(description="Restart the public app")
def restart_public_app(modeladmin, request, queryset):
    subprocess.call("systemctl restart streamlit2", shell=True)


@admin.action(description="Restart the hidden app instance (hidden.thetower.lol)")
def restart_hidden_app(modeladmin, request, queryset):
    subprocess.call("systemctl restart streamlit", shell=True)


@admin.action(description="Restart django")
def restart_django(modeladmin, request, queryset):
    subprocess.call("systemctl restart django", shell=True)


@admin.action(description="Restart discord bot")
def restart_discord_bot(modeladmin, request, queryset):
    subprocess.call("systemctl restart discord_bot", shell=True)


@admin.action(description="Restart verification bot")
def restart_verify_bot(modeladmin, request, queryset):
    subprocess.call("systemctl restart validation_bot", shell=True)


#@admin.register(Service)
#class StatusAdmin(SimpleHistoryAdmin):
#    list_display = (
#        "text",
#        "user",
#    )

