from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sus", "0030_historicallinkedaccount_active_linkedaccount_active"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historicalknownplayer",
            name="name",
            field=models.CharField(
                blank=True, db_index=True, help_text="Player's friendly name, e.g. common discord handle", max_length=100, null=True
            ),
        ),
        migrations.AlterField(
            model_name="knownplayer",
            name="name",
            field=models.CharField(
                blank=True, db_index=True, help_text="Player's friendly name, e.g. common discord handle", max_length=100, null=True
            ),
        ),
        # Replace the auto-created regular B-tree index with a functional UPPER() index
        # to support efficient case-insensitive prefix searches.
        migrations.RunSQL(
            sql=[
                "DROP INDEX IF EXISTS sus_knownplayer_name_98998fc1;",
                "CREATE INDEX IF NOT EXISTS sus_knownplayer_name_upper ON sus_knownplayer (upper(name));",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS sus_knownplayer_name_upper;",
                "CREATE INDEX sus_knownplayer_name_98998fc1 ON sus_knownplayer (name);",
            ],
        ),
    ]
