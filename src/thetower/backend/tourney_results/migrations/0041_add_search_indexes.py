from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tourney_results", "0040_add_player_id_index_to_tourneyrow"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historicaltourneyrow",
            name="nickname",
            field=models.CharField(db_index=True, help_text="Tourney name", max_length=32),
        ),
        migrations.AlterField(
            model_name="tourneyrow",
            name="nickname",
            field=models.CharField(db_index=True, help_text="Tourney name", max_length=32),
        ),
        # Replace the auto-created regular B-tree index with a functional UPPER() index
        # so that raw SQL range scans (WHERE UPPER(nickname) >= lo AND UPPER(nickname) < hi)
        # can use it as a B-tree range scan instead of a full table scan.
        migrations.RunSQL(
            sql=[
                "DROP INDEX IF EXISTS tourney_results_tourneyrow_nickname_011d795d;",
                "CREATE INDEX IF NOT EXISTS tourney_results_tourneyrow_nickname_upper ON tourney_results_tourneyrow (upper(nickname));",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS tourney_results_tourneyrow_nickname_upper;",
                "CREATE INDEX tourney_results_tourneyrow_nickname_011d795d ON tourney_results_tourneyrow (nickname);",
            ],
        ),
    ]
