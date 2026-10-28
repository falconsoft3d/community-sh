import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def keep_client_names(apps, schema_editor):
    """Project.client was free text; keep it in the description before it becomes a user link."""
    db = schema_editor.connection.alias
    Project = apps.get_model('orchestrator', 'Project')
    for project in Project.objects.using(db).exclude(client_text=''):
        note = f"Cliente: {project.client_text}"
        project.description = f"{note}\n\n{project.description}".strip() if project.description else note
        project.save(using=db, update_fields=['description'])


class Migration(migrations.Migration):

    dependencies = [
        ('orchestrator', '0033_odoo_20'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='is_client',
            field=models.BooleanField(default=False, help_text='Client account: sees and operates only its projects'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='company',
            field=models.CharField(blank=True, help_text='Client company name', max_length=150),
        ),
        migrations.RenameField(model_name='project', old_name='client', new_name='client_text'),
        migrations.RunPython(keep_client_names, migrations.RunPython.noop),
        migrations.RemoveField(model_name='project', name='client_text'),
        migrations.AddField(
            model_name='project',
            name='client',
            field=models.ForeignKey(blank=True, help_text='Usuario cliente que ve y opera este proyecto', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='client_projects', to=settings.AUTH_USER_MODEL),
        ),
    ]
