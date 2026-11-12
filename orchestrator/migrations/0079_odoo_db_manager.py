from django.db import migrations, models


class Migration(migrations.Migration):
    """Instances that already exist keep the manager open (as until now); new ones start closed."""

    dependencies = [
        ('orchestrator', '0078_client_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='instance',
            name='odoo_db_manager',
            field=models.BooleanField(default=True, help_text="Odoo's database manager reachable from the internet"),
        ),
        migrations.AlterField(
            model_name='instance',
            name='odoo_db_manager',
            field=models.BooleanField(default=False, help_text="Odoo's database manager reachable from the internet"),
        ),
    ]
