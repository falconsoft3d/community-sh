from django.db import migrations, models


def turn_on(apps, schema_editor):
    """Every instance follows its repositories: the ones with automatic update off get "pull"."""
    apps.get_model('orchestrator', 'Instance').objects.filter(auto_update='').update(auto_update='pull')


class Migration(migrations.Migration):

    dependencies = [
        ('orchestrator', '0063_instance_env_vars'),
    ]

    operations = [
        migrations.AlterField(
            model_name='instance',
            name='auto_update',
            field=models.CharField(blank=True, choices=[('', 'Desactivada'), ('pull', 'Pull y reiniciar Odoo'), ('update', 'Pull y actualizar todos los módulos (-u all)')], default='pull', max_length=10),
        ),
        migrations.RunPython(turn_on, migrations.RunPython.noop),
    ]
