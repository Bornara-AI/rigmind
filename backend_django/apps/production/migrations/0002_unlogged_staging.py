from django.db import migrations


class Migration(migrations.Migration):
    """Staging rows are rebuilt on every load, so they need no crash-safe WAL logging.

    An UNLOGGED table skips the write-ahead log, which makes COPY into it faster.
    Its contents are emptied after a crash, which is fine for staging.
    """

    dependencies = [("production", "0001_initial")]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE stg_volumetric SET UNLOGGED",
            reverse_sql="ALTER TABLE stg_volumetric SET LOGGED",
        )
    ]
