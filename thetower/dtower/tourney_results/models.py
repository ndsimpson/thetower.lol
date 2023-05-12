from colorfield.fields import ColorField
from django.db import models
from simple_history.models import HistoricalRecords

from dtower.tourney_results.constants import leagues_choices, wave_border_choices


class Patch(models.Model):
    version_minor = models.IntegerField(primary_key=True, help_text="The xx in 0.xx version.")
    start_date = models.DateField(blank=False, null=False, help_text="First tourney when patch was enforced.")
    end_date = models.DateField(blank=False, null=False, help_text="Last tourney when patch was in use.")

    def __str__(self):
        return f"0.{self.version_minor}"


class Role(models.Model):
    wave_bottom = models.IntegerField(blank=False, null=False, choices=[(wave, wave) for wave in wave_border_choices])
    wave_top = models.IntegerField(blank=False, null=False, choices=[(wave, wave) for wave in wave_border_choices])
    patch = models.ForeignKey(Patch, null=False, blank=False, related_name="roles", on_delete=models.CASCADE, help_text="Patch related to a given role.")
    league = models.CharField(blank=False, null=False, choices=leagues_choices, help_text="Which league are those results from?", max_length=16)
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


class TourneyResult(models.Model):
    result_file = models.FileField(upload_to="uploads/", blank=False, null=False, help_text="CSV file from discord with results.")
    date = models.DateField(blank=False, null=False, help_text="Date of the tournament")
    league = models.CharField(blank=False, null=False, choices=leagues_choices, help_text="Which league are those results from?", max_length=16)
    public = models.BooleanField(blank=False, null=False, default=False, help_text="Are the results shown to everyone or just to review?")

    history = HistoricalRecords()

    def __str__(self):
        return f"({self.pk}): {self.league} {self.date.isoformat()}"