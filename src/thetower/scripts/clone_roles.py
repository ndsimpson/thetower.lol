import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
django.setup()


from thetower.backend.tourney_results.models import Patch, Role

for role in Role.objects.filter(patch__version_minor=18):
    Role.objects.create(
        patch=Patch.objects.get(version_minor=19),
        wave_bottom=role.wave_bottom,
        wave_top=role.wave_top,
        league=role.league,
        color=role.color,
    )
