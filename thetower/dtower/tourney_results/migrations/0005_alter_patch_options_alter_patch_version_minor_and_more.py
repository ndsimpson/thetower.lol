# Generated by Django 4.2 on 2023-05-20 12:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tourney_results", "0004_fill_roles_patches"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="patch",
            options={"verbose_name_plural": "pathes"},
        ),
        migrations.AlterField(
            model_name="patch",
            name="version_minor",
            field=models.SmallIntegerField(
                help_text="The xx in 0.xx version.", primary_key=True, serialize=False
            ),
        ),
        migrations.AlterField(
            model_name="role",
            name="wave_bottom",
            field=models.SmallIntegerField(
                choices=[
                    (0, 0),
                    (250, 250),
                    (500, 500),
                    (750, 750),
                    (1000, 1000),
                    (1250, 1250),
                    (1500, 1500),
                    (1750, 1750),
                    (2000, 2000),
                    (2250, 2250),
                    (2500, 2500),
                    (2750, 2750),
                    (3000, 3000),
                    (3500, 3500),
                    (4000, 4000),
                    (100000, 100000),
                ]
            ),
        ),
        migrations.AlterField(
            model_name="role",
            name="wave_top",
            field=models.SmallIntegerField(
                choices=[
                    (0, 0),
                    (250, 250),
                    (500, 500),
                    (750, 750),
                    (1000, 1000),
                    (1250, 1250),
                    (1500, 1500),
                    (1750, 1750),
                    (2000, 2000),
                    (2250, 2250),
                    (2500, 2500),
                    (2750, 2750),
                    (3000, 3000),
                    (3500, 3500),
                    (4000, 4000),
                    (100000, 100000),
                ]
            ),
        ),
    ]
