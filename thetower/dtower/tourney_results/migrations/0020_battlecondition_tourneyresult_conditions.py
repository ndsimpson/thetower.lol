# Generated by Django 4.2 on 2023-09-14 18:28

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tourney_results", "0019_populate_position_role"),
    ]

    operations = [
        migrations.CreateModel(
            name="BattleCondition",
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
                    models.CharField(help_text="Name of the condition.", max_length=64),
                ),
                (
                    "shortcut",
                    models.CharField(
                        help_text="Shortcut of the condition.", max_length=8
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="tourneyresult",
            name="conditions",
            field=models.ManyToManyField(
                help_text="Battle conditions for the tourney.",
                related_name="results",
                to="tourney_results.battlecondition",
            ),
        ),
    ]