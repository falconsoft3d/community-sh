from django.db import migrations, models


def fill_subdomains(apps, schema_editor):
    from orchestrator.services.domains import build_subdomain
    Instance = apps.get_model('orchestrator', 'Instance')
    for instance in Instance.objects.using(schema_editor.connection.alias).select_related('project__client'):
        instance.subdomain = build_subdomain(instance)
        instance.save(update_fields=['subdomain'])


class Migration(migrations.Migration):

    dependencies = [
        ('orchestrator', '0045_metrics_history'),
    ]

    operations = [
        migrations.AddField(
            model_name='instance',
            name='subdomain',
            field=models.CharField(blank=True, default='', help_text='Subdomain under the platform domain (client-version-name)', max_length=63),
        ),
        migrations.RunPython(fill_subdomains, migrations.RunPython.noop),
    ]
