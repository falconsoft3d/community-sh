from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orchestrator', '0079_odoo_db_manager'),
    ]

    operations = [
        migrations.AddField(
            model_name='mcptoken',
            name='expires_at',
            field=models.DateTimeField(blank=True, null=True, help_text='Stops working after this moment (empty: never)'),
        ),
        migrations.AddField(
            model_name='mcptoken',
            name='read_only',
            field=models.BooleanField(default=False, help_text='Only reads: GET in the API, the list_/get_ tools in MCP'),
        ),
    ]
