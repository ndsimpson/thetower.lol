from django.apps import AppConfig


class TourneyResultsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "thetower.backend.tourney_results"

    def ready(self):
        from django.db.backends.signals import connection_created

        def set_wal_mode(sender, connection, **kwargs):
            if connection.vendor == "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute("PRAGMA journal_mode=WAL;")
                    cursor.execute("PRAGMA synchronous=NORMAL;")

        connection_created.connect(set_wal_mode, weak=False)
