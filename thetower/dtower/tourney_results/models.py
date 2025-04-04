from colorfield.fields import ColorField
from django.db import models
from simple_history.models import HistoricalRecords
from django.core.cache import cache
from django.utils import timezone

from dtower.sus.models import KnownPlayer
from dtower.tourney_results.constants import leagues_choices, wave_border_choices


class PatchNew(models.Model):
    class Meta:
        verbose_name_plural = "patches"

    version_minor = models.SmallIntegerField(blank=False, null=False, help_text="The xx in 0.xx version.")
    version_patch = models.SmallIntegerField(blank=False, null=False, help_text="The yy in 0.xx.yy version.", default=0)
    interim = models.BooleanField(blank=False, null=False, default=False, help_text="Maybe it's just an interim version between the patches?")
    start_date = models.DateField(blank=False, null=False, help_text="First tourney when patch was enforced.")
    end_date = models.DateField(blank=False, null=False, help_text="Last tourney when patch was in use.")

    def __str__(self):
        return f"0.{self.version_minor}.{self.version_patch}{'' if not self.interim else ' interim'}"

    def __gt__(self, other):
        if self.version_minor > other.version_minor:
            return True

        if self.version_minor == other.version_minor:
            if self.version_patch > other.version_patch:
                return True

            if self.version_patch == other.version_patch:
                if not self.interim and other.interim:
                    return True

        return False

    def __ge__(self, other):
        if self.version_minor > other.version_minor:
            return True

        if self.version_minor == other.version_minor:
            if self.version_patch > other.version_patch:
                return True

            if self.version_patch == other.version_patch:
                if self.interim:
                    return True

                if not self.interim and not other.interim:
                    return True

        return False


class Role(models.Model):
    wave_bottom = models.SmallIntegerField(blank=False, null=False, choices=[(wave, wave) for wave in wave_border_choices])
    wave_top = models.SmallIntegerField(blank=False, null=False, choices=[(wave, wave) for wave in wave_border_choices])
    patch = models.ForeignKey(
        PatchNew,
        null=True,
        blank=True,
        related_name="roles",
        on_delete=models.CASCADE,
        help_text="Patch related to a given role.",
    )
    league = models.CharField(
        blank=False,
        null=False,
        choices=leagues_choices,
        help_text="Which league are those results from?",
        max_length=16,
    )
    color = ColorField(max_length=255, null=False, blank=False)

    def __str__(self):
        return f"{self.wave_bottom}:{self.wave_top}, {self.patch}, {self.league}"

    def __gt__(self, other):
        try:
            return self.wave_top > other.wave_top
        except (AttributeError, TypeError):
            return True

    def __ge__(self, other):
        try:
            return self.wave_top >= other.wave_top
        except (AttributeError, TypeError):
            return True


class PositionRole(models.Model):
    position = models.IntegerField(blank=False, null=False, help_text="Position in the tourney.")
    patch = models.ForeignKey(
        PatchNew,
        null=True,
        blank=True,
        related_name="position_roles",
        on_delete=models.CASCADE,
        help_text="Patch related to a given role.",
    )
    league = models.CharField(
        blank=False,
        null=False,
        choices=leagues_choices,
        help_text="Which league are those results from?",
        max_length=16,
    )
    color = ColorField(max_length=255, null=False, blank=False)

    def __str__(self):
        return f"Pos={self.position}, {self.patch}, {self.league}"

    def __gt__(self, other):
        try:
            return self.position > other.position
        except (AttributeError, TypeError):
            return True

    def __ge__(self, other):
        try:
            return self.position >= other.position
        except (AttributeError, TypeError):
            return True


class BattleCondition(models.Model):
    name = models.CharField(max_length=64, null=False, blank=False, help_text="Name of the condition.")
    shortcut = models.CharField(max_length=8, null=False, blank=False, help_text="Shortcut of the condition.")

    def __str__(self):
        return f"{self.name} ({self.shortcut})"


class TourneyResult(models.Model):
    result_file = models.FileField(upload_to="uploads/", blank=False, null=False, help_text="CSV file from discord with results.")
    date = models.DateField(blank=False, null=False, help_text="Date of the tournament")
    league = models.CharField(
        blank=False,
        null=False,
        choices=leagues_choices,
        help_text="Which league are those results from?",
        max_length=16,
    )
    public = models.BooleanField(blank=False, null=False, default=False, help_text="Are the results shown to everyone or just to review?")
    conditions = models.ManyToManyField(BattleCondition, related_name="results", help_text="Battle conditions for the tourney.", blank=True)
    overview = models.TextField(null=True, blank=True, help_text="Overview of the tourney.")

    history = HistoricalRecords()

    def __str__(self):
        return f"({self.pk}): {self.league} {self.date.isoformat()}"


class NameDayWinner(models.Model):
    winner = models.ForeignKey(KnownPlayer, null=False, blank=False, related_name="name_day_winners", on_delete=models.CASCADE)
    tourney = models.ForeignKey(TourneyResult, null=False, blank=False, related_name="name_day_winners", on_delete=models.CASCADE)
    winning_nickname = models.CharField(max_length=32, null=False, blank=False, help_text="Tourney name that won that day")
    nameday_theme = models.CharField(max_length=32, null=False, blank=False)


class TourneyRow(models.Model):
    # player = models.ForeignKey(
    #     KnownPlayer, null=False, blank=False, related_name="results", on_delete=models.CASCADE, help_text="Player achieving a given result."
    # )
    player_id = models.CharField(max_length=32, null=False, blank=False, help_text="Player id from The Tower")
    position = models.IntegerField(null=False, blank=False, help_text="Position in a given tourney")
    nickname = models.CharField(max_length=32, null=False, blank=False, help_text="Tourney name")
    wave = models.IntegerField(null=False, blank=False, help_text="Tourney score")
    avatar_id = models.SmallIntegerField(null=True, blank=True, help_text="Avatar id")
    relic_id = models.SmallIntegerField(null=True, blank=True, help_text="Relic id")

    result = models.ForeignKey(TourneyResult, null=False, blank=False, related_name="rows", on_delete=models.CASCADE, help_text="Full results file")

    def __str__(self):
        return f"{self.position} {self.player_id} {self.nickname} {self.wave}"

    def save(self, *args, **kwargs):
        self.nickname = self.nickname.strip()
        super().save(*args, **kwargs)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-result__date", "position"]


class Avatar(models.Model):
    id = models.SmallIntegerField(primary_key=True, help_text="Avatar id from The Tower")
    file_name = models.CharField(max_length=32, null=False, blank=False, help_text="Avatar file name")

    def __str__(self):
        return f"{self.id}: {self.file_name}"


class Relic(models.Model):
    id = models.SmallIntegerField(primary_key=True, help_text="Avatar id from The Tower")
    file_name = models.CharField(max_length=32, null=False, blank=False, help_text="Avatar file name")
    name = models.CharField(max_length=32, null=False, blank=False, help_text="Relic name")
    bonus_amount = models.SmallIntegerField(null=False, blank=False, help_text="Relic bonus amount")
    bonus_type = models.CharField(max_length=16, null=False, blank=False, help_text="Relic bonus type")

    def __str__(self):
        return f"{self.id}: {self.file_name}"


class Injection(models.Model):
    text = models.TextField(null=False, blank=False, max_length=100, help_text="Prompt injection for AI summary")
    user = models.CharField(max_length=100, null=False, blank=False, help_text="Discord id of the user who injected the prompt")

    history = HistoricalRecords()


class PromptTemplate(models.Model):
    text = models.TextField(null=False, blank=False, help_text="Prompt injection for AI summary")
    history = HistoricalRecords()


class RainPeriod(models.Model):
    emoji = models.CharField(max_length=8, null=False, blank=False, help_text="The emoji to display during the rain effect")
    start_date = models.DateField(null=False, blank=False, help_text="Start date of the rain effect")
    end_date = models.DateField(null=False, blank=False, help_text="End date of the rain effect")
    enabled = models.BooleanField(default=True, help_text="Whether this rain period is currently enabled")
    description = models.CharField(max_length=100, null=True, blank=True, help_text="Optional description of this rain period")

    history = HistoricalRecords()

    @classmethod
    def get_active_period(cls) -> "RainPeriod | None":
        """Get the currently active rain period, with caching of period data but not active status."""
        cache_key = "rain_periods"
        cached_periods = cache.get(cache_key)
        today = timezone.now().date()

        if cached_periods is None:
            # Cache all enabled periods
            cached_periods = list(cls.objects.filter(enabled=True))
            # Cache for 24 hours since cache is invalidated on any changes anyway
            cache.set(cache_key, cached_periods, timeout=86400)  # 24 hours = 86400 seconds

        # Check which period is active right now - don't cache this result
        for period in cached_periods:
            if period.start_date <= today <= period.end_date:
                return period

        return None

    def save(self, *args, **kwargs):
        """Override save to invalidate cache when a rain period is modified."""
        cache.delete("rain_periods")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.emoji} ({self.start_date} - {self.end_date})"

    class Meta:
        ordering = ["-start_date"]
