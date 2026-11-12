from django.db import migrations

SECRET_PARAMS = ('password',)


def scrub(apps, schema_editor):
    """Finished tasks no longer keep the passwords they were given (create a database, reset the admin's)."""
    Task = apps.get_model('orchestrator', 'Task')
    for task in Task.objects.filter(status__in=('done', 'failed')).iterator():
        params = task.params or {}
        if any(params.get(key) for key in SECRET_PARAMS):
            task.params = {key: ('••••••' if key in SECRET_PARAMS and value else value) for key, value in params.items()}
            task.save(update_fields=['params'])


class Migration(migrations.Migration):

    dependencies = [
        ('orchestrator', '0067_instance_memory_limit'),
    ]

    operations = [
        migrations.RunPython(scrub, migrations.RunPython.noop),
    ]
