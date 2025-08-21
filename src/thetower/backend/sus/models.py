import datetime
import secrets
from django.utils import timezone
from django.db import models
from django.db.models import Q
from simple_history.models import HistoricalRecords


class ApiKey(models.Model):
    user = models.ForeignKey("auth.User", on_delete=models.CASCADE, related_name='api_keys')
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
        return self.key[-8:] if self.key else ''

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

    def __str__(self):
        return f"{self.id}"

    def save_base(self, *args, force_insert=False, **kwargs):
        if force_insert and self.primary:
            self.player.ids.filter(~Q(id=self.id), primary=True).update(primary=False)

        return super().save_base(*args, **kwargs)

    history = HistoricalRecords()


class SusPerson(models.Model):
    player_id = models.CharField(max_length=32, primary_key=True, help_text="Player id from The Tower, pk")
    name = models.CharField(max_length=100, blank=True, null=True, help_text="Player's friendly name, e.g. common discord handle")
    notes = models.TextField(null=True, blank=True, max_length=1000, help_text="Additional comments")
    shun = models.BooleanField(null=False, blank=False, default=False, help_text="Are they shunned from the Discord? If checked, user won't appear in leaderboards or earn tourney roles.")
    sus = models.BooleanField(
        null=False, blank=False, default=True, help_text="Is the person sus? If checked, they will be removed from the results on the public website."
    )
    soft_banned = models.BooleanField(null=False, blank=False, default=False, help_text="Soft-banned by Pog. For internal use.")
    banned = models.BooleanField(null=False, blank=False, default=False, help_text="Banned by support. For internal use.")

    created = models.DateTimeField(auto_now_add=datetime.datetime.now, null=False, editable=False, db_index=True)
    modified = models.DateTimeField(auto_now=datetime.datetime.now, null=False, editable=False)

    class Meta:
        ordering = ("-modified",)

    history = HistoricalRecords()
