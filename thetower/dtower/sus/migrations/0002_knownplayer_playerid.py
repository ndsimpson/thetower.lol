# Generated by Django 4.2 on 2023-05-05 08:31

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sus", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="KnownPlayer",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        blank=True,
                        help_text="Player's friendly name, e.g. common discord handle",
                        max_length=100,
                        null=True,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="PlayerId",
            fields=[
                (
                    "id",
                    models.CharField(
                        help_text="Player id from The Tower, pk",
                        max_length=32,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "player",
                    models.ForeignKey(
                        help_text="Player id from The Tower, pk",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ids",
                        to="sus.knownplayer",
                    ),
                ),
                (
                    "primary",
                    models.BooleanField(default=False),
                ),
            ],
        ),
    ]
