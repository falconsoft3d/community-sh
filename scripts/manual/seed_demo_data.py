"""
Sample data for the manual's screenshots. Run it on an EMPTY database, never on a real one:

    DATABASE_URL=sqlite:////tmp/manual.sqlite3 DEBUG=True python manage.py migrate
    DATABASE_URL=sqlite:////tmp/manual.sqlite3 DEBUG=True python manage.py shell -c "exec(open('scripts/manual/seed_demo_data.py').read())"

It creates the user demo / Manual-2026! and writes the demo tokens to $MANUAL_TOKENS (default /tmp/manual-tokens.txt).
"""
from datetime import timedelta
from django.contrib.auth.models import User
from django.utils import timezone
from orchestrator.models import Instance, Project, TrialRequest, Backup, Task, Todo, GitHubConfig

admin = User.objects.create_superuser('demo', 'demo@example.com', 'Manual-2026!', first_name='Marta', last_name='Ruiz')
_config, _ = GitHubConfig.objects.get_or_create(user=admin)
_config.smtp_enabled, _config.smtp_host, _config.smtp_port, _config.smtp_security = True, 'smtp.gmail.com', 587, 'starttls'
_config.smtp_username, _config.smtp_password = 'demos@communitysh.xyz', 'app-password'
_config.smtp_from_email, _config.smtp_from_name = 'demos@communitysh.xyz', 'Community SH Demos'
_config.save()
client = User.objects.create_user('acme', 'it@acme.example', 'Cliente-2026!', first_name='Laura', last_name='Gómez')
client.profile.is_client = True; client.profile.company = 'ACME Construcciones'; client.profile.save()

acme = Project.objects.create(name='ACME', owner=admin, client=client, description='Implantación de Odoo para ACME Construcciones')
demos = Project.objects.create(name='BIM demos', owner=admin, description='Copias de prueba que piden los clientes desde /bim')
bim = Project.objects.create(name='BIM', owner=admin, description='Plantillas del Odoo para la construcción (una por versión)',
    trial_enabled=True, trial_slug='bim', trial_days=15, trial_target_project=demos, trial_max_active=3,
    trial_message='Prueba gratis durante 15 días nuestro Odoo para empresas de construcción: presupuestos BIM, certificaciones de obra y control de costes.\nElige la versión, deja tus datos y en unos minutos tendrás tu propia copia.')

port = 30100
def inst(name, project, version, status='running', description='', **kw):
    global port; port += 1
    return Instance.objects.create(name=name, project=project, owner=admin, odoo_version=version, status=status,
                                   port=port, description=description, github_repo='https://github.com/acme/odoo-addons.git', **kw)
prod = inst('produccion', acme, '18.0')
inst('pruebas', acme, '18.0', status='stopped')
inst('migracion-19', acme, '19.0', status='deploying')
b18 = inst('bim18', bim, '18.0', description='Odoo 18 estable con los módulos BIM, certificaciones y app móvil de partes de obra.')
b19 = inst('bim19', bim, '19.0', description='Odoo 19 con la nueva planificación de obra y el cuadro de mando de costes.')
inst('bim20', bim, '20.0', description='Odoo 20 (vista previa): las últimas novedades, para quien quiere ir por delante.')
d1 = inst('bim-constructora-sol-a3f2', demos, '18.0', origin='trial')
d2 = inst('bim-obras-norte-7c1e', demos, '19.0', origin='trial')
now = timezone.now()
TrialRequest.objects.create(project=bim, source=b18, instance=d1, name='Ana Pérez', email='ana@constructorasol.es', company='Constructora Sol', job_title='Directora técnica', country='España', emailed_at=now,
    phone='+34 600 111 222', version='18.0', status='ready', admin_login='admin', admin_password='Xk3-pQ9vT2mL', expires_at=now + timedelta(days=12))
TrialRequest.objects.create(project=bim, source=b19, instance=d2, name='Jon Etxeberria', email='jon@obrasnorte.eus', company='Obras Norte', job_title='Jefe de obra', country='España', phone='+34 611 222 333', emailed_at=now,
    version='19.0', status='ready', admin_login='admin', admin_password='Rt7-aZ2wQ8nB', expires_at=now + timedelta(days=4))
TrialRequest.objects.create(project=bim, source=b18, name='Lucía Martín', email='lucia@reformasmartin.com', company='Reformas Martín', job_title='Gerente', country='México',
    version='18.0', status='expired', expires_at=now - timedelta(days=2), stopped_at=now - timedelta(days=2))

for i, inst_ in enumerate([prod, prod, b18]):
    Backup.objects.create(instance=inst_, filename=f'{inst_.name}_backup_2026110{i+1}_030000.zip', file_path=f'/backups/{inst_.name}_{i}.zip',
                          file_size=(180 + 40 * i) * 1024 * 1024, created_by=admin)
for kind, inst_, status, step in [('deploy', prod, 'done', 'Completada'), ('backup', prod, 'done', 'Completada'), ('trial', d1, 'done', 'Completada'),
                                   ('duplicate', b19, 'running', 'Copiando los adjuntos (filestore)')]:
    t = Task.objects.create(kind=kind, instance=inst_, created_by=admin, status=status, step=step, progress=100 if status == 'done' else 85,
                            started_at=now - timedelta(minutes=5), finished_at=now if status == 'done' else None,
                            log='[03:00:01] Inicio\n[03:00:12] Copiando la base de datos\n[03:02:40] Completada')
Todo.objects.create(title='Revisar la migración a Odoo 19', status='in_progress', created_by=admin)
Todo.objects.create(title='Añadir descripción a las plantillas BIM', status='done', created_by=admin, completed_by='Marta', completion_note='Hecho en las tres versiones')
Todo.objects.create(title='Preparar demo para Obras Norte', created_by=admin)
print('seeded', TrialRequest.objects.count())

from orchestrator.models import Task as _Task
_bim = Project.objects.get(name='BIM')
_task = _Task.objects.create(kind='trial', status='running', progress=55, step='Desplegando la nueva instancia',
                             started_at=timezone.now(), params={})
_building = TrialRequest.objects.create(project=_bim, source=b19, name='Pedro Gil', email='pedro@gilobras.es',
                                        company='Gil Obras', job_title='Arquitecto', country='España', version='19.0', task=_task)
_task.params = {'trial': _building.pk}
_task.save()
_ready = TrialRequest.objects.get(email='ana@constructorasol.es')
from orchestrator.container_models import Container as _Container
_Container.objects.create(name='n8n-acme', image='n8nio/n8n:latest', port=31678, container_port=5678, status='running',
                          description='Automatizaciones de ACME', created_by=admin, project=acme, template='n8n')
import os as _os
open(_os.environ.get('MANUAL_TOKENS', '/tmp/manual-tokens.txt'), 'w').write(f'{_building.token} {_ready.token}')
