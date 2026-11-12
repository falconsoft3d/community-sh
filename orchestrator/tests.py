import os
from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from .backup_models import Backup
from .config_models import GitHubConfig
from .container_models import Container
from .models import Instance
from .permissions import domain_in_use, validate_domain, validate_resource_name


@override_settings(ALLOWED_HOSTS=['*'])
class BaseTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pass-12345')
        self.alice = User.objects.create_user('alice', password='pass-12345')
        self.bob = User.objects.create_user('bob', password='pass-12345')
        self.config = GitHubConfig.objects.create(user=self.admin)
        from .project_models import Project
        self.alice_project = Project.objects.create(name='ACME', owner=self.alice)
        self.bob_project = Project.objects.create(name='Globex', owner=self.bob)
        self.alice_instance = Instance.objects.create(name='alice-odoo', owner=self.alice, project=self.alice_project)
        self.bob_instance = Instance.objects.create(name='bob-odoo', owner=self.bob, project=self.bob_project)

        # One mock shared by every views module that talks to Docker
        self.docker = mock.MagicMock()
        for target in ('orchestrator.views.api', 'orchestrator.views.instances', 'orchestrator.tasks'):
            docker_patch = mock.patch(f'{target}.DockerService', self.docker)
            docker_patch.start()
            self.addCleanup(docker_patch.stop)


class ApiPermissionTests(BaseTestCase):
    def test_anonymous_cannot_use_api(self):
        # 401 + WWW-Authenticate: Bearer (token auth is available)
        response = self.client.get('/api/instances/')
        self.assertEqual(response.status_code, 401)

        response = self.client.post('/api/instances/', {'name': 'evil'})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(Instance.objects.filter(name='evil').exists())

    def test_user_only_sees_own_instances(self):
        self.client.force_login(self.alice)
        names = [i['name'] for i in self.client.get('/api/instances/').json()]
        self.assertEqual(names, ['alice-odoo'])

        response = self.client.delete(f'/api/instances/{self.bob_instance.pk}/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Instance.objects.filter(pk=self.bob_instance.pk).exists())

    def test_superuser_sees_all_instances(self):
        self.client.force_login(self.admin)
        self.assertEqual(len(self.client.get('/api/instances/').json()), 2)

    def test_api_create_sets_owner(self):
        self.client.force_login(self.alice)
        response = self.client.post('/api/instances/', {'name': 'alice-two', 'owner': self.bob.pk, 'project': self.alice_project.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Instance.objects.get(name='alice-two').owner, self.alice)

    def test_api_requires_own_project(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.post('/api/instances/', {'name': 'no-project'}).status_code, 400)
        self.assertEqual(self.client.post('/api/instances/', {'name': 'other', 'project': self.bob_project.pk}).status_code, 400)


class InstanceOwnershipTests(BaseTestCase):
    def test_instance_list_is_scoped(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse('instance-list'))
        self.assertContains(response, 'alice-odoo')
        self.assertNotContains(response, 'bob-odoo')

    def test_cannot_open_or_operate_other_users_instance(self):
        self.client.force_login(self.alice)
        pk = self.bob_instance.pk
        self.assertEqual(self.client.get(reverse('instance-detail', args=[pk])).status_code, 404)
        for name in ('instance-stop', 'instance-delete', 'instance-console-exec', 'instance-restore'):
            response = self.client.post(reverse(name, args=[pk]), '{"command": "id"}', content_type='application/json')
            self.assertEqual(response.status_code, 404, name)
        self.docker.return_value.execute_command.assert_not_called()
        self.assertTrue(Instance.objects.filter(pk=pk).exists())

    def test_owner_can_use_console(self):
        self.docker.return_value.execute_command.return_value = 'ok'
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse('instance-console-exec', args=[self.alice_instance.pk]),
            '{"command": "id"}', content_type='application/json',
        )
        self.assertEqual(response.json()['output'], 'ok')

    def test_cannot_touch_other_users_backups(self):
        backup = Backup.objects.create(
            instance=self.bob_instance, filename='b.zip', file_path='/nonexistent/b.zip', file_size=1,
        )
        self.client.force_login(self.alice)
        for name in ('backup-download', 'backup-delete', 'backup-restore-action', 'backup-create-instance'):
            self.assertEqual(self.client.post(reverse(name, args=[backup.pk])).status_code, 404, name)
        self.assertTrue(Backup.objects.filter(pk=backup.pk).exists())

    def test_rename_rejects_invalid_names(self):
        self.client.force_login(self.alice)
        self.client.post(reverse('instance-update-name', args=[self.alice_instance.pk]), {'name': '../etc'})
        self.alice_instance.refresh_from_db()
        self.assertEqual(self.alice_instance.name, 'alice-odoo')


class AdminOnlyTests(BaseTestCase):
    def test_metrics_requires_superuser(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('metrics')).status_code, 403)

    def test_run_backups_requires_superuser_and_post(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.post(reverse('run-auto-backups')).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('run-auto-backups')).status_code, 405)

    def test_generate_ssl_requires_superuser(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse('generate-ssl'), {'domain': 'x.com', 'email': 'a@x.com'})
        self.assertEqual(response.status_code, 403)

    def test_regular_user_cannot_change_platform_settings(self):
        self.client.force_login(self.alice)
        self.client.post(reverse('settings'), {
            'section': 'domain', 'main_domain': 'evil.com',
            'registration_enabled': 'on', 'two_factor_required': 'on',
        })
        config = GitHubConfig.objects.get(user=self.alice)
        self.assertEqual(config.main_domain, '')
        self.assertFalse(config.registration_enabled)

    def test_regular_user_can_save_own_github_token(self):
        self.client.force_login(self.alice)
        self.client.post(reverse('settings'), {'section': 'github', 'personal_access_token': 'tok'})
        self.assertEqual(GitHubConfig.objects.get(user=self.alice).personal_access_token, 'tok')


class RegistrationTests(TestCase):
    @override_settings(ALLOWED_HOSTS=['*'])
    def test_first_user_becomes_superuser_then_registration_closes(self):
        data = {'username': 'first', 'password1': 'S3cure-pass-123', 'password2': 'S3cure-pass-123'}
        self.client.post(reverse('register'), data)
        self.assertTrue(User.objects.get(username='first').is_superuser)

        self.client.logout()
        data['username'] = 'second'
        self.client.post(reverse('register'), data)
        self.assertFalse(User.objects.filter(username='second').exists())


class TwoFactorEnforcementTests(BaseTestCase):
    def test_required_2fa_forces_setup(self):
        self.config.two_factor_required = True
        self.config.save()
        self.client.force_login(self.alice)

        response = self.client.get(reverse('instance-list'))
        self.assertRedirects(response, reverse('two-factor-setup'), fetch_redirect_response=False)
        self.assertEqual(self.client.get('/api/instances/').status_code, 403)
        self.assertEqual(self.client.get(reverse('two-factor-setup')).status_code, 200)

    def test_cannot_disable_required_2fa(self):
        self.config.two_factor_required = True
        self.config.save()
        profile = self.alice.profile
        profile.two_factor_enabled = True
        profile.two_factor_secret = 'JBSWY3DPEHPK3PXP'
        profile.save()
        self.client.force_login(self.alice)

        self.client.post(reverse('two-factor-setup'), {'action': 'disable'})
        profile.refresh_from_db()
        self.assertTrue(profile.two_factor_enabled)


@override_settings(ALLOWED_HOSTS=['*'])
class ContainerRestrictionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('carol', password='pass-12345')
        patcher = mock.patch('orchestrator.container_views.ContainerService')
        self.service = patcher.start()
        self.service.return_value.create_container.return_value = (True, 'ok')
        self.addCleanup(patcher.stop)
        self.client.force_login(self.user)

    def test_template_with_docker_socket_is_admin_only(self):
        self.client.post(reverse('container-create'), {'template': 'coolify', 'name': 'coolify1'})
        self.assertFalse(Container.objects.exists())

    def test_yaml_host_mount_is_rejected(self):
        yaml_config = 'volumes:\n  root:\n    host: "/"\n    container: "/host"\n'
        self.client.post(reverse('container-create'), {'template': 'n8n', 'name': 'n8n1', 'yaml_config': yaml_config})
        self.assertFalse(Container.objects.exists())

    def test_yaml_network_change_is_rejected(self):
        self.client.post(reverse('container-create'), {'template': 'n8n', 'name': 'n8n1', 'yaml_config': 'network: net_bob-odoo'})
        self.assertFalse(Container.objects.exists())

    def test_regular_template_is_allowed(self):
        self.client.post(reverse('container-create'), {'template': 'n8n', 'name': 'n8n1'})
        self.assertTrue(Container.objects.filter(name='n8n1').exists())

    def test_invalid_container_name_is_rejected(self):
        self.client.post(reverse('container-create'), {'template': 'n8n', 'name': 'bad.name`)'})
        self.assertFalse(Container.objects.exists())


class ValidationTests(TestCase):
    def test_resource_names(self):
        for ok in ('odoo17', 'mi-empresa', 'a'):
            validate_resource_name(ok)
        for bad in ('', '-x', 'x-', 'Upper', '../x', 'a.b', 'x' * 64):
            with self.assertRaises(ValidationError, msg=bad):
                validate_resource_name(bad)

    def test_domains(self):
        validate_domain('erp.example.com')
        for bad in ('example', 'a`) || Host(`b.com', 'exa mple.com'):
            with self.assertRaises(ValidationError, msg=bad):
                validate_domain(bad)

    def test_main_domain_cannot_be_claimed(self):
        admin = User.objects.create_superuser('admin', 'a@example.com', 'pass-12345')
        GitHubConfig.objects.create(user=admin, main_domain='panel.example.com')
        self.assertTrue(domain_in_use('panel.example.com'))
        self.assertTrue(domain_in_use('WWW.panel.example.com'))
        self.assertFalse(domain_in_use('erp.example.com'))


class HostPathTests(TestCase):
    def test_translates_project_paths_to_host(self):
        from django.conf import settings
        from .services import host_path
        base = str(settings.BASE_DIR)
        with mock.patch.dict('os.environ', {'HOST_WORKDIR': '/opt/community-sh'}):
            self.assertEqual(host_path(f'{base}/instances/x/addons'), '/opt/community-sh/instances/x/addons')
            self.assertEqual(host_path('/var/run/docker.sock'), '/var/run/docker.sock')
            self.assertEqual(host_path(f'{base}-other/x'), f'{base}-other/x')
        with mock.patch.dict('os.environ', {'HOST_WORKDIR': ''}):
            self.assertEqual(host_path(f'{base}/instances/x'), f'{base}/instances/x')


class DockerServiceTests(TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__('shutil').rmtree, self.tmp, True)
        settings_patch = override_settings(BASE_DIR=self.tmp)
        settings_patch.enable()
        self.addCleanup(settings_patch.disable)
        client_patch = mock.patch('orchestrator.services.docker_service.docker.from_env')
        self.client = client_patch.start().return_value
        self.addCleanup(client_patch.stop)

        import docker
        self.not_found = docker.errors.NotFound('missing')
        self.instance = Instance.objects.create(name='acme')

    def _service(self):
        from .services import DockerService
        return DockerService()

    def test_master_passwords_are_unique(self):
        other = Instance.objects.create(name='other')
        self.assertTrue(self.instance.master_password)
        self.assertNotEqual(self.instance.master_password, other.master_password)

    def test_reuses_existing_anonymous_data_volume(self):
        container = mock.Mock(attrs={'Mounts': [
            {'Destination': '/mnt/extra-addons', 'Name': None},
            {'Destination': '/var/lib/odoo', 'Name': 'a1b2c3'},
        ]})
        service = self._service()
        self.assertEqual(service._resolve_data_volume(self.instance, container), 'a1b2c3')
        self.assertEqual(service._resolve_data_volume(self.instance, None), 'odoo_data_acme')

    def test_deploy_mounts_data_volume_and_config(self):
        self.client.containers.get.side_effect = self.not_found
        odoo = self.client.containers.run.return_value
        odoo.id = 'abc123'
        odoo.attrs = {'NetworkSettings': {'Ports': {'8069/tcp': [{'HostPort': '32768'}]}}}

        with mock.patch.dict('os.environ', {'HOST_WORKDIR': '/srv/csh'}):
            self._service().deploy_instance(self.instance)

        odoo_call = [c for c in self.client.containers.run.call_args_list if c.args[0].startswith('odoo:')][0]
        volumes = odoo_call.kwargs['volumes']
        self.assertEqual(volumes['odoo_data_acme'], {'bind': '/var/lib/odoo', 'mode': 'rw'})
        self.assertEqual(volumes['/srv/csh/instances/acme/conf']['bind'], '/etc/odoo')
        self.assertEqual(volumes['/srv/csh/instances/acme/addons']['bind'], '/mnt/extra-addons')

        with open(f'{self.tmp}/instances/acme/conf/odoo.conf') as f:
            conf = f.read()
        self.assertIn(f'admin_passwd = {self.instance.master_password}', conf)
        self.assertIn('http_interface = 0.0.0.0', conf)
        db_call = [c for c in self.client.containers.run.call_args_list if c.args[0].startswith('postgres:')][0]
        self.assertEqual(db_call.args[0], 'postgres:15')  # default instance version is 17.0
        # Logs capped on both, so a looping error can't fill the disk
        for call in (odoo_call, db_call):
            self.assertEqual(call.kwargs['log_config']['Config'], {'max-size': '20m', 'max-file': '3'})
        self.instance.refresh_from_db()
        self.assertEqual(self.instance.data_volume, 'odoo_data_acme')
        # Published on an explicit port (kept across restarts), stored on the instance
        self.assertEqual(odoo_call.kwargs['ports'], {'8069/tcp': ('0.0.0.0', self.instance.port)})
        self.assertTrue(20000 <= self.instance.port < 40000)

    def test_rename_moves_resources_and_keeps_data(self):
        import os
        os.makedirs(f'{self.tmp}/instances/acme')
        old_odoo = mock.Mock(attrs={'Mounts': [{'Destination': '/var/lib/odoo', 'Name': 'vol123'}]})
        db = mock.Mock()
        containers = {'odoo_acme': old_odoo, 'db_acme': db}

        def get_container(name):
            if name in containers:
                return containers[name]
            raise self.not_found
        self.client.containers.get.side_effect = get_container
        new_network = mock.Mock()
        old_network = mock.Mock()
        self.client.networks.get.side_effect = lambda n: {'net_acme': old_network}.get(n) or (_ for _ in ()).throw(self.not_found)
        self.client.networks.create.return_value = new_network

        service = self._service()
        self.instance.name = 'acme-new'
        with mock.patch.object(service, 'deploy_instance') as deploy:
            service.rename_instance(self.instance, 'acme')

        old_odoo.remove.assert_called_once_with(force=True)
        db.rename.assert_called_once_with('db_acme-new')
        new_network.connect.assert_called_once_with(db)
        old_network.disconnect.assert_called_once_with(db)
        old_network.remove.assert_called_once()
        self.assertTrue(os.path.isdir(f'{self.tmp}/instances/acme-new'))
        deploy.assert_called_once_with(self.instance)
        self.instance.refresh_from_db()
        self.assertEqual((self.instance.name, self.instance.data_volume), ('acme-new', 'vol123'))


class AutoBackupScheduleTests(TestCase):
    def setUp(self):
        admin = User.objects.create_superuser('admin', 'a@example.com', 'pass-12345')
        self.config = GitHubConfig.objects.create(
            user=admin, auto_backup_enabled=True,
            auto_backup_frequency_unit='hour', auto_backup_frequency_value=6,
        )
        patcher = mock.patch('orchestrator.tasks.DockerService')
        self.service = patcher.start()
        self.addCleanup(patcher.stop)
        Instance.objects.create(name='acme')

    def run_command(self):
        from io import StringIO
        from django.core.management import call_command
        call_command('run_auto_backups', stdout=StringIO())

    def test_runs_once_per_interval(self):
        from datetime import timedelta
        from django.utils import timezone
        self.run_command()
        self.run_command()
        self.assertEqual(self.service.return_value.backup_all_databases.call_count, 1)

        self.config.refresh_from_db()
        self.config.last_auto_backup_at = timezone.now() - timedelta(hours=6, minutes=1)
        self.config.save()
        self.run_command()
        self.assertEqual(self.service.return_value.backup_all_databases.call_count, 2)

    def test_disabled_does_nothing(self):
        self.config.auto_backup_enabled = False
        self.config.save()
        self.run_command()
        self.service.return_value.backup_all_databases.assert_not_called()


class PostOnlyActionTests(BaseTestCase):
    def test_backup_and_container_actions_reject_get(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('instance-backup', args=[self.alice_instance.pk])).status_code, 405)
        container = Container.objects.create(name='c1', image='x', port=1, container_port=1, created_by=self.alice)
        for name in ('container-start', 'container-stop', 'container-restart'):
            self.assertEqual(self.client.get(reverse(name, args=[container.pk])).status_code, 405, name)


@override_settings(ALLOWED_HOSTS=['*'])
class LockoutTests(TestCase):
    def setUp(self):
        User.objects.create_user('dave', password='right-pass-123')

    def test_login_locks_after_repeated_failures(self):
        for _ in range(5):
            self.client.post(reverse('login'), {'username': 'dave', 'password': 'wrong'})
        self.client.post(reverse('login'), {'username': 'dave', 'password': 'right-pass-123'})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_2fa_locks_after_repeated_failures(self):
        user = User.objects.get(username='dave')
        user.profile.two_factor_enabled = True
        user.profile.two_factor_secret = 'JBSWY3DPEHPK3PXP'
        user.profile.save()
        self.client.post(reverse('login'), {'username': 'dave', 'password': 'right-pass-123'})
        for _ in range(5):
            self.client.post(reverse('two-factor-verify'), {'code': '000000'})

        import pyotp
        self.client.post(reverse('two-factor-verify'), {'code': pyotp.TOTP('JBSWY3DPEHPK3PXP').now()})
        self.assertNotIn('_auth_user_id', self.client.session)


class TaskQueueTests(BaseTestCase):
    def run_worker(self):
        from io import StringIO
        from django.core.management import call_command
        call_command('run_worker', once=True, stdout=StringIO())

    def test_create_view_enqueues_deploy(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        with mock.patch('orchestrator.forms.requests'):
            response = self.client.post(reverse('instance-create'), {'name': 'NewOne', 'odoo_version': '17.0', 'project': self.alice_project.pk})
        instance = Instance.objects.get(name='newone')
        self.assertRedirects(response, reverse('instance-detail', args=[instance.pk]), fetch_redirect_response=False)
        task = Task.objects.get(instance=instance)
        self.assertEqual((task.kind, task.status, instance.status), ('deploy', 'pending', 'deploying'))
        self.assertTrue(task.params['create_branch'])
        self.docker.return_value.deploy_instance.assert_not_called()

    def test_worker_runs_and_records_tasks(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        self.client.post(reverse('instance-deploy', args=[self.alice_instance.pk]))
        self.client.post(reverse('instance-backup', args=[self.alice_instance.pk]), {'filestore': 'false'})
        self.docker.return_value.backup_all_databases.side_effect = Exception('disk full')

        self.run_worker()

        self.docker.return_value.deploy_instance.assert_called_once()
        deploy, backup = Task.objects.order_by('created_at')
        self.assertEqual(deploy.status, 'done')
        self.assertEqual((backup.status, backup.result), ('failed', 'disk full'))
        self.assertIsNotNone(backup.finished_at)

    def test_interrupted_tasks_are_marked_failed(self):
        from .task_models import Task
        task = Task.objects.create(kind='deploy', instance=self.alice_instance, status='running')
        self.run_worker()
        task.refresh_from_db()
        self.assertEqual(task.status, 'failed')

    def test_deploy_rejects_get(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('instance-deploy', args=[self.alice_instance.pk])).status_code, 405)

    def test_tasks_api_is_scoped_and_reports_activity(self):
        from .tasks import enqueue
        enqueue('backup', self.alice_instance, self.alice)
        self.client.force_login(self.alice)
        data = self.client.get(reverse('instance-tasks-api', args=[self.alice_instance.pk])).json()
        self.assertTrue(data['active'])
        self.assertEqual(data['tasks'][0]['status'], 'pending')
        self.assertEqual(self.client.get(reverse('instance-tasks-api', args=[self.bob_instance.pk])).status_code, 404)

    def test_uploaded_restore_file_is_removed_after_task(self):
        import os
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .task_models import Task
        self.client.force_login(self.alice)
        upload = SimpleUploadedFile('b.zip', b'zipdata')
        self.client.post(reverse('instance-restore', args=[self.alice_instance.pk]), {'backup_file': upload})
        task = Task.objects.get(kind='restore')
        path = task.params['file_path']
        self.assertTrue(os.path.exists(path))

        self.run_worker()

        self.docker.return_value.restore_instance.assert_called_once_with(self.alice_instance, path)
        self.assertFalse(os.path.exists(path))

    def test_rename_and_duplicate_are_queued(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        self.client.post(reverse('instance-update-name', args=[self.alice_instance.pk]), {'name': 'alice-new'})
        self.client.post(reverse('instance-duplicate', args=[self.alice_instance.pk]), {'new_name': 'alice-copy'})
        self.assertEqual(set(Task.objects.values_list('kind', flat=True)), {'rename', 'duplicate'})
        self.alice_instance.refresh_from_db()
        self.assertEqual(self.alice_instance.name, 'alice-odoo')

        self.docker.return_value.copy_instance.side_effect = lambda source, name, **kw: Instance.objects.create(name=name)
        self.run_worker()
        # The form's checkbox was left unticked: not neutralized
        self.assertIsNone(self.docker.return_value.copy_instance.call_args.kwargs['neutralize'])

        rename_call = self.docker.return_value.rename_instance.call_args
        self.assertEqual((rename_call.args[0].name, rename_call.args[1]), ('alice-new', 'alice-odoo'))
        self.assertEqual(Instance.objects.get(name='alice-copy').owner, self.alice)
        self.assertFalse(Task.objects.exclude(status='done').exists())

    def test_create_from_backup_creates_instance_and_task(self):
        import json, tempfile, zipfile
        from .task_models import Task
        path = tempfile.mktemp(suffix='.zip')
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('database.dump', 'PGDMP')
            zf.writestr('metadata.json', json.dumps({'database_name': 'alice_db', 'odoo_version': '16.0'}))
        backup = Backup.objects.create(instance=self.alice_instance, filename='a.zip', file_path=path, file_size=1)
        self.client.force_login(self.alice)

        self.client.post(reverse('backup-create-instance', args=[backup.pk]), {'name': 'from-backup'})

        instance = Instance.objects.get(name='from-backup')
        self.assertEqual((instance.owner, instance.database_name, instance.odoo_version), (self.alice, 'alice_db', '16.0'))
        self.assertEqual(Task.objects.get(instance=instance).params, {'backup_id': backup.pk})

    def test_backup_with_bad_database_name_is_rejected(self):
        import json, os, tempfile, zipfile
        path = tempfile.mktemp(suffix='.zip')
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('metadata.json', json.dumps({'database_name': 'x"; DROP DATABASE y; --'}))
        backup = Backup.objects.create(instance=self.alice_instance, filename='a.zip', file_path=path, file_size=1)
        self.client.force_login(self.alice)
        self.client.post(reverse('backup-create-instance', args=[backup.pk]), {'name': 'from-backup'})
        self.assertFalse(Instance.objects.filter(name='from-backup').exists())


class TaskLogTests(BaseTestCase):
    """What a task prints and logs is kept in its log, with a progress bar; the activity pages show it."""

    def run_worker(self):
        from io import StringIO
        from django.core.management import call_command
        call_command('run_worker', once=True, stdout=StringIO())

    def test_log_and_progress_of_a_task(self):
        import logging
        from .task_log import progress
        from .task_models import Task
        from .tasks import enqueue

        def deploy(instance):
            progress(40, 'Clonando el repositorio')
            print('Cloning into alice-odoo...')
            logging.getLogger('orchestrator.services').warning('Imagen sin firma')
            progress(20, 'Un paso de otro paso')  # the bar never goes back
            self.assertEqual(Task.objects.get(kind='deploy').progress, 40)
        self.docker.return_value.deploy_instance.side_effect = deploy
        self.docker.return_value.deploy_notes = []
        enqueue('deploy', self.alice_instance, self.alice)

        with mock.patch('orchestrator.tasks.TraefikService.generate_instance_config', return_value=(True, '')):
            self.run_worker()

        task = Task.objects.get(kind='deploy')
        self.assertEqual((task.status, task.progress, task.bar_percent, task.step), ('done', 100, 100, 'Completada'))
        for text in ('Desplegar · alice-odoo · alice', '▶ Clonando el repositorio', 'Cloning into alice-odoo...',
                     'WARNING: Imagen sin firma', '▶ Rutas de Traefik', 'Instancia desplegada'):
            self.assertIn(text, task.log)
        self.assertRegex(task.log.splitlines()[0], r'^\d\d:\d\d:\d\d ')

    def test_failed_task_keeps_the_error_in_its_log(self):
        from .task_models import Task
        from .tasks import enqueue
        self.docker.return_value.backup_all_databases.side_effect = Exception('disk full')
        enqueue('backup', self.alice_instance, self.alice)
        self.run_worker()
        task = Task.objects.get(kind='backup')
        self.assertEqual((task.status, task.bar_percent), ('failed', 100))
        self.assertIn('✖ Fallida: disk full', task.log)
        self.assertIn('Traceback', task.log)

    def test_print_outside_a_task_is_not_kept(self):
        from .task_log import line, progress
        progress(50, 'nada')
        line('nada')  # no task running: nothing happens

    def test_activity_pages_are_scoped(self):
        from .task_models import Task
        mine = Task.objects.create(kind='deploy', instance=self.alice_instance, created_by=self.alice, status='running',
                                   progress=30, step='Base de datos PostgreSQL', log='10:00:00 ▶ Base de datos PostgreSQL\n')
        other = Task.objects.create(kind='backup', instance=self.bob_instance, created_by=self.bob, status='done', log='secreto')
        self.client.force_login(self.alice)

        page = self.client.get(reverse('activity'))
        self.assertContains(page, 'Base de datos PostgreSQL')
        self.assertNotContains(page, 'secreto')
        self.assertContains(page, 'width: 30%')
        self.assertEqual(self.client.get(reverse('activity-detail', args=[other.pk])).status_code, 404)
        self.assertContains(self.client.get(reverse('activity-detail', args=[mine.pk])), 'Base de datos PostgreSQL')

        data = self.client.get(reverse('task-live'), {'ids': f'{mine.pk},{other.pk}'}).json()
        self.assertEqual([t['id'] for t in data['tasks']], [mine.pk])
        self.assertEqual((data['tasks'][0]['progress'], data['tasks'][0]['active']), (30, True))

        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('activity'), {'status': 'done'}), 'secreto')

    def test_sidebar_counts_the_running_tasks(self):
        from .task_models import Task
        Task.objects.create(kind='deploy', instance=self.alice_instance, created_by=self.alice, status='running')
        self.client.force_login(self.alice)
        response = self.client.get(reverse('activity'))
        self.assertEqual(response.context['nav_counts']['activity'], 1)


class PipInstallTests(BaseTestCase):
    """pip in an instance installs for the odoo user, on the data volume: it works on Odoo 17+ and lasts."""

    def test_command_rewrite(self):
        from .services.docker_service import pip_user_command
        self.assertEqual(pip_user_command('pip install websocket-client'), 'pip install --user --break-system-packages websocket-client')
        self.assertEqual(pip_user_command('pip3 install -r req.txt'), 'pip3 install --user --break-system-packages -r req.txt')
        self.assertEqual(pip_user_command('python3 -m pip install a b'), 'python3 -m pip install --user --break-system-packages a b')
        for command in ('pip install --user x', 'pip install -t /tmp x', 'pip list', 'ls -la'):
            self.assertEqual(pip_user_command(command), command)

    def test_old_pip_without_the_flag(self):
        from .services.docker_service import DockerService
        service = DockerService.__new__(DockerService)
        calls = []
        def execute(instance, command):
            calls.append(command)
            return '[Exit Code: 2]\nno such option: --break-system-packages' if 'break' in command else 'Successfully installed x'
        service.execute_command = execute
        self.assertEqual(service.pip_install(self.alice_instance, 'pip install x'), (True, 'Successfully installed x'))
        self.assertEqual(calls, ['pip install --user --break-system-packages x', 'pip install --user x'])

    def test_console_installs_for_the_odoo_user(self):
        import json
        self.docker.return_value.pip_install.return_value = (True, 'Successfully installed websocket-client')
        self.client.force_login(self.alice)
        response = self.client.post(reverse('instance-console-exec', args=[self.alice_instance.pk]),
                                    json.dumps({'command': 'pip install websocket-client'}), content_type='application/json')
        self.docker.return_value.pip_install.assert_called_once_with(self.alice_instance, 'pip install websocket-client')
        self.assertIn('se conserva al redesplegar', response.json()['output'])
        self.docker.return_value.execute_command.assert_not_called()


class BrowserTests(BaseTestCase):
    """Google Chrome in the Odoo container, for WhatsApp Web: installed from the panel and on every deploy."""

    def test_enable_and_disable(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        self.client.post(reverse('instance-browser', args=[self.alice_instance.pk]), {'enable': '1'})
        self.alice_instance.refresh_from_db()
        self.assertTrue(self.alice_instance.browser)
        self.assertEqual(Task.objects.get(instance=self.alice_instance).kind, 'install_browser')
        self.client.post(reverse('instance-browser', args=[self.alice_instance.pk]), {'enable': '0'})
        self.alice_instance.refresh_from_db()
        self.assertFalse(self.alice_instance.browser)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(reverse('instance-browser', args=[self.alice_instance.pk]), {'enable': '1'}).status_code, 404)

    def test_install_streams_and_reports(self):
        with mock.patch('orchestrator.services.docker_service.docker.from_env') as from_env:
            from .services import DockerService
            service = DockerService()
            api = from_env.return_value.api
        api.exec_create.return_value = {'Id': 'x'}
        api.exec_start.return_value = iter([b'Descargando Google Chrome...\n', b'Google Chrome 142.0.7444.59 \n'])
        api.exec_inspect.return_value = {'ExitCode': 0}
        container = mock.Mock(id='abc')
        self.assertEqual(service.install_browser(self.alice_instance, container), 'Navegador: Google Chrome 142.0.7444.59 ')
        self.assertEqual(api.exec_create.call_args.kwargs['user'], 'root')
        api.exec_start.return_value = iter([b'E: Unable to locate package\n'])
        api.exec_inspect.return_value = {'ExitCode': 100}
        with self.assertRaisesRegex(Exception, 'Unable to locate package'):
            service.install_browser(self.alice_instance, container)


class PullTests(BaseTestCase):
    """Pull: the repositories updated and Odoo restarted, in the worker, without redeploying."""

    def test_pull_is_queued_and_run(self):
        from io import StringIO
        from django.core.management import call_command
        from .task_models import Task
        self.alice_instance.github_repo = 'https://github.com/acme/addons'
        self.alice_instance.save()
        self.docker.return_value.pull_repositories.return_value = ['principal: abc1234 Fix the bridge']
        self.client.force_login(self.alice)
        response = self.client.post(reverse('instance-pull', args=[self.alice_instance.pk]))
        self.assertTrue(response.url.endswith('#tasks'))
        call_command('run_worker', once=True, stdout=StringIO())
        task = Task.objects.get(kind='pull_repos')
        self.assertEqual(task.status, 'done')
        self.assertIn('abc1234 Fix the bridge', task.result)
        self.docker.return_value.deploy_instance.assert_not_called()

    def test_nothing_to_pull(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        self.client.post(reverse('instance-pull', args=[self.alice_instance.pk]))
        self.assertFalse(Task.objects.filter(kind='pull_repos').exists())
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(reverse('instance-pull', args=[self.alice_instance.pk])).status_code, 404)


class GitHubServiceTests(TestCase):
    def test_token_is_redacted_from_errors(self):
        import subprocess
        from .services.github import create_branch
        error = subprocess.CalledProcessError(128, 'git', stderr='fatal: https://secret-token@github.com/x/y not found')
        with mock.patch('orchestrator.services.github.subprocess.run', side_effect=error):
            ok, message = create_branch('https://github.com/x/y', 'main', 'new', 'secret-token')
        self.assertFalse(ok)
        self.assertNotIn('secret-token', message)



class MediaServingTests(TestCase):
    def test_media_is_routed_regardless_of_debug(self):
        from django.urls import resolve
        from django.views.static import serve
        match = resolve('/media/avatars/a.png')
        self.assertIs(match.func, serve)
        self.assertEqual(match.kwargs['path'], 'avatars/a.png')


class PublishedPortTests(TestCase):
    def test_waits_until_docker_publishes_the_port(self):
        from .services import DockerService
        with mock.patch('orchestrator.services.docker_service.docker.from_env'):
            service = DockerService()
        container = mock.Mock()
        states = iter([{}, {'8069/tcp': None}, {'8069/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '55004'}]}])
        container.reload.side_effect = lambda: setattr(container, 'attrs', {'NetworkSettings': {'Ports': next(states)}})
        with mock.patch('time.sleep'):
            self.assertEqual(service._published_port(container, '8069/tcp'), 55004)



class ProjectTests(BaseTestCase):
    def test_projects_are_scoped_to_owner(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse('project-list'))
        self.assertContains(response, 'ACME')
        self.assertNotContains(response, 'Globex')
        self.assertEqual(self.client.get(reverse('project-detail', args=[self.bob_project.pk])).status_code, 404)

    def test_create_and_detail_show_project_instances(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse('project-create'), {'name': 'Initech', 'client': 'Initech Inc.'})
        from .project_models import Project
        project = Project.objects.get(name='Initech')
        self.assertEqual(project.owner, self.alice)
        self.assertRedirects(response, reverse('project-detail', args=[project.pk]), fetch_redirect_response=False)
        detail = self.client.get(reverse('project-detail', args=[self.alice_project.pk]))
        self.assertContains(detail, 'alice-odoo')

    def test_duplicate_project_name_is_rejected(self):
        self.client.force_login(self.alice)
        self.client.post(reverse('project-create'), {'name': 'acme'})
        from .project_models import Project
        self.assertEqual(Project.objects.filter(owner=self.alice).count(), 1)

    def test_instance_form_cannot_use_other_users_project(self):
        self.client.force_login(self.alice)
        with mock.patch('orchestrator.forms.requests'):
            self.client.post(reverse('instance-create'), {'name': 'sneaky', 'odoo_version': '17.0', 'project': self.bob_project.pk})
            self.client.post(reverse('instance-create'), {'name': 'orphan', 'odoo_version': '17.0'})
        self.assertFalse(Instance.objects.filter(name__in=['sneaky', 'orphan']).exists())

    def test_project_with_instances_cannot_be_deleted(self):
        self.client.force_login(self.alice)
        self.client.post(reverse('project-delete', args=[self.alice_project.pk]))
        from .project_models import Project
        self.assertTrue(Project.objects.filter(pk=self.alice_project.pk).exists())

    def test_instance_list_filters_by_project_and_shows_project_name(self):
        from .project_models import Project
        other = Project.objects.create(name='Other', owner=self.alice)
        Instance.objects.create(name='alice-other', owner=self.alice, project=other)
        self.client.force_login(self.alice)
        response = self.client.get(reverse('instance-list') + f'?project={other.pk}')
        self.assertContains(response, 'alice-other')
        self.assertNotContains(response, 'alice-odoo')
        self.assertContains(response, f'href="{reverse("project-detail", args=[other.pk])}"')


class EnsureImageTests(TestCase):
    def setUp(self):
        import docker
        patcher = mock.patch('orchestrator.services.docker_service.docker.from_env')
        self.client = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.client.images.get.side_effect = docker.errors.ImageNotFound('missing')
        from .services import DockerService
        self.service = DockerService()

    def test_falls_back_to_amd64_when_no_native_build(self):
        import docker
        self.client.images.pull.side_effect = [docker.errors.APIError('no matching manifest for linux/arm64/v8'), None]
        self.client.images.get.side_effect = [docker.errors.ImageNotFound('missing'), mock.Mock()]
        self.assertEqual(self.service._ensure_image('odoo:10.0'), 'linux/amd64')
        self.client.images.pull.assert_called_with('odoo', tag='10.0', platform='linux/amd64')

    def test_falls_back_when_docker_py_reports_no_such_image(self):
        import docker
        # What docker-py actually raises on arm64 for amd64-only images
        self.client.images.pull.side_effect = [docker.errors.ImageNotFound('no such image: odoo:10.0'), None]
        self.client.images.get.side_effect = [docker.errors.ImageNotFound('missing'), mock.Mock()]
        self.assertEqual(self.service._ensure_image('odoo:10.0'), 'linux/amd64')

    def test_other_pull_errors_are_reported(self):
        import docker
        self.client.images.pull.side_effect = docker.errors.APIError('manifest unknown')
        with self.assertRaisesMessage(Exception, 'No se pudo descargar la imagen odoo:99.0'):
            self.service._ensure_image('odoo:99.0')


class ClientTests(BaseTestCase):
    """A client is a user assigned to a project; flagged clients can't create anything."""

    def make_client(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('user-create'), {
            'username': 'veolia', 'email': 'ana@veolia.example', 'password': 'Cl1ent-pass-2026',
            'is_client': 'on', 'company': 'Veolia',
        })
        client_user = User.objects.get(username='veolia')
        self.alice_project.client = client_user
        self.alice_project.save()
        return client_user

    def test_user_form_marks_client(self):
        client_user = self.make_client()
        self.assertTrue(client_user.profile.is_client)
        self.assertEqual(client_user.profile.company, 'Veolia')

    def test_project_form_lets_admin_pick_any_user_as_client(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('project-edit', args=[self.alice_project.pk]),
                                    {'name': 'ACME', 'client': self.bob.pk, 'description': ''})
        self.assertEqual(response.status_code, 302)
        self.alice_project.refresh_from_db()
        self.assertEqual(self.alice_project.client, self.bob)

    def test_client_sees_and_operates_but_cannot_manage(self):
        client_user = self.make_client()
        self.client.force_login(client_user)
        pk = self.alice_instance.pk
        self.assertContains(self.client.get(reverse('project-list')), 'ACME')
        self.assertEqual(self.client.get(reverse('instance-detail', args=[pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('instance-detail', args=[self.bob_instance.pk])).status_code, 404)
        self.client.post(reverse('instance-deploy', args=[pk]))
        self.client.post(reverse('instance-backup', args=[pk]))
        from .task_models import Task
        self.assertEqual(set(Task.objects.values_list('kind', flat=True)), {'deploy', 'backup'})
        for name in ('instance-delete', 'instance-duplicate', 'instance-console-exec', 'instance-update-name', 'instance-restore'):
            self.assertEqual(self.client.post(reverse(name, args=[pk])).status_code, 403, name)
        self.assertEqual(self.client.post(reverse('project-edit', args=[self.alice_project.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('instance-create')).status_code, 403)
        self.assertEqual(self.client.get(reverse('project-create')).status_code, 403)
        self.assertEqual(self.client.get(reverse('container-create')).status_code, 403)
        self.assertTrue(Instance.objects.filter(pk=pk).exists())

    def test_assigned_regular_user_operates_but_does_not_manage(self):
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse('instance-detail', args=[self.alice_instance.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse('instance-delete', args=[self.alice_instance.pk])).status_code, 403)

    def test_client_api_is_read_and_operate_only(self):
        client_user = self.make_client()
        self.client.force_login(client_user)
        self.assertEqual([i['name'] for i in self.client.get('/api/instances/').json()], ['alice-odoo'])
        self.assertEqual(self.client.post(f'/api/instances/{self.alice_instance.pk}/deploy/').status_code, 202)
        self.assertEqual(self.client.delete(f'/api/instances/{self.alice_instance.pk}/').status_code, 403)
        self.assertEqual(self.client.post('/api/instances/', {'name': 'x', 'project': self.alice_project.pk}).status_code, 403)


class BackupListTests(BaseTestCase):
    def test_lists_only_visible_backups_and_filters_by_project(self):
        Backup.objects.create(instance=self.alice_instance, filename='alice.zip', file_path='/x/a.zip', file_size=10)
        Backup.objects.create(instance=self.bob_instance, filename='bob.zip', file_path='/x/b.zip', file_size=10)
        self.client.force_login(self.alice)
        response = self.client.get(reverse('backup-list'))
        self.assertContains(response, 'alice.zip')
        self.assertNotContains(response, 'bob.zip')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('backup-list') + f'?project={self.bob_project.pk}')
        self.assertContains(response, 'bob.zip')
        self.assertNotContains(response, 'alice.zip')


class DockerAdminTests(BaseTestCase):
    def test_docker_menu_is_admin_only(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('docker-overview')).status_code, 403)
        self.assertEqual(self.client.post(reverse('docker-prune', args=['volumes'])).status_code, 403)

    def test_panel_containers_are_protected(self):
        from .services import docker_admin
        panel = mock.Mock(labels={'com.docker.compose.project': 'community-sh'}, name='community-sh-db-1')
        with mock.patch('orchestrator.services.docker_admin._client') as client:
            client.return_value.containers.get.return_value = panel
            with self.assertRaises(PermissionError):
                docker_admin.container_action('abc', 'stop')
        panel.stop.assert_not_called()

    def test_volume_prune_requires_typed_confirmation(self):
        self.client.force_login(self.admin)
        with mock.patch('orchestrator.services.docker_admin.prune') as prune:
            self.client.post(reverse('docker-prune', args=['volumes']))
            prune.assert_not_called()
            prune.return_value = (2, 1024)
            self.client.post(reverse('docker-prune', args=['volumes']), {'confirm': 'BORRAR'})
            prune.assert_called_once_with('volumes')

    def test_cleanup_keeps_stopped_instances_and_app_containers(self):
        from .services import docker_admin
        Container.objects.create(name='redis1', image='redis', port=40020, container_port=6379, created_by=self.admin)

        def named(name, attrs=None, **fields):
            obj = mock.Mock(attrs=attrs or {}, **fields)
            obj.name = name
            return obj

        def container(name, status, image, volumes=(), networks=(), labels=None):
            return named(name, id=name, status=status, labels=labels or {}, attrs={
                'Image': image, 'HostConfig': {'NetworkMode': 'default'},
                'NetworkSettings': {'Networks': {n: {} for n in networks}},
                'Mounts': [{'Type': 'volume', 'Name': v} for v in volumes],
            })

        client = mock.Mock()
        client.containers.list.return_value = [
            container('odoo_alice-odoo', 'exited', 'sha-odoo', ['odoo_data_alice-odoo'], ['net_alice-odoo']),
            container('db_alice-odoo', 'exited', 'sha-pg', ['anon-pg'], ['net_alice-odoo']),
            container('redis1', 'exited', 'sha-redis'),
            container('community-sh-db-1', 'exited', 'sha-pg', labels={'com.docker.compose.project': 'community-sh'}),
            container('leftover', 'exited', 'sha-old', ['anon-leftover'], ['net_gone']),
        ]
        client.images.list.return_value = [
            mock.Mock(id=i, short_id=i, tags=tags, attrs={'Size': 100})
            for i, tags in [('sha-odoo', ['odoo:18.0']), ('sha-pg', ['postgres:16']), ('sha-redis', ['redis:7']),
                            ('sha-old', ['old:1']), ('sha-dangling', []), ('sha-spare', ['odoo:16.0'])]
        ]
        client.networks.list.return_value = [named(n) for n in ('bridge', 'net_alice-odoo', 'net_gone', 'community-sh_default')]
        client.volumes.list.return_value = [named(v) for v in (
            'odoo_data_alice-odoo', 'anon-pg', 'anon-leftover', 'redis1_data', 'community-sh_pgdata', 'odoo_data_deleted')]
        df = {'Containers': [{'Id': 'leftover', 'SizeRw': 5}], 'Volumes': [{'Name': 'odoo_data_deleted', 'UsageData': {'Size': 7}}],
              'BuildCache': [{'ID': 'b1', 'Size': 9, 'InUse': False}, {'ID': 'b2', 'Size': 9, 'InUse': True}]}

        plan = docker_admin.cleanup_plan(client, df)
        names = {kind: [name for name, _, _ in items] for kind, items in plan.items()}
        self.assertEqual(names['containers'], ['leftover'])
        self.assertEqual(names['images'], ['sha-dangling'])
        self.assertEqual(names['unused_images'], ['old:1', 'odoo:16.0'])
        self.assertEqual(names['build_cache'], ['b1'])
        self.assertEqual(names['networks'], ['net_gone'])
        self.assertEqual(names['volumes'], ['anon-leftover', 'odoo_data_deleted'])

        # Without removing the stopped containers, what the leftover one uses stays
        names = {kind: [n for n, _, _ in items] for kind, items in docker_admin.cleanup_plan(client, df, remove_stopped=False).items()}
        self.assertEqual(names['unused_images'], ['odoo:16.0'])
        self.assertEqual(names['volumes'], ['odoo_data_deleted'])

    def test_cleanup_is_queued_and_volumes_need_confirmation(self):
        from .task_models import Task
        self.client.force_login(self.admin)
        self.client.post(reverse('docker-cleanup'), {'kinds': ['containers', 'volumes']})
        self.assertFalse(Task.objects.exists())
        self.client.post(reverse('docker-cleanup'), {'kinds': ['containers', 'volumes', 'everything'], 'confirm': 'BORRAR'})
        self.assertEqual(Task.objects.get().params['kinds'], ['containers', 'volumes'])
        self.client.force_login(self.alice)
        self.assertEqual(self.client.post(reverse('docker-cleanup'), {'kinds': ['images']}).status_code, 403)

    def test_cleanup_waits_for_a_running_build(self):
        from .task_models import Task
        from .tasks import enqueue, run_task
        Task.objects.create(kind=Task.Kind.BUILD_CONTAINER, status=Task.Status.RUNNING)
        with mock.patch('orchestrator.services.docker_admin.cleanup') as cleanup:
            task = run_task(enqueue(Task.Kind.DOCKER_CLEANUP, user=self.admin, kinds=['images']))
            cleanup.assert_not_called()
        self.assertEqual(task.status, Task.Status.FAILED)

    def test_a_new_instance_is_followed_by_one_automatic_cleanup(self):
        from .task_models import Task
        from .tasks import AUTO_CLEANUP_KINDS, HANDLERS, enqueue, run_task
        cleanups = Task.objects.filter(kind=Task.Kind.DOCKER_CLEANUP)
        with mock.patch.dict(HANDLERS, {Task.Kind.DEPLOY: lambda task: 'ok', Task.Kind.DUPLICATE: lambda task: 'ok'}):
            # A redeploy is not a new instance
            run_task(enqueue(Task.Kind.DEPLOY, self.alice_instance, self.alice))
            self.assertFalse(cleanups.exists())
            run_task(enqueue(Task.Kind.DEPLOY, self.alice_instance, self.alice, created=True))
            run_task(enqueue(Task.Kind.DUPLICATE, self.alice_instance, self.alice, new_name='copy'))
        cleanup = cleanups.get()
        self.assertEqual(cleanup.params, {'kinds': AUTO_CLEANUP_KINDS, 'auto': True})
        self.assertNotIn('volumes', AUTO_CLEANUP_KINDS)
        self.assertIn('unused_images', AUTO_CLEANUP_KINDS)
        # A failed creation doesn't queue one; once it ran, the next instance queues another
        with mock.patch('orchestrator.services.docker_admin.cleanup', return_value={'images': (2, 300)}) as docker_cleanup:
            self.assertEqual(run_task(cleanup).status, Task.Status.DONE)
            docker_cleanup.assert_called_once()
        with mock.patch.dict(HANDLERS, {Task.Kind.DEPLOY: mock.Mock(side_effect=Exception('boom'))}):
            run_task(enqueue(Task.Kind.DEPLOY, self.alice_instance, self.alice, created=True))
        self.assertEqual(cleanups.count(), 1)
        # While a container builds, the automatic one is skipped instead of failing
        Task.objects.create(kind=Task.Kind.BUILD_CONTAINER, status=Task.Status.RUNNING)
        with mock.patch('orchestrator.services.docker_admin.cleanup') as docker_cleanup:
            task = run_task(enqueue(Task.Kind.DOCKER_CLEANUP, kinds=AUTO_CLEANUP_KINDS, auto=True))
            docker_cleanup.assert_not_called()
        self.assertEqual(task.status, Task.Status.DONE)

    def test_creating_an_instance_marks_its_deploy(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        response = self.client.post('/api/instances/', {'name': 'auto-clean', 'project': self.alice_project.pk},
                                    content_type='application/json')
        self.assertTrue(Task.objects.get(pk=response.json()['task_id']).params['created'])

    def test_dashboard_cleanup_button_for_administrators(self):
        from .task_models import Task
        from .tasks import AUTO_CLEANUP_KINDS
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/dashboard/'), reverse('docker-cleanup-unused'))
        self.assertRedirects(self.client.post(reverse('docker-cleanup-unused')), '/dashboard/', fetch_redirect_response=False)
        self.client.post(reverse('docker-cleanup-unused'))  # one in the queue is enough
        self.assertEqual(Task.objects.get(kind=Task.Kind.DOCKER_CLEANUP).params['kinds'], AUTO_CLEANUP_KINDS)
        self.client.force_login(self.alice)
        self.assertNotContains(self.client.get('/dashboard/'), reverse('docker-cleanup-unused'))
        self.assertEqual(self.client.post(reverse('docker-cleanup-unused')).status_code, 403)

    def test_help_page_is_in_the_menu_and_covers_every_section(self):
        from .views.public import HELP_SECTIONS
        self.client.force_login(self.alice)
        page = self.client.get(reverse('help')).content.decode()
        for anchor, title, _ in HELP_SECTIONS:
            self.assertIn(f'id="{anchor}"', page)
            self.assertIn(title, page)
        self.assertIn('Cómo funciona cada proceso', page)
        self.assertIn(f'href="{reverse("help")}"', self.client.get('/dashboard/').content.decode())
        # In English: the English page, with the same sections, and the menu entry translated
        self.client.cookies['django_language'] = 'en'
        page = self.client.get(reverse('help')).content.decode()
        self.assertIn('How every process in Community SH works', page)
        for anchor, _, title in HELP_SECTIONS:
            self.assertIn(f'id="{anchor}"', page)
            self.assertIn(title, page)
        self.assertIn('>Help</span>', page)

    def test_pull_is_queued_and_validated(self):
        from .task_models import Task
        self.client.force_login(self.admin)
        self.client.post(reverse('docker-image-pull'), {'image': 'odoo:18.0'})
        self.client.post(reverse('docker-image-pull'), {'image': 'bad image; rm -rf /'})
        self.assertEqual(list(Task.objects.values_list('params__image', flat=True)), ['odoo:18.0'])


class LanguageTests(TestCase):
    @override_settings(ALLOWED_HOSTS=['*'])
    def test_landing_in_english_and_spanish(self):
        self.assertContains(self.client.get('/', HTTP_ACCEPT_LANGUAGE='en'), 'Your own Odoo hosting,')
        self.assertContains(self.client.get('/', HTTP_ACCEPT_LANGUAGE='es'), 'Tu propio hosting de Odoo,')

    @override_settings(ALLOWED_HOSTS=['*'])
    def test_language_switch_is_remembered(self):
        self.client.post('/i18n/setlang/', {'language': 'en', 'next': '/'})
        self.assertContains(self.client.get('/'), 'Features')



class PostgresVersionTests(TestCase):
    def test_each_odoo_version_gets_a_supported_postgres(self):
        from .services.docker_service import postgres_image
        expected = {'8.0': 'postgres:9.6', '9.0': 'postgres:9.6', '10.0': 'postgres:10', '11.0': 'postgres:10', '12.0': 'postgres:12', '13.0': 'postgres:12',
                    '14.0': 'postgres:13', '15.0': 'postgres:13', '16.0': 'postgres:15', '17.0': 'postgres:15',
                    '18.0': 'postgres:16', '19.0': 'postgres:16', '20.0': 'postgres:16'}
        choices = [v for v, _ in Instance._meta.get_field('odoo_version').choices]
        self.assertEqual(sorted(expected), sorted(choices))
        for version, image in expected.items():
            self.assertEqual(postgres_image(version), image, version)

    def test_empty_db_with_wrong_postgres_is_recreated_but_data_is_kept(self):
        with mock.patch('orchestrator.services.docker_service.docker.from_env') as from_env:
            from .services import DockerService
            service = DockerService()
            client = from_env.return_value
        instance = Instance(name='twenty', odoo_version='20.0')
        old_db = mock.Mock(status='running', attrs={'Config': {'Image': 'postgres:13'}})
        client.containers.get.return_value = old_db
        with mock.patch.object(service, '_wait_for_postgres'), mock.patch.object(service, '_ensure_image'):
            with mock.patch.object(service, '_list_user_databases', return_value=[]):
                notes = []
                service._ensure_db_container(instance, 'net_twenty', notes)
            old_db.remove.assert_called_once_with(force=True, v=True)
            self.assertEqual(client.containers.run.call_args.args[0], 'postgres:16')

            old_db.reset_mock(); client.containers.run.reset_mock()
            with mock.patch.object(service, '_list_user_databases', return_value=['prod']):
                notes = []
                service._ensure_db_container(instance, 'net_twenty', notes)
            old_db.remove.assert_not_called()
            client.containers.run.assert_not_called()
            self.assertIn('ya tiene datos', notes[0])

    def test_restart_starts_a_stopped_database_first(self):
        with mock.patch('orchestrator.services.docker_service.docker.from_env') as from_env:
            from .services import DockerService
            service = DockerService()
            client = from_env.return_value
        instance = Instance.objects.create(name='rebooted', container_id='abc')
        db = mock.Mock(status='exited', attrs={'HostConfig': {'RestartPolicy': {'Name': 'no'}}})
        odoo = mock.Mock(status='exited', attrs={'HostConfig': {'RestartPolicy': {'Name': 'no'}}})
        order = mock.Mock()
        order.attach_mock(db.start, 'db_start'); order.attach_mock(odoo.restart, 'odoo_restart')
        client.containers.get.side_effect = lambda name: db if name == 'db_rebooted' else odoo
        with mock.patch.object(service, '_wait_for_postgres'):
            service.restart_instance(instance)
        self.assertEqual([c[0] for c in order.mock_calls], ['db_start', 'odoo_restart'])
        db.update.assert_called_once_with(restart_policy={'Name': 'unless-stopped'})
        odoo.update.assert_called_once_with(restart_policy={'Name': 'unless-stopped'})

    def test_instance_containers_come_back_after_a_reboot(self):
        with mock.patch('orchestrator.services.docker_service.docker.from_env') as from_env:
            from .services import DockerService
            service = DockerService()
            client = from_env.return_value
        instance = Instance(name='twenty', odoo_version='20.0')
        # A database created before the restart policy gets it when it is reused
        old_db = mock.Mock(status='running', attrs={'Config': {'Image': 'postgres:16'}, 'HostConfig': {'RestartPolicy': {'Name': 'no'}}})
        client.containers.get.return_value = old_db
        service._ensure_db_container(instance, 'net_twenty', [])
        old_db.update.assert_called_once_with(restart_policy={'Name': 'unless-stopped'})
        # A new one is created with it
        import docker
        client.containers.get.side_effect = docker.errors.NotFound('no')
        with mock.patch.object(service, '_ensure_image'):
            service._ensure_db_container(instance, 'net_twenty', [])
        self.assertEqual(client.containers.run.call_args.kwargs['restart_policy'], {'Name': 'unless-stopped'})


class VersionTests(TestCase):
    def test_current_version_is_documented(self):
        from django.conf import settings
        from config.version import CHANGELOG, VERSION
        self.assertEqual(CHANGELOG[0]['version'], VERSION)
        with open(settings.BASE_DIR / 'CHANGELOG.md', encoding='utf-8') as f:
            self.assertIn(f'## {VERSION} ', f.read())


class AIAssistantTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        import tempfile, shutil
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        settings_patch = override_settings(BASE_DIR=self.tmp)
        settings_patch.enable()
        self.addCleanup(settings_patch.disable)
        self.config.ai_enabled = True
        self.config.openai_api_key = 'sk-test'
        self.config.openai_model = 'gpt-test'
        self.config.save()

    def test_tools_stay_inside_the_addons_folder(self):
        from .services.ai_assistant import run_tool
        result = run_tool(self.alice_instance, self.alice, 'write_file', {'path': 'my_mod/__init__.py', 'content': 'x = 1\n'})
        self.assertIn('Escrito', result)
        self.assertEqual(run_tool(self.alice_instance, self.alice, 'read_file', {'path': 'my_mod/__init__.py'}), 'x = 1\n')
        self.assertIn('my_mod/__init__.py', run_tool(self.alice_instance, self.alice, 'list_files', {}))
        # The addons folder itself as a prefix is the same path
        run_tool(self.alice_instance, self.alice, 'write_file', {'path': 'addons/other/__init__.py', 'content': ''})
        run_tool(self.alice_instance, self.alice, 'write_file', {'path': '/mnt/extra-addons/third/__init__.py', 'content': ''})
        listed = run_tool(self.alice_instance, self.alice, 'list_files', {})
        self.assertIn('other/__init__.py', listed)
        self.assertIn('third/__init__.py', listed)
        self.assertNotIn('addons/other', listed)
        for evil in ('../../etc/passwd', '/etc/passwd', 'my_mod/../../../x', 'addons/../../x'):
            self.assertIn('dentro de la carpeta de addons', run_tool(self.alice_instance, self.alice, 'write_file', {'path': evil, 'content': 'x'}))

    def test_write_file_rejects_what_odoo_would_skip(self):
        from .services.ai_assistant import run_tool
        write = lambda path, content: run_tool(self.alice_instance, self.alice, 'write_file', {'path': path, 'content': content})
        self.assertIn('True/False', write('m/__manifest__.py', '{"name": "M", "installable": true}'))
        self.assertIn('sintaxis', write('m/models.py', 'def broken(:\n'))
        self.assertIn('XML mal formado', write('m/views.xml', '<odoo><record></odoo>'))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'instances', 'alice-odoo', 'addons', 'm', '__manifest__.py')))
        self.assertIn('Escrito', write('m/__manifest__.py', "{'name': 'M', 'installable': True}"))

    def test_install_errors_are_summarised_by_whole_lines(self):
        from .services.ai_assistant import install_error_summary
        log = '\n'.join(['INFO loading'] * 50 + ['  File "/odoo/registry.py", line 86, in new', 'odoo.exceptions.UserError: depends on contacts'])
        summary = install_error_summary(log, limit=60)
        self.assertEqual(summary, 'odoo.exceptions.UserError: depends on contacts')

    def test_install_tool_queues_a_task(self):
        from .services.ai_assistant import run_tool
        from .task_models import Task
        run_tool(self.alice_instance, self.alice, 'install_module', {'module': 'my_mod', 'upgrade': True})
        task = Task.objects.get(kind='ai_module')
        self.assertEqual(task.params, {'module': 'my_mod', 'upgrade': True})
        self.assertIn('inválido', run_tool(self.alice_instance, self.alice, 'install_module', {'module': 'x; rm -rf /'}))

    def test_chat_runs_tools_until_the_model_answers(self):
        import json
        replies = [
            {'content': None, 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {
                'name': 'write_file', 'arguments': json.dumps({'path': 'hello/__manifest__.py', 'content': "{'name': 'Hello'}"})}}]},
            {'content': 'Listo: módulo hello creado.'},
        ]
        self.client.force_login(self.alice)
        with mock.patch('orchestrator.services.ai_assistant.chat', side_effect=replies) as chat:
            response = self.client.post(reverse('instance-ai-chat', args=[self.alice_instance.pk]),
                                        json.dumps({'message': 'crea hello'}), content_type='application/json')
            # Queued for the AI worker; a second request waits for it
            self.assertTrue(response.json()['running'])
            self.assertEqual(self.client.post(reverse('instance-ai-chat', args=[self.alice_instance.pk]),
                                              json.dumps({'message': 'otra'}), content_type='application/json').status_code, 409)
            self.run_ai_worker()
        data = self.client.get(reverse('instance-ai-chat', args=[self.alice_instance.pk])).json()
        self.assertFalse(data['running'])
        self.assertEqual([m['role'] for m in data['messages']], ['user', 'assistant', 'assistant'])
        self.assertEqual(data['messages'][1]['tools'], [{'name': 'write_file', 'target': 'hello/__manifest__.py'}])
        self.assertEqual(data['messages'][2]['content'], 'Listo: módulo hello creado.')
        # The second call included the tool result
        history = chat.call_args_list[1].args[1]
        self.assertTrue(any(m['role'] == 'tool' and m['tool_call_id'] == 'c1' for m in history))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'instances', 'alice-odoo', 'addons', 'hello', '__manifest__.py')))

    def run_ai_worker(self):
        from io import StringIO
        from django.core.management import call_command
        call_command('run_worker', once=True, only=['ai_chat'], stdout=StringIO())

    def test_pdf_attachment_plan_and_stop(self):
        import json
        from django.core.cache import cache
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .services.ai_assistant import stop_key
        from .task_models import Task
        replies = [
            {'content': None, 'tool_calls': [{'id': 'p1', 'type': 'function', 'function': {'name': 'update_plan', 'arguments': json.dumps(
                {'steps': [{'step': 'Leer el PDF', 'status': 'done'}, {'step': 'Crear el módulo', 'status': 'in_progress'}]})}}]},
            {'content': 'Hecho.'},
        ]
        self.client.force_login(self.alice)
        url = reverse('instance-ai-chat', args=[self.alice_instance.pk])
        pdf = SimpleUploadedFile('spec.pdf', b'%PDF-1.4 fake', content_type='application/pdf')
        self.assertEqual(self.client.post(url, {'message': 'x', 'files': [SimpleUploadedFile('x.exe', b'MZ')]}).status_code, 400)
        self.client.post(url, {'message': 'Implementa lo del PDF', 'modules': '[]', 'files': [pdf]})
        with mock.patch('orchestrator.services.ai_assistant.chat', side_effect=replies) as chat:
            self.run_ai_worker()
        # The PDF went to the model as a file part
        user_content = chat.call_args_list[0].args[1][1]['content']
        self.assertEqual(user_content[1]['type'], 'file')
        self.assertTrue(user_content[1]['file']['file_data'].startswith('data:application/pdf;base64,'))
        user = self.client.get(url).json()['messages'][0]
        self.assertEqual(user['attachments'], [{'name': 'spec.pdf', 'size': 13, 'type': 'application/pdf'}])
        self.assertEqual([s['status'] for s in user['plan']], ['done', 'in_progress'])

        # Stop: the worker ends the turn before calling the model again
        self.client.post(url, json.dumps({'message': 'sigue'}), content_type='application/json')
        task = Task.objects.filter(kind='ai_chat').order_by('-id').first()
        task.status = Task.Status.RUNNING
        task.save()
        self.assertEqual(self.client.post(reverse('instance-ai-stop', args=[self.alice_instance.pk])).status_code, 200)
        self.assertTrue(cache.get(stop_key(task.params['turn'])))
        task.status = Task.Status.PENDING
        task.save()
        with mock.patch('orchestrator.services.ai_assistant.chat') as chat:
            self.run_ai_worker()
        chat.assert_not_called()
        self.assertIn('Detenido', self.client.get(url).json()['messages'][-1]['content'])

    def test_multi_step_requests_start_with_a_plan_and_close_it(self):
        import json
        plan = lambda status: {'content': None, 'tool_calls': [{'id': f'p-{status}', 'type': 'function', 'function': {
            'name': 'update_plan', 'arguments': json.dumps({'steps': [{'step': 'Crear', 'status': status}, {'step': 'Instalar', 'status': status}]})}}]}
        replies = [plan('pending'), {'content': 'Listo'}, plan('done')]
        self.client.force_login(self.alice)
        url = reverse('instance-ai-chat', args=[self.alice_instance.pk])
        self.client.post(url, json.dumps({'message': 'Tareas:\n1. crear\n2. campo\n3. instalar'}), content_type='application/json')
        with mock.patch('orchestrator.services.ai_assistant.chat', side_effect=replies) as chat:
            self.run_ai_worker()
        # First call forced to plan; the answer with open steps triggered one forced plan update
        self.assertEqual(chat.call_args_list[0].kwargs['tool_choice']['function']['name'], 'update_plan')
        self.assertIsNone(chat.call_args_list[1].kwargs['tool_choice'])
        self.assertEqual(chat.call_args_list[2].kwargs['tool_choice']['function']['name'], 'update_plan')
        messages = self.client.get(url).json()['messages']
        self.assertEqual([s['status'] for s in messages[0]['plan']], ['done', 'done'])
        # Plan-only assistant messages are not shown as chat bubbles
        self.assertEqual([m['content'] for m in messages[1:]], ['Listo'])

    def test_unanswered_tool_calls_are_dropped_from_history(self):
        from .services.ai_assistant import clean_history
        history = [
            {'role': 'user', 'content': 'a'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'lost', 'function': {'name': 'x'}}]},
            {'role': 'assistant', 'content': 'ok', 'tool_calls': [{'id': 't1', 'function': {'name': 'x'}}]},
            {'role': 'tool', 'tool_call_id': 't1', 'content': 'r'},
        ]
        self.assertEqual([m['role'] for m in clean_history(history)], ['user', 'assistant', 'tool'])

    def test_chat_needs_manage_permission_and_configuration(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse('instance-ai-chat', args=[self.alice_instance.pk])).status_code, 404)
        self.config.ai_enabled = False
        self.config.save()
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('instance-ai-chat', args=[self.alice_instance.pk])).status_code, 400)

    def test_settings_saves_ai_config_and_keeps_key_when_blank(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('settings'), {'section': 'ia', 'ai_enabled': 'on', 'openai_api_key': '', 'openai_model': 'gpt-x'})
        self.config.refresh_from_db()
        self.assertEqual((self.config.openai_api_key, self.config.openai_model, self.config.ai_enabled), ('sk-test', 'gpt-x', True))


class RepositoryTests(BaseTestCase):
    def test_slug_and_url_validation(self):
        from .repository_models import InstanceRepository
        self.assertEqual(InstanceRepository(url='https://github.com/OCA/web.git').slug, 'OCA-web')
        self.client.force_login(self.alice)
        add = reverse('instance-repo-add', args=[self.alice_instance.pk])
        self.client.post(add, {'url': 'https://github.com/OCA/web.git', 'branch': '17.0'})
        self.client.post(add, {'url': 'git@github.com:OCA/web.git', 'branch': '17.0'})
        self.client.post(add, {'url': 'https://github.com/OCA/web.git', 'branch': '17.0'})
        self.client.post(add, {'url': 'https://github.com/OCA/server-tools', 'branch': '17.0; rm -rf /'})
        self.assertEqual(list(self.alice_instance.repositories.values_list('url', 'branch')), [('https://github.com/OCA/web.git', '17.0')])

    def test_only_managers_edit_repositories(self):
        self.client.force_login(self.bob)
        response = self.client.post(reverse('instance-repo-add', args=[self.alice_instance.pk]), {'url': 'https://github.com/OCA/web.git'})
        self.assertEqual(response.status_code, 404)

    def test_repositories_through_the_api(self):
        self.client.force_login(self.alice)
        url = f'/api/instances/{self.alice_instance.pk}/repositories/'
        response = self.client.post(url, {'url': 'https://github.com/odoo/enterprise', 'branch': '19.0'}, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        repo_id = response.json()['id']
        self.assertEqual(response.json()['folder'], 'odoo-enterprise')
        self.assertEqual(self.client.get(url).json()[0]['branch'], '19.0')
        # Same checks as the web form: duplicates, invalid URL or branch
        for data in ({'url': 'https://github.com/odoo/enterprise', 'branch': '19.0'}, {'url': 'git@github.com:odoo/enterprise.git'},
                     {'url': 'https://github.com/OCA/web', 'branch': '19.0; rm -rf /'}):
            self.assertEqual(self.client.post(url, data, content_type='application/json').status_code, 400)
        # Clients of the project read but don't change them
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {'url': 'https://github.com/OCA/web'}, content_type='application/json').status_code, 403)
        self.assertEqual(self.client.delete(f'{url}{repo_id}/').status_code, 403)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.delete(f'{url}{repo_id}/').status_code, 204)
        self.assertFalse(self.alice_instance.repositories.exists())
        self.assertEqual(self.client.delete(f'{url}{repo_id}/').status_code, 404)


class RepositorySyncTests(DockerServiceTests):
    def test_deploy_clones_extra_repos_into_addons_path(self):
        import os
        self.instance.repositories.create(url='https://github.com/OCA/web.git', branch='17.0')
        self.client.containers.get.side_effect = self.not_found
        odoo = self.client.containers.run.return_value
        odoo.id = 'abc'
        odoo.attrs = {'NetworkSettings': {'Ports': {'8069/tcp': [{'HostPort': '1'}]}}}

        def fake_clone(url, target, **kwargs):
            os.makedirs(os.path.join(target, '.git'))
            repo = mock.Mock()
            fake_clone.repo = repo
            return repo
        with mock.patch('orchestrator.services.docker_service.git.Repo.clone_from', side_effect=fake_clone) as clone, \
                mock.patch.dict('os.environ', {'HOST_WORKDIR': ''}):
            service = self._service()
            with mock.patch.object(service, '_github_token', return_value='ghp_secret'):
                service.deploy_instance(self.instance)
        self.assertEqual(clone.call_args.args[0], 'https://x-access-token:ghp_secret@github.com/OCA/web.git')
        # Token used to clone, then removed from the remote
        fake_clone.repo.remotes.origin.set_url.assert_called_with('https://github.com/OCA/web.git')
        with open(f'{self.tmp}/instances/acme/conf/odoo.conf') as f:
            self.assertIn('addons_path = /mnt/extra-addons,/mnt/repos/OCA-web', f.read())
        odoo_call = [c for c in self.client.containers.run.call_args_list if c.args[0].startswith('odoo:')][0]
        self.assertEqual(odoo_call.kwargs['volumes'][f'{self.tmp}/instances/acme/repos']['bind'], '/mnt/repos')


class MCPServerTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.config.mcp_enabled = True
        self.config.save()
        from .mcp_models import MCPToken
        self.token_record, self.token = MCPToken.issue(self.alice, 'test')

    def rpc(self, method, params=None, token=None, request_id=1):
        import json
        body = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
        if request_id is not None:
            body['id'] = request_id
        return self.client.post('/mcp/', json.dumps(body), content_type='application/json',
                                HTTP_AUTHORIZATION=f'Bearer {token or self.token}')

    def test_token_is_stored_hashed(self):
        self.assertNotEqual(self.token_record.token_hash, self.token)
        self.assertTrue(self.token.startswith('csh_'))

    def test_auth_and_enable_switch(self):
        self.assertEqual(self.rpc('ping', token='csh_wrong').status_code, 401)
        self.assertEqual(self.client.get('/mcp/').status_code, 405)
        self.config.mcp_enabled = False
        self.config.save()
        self.assertEqual(self.rpc('ping').status_code, 404)

    def test_initialize_and_list_tools(self):
        init = self.rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'claude'}}).json()
        self.assertEqual(init['result']['protocolVersion'], '2025-06-18')
        self.assertIn('tools', init['result']['capabilities'])
        self.assertEqual(self.rpc('notifications/initialized', request_id=None).status_code, 202)
        names = {t['name'] for t in self.rpc('tools/list').json()['result']['tools']}
        self.assertTrue({'list_instances', 'deploy_instance', 'create_backup', 'get_task'} <= names)

    def test_repository_tools(self):
        import json
        args = {'instance': 'alice-odoo', 'url': 'https://github.com/odoo/enterprise', 'branch': '19.0'}
        added = self.rpc('tools/call', {'name': 'add_instance_repository', 'arguments': args}).json()['result']
        self.assertFalse(added['isError'])
        self.assertEqual(json.loads(added['content'][0]['text'])['folder'], 'odoo-enterprise')
        self.assertTrue(self.rpc('tools/call', {'name': 'add_instance_repository', 'arguments': args}).json()['result']['isError'])
        denied = self.rpc('tools/call', {'name': 'add_instance_repository',
                                         'arguments': dict(args, instance='bob-odoo')}).json()['result']
        self.assertTrue(denied['isError'])
        removed = self.rpc('tools/call', {'name': 'remove_instance_repository',
                                          'arguments': {'instance': 'alice-odoo', 'url': args['url']}}).json()['result']
        self.assertFalse(removed['isError'])
        self.assertFalse(self.alice_instance.repositories.exists())

    def test_reset_admin_password_through_mcp_and_api(self):
        import json
        from .task_models import Task
        result = self.rpc('tools/call', {'name': 'reset_admin_password', 'arguments': {'instance': 'alice-odoo'}}).json()['result']
        data = json.loads(result['content'][0]['text'])
        self.assertGreaterEqual(len(data['password']), 12)
        self.assertEqual(Task.objects.get(pk=data['task_id']).params['password'], data['password'])
        bad = self.rpc('tools/call', {'name': 'reset_admin_password', 'arguments': {'instance': 'alice-odoo', 'password': "x' or 1=1"}})
        self.assertTrue(bad.json()['result']['isError'])
        # get_instance shows the administrator to who manages it
        Instance.objects.filter(pk=self.alice_instance.pk).update(admin_login='admin', admin_password='Known-pass-1')
        info = json.loads(self.rpc('tools/call', {'name': 'get_instance', 'arguments': {'instance': 'alice-odoo'}}).json()['result']['content'][0]['text'])
        self.assertEqual(info['administrator']['password'], 'Known-pass-1')
        # API
        import json as _json
        response = self.client.post(f'/api/instances/{self.alice_instance.pk}/reset-admin-password/', _json.dumps({'password': 'Chosen_pass-9'}),
                                    content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {self.token}')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['password'], 'Chosen_pass-9')
        self.assertEqual(self.client.post(f'/api/instances/{self.alice_instance.pk}/reset-admin-password/', _json.dumps({'password': 'short'}),
                                          content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {self.token}').status_code, 400)
        # Clients of the project can't, and don't see the administrator
        self.alice_project.client = self.bob
        self.alice_project.save()
        from .mcp_models import MCPToken
        _, bob_token = MCPToken.issue(self.bob, 'bob')
        denied = self.rpc('tools/call', {'name': 'reset_admin_password', 'arguments': {'instance': 'alice-odoo'}}, token=bob_token)
        self.assertTrue(denied.json()['result']['isError'])
        info = json.loads(self.rpc('tools/call', {'name': 'get_instance', 'arguments': {'instance': 'alice-odoo'}}, token=bob_token).json()['result']['content'][0]['text'])
        self.assertNotIn('administrator', info)
        self.assertEqual(self.client.post(f'/api/instances/{self.alice_instance.pk}/reset-admin-password/', '{}',
                                          content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {bob_token}').status_code, 403)

    def test_tools_respect_permissions(self):
        import json
        result = self.rpc('tools/call', {'name': 'list_instances', 'arguments': {}}).json()['result']
        self.assertEqual([i['name'] for i in json.loads(result['content'][0]['text'])], ['alice-odoo'])
        denied = self.rpc('tools/call', {'name': 'deploy_instance', 'arguments': {'instance': 'bob-odoo'}}).json()['result']
        self.assertTrue(denied['isError'])

    def test_deploy_queues_a_task_and_get_task_reports_it(self):
        import json
        out = json.loads(self.rpc('tools/call', {'name': 'deploy_instance', 'arguments': {'instance': 'alice-odoo'}}).json()['result']['content'][0]['text'])
        task = json.loads(self.rpc('tools/call', {'name': 'get_task', 'arguments': {'task_id': out['task_id']}}).json()['result']['content'][0]['text'])
        self.assertEqual((task['kind'], task['status'], task['instance']), ('deploy', 'pending', 'alice-odoo'))

    def test_batch_and_unknown_method(self):
        import json
        response = self.client.post('/mcp/', json.dumps([
            {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'nope'},
        ]), content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {self.token}')
        replies = {r['id']: r for r in response.json()}
        self.assertEqual(replies[1]['result'], {})
        self.assertEqual(replies[2]['error']['code'], -32601)

    def test_settings_creates_and_revokes_tokens(self):
        from .mcp_models import MCPToken
        self.client.force_login(self.alice)
        self.client.post(reverse('mcp-token-create'), {'name': 'portátil'})
        created = MCPToken.objects.get(user=self.alice, name='portátil')
        self.client.post(reverse('mcp-token-revoke', args=[created.pk]))
        self.assertFalse(MCPToken.objects.filter(pk=created.pk).exists())
        # Can't revoke someone else's token
        self.client.force_login(self.bob)
        self.client.post(reverse('mcp-token-revoke', args=[self.token_record.pk]))
        self.assertTrue(MCPToken.objects.filter(pk=self.token_record.pk).exists())


class AIModuleTagTests(AIAssistantTests):
    def make_module(self, root, name, title):
        path = os.path.join(root, name)
        os.makedirs(path)
        with open(os.path.join(path, '__manifest__.py'), 'w') as f:
            f.write(f"{{'name': '{title}', 'depends': ['base']}}")

    def test_finds_modules_in_addons_and_repos_and_repos_are_read_only(self):
        from .services.ai_assistant import addons_dir, find_custom_modules, repos_dir, run_tool
        self.make_module(addons_dir(self.alice_instance), 'acme_sales', 'ACME Sales')
        self.make_module(os.path.join(repos_dir(self.alice_instance), 'OCA-web'), 'web_responsive', 'Web Responsive')
        os.makedirs(os.path.join(addons_dir(self.alice_instance), 'not_a_module'))
        modules = {m['name']: m for m in find_custom_modules(self.alice_instance)}
        self.assertEqual(set(modules), {'acme_sales', 'web_responsive'})
        self.assertTrue(modules['acme_sales']['editable'])
        self.assertEqual(modules['web_responsive']['path'], 'repos/OCA-web/web_responsive')
        self.assertIn('Web Responsive', run_tool(self.alice_instance, self.alice, 'read_file', {'path': 'repos/OCA-web/web_responsive/__manifest__.py'}))
        self.assertIn('solo lectura', run_tool(self.alice_instance, self.alice, 'write_file', {'path': 'repos/OCA-web/web_responsive/x.py', 'content': 'x'}))

    def test_tagged_modules_are_sent_to_the_model_but_not_shown(self):
        import json
        from .services.ai_assistant import addons_dir
        self.make_module(addons_dir(self.alice_instance), 'acme_sales', 'ACME Sales')
        self.client.force_login(self.alice)
        with mock.patch('orchestrator.services.ai_assistant.chat', return_value={'content': 'ok'}) as chat:
            response = self.client.post(reverse('instance-ai-chat', args=[self.alice_instance.pk]),
                                        json.dumps({'message': 'añade un campo a @acme_sales', 'modules': ['acme_sales']}),
                                        content_type='application/json')
            self.run_ai_worker()
        sent = [m for m in chat.call_args.args[1] if m['role'] == 'user'][-1]['content']
        self.assertIn('[Módulos etiquetados]', sent)
        self.assertIn('@acme_sales — «ACME Sales»', sent)
        self.assertEqual(response.json()['messages'][0]['content'], 'añade un campo a @acme_sales')
        listed = self.client.get(reverse('instance-ai-modules', args=[self.alice_instance.pk])).json()['modules']
        self.assertEqual([m['name'] for m in listed], ['acme_sales'])


class AIUndoTests(AIAssistantTests):
    def chat(self, text, replies):
        import json
        self.client.force_login(self.alice)
        url = reverse('instance-ai-chat', args=[self.alice_instance.pk])
        with mock.patch('orchestrator.services.ai_assistant.chat', side_effect=replies):
            self.client.post(url, json.dumps({'message': text}), content_type='application/json')
            self.run_ai_worker()
        return self.client.get(url).json()

    def write_call(self, call_id, path, content):
        import json
        return {'content': None, 'tool_calls': [{'id': call_id, 'type': 'function', 'function': {
            'name': 'write_file', 'arguments': json.dumps({'path': path, 'content': content})}}]}

    def read(self, path):
        from .services.ai_assistant import addons_dir
        full = os.path.join(addons_dir(self.alice_instance), path)
        return open(full).read() if os.path.exists(full) else None

    def test_undo_restores_files_and_later_turns(self):
        from .task_models import Task
        manifest = "{'name': 'Mod'}"
        first = self.chat('crea mod', [self.write_call('a', 'mod/__manifest__.py', manifest),
                                        self.write_call('b', 'mod/models.py', 'v1'), {'content': 'hecho'}])
        self.chat('cambia', [self.write_call('c', 'mod/models.py', 'v2'), {'content': 'cambiado'}])
        self.assertEqual(self.read('mod/models.py'), 'v2')
        undo = first['messages'][-1]['undo']
        self.assertEqual((undo['files'], undo['reverted']), (2, False))

        # Undoing the second turn only brings back v1 and upgrades the module
        second_turn = self.alice_instance.ai_messages.filter(role='user').last()
        self.client.post(reverse('instance-ai-revert', args=[self.alice_instance.pk, second_turn.pk]))
        self.assertEqual(self.read('mod/models.py'), 'v1')
        self.assertTrue(Task.objects.filter(kind='ai_module', params__module='mod', params__upgrade=True).exists())

        # Undoing the first turn removes the files it created
        data = self.client.post(reverse('instance-ai-revert', args=[self.alice_instance.pk, undo['turn']])).json()
        self.assertIsNone(self.read('mod/models.py'))
        self.assertIsNone(self.read('mod/__manifest__.py'))
        self.assertIn('ya no existe', data['summary'])
        self.assertTrue(all(m['undo']['reverted'] for m in data['messages'] if 'undo' in m))

    def test_ai_can_undo_the_previous_request(self):
        import json
        self.chat('crea', [self.write_call('a', 'mod/models.py', 'v1'), {'content': 'ok'}])
        self.chat('cambia', [self.write_call('b', 'mod/models.py', 'v2'), {'content': 'ok'}])
        undo_call = {'content': None, 'tool_calls': [{'id': 'u', 'type': 'function', 'function': {'name': 'undo_last_change', 'arguments': '{}'}}]}
        self.chat('vuelve atrás', [undo_call, {'content': 'deshecho'}])
        self.assertEqual(self.read('mod/models.py'), 'v1')

    def test_revert_requires_manage_permission(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(reverse('instance-ai-revert', args=[self.alice_instance.pk, 1])).status_code, 404)


@override_settings(ALLOWED_HOSTS=['*'])
class ReleaseNotesPaginationTests(TestCase):
    def test_release_notes_are_paginated(self):
        from config.version import CHANGELOG
        first = self.client.get('/')
        self.assertContains(first, f"v{CHANGELOG[0]['version']}")
        self.assertNotContains(first, f"v{CHANGELOG[3]['version']}<")
        second = self.client.get('/?novedades=2')
        self.assertContains(second, f"v{CHANGELOG[3]['version']}")
        self.assertContains(second, '?novedades=1#novedades')


class ProjectDeleteAllTests(BaseTestCase):
    def test_needs_typed_name_then_worker_deletes_everything(self):
        from io import StringIO
        from django.core.management import call_command
        from .project_models import Project
        from .task_models import Task
        Backup.objects.create(instance=self.alice_instance, filename='a.zip', file_path='/nonexistent/a.zip', file_size=1)
        self.client.force_login(self.alice)
        url = reverse('project-delete', args=[self.alice_project.pk])
        self.client.post(url, {'confirm': 'wrong'})
        self.assertFalse(Task.objects.filter(kind='delete_project').exists())
        self.client.post(url, {'confirm': 'ACME'})
        self.client.post(url, {'confirm': 'ACME'})  # a second click doesn't queue twice
        self.assertEqual(Task.objects.filter(kind='delete_project').count(), 1)

        call_command('run_worker', once=True, stdout=StringIO())

        self.docker.return_value.delete_instance.assert_called_once()
        self.assertFalse(Project.objects.filter(pk=self.alice_project.pk).exists())
        self.assertFalse(Instance.objects.filter(pk=self.alice_instance.pk).exists())
        self.assertEqual(Task.objects.get(kind='delete_project').status, 'done')

    def test_only_managers_delete(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(reverse('project-delete', args=[self.alice_project.pk]), {'confirm': 'ACME'}).status_code, 404)


class TodoTests(MCPServerTests):
    def test_ui_add_complete_and_reopen(self):
        from .todo_models import Todo
        self.client.force_login(self.alice)
        self.client.post(reverse('todo-create'), {'title': 'Revisar backups', 'description': 'todas las versiones'})
        todo = Todo.objects.get(title='Revisar backups')
        self.assertContains(self.client.get(reverse('todo-list')), 'Revisar backups')
        self.client.post(reverse('todo-status', args=[todo.pk]), {'status': 'done', 'note': 'probadas 10-20'})
        todo.refresh_from_db()
        from config.version import VERSION
        self.assertEqual((todo.status, todo.completion_note, todo.completed_in_version), ('done', 'probadas 10-20', VERSION))
        self.client.post(reverse('todo-status', args=[todo.pk]), {'status': 'pending'})
        todo.refresh_from_db()
        self.assertEqual((todo.status, todo.completed_in_version), ('pending', ''))

    def test_edit_and_kpis(self):
        from .todo_models import Todo
        todo = Todo.objects.create(title='Viejo', created_by=self.alice)
        Todo.objects.create(title='Hecha', created_by=self.alice, status='done')
        self.client.force_login(self.alice)
        self.client.post(reverse('todo-edit', args=[todo.pk]), {'title': 'Nuevo', 'description': 'línea 1\r\nlínea 2'})
        todo.refresh_from_db()
        self.assertEqual((todo.title, todo.description), ('Nuevo', 'línea 1\r\nlínea 2'))
        kpis = self.client.get(reverse('todo-list')).context['kpis']
        self.assertEqual(kpis, {'done': 1, 'open': 1, 'in_progress': 0, 'percent': 50})
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(reverse('todo-edit', args=[todo.pk]), {'title': 'x'}).status_code, 404)

    def test_scoping_and_clients(self):
        from .todo_models import Todo
        Todo.objects.create(title='de bob', created_by=self.bob)
        self.client.force_login(self.alice)
        self.assertNotContains(self.client.get(reverse('todo-list')), 'de bob')
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('todo-list')), 'de bob')
        self.bob.profile.is_client = True
        self.bob.profile.save()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse('todo-list')).status_code, 403)

    def test_claude_completes_todos_over_mcp(self):
        import json
        from .todo_models import Todo
        todo = Todo.objects.create(title='Menú Todo', created_by=self.alice)
        listed = json.loads(self.rpc('tools/call', {'name': 'list_todos', 'arguments': {'status': 'pending'}}).json()['result']['content'][0]['text'])
        self.assertEqual([t['id'] for t in listed], [todo.id])
        self.rpc('tools/call', {'name': 'update_todo', 'arguments': {'todo_id': todo.id, 'status': 'done', 'note': 'hecho'}})
        todo.refresh_from_db()
        self.assertEqual((todo.status, todo.completed_by), ('done', 'Claude (MCP, alice)'))


class MetricsHistoryTests(BaseTestCase):
    def test_samples_rollups_retention_and_ranges(self):
        from datetime import timedelta
        from django.utils import timezone
        from .metrics_models import MetricRollup, MetricSample
        from .services import metrics
        now = timezone.now().replace(minute=30, second=0, microsecond=0)
        cpu = iter([10.0, 30.0]); mem = iter([40.0, 60.0])
        with mock.patch.object(metrics.psutil, 'cpu_percent', side_effect=lambda interval: next(cpu)), \
                mock.patch.object(metrics.psutil, 'virtual_memory', side_effect=lambda: mock.Mock(percent=next(mem))):
            metrics.record_sample(now - timedelta(minutes=1))
            metrics.record_sample(now)
        hour = MetricRollup.objects.get(period='hour')
        self.assertEqual((hour.cpu_avg, hour.cpu_max, hour.memory_max), (20.0, 30.0, 60.0))
        self.assertEqual(MetricRollup.objects.get(period='day').cpu_max, 30.0)

        # Old raw samples are pruned on the next sample
        MetricSample.objects.create(timestamp=now - timedelta(days=3), cpu_percent=1, memory_percent=1)
        with mock.patch.object(metrics.psutil, 'cpu_percent', return_value=5.0), \
                mock.patch.object(metrics.psutil, 'virtual_memory', return_value=mock.Mock(percent=50.0)):
            metrics.record_sample(now + timedelta(minutes=1))
        self.assertFalse(MetricSample.objects.filter(timestamp__lt=now - timedelta(days=2)).exists())

        day_points = metrics.metrics_history('24h', now=now + timedelta(minutes=2))
        self.assertTrue(all(set(p) == {'t', 'cpu', 'cpu_max', 'memory', 'memory_max'} for p in day_points))
        self.assertEqual(max(p['cpu_max'] for p in day_points), 30.0)
        self.assertEqual(len(metrics.metrics_history('12m', now=now)), 1)

    def test_history_endpoint_is_admin_only(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('metrics-history')).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('metrics-history') + '?range=bogus').json()['range'], '24h')


class RestAPITests(MCPServerTests):
    def test_generate_token_from_api_tab_shown_once(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse('mcp-token-create'), {'name': 'script', 'tab': 'api'})
        self.assertEqual(response['Location'], reverse('settings') + '#api')
        page = self.client.get(reverse('settings'))
        token = page.context['new_token']['token']
        self.assertContains(page, f'Bearer {token}')  # the examples use it
        self.assertEqual(self.api('get', '/api/projects/', token=token).status_code, 200)
        self.assertIsNone(self.client.get(reverse('settings')).context['new_token'])

    def test_markdown_for_an_ai_carries_a_working_token_and_the_documentation(self):
        import re
        from .api_docs import API_ENDPOINTS
        from .mcp_models import MCPToken
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('api-token-markdown')).status_code, 405)
        response = self.client.post(reverse('api-token-markdown'), {'name': 'Claude'})
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="community-sh-api.md"')
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertTrue(response['Content-Type'].startswith('text/markdown'))
        text = response.content.decode()
        token = re.search(r'Authorization: Bearer (csh_[A-Za-z0-9_-]+)', text).group(1)
        self.assertEqual(self.api('get', '/api/projects/', token=token).status_code, 200)
        self.assertTrue(MCPToken.objects.filter(user=self.alice, name='Claude', hint=token[-6:]).exists())
        self.assertIn('http://testserver/api/', text)
        self.assertIn('`alice`', text)
        for method, path, _ in API_ENDPOINTS:
            self.assertIn(f'`{path}`', text)
        self.assertIn('19.0', text)
        # The settings table comes from the same list, and the button is there
        page = self.client.get(reverse('settings')).content.decode()
        self.assertIn(reverse('api-token-markdown'), page)
        self.assertIn('/api/instances/{id}/create-database/', page)
        # Without the mandatory 2FA the token wouldn't work: no file
        with mock.patch('orchestrator.permissions.missing_required_2fa', return_value=True):
            response = self.client.post(reverse('api-token-markdown'))
        self.assertEqual(response.status_code, 302)

    def api(self, method, path, data=None, token=None):
        import json
        kwargs = {'HTTP_AUTHORIZATION': f'Bearer {token or self.token}'}
        if data is not None:
            kwargs.update(data=json.dumps(data), content_type='application/json')
        return getattr(self.client, method)(path, **kwargs)

    def test_bearer_token_and_scoping(self):
        self.assertEqual(self.api('get', '/api/projects/', token='csh_bad').status_code, 401)
        self.assertEqual([p['name'] for p in self.api('get', '/api/projects/').json()], ['ACME'])
        self.assertEqual([i['name'] for i in self.api('get', '/api/instances/').json()], ['alice-odoo'])

    def test_instance_actions_return_tasks(self):
        pk = self.alice_instance.pk
        backup = self.api('post', f'/api/instances/{pk}/backup/', {'include_filestore': False}).json()
        task = self.api('get', f"/api/tasks/{backup['task_id']}/").json()
        self.assertEqual((task['kind'], task['params']), ('backup', {'include_filestore': False}))
        self.assertEqual(self.api('post', f'/api/instances/{pk}/duplicate/', {'new_name': 'Bad Name!'}).status_code, 400)
        self.assertEqual(self.api('post', f'/api/instances/{pk}/duplicate/', {'new_name': 'alice-copy'}).status_code, 202)

    def test_project_crud_and_guarded_delete(self):
        created = self.api('post', '/api/projects/', {'name': 'Nuevo', 'client': self.bob.pk}).json()
        self.assertIsNone(created['client'])  # only admins assign clients
        self.assertEqual(self.api('delete', f'/api/projects/{self.alice_project.pk}/').status_code, 409)
        self.assertEqual(self.api('delete', f"/api/projects/{created['id']}/").status_code, 204)

    def test_backups_and_todos(self):
        backup = Backup.objects.create(instance=self.alice_instance, filename='a.zip', file_path='/nonexistent/a.zip', file_size=1)
        Backup.objects.create(instance=self.bob_instance, filename='b.zip', file_path='/x/b.zip', file_size=1)
        self.assertEqual([b['filename'] for b in self.api('get', '/api/backups/').json()], ['a.zip'])
        self.assertEqual(self.api('post', f'/api/backups/{backup.pk}/restore/').status_code, 202)
        todo = self.api('post', '/api/todos/', {'title': 'Desde la API'}).json()
        done = self.api('patch', f"/api/todos/{todo['id']}/", {'status': 'done', 'completion_note': 'ok'}).json()
        self.assertEqual((done['status'], done['completion_note']), ('done', 'ok'))


class BackupImportTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        import tempfile, shutil
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        settings_patch = override_settings(BASE_DIR=self.tmp)
        settings_patch.enable()
        self.addCleanup(settings_patch.disable)

    def odoo_zip(self, version='17.0', db='prod'):
        import io, json, zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zf:
            zf.writestr('dump.sql', 'SELECT 1;')
            zf.writestr('manifest.json', json.dumps({'db_name': db, 'version': version}))
            zf.writestr('filestore/ab/abcdef', 'file')
        return buffer.getvalue()

    def test_detects_the_three_formats(self):
        import zipfile
        from .services.docker_service import read_backup_metadata
        odoo_path = os.path.join(self.tmp, 'odoo.zip')
        open(odoo_path, 'wb').write(self.odoo_zip('16.0+e'))
        self.assertEqual(read_backup_metadata(odoo_path), {'format': 'odoo', 'database_name': 'prod', 'odoo_version': '16.0', 'has_filestore': True})
        panel_path = os.path.join(self.tmp, 'panel.zip')
        with zipfile.ZipFile(panel_path, 'w') as zf:
            zf.writestr('database.dump', 'PGDMP')
            zf.writestr('metadata.json', '{"database_name": "qa", "odoo_version": "18.0"}')
        self.assertEqual(read_backup_metadata(panel_path)['format'], 'panel')
        dump_path = os.path.join(self.tmp, 'x.dump')
        open(dump_path, 'wb').write(b'PGDMP\x01\x0e')
        self.assertEqual(read_backup_metadata(dump_path)['format'], 'pg_dump')
        bad = os.path.join(self.tmp, 'bad.txt')
        open(bad, 'w').write('hello')
        with self.assertRaises(Exception):
            read_backup_metadata(bad)

    def test_import_creates_instance_backup_and_task(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .task_models import Task
        self.client.force_login(self.alice)
        upload = SimpleUploadedFile('prod.zip', self.odoo_zip('17.0', 'prod'))
        self.client.post(reverse('backup-import'), {'backup_file': upload, 'name': 'imported', 'project': self.alice_project.pk})
        instance = Instance.objects.get(name='imported')
        self.assertEqual((instance.odoo_version, instance.database_name, instance.owner, instance.project),
                         ('17.0', 'prod', self.alice, self.alice_project))
        backup = instance.backups.get()
        self.assertTrue(backup.include_filestore)
        self.assertEqual(Task.objects.get(kind='create_from_backup').params, {'backup_id': backup.pk})

    def test_import_rejects_unknown_version_and_other_projects(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.alice)
        self.client.post(reverse('backup-import'), {'backup_file': SimpleUploadedFile('a.dump', b'PGDMP\x01'),
                                                    'name': 'noversion', 'project': self.alice_project.pk})
        self.client.post(reverse('backup-import'), {'backup_file': SimpleUploadedFile('b.zip', self.odoo_zip()),
                                                    'name': 'notmine', 'project': self.bob_project.pk})
        self.assertFalse(Instance.objects.filter(name__in=['noversion', 'notmine']).exists())


class AIModuleInstallTests(BaseTestCase):
    def test_failed_install_resets_pending_module_states(self):
        from .task_models import Task
        from .tasks import enqueue, run_task
        odoo = mock.Mock(attrs={'Mounts': [{'Destination': '/mnt/extra-addons'}]})
        odoo.exec_run.return_value = mock.Mock(exit_code=1, output=b'Traceback ... External ID not found')
        db = mock.Mock()
        service = self.docker.return_value
        service._get_container.side_effect = lambda name: odoo if name.startswith('odoo_') else db
        self.alice_instance.database_name = 'qa'
        self.alice_instance.save()
        task = run_task(enqueue(Task.Kind.AI_MODULE, self.alice_instance, self.alice, module='bad_mod', upgrade=False))
        self.assertEqual(task.status, 'failed')
        self.assertIn('la base queda como estaba', task.result)
        sql = db.exec_run.call_args.args[0][-1]
        self.assertIn("'to install' THEN 'uninstalled'", sql)
        odoo.restart.assert_not_called()


class AdminLoginTests(BaseTestCase):
    def test_signed_one_minute_link_for_odoo_12_and_later(self):
        import hashlib
        import hmac
        import time
        from urllib.parse import parse_qs, urlparse
        from .services.docker_service import admin_login_secret
        self.alice_instance.odoo_version, self.alice_instance.database_name = '17.0', 'acme'
        self.alice_instance.save()
        self.client.force_login(self.alice)
        response = self.client.post(reverse('instance-admin-login', args=[self.alice_instance.pk]))
        url = urlparse(response['Location'])
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.assertEqual((url.path, query['db']), ('/community_sh/login', 'acme'))
        self.assertLessEqual(int(query['exp']) - time.time(), 60)
        expected = hmac.new(admin_login_secret(self.alice_instance).encode(),
                            f"acme:{query['exp']}:{query['nonce']}".encode(), hashlib.sha256).hexdigest()
        self.assertEqual(query['sig'], expected)

    def test_only_managers(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(reverse('instance-admin-login', args=[self.alice_instance.pk])).status_code, 404)


class DemoDatabasesTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        import tempfile
        from .services.docker_service import DockerService
        self.workspace = tempfile.mkdtemp()
        self.instance = self.alice_instance
        with mock.patch('orchestrator.services.docker_service.docker.from_env'):
            self.service = DockerService()

    def odoo_conf(self):
        self.service._write_odoo_config(self.instance, self.workspace, [])
        with open(os.path.join(self.workspace, 'conf', 'odoo.conf')) as conf:
            return conf.read()

    def test_demo_instance_loads_the_module_and_hides_the_databases(self):
        self.instance.odoo_version = '20.0'
        self.assertNotIn('community_sh_demo', self.odoo_conf())
        self.instance.demo_default_db = 'shop'
        config = self.odoo_conf()
        self.assertIn('community_sh_login,community_sh_ai,community_sh_demo', config)
        self.assertIn('community_sh_demo_default = shop', config)
        self.assertIn('list_db = False', config)

    def test_demos_need_odoo_18(self):
        self.instance.odoo_version = '17.0'
        self.instance.demo_default_db = 'shop'
        self.assertNotIn('community_sh_demo', self.odoo_conf())

    def test_one_backup_per_database(self):
        container = mock.Mock()
        with mock.patch.object(self.service, '_get_container', return_value=container), \
                mock.patch.object(self.service, '_list_user_databases', return_value=['hotel', 'shop']), \
                mock.patch.object(self.service, 'backup_instance') as backup:
            self.assertEqual(len(self.service.backup_all_databases(self.instance)), 2)
        self.assertEqual([call.kwargs['database'] for call in backup.call_args_list], ['hotel', 'shop'])

    def test_one_database_keeps_one_plain_backup(self):
        with mock.patch.object(self.service, '_get_container', return_value=mock.Mock()), \
                mock.patch.object(self.service, '_list_user_databases', return_value=['acme']), \
                mock.patch.object(self.service, 'backup_instance') as backup:
            self.service.backup_all_databases(self.instance)
        self.assertNotIn('database', backup.call_args.kwargs)


class CloneRepoTests(BaseTestCase):
    REPO = 'https://github.com/acme/private'

    def setUp(self):
        super().setUp()
        import tempfile
        from .config_models import GitHubConfig
        from .services.docker_service import DockerService
        self.workspace = tempfile.mkdtemp()
        self.alice_instance.github_repo = self.REPO
        self.alice_instance.github_branch = '20.0'
        self.alice_instance.owner = self.alice
        GitHubConfig.objects.filter(user=self.alice).delete()
        GitHubConfig.objects.create(user=self.alice, personal_access_token='s3cret')
        with mock.patch('orchestrator.services.docker_service.docker.from_env'):
            self.service = DockerService()
        self.service.deploy_notes = []

    def fake_clone(self, url, path, **kwargs):
        os.makedirs(os.path.join(path, '.git'))
        return mock.MagicMock()

    def test_private_repository_is_cloned_with_the_token_of_the_owner(self):
        with mock.patch('orchestrator.services.docker_service.git.Repo.clone_from', side_effect=self.fake_clone) as clone:
            self.service._clone_repo(self.alice_instance, self.workspace)
        self.assertIn('s3cret', clone.call_args.args[0])
        self.assertTrue(os.path.isdir(os.path.join(self.workspace, 'addons', '.git')))
        self.assertFalse(os.path.exists(os.path.join(self.workspace, 'addons.new')))

    def test_failed_clone_without_code_fails_the_deploy_and_hides_the_token(self):
        import git
        failure = git.exc.GitCommandError('git clone https://s3cret@github.com/acme/private', 128)
        with mock.patch('orchestrator.services.docker_service.git.Repo.clone_from', side_effect=failure):
            with self.assertRaises(Exception) as caught:
                self.service._clone_repo(self.alice_instance, self.workspace)
        self.assertIn('No se pudo obtener', str(caught.exception))
        self.assertNotIn('s3cret', str(caught.exception))

    def test_failed_update_keeps_the_code_in_place(self):
        import git
        addons = os.path.join(self.workspace, 'addons')
        os.makedirs(os.path.join(addons, '.git'))
        open(os.path.join(addons, 'module.py'), 'w').close()
        failure = git.exc.GitCommandError('git clone', 128)
        with mock.patch('orchestrator.services.docker_service.git.Repo', side_effect=failure) as repo:
            repo.clone_from.side_effect = failure
            self.service._clone_repo(self.alice_instance, self.workspace)
        self.assertTrue(os.path.exists(os.path.join(addons, 'module.py')))
        self.assertEqual(len(self.service.deploy_notes), 1)


class DomainTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        import tempfile
        from .services.domains import clear_cache
        clear_cache()
        self.addCleanup(clear_cache)
        self.base_dir = tempfile.mkdtemp()
        base_dir = override_settings(BASE_DIR=self.base_dir)
        base_dir.enable()
        self.addCleanup(base_dir.disable)

    def routes(self, instance):
        import yaml
        from .traefik_service import TraefikService
        TraefikService.generate_instance_config(instance)
        path = os.path.join(self.base_dir, 'traefik', f'instance-{instance.name}.yml')
        return yaml.safe_load(open(path)) if os.path.exists(path) else None

    @mock.patch.dict(os.environ, {'MAIN_DOMAIN': 'hosting.example.com', 'LETSENCRYPT_EMAIL': 'ops@example.com'})
    def test_stopped_instance_has_no_route(self):
        self.alice_instance.status = Instance.Status.RUNNING
        self.assertIsNotNone(self.routes(self.alice_instance))
        self.alice_instance.status = Instance.Status.STOPPED
        self.assertIsNone(self.routes(self.alice_instance))

    def acme_storage(self, *hosts):
        import json
        path = os.path.join(self.base_dir, 'acme.json')
        with open(path, 'w') as storage:
            json.dump({'letsencrypt': {'Certificates': [{'domain': {'main': host}, 'key': 'secret'} for host in hosts]}}, storage)
        return path

    @mock.patch.dict(os.environ, {'MAIN_DOMAIN': 'hosting.example.com', 'LETSENCRYPT_EMAIL': 'ops@example.com'})
    def test_certificate_problem(self):
        from .services import domains
        host = 'acme-17-alice-odoo.hosting.example.com'
        self.alice_instance.status = Instance.Status.RUNNING
        limit = (f'level=error msg="Unable to obtain ACME certificate for domains \\"{host}\\": too many certificates (50) '
                 'already issued for \\"hosting.example.com\\" in the last 168h0m0s, retry after 2026-10-30 14:02:41 UTC"')
        with mock.patch.object(domains, 'ACME_STORAGE', self.acme_storage('other.hosting.example.com')), \
                mock.patch.object(domains, '_traefik_log', return_value=limit):
            self.assertEqual(domains.certificate_problem(self.alice_instance),
                             {'hosts': [host], 'kind': 'rate_limit', 'retry_after': '2026-10-30 14:02'})
        with mock.patch.object(domains, 'ACME_STORAGE', self.acme_storage(host)):
            self.assertIsNone(domains.certificate_problem(self.alice_instance))
        with mock.patch.object(domains, 'ACME_STORAGE', self.acme_storage('*.hosting.example.com')):
            self.assertIsNone(domains.certificate_problem(self.alice_instance))
        with mock.patch.object(domains, 'ACME_STORAGE', '/nonexistent/acme.json'):
            self.assertIsNone(domains.certificate_problem(self.alice_instance))
        self.alice_instance.status = Instance.Status.STOPPED
        self.assertIsNone(domains.certificate_problem(self.alice_instance))

    def test_subdomain_is_client_version_name(self):
        self.alice_project.client = self.bob
        self.alice_project.save()
        instance = Instance.objects.create(name='erp_prod', odoo_version='20.0', project=self.alice_project)
        self.assertEqual(instance.subdomain, 'bob-20-erp-prod')
        self.assertEqual(Instance.objects.create(name='solo', odoo_version='16.0').subdomain, '16-solo')
        self.assertEqual(self.alice_instance.subdomain, 'acme-17-alice-odoo')  # no client: the project name

    @mock.patch.dict(os.environ, {'MAIN_DOMAIN': 'hosting.example.com', 'LETSENCRYPT_EMAIL': ''})
    def test_http_routes_without_certificates(self):
        self.assertEqual(self.alice_instance.url, 'http://acme-17-alice-odoo.hosting.example.com')
        routers = self.routes(self.alice_instance)['http']['routers']
        self.assertEqual([r['rule'] for r in routers.values()], ['Host(`acme-17-alice-odoo.hosting.example.com`)'])

    @mock.patch.dict(os.environ, {'MAIN_DOMAIN': 'hosting.example.com', 'LETSENCRYPT_EMAIL': 'ops@example.com'})
    def test_lets_encrypt_per_host_and_redirect(self):
        self.alice_instance.custom_domain = 'erp.acme.com'
        self.alice_instance.save()
        self.assertEqual(self.alice_instance.url, 'https://erp.acme.com')
        config = self.routes(self.alice_instance)['http']
        secure = {k: v for k, v in config['routers'].items() if k.endswith('-secure')}
        self.assertEqual(sorted(r['rule'] for r in secure.values()), [
            'Host(`acme-17-alice-odoo.hosting.example.com`)', 'Host(`erp.acme.com`)', 'Host(`www.erp.acme.com`)'])
        self.assertTrue(all(r['tls'] == {'certResolver': 'letsencrypt'} for r in secure.values()))
        self.assertTrue(all(r['middlewares'] == ['instance-alice-odoo-redirect-https']
                            for k, r in config['routers'].items() if not k.endswith('-secure')))
        self.assertEqual(config['services']['instance-alice-odoo-service']['loadBalancer']['servers'],
                         [{'url': 'http://odoo_alice-odoo:8069'}])

    def test_no_domain_keeps_ip_and_port(self):
        self.alice_instance.port = 8123
        self.assertEqual(self.alice_instance.url, 'http://127.0.0.1:8123')
        self.assertIsNone(self.routes(self.alice_instance))

    @mock.patch.dict(os.environ, {'MAIN_DOMAIN': 'hosting.example.com', 'LETSENCRYPT_EMAIL': 'ops@example.com'})
    def test_startup_command_writes_panel_and_instances(self):
        import yaml
        from io import StringIO
        from django.core.management import call_command
        call_command('configure_domain', stdout=StringIO())
        traefik = os.path.join(self.base_dir, 'traefik')
        panel = yaml.safe_load(open(os.path.join(traefik, 'dynamic.yml')))['http']['routers']
        self.assertEqual(panel['app-domain-0-secure']['rule'], 'Host(`hosting.example.com`)')
        self.assertTrue(os.path.exists(os.path.join(traefik, 'instance-bob-odoo.yml')))


class FixedPortTests(BaseTestCase):
    def service(self):
        from .services.docker_service import DockerService
        with mock.patch('orchestrator.services.docker_service.docker.from_env'):
            return DockerService()

    def test_keeps_the_instance_port_and_skips_busy_ones(self):
        import docker
        service = self.service()
        service._get_container = mock.Mock(return_value=None)
        run = mock.Mock(side_effect=lambda port: 'container')
        self.assertEqual(service._run_on_fixed_port('odoo_x', 23456, run), ('container', 23456))

        busy = docker.errors.APIError('Bind for 0.0.0.0:23456 failed: port is already allocated')
        stale = mock.Mock()
        service._get_container = mock.Mock(return_value=stale)
        run = mock.Mock(side_effect=[busy, 'container'])
        container, port = service._run_on_fixed_port('odoo_x', 23456, run)
        self.assertEqual(container, 'container')
        self.assertNotEqual(port, 23456)
        self.assertTrue(20000 <= port < 40000)
        stale.remove.assert_called_once_with(force=True)

    def test_other_errors_are_not_retried(self):
        import docker
        service = self.service()
        with self.assertRaises(docker.errors.APIError):
            service._run_on_fixed_port('odoo_x', None, mock.Mock(side_effect=docker.errors.APIError('no such image')))

    def test_sync_published_ports(self):
        service = self.service()
        self.alice_instance.port = 30001
        self.alice_instance.save()
        container = mock.Mock(attrs={'NetworkSettings': {'Ports': {'8069/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '30555'}]}}})
        container.name = 'odoo_alice-odoo'
        service.client.containers.list.return_value = [container]
        self.assertEqual(service.sync_published_ports(), ['alice-odoo'])
        self.alice_instance.refresh_from_db()
        self.assertEqual(self.alice_instance.port, 30555)
        self.assertEqual(service.sync_published_ports(), [])


class Odoo8And9Tests(TestCase):
    def test_openerp_config_command_and_manifest(self):
        from .services.docker_service import odoo_command, odoo_config_target
        self.assertEqual((odoo_config_target('8.0'), odoo_command('9.0')), ('/etc/odoo/openerp-server.conf', 'openerp-server'))
        self.assertEqual((odoo_config_target('10.0'), odoo_command('10.0')), ('/etc/odoo/odoo.conf', 'odoo'))
        from .services.ai_assistant import system_prompt
        config = GitHubConfig(ai_instructions='')
        self.assertIn('__openerp__.py', system_prompt(Instance(name='old', odoo_version='9.0'), config))
        self.assertIn('__manifest__.py', system_prompt(Instance(name='new', odoo_version='16.0'), config))


class OdooChatterAITests(AIAssistantTests):
    def signed_post(self, data, tamper=False):
        import hashlib, hmac, json, time
        from .services.docker_service import admin_login_secret
        body = json.dumps(data).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(admin_login_secret(self.alice_instance).encode(), timestamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
        return self.client.post(reverse('odoo-ai-request', args=[self.alice_instance.name]), body, content_type='application/json',
                                HTTP_X_CSH_TIMESTAMP=timestamp, HTTP_X_CSH_SIGNATURE='0' * 64 if tamper else signature)

    def test_chatter_request_runs_and_answers_in_odoo(self):
        from .task_models import Task
        request = {'db': 'acme', 'model': 'sale.order', 'res_id': 7, 'record': 'S00007', 'login': 'admin', 'text': 'añade una columna Obra'}
        self.assertEqual(self.signed_post(request, tamper=True).status_code, 403)
        response = self.signed_post(request)
        self.assertEqual(response.status_code, 202)
        task = Task.objects.get(kind='ai_chat')
        self.assertEqual(task.params['odoo'], {'db': 'acme', 'model': 'sale.order', 'res_id': 7})
        turn = self.alice_instance.ai_messages.get(pk=task.params['turn'])
        self.assertIn('sale.order #7', turn.content)
        self.assertEqual(turn.user, self.alice)  # the instance owner
        # The same signed request can't be sent again
        self.assertEqual(self.signed_post(request).json()['message'], 'Petición repetida')
        # A second request while the first runs is turned away with a message
        self.assertIn('trabajando', self.signed_post({**request, 'text': 'y otra cosa'}).json()['message'])

        with mock.patch('orchestrator.services.ai_assistant.chat', return_value={'content': 'Columna añadida.'}), \
                mock.patch('orchestrator.services.odoo_bridge.post_reply') as post_reply:
            self.run_ai_worker()
        post_reply.assert_called_once_with(self.alice_instance, 'acme', 'sale.order', 7, 'Columna añadida.')

    def test_model_info_tool_formats_fields_and_views(self):
        from .services.ai_assistant import run_tool
        answer = {'fields': [{'name': 'partner_id', 'type': 'many2one', 'relation': 'res.partner', 'string': 'Cliente', 'required': True}],
                  'views': [{'xml_id': 'sale.view_order_form', 'type': 'form', 'name': 'sale.order.form', 'priority': 16}]}
        with mock.patch('orchestrator.services.odoo_bridge._post', return_value=answer) as post:
            self.alice_instance.database_name = 'acme'
            text = run_tool(self.alice_instance, self.alice, 'odoo_model_info', {'model': 'sale.order'})
        self.assertEqual(post.call_args.args[1:], ('/community_sh/ai/introspect', {'db': 'acme', 'model': 'sale.order'}))
        self.assertIn('form: sale.view_order_form', text)
        self.assertIn('partner_id (many2one, res.partner) «Cliente» obligatorio', text)


class OdooMigrationTests(BaseTestCase):
    def post(self, instance, **extra):
        data = {'source_url': 'erp.example.com', 'source_db': 'prod', 'source_login': 'admin', 'source_password': 's3cret',
                'target_db': 'new', 'target_login': 'admin', 'target_password': 't4rget', 'steps': ['contacts', 'invoices']}
        data.update(extra)
        return self.client.post(reverse('instance-migrate', args=[instance.pk]), data)

    def test_queues_with_passwords_only_in_the_cache(self):
        import json
        from django.core.cache import cache
        from .task_models import Task
        self.alice_instance.odoo_version = '18.0'
        self.alice_instance.save()
        self.client.force_login(self.alice)
        self.post(self.alice_instance)
        task = Task.objects.get(kind='odoo_migration')
        self.assertEqual(task.params['steps'], ['contacts', 'invoices'])
        self.assertNotIn('s3cret', json.dumps(task.params))
        credentials = cache.get(task.params['credentials'])
        self.assertEqual((credentials['source_url'], credentials['target_password']), ('https://erp.example.com', 't4rget'))
        # One at a time per instance
        self.post(self.alice_instance)
        self.assertEqual(Task.objects.filter(kind='odoo_migration').count(), 1)

    def test_needs_a_recent_target_and_manage_permission(self):
        from .task_models import Task
        self.alice_instance.odoo_version = '12.0'
        self.alice_instance.save()
        self.client.force_login(self.alice)
        self.post(self.alice_instance)
        self.assertFalse(Task.objects.filter(kind='odoo_migration').exists())
        self.client.force_login(self.bob)
        self.assertEqual(self.post(self.alice_instance).status_code, 404)

    def test_worker_fails_cleanly_when_credentials_expired(self):
        from .task_models import Task
        from .tasks import enqueue, run_task
        task = run_task(enqueue(Task.Kind.ODOO_MIGRATION, self.alice_instance, self.alice, credentials='gone', steps=['contacts']))
        self.assertEqual(task.status, 'failed')
        self.assertIn('caducaron', task.result)


class SidebarCountTests(BaseTestCase):
    def test_counts_follow_visibility(self):
        from .todo_models import Todo
        Todo.objects.create(title='abierta', created_by=self.alice)
        Todo.objects.create(title='hecha', created_by=self.alice, status='done')
        self.client.force_login(self.alice)
        counts = self.client.get(reverse('project-list')).context['nav_counts']
        self.assertEqual((counts['projects'], counts['instances'], counts['todo']), (1, 1, 1))
        self.assertNotIn('users', counts)
        with mock.patch('orchestrator.context_processors._docker_running', return_value=7):
            self.client.force_login(self.admin)
            counts = self.client.get(reverse('project-list')).context['nav_counts']
        self.assertEqual((counts['instances'], counts['users'], counts['docker']), (2, 3, 7))


class InstanceListAdminLoginTests(BaseTestCase):
    def test_admin_button_only_for_managers_of_running_instances(self):
        self.alice_instance.status = 'running'
        self.alice_instance.save()
        url = reverse('instance-admin-login', args=[self.alice_instance.pk])
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(reverse('instance-list')), f'action="{url}"')
        # A project's client sees and operates the instance, but doesn't manage it
        self.bob.profile.is_client = True
        self.bob.profile.save()
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.client.force_login(self.bob)
        page = self.client.get(reverse('instance-list'))
        self.assertContains(page, 'alice-odoo')
        self.assertNotContains(page, f'action="{url}"')


class PaginationTests(BaseTestCase):
    def test_lists_show_twenty_rows_and_keep_filters(self):
        for number in range(25):
            Instance.objects.create(name=f'bulk-{number}', owner=self.alice, project=self.alice_project)
        self.client.force_login(self.alice)
        first = self.client.get(reverse('instance-list') + f'?project={self.alice_project.pk}')
        self.assertEqual(len(first.context['object_list']), 20)
        self.assertContains(first, f'?project={self.alice_project.pk}&amp;page=2')
        second = self.client.get(reverse('instance-list') + f'?project={self.alice_project.pk}&page=2')
        self.assertEqual(len(second.context['object_list']), 6)  # 25 + alice-odoo
        detail = self.client.get(reverse('project-detail', args=[self.alice_project.pk]))
        self.assertEqual((len(detail.context['instances']), detail.context['all_instances'].count()), (20, 26))


class LandingProjectsTests(TestCase):
    @override_settings(TICKETPROO_API_TOKEN='token', ALLOWED_HOSTS=['*'])
    def test_projects_section_reads_the_api_once_and_skips_this_site(self):
        from django.core.cache import cache
        from .services import showcase
        cache.delete(showcase.CACHE_KEY)
        rows = [{'id': 2, 'nombre': 'falconteams.xyz', 'web': 'falconteams.xyz', 'descripcion': 'Control horario'},
                {'id': 1, 'nombre': 'communitysh.xyz', 'web': 'communitysh.xyz', 'descripcion': 'Este sitio'}]
        response = mock.Mock(json=lambda: {'success': True, 'total': 2, 'data': rows}, raise_for_status=lambda: None)
        with mock.patch('orchestrator.services.showcase.requests.get', return_value=response) as get:
            page = self.client.get('/', HTTP_HOST='communitysh.xyz')
            self.client.get('/', HTTP_HOST='communitysh.xyz')
        self.assertEqual(get.call_count, 1)  # cached
        self.assertEqual(get.call_args.kwargs['headers'], {'X-API-Token': 'token'})
        self.assertContains(page, 'href="https://falconteams.xyz"')
        self.assertNotContains(page, 'Este sitio')
        cache.delete(showcase.CACHE_KEY)

    @override_settings(TICKETPROO_API_TOKEN='')
    def test_hidden_without_token(self):
        self.assertNotContains(self.client.get('/'), 'id="proyectos"')


class GitHubTokenURLTests(TestCase):
    def test_token_goes_as_the_password(self):
        from .services.github import authed_url
        self.assertEqual(authed_url('https://github.com/acme/private', 'github_pat_X'),
                         'https://x-access-token:github_pat_X@github.com/acme/private')
        self.assertEqual(authed_url('https://github.com/acme/public', ''), 'https://github.com/acme/public')


class ContainerApiTests(BaseTestCase):
    """Generic containers through the REST API, also built from a repository."""

    def setUp(self):
        super().setUp()
        service = mock.patch('orchestrator.container_service.ContainerService')
        self.service = service.start()
        self.addCleanup(service.stop)
        self.service.return_value.create_container.return_value = (True, 'creado')
        self.service.return_value.delete_container.return_value = (True, 'borrado')

    def test_create_from_image_gets_a_free_port(self):
        Container.objects.create(name='old', image='redis', port=40000, container_port=6379, created_by=self.bob)
        self.client.force_login(self.alice)
        response = self.client.post('/api/containers/', {'name': 'Web1', 'image': 'nginx', 'container_port': 80},
                                    content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        container = Container.objects.get(name='web1')
        self.assertEqual((container.created_by, container.port), (self.alice, 40001))
        self.service.return_value.create_container.assert_called_once()

    def test_create_from_repository_queues_a_build(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        response = self.client.post('/api/containers/', {
            'name': 'erpsqlite', 'git_repo': 'https://github.com/acme/erp.git', 'dockerfile': 'Dockerfile.server',
            'container_port': 8169, 'environment': {'ERPSQLITE_ADMIN_KEY': 'k'},
        }, content_type='application/json')
        self.assertEqual(response.status_code, 202, response.content)
        task = Task.objects.get(pk=response.json()['task_id'])
        container = Container.objects.get(name='erpsqlite')
        self.assertEqual((task.kind, task.params['container']), (Task.Kind.BUILD_CONTAINER, container.pk))
        self.assertEqual(container.environment, {'ERPSQLITE_ADMIN_KEY': 'k'})
        self.service.return_value.create_container.assert_not_called()
        # The build task is the user's even without an instance
        ids = [t['id'] for t in self.client.get('/api/tasks/').json()]
        self.assertIn(task.pk, ids)
        self.client.force_login(self.bob)
        self.assertNotIn(task.pk, [t['id'] for t in self.client.get('/api/tasks/').json()])

    def test_image_or_repository_is_required(self):
        self.client.force_login(self.alice)
        response = self.client.post('/api/containers/', {'name': 'empty', 'container_port': 80},
                                    content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_users_only_see_and_delete_their_containers(self):
        bobs = Container.objects.create(name='bobs', image='redis', port=40010, container_port=6379, created_by=self.bob)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get('/api/containers/').json(), [])
        self.assertEqual(self.client.delete(f'/api/containers/{bobs.pk}/').status_code, 404)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.delete(f'/api/containers/{bobs.pk}/').status_code, 204)
        self.assertFalse(Container.objects.filter(pk=bobs.pk).exists())

    def test_only_admins_mount_volumes(self):
        self.client.force_login(self.alice)
        self.client.post('/api/containers/', {
            'name': 'sneaky', 'image': 'alpine', 'container_port': 80, 'volumes': {'root': {'host': '/', 'container': '/host'}},
        }, content_type='application/json')
        self.assertEqual(Container.objects.get(name='sneaky').volumes, {})

    def test_name_cannot_take_an_instance_subdomain(self):
        self.client.force_login(self.alice)
        response = self.client.post('/api/containers/', {'name': self.alice_instance.subdomain, 'image': 'nginx',
                                                         'container_port': 80}, content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_build_task_builds_and_starts(self):
        from .task_models import Task
        from .tasks import run_task
        container = Container.objects.create(name='erpsqlite', image='', port=40020, container_port=8169,
                                             git_repo='https://github.com/acme/erp.git', created_by=self.alice)
        self.service.return_value.build_image.return_value = container.built_image
        self.service.return_value.restart_container.return_value = (True, 'arrancado')
        task = Task.objects.create(kind=Task.Kind.BUILD_CONTAINER, created_by=self.alice, params={'container': container.pk})
        run_task(task)
        task.refresh_from_db()
        container.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DONE, task.result)
        self.assertEqual(container.image, 'csh-build/erpsqlite:latest')


class ContainerTemplateBuildTests(BaseTestCase):
    """Templates built from a repository, such as ERPSqlite."""

    def setUp(self):
        super().setUp()
        service = mock.patch('orchestrator.container_views.ContainerService')
        self.service = service.start()
        self.addCleanup(service.stop)

    def test_form_queues_the_build_and_generates_keys(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        response = self.client.post(reverse('container-create'), {
            'template': 'erpsqlite', 'name': 'erp', 'image': 'github.com/falconsoft3d/erp-sqlite (Dockerfile.server)',
            'port': 8169, 'container_port': 8169,
        })
        container = Container.objects.get(name='erp')
        self.assertRedirects(response, reverse('container-detail', args=[container.pk]), fetch_redirect_response=False)
        self.assertEqual((container.image, container.dockerfile), ('', 'Dockerfile.server'))
        self.assertEqual(container.git_repo, 'https://github.com/falconsoft3d/erp-sqlite.git')
        keys = container.environment['ERPSQLITE_ADMIN_KEY'], container.environment['ERPSQLITE_SELLER_KEY']
        self.assertTrue(all(len(key) == 40 for key in keys))
        self.assertNotEqual(*keys)
        task = Task.objects.get(kind=Task.Kind.BUILD_CONTAINER)
        self.assertEqual(task.params['container'], container.pk)
        self.service.return_value.create_container.assert_not_called()

    def test_api_template_brings_the_repository(self):
        self.client.force_login(self.alice)
        with mock.patch('orchestrator.container_service.ContainerService'):
            response = self.client.post('/api/containers/', {'name': 'erp2', 'template': 'erpsqlite'},
                                        content_type='application/json')
        self.assertEqual(response.status_code, 202, response.content)
        container = Container.objects.get(name='erp2')
        self.assertEqual((container.dockerfile, container.container_port), ('Dockerfile.server', 8169))
        self.assertNotEqual(container.environment['ERPSQLITE_ADMIN_KEY'], '{secret}')


class InstanceApiDeployTests(BaseTestCase):
    def test_created_instance_is_deployed(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        response = self.client.post('/api/instances/', {'name': 'alice-new', 'project': self.alice_project.pk})
        self.assertEqual(response.status_code, 201)
        task = Task.objects.get(pk=response.json()['task_id'])
        self.assertEqual((task.kind, task.instance.name), (Task.Kind.DEPLOY, 'alice-new'))


@override_settings(ALLOWED_HOSTS=['*'])
class ContainerRouteTests(TestCase):
    def setUp(self):
        import tempfile
        from .services.domains import clear_cache
        clear_cache()
        self.addCleanup(clear_cache)
        self.base_dir = tempfile.mkdtemp()
        base_dir = override_settings(BASE_DIR=self.base_dir)
        base_dir.enable()
        self.addCleanup(base_dir.disable)
        user = User.objects.create_user('carol', password='pass-12345')
        self.container = Container.objects.create(name='erpsqlite', image='x', port=40030, container_port=8169,
                                                  created_by=user)

    def routes(self):
        import yaml
        from .traefik_service import TraefikService
        TraefikService.generate_container_config(self.container)
        path = os.path.join(self.base_dir, 'traefik', 'container-erpsqlite.yml')
        return yaml.safe_load(open(path)) if os.path.exists(path) else None

    @mock.patch.dict(os.environ, {'MAIN_DOMAIN': 'hosting.example.com', 'LETSENCRYPT_EMAIL': 'ops@example.com'})
    def test_running_container_gets_https_subdomain(self):
        self.container.status = 'running'
        routes = self.routes()
        secure = routes['http']['routers']['container-erpsqlite-0-secure']
        self.assertEqual(secure['rule'], 'Host(`erpsqlite.hosting.example.com`)')
        service = routes['http']['services']['container-erpsqlite-service']
        self.assertEqual(service['loadBalancer']['servers'], [{'url': 'http://erpsqlite:8169'}])
        self.assertEqual(self.container.url, 'https://erpsqlite.hosting.example.com')

    @mock.patch.dict(os.environ, {'MAIN_DOMAIN': 'hosting.example.com', 'LETSENCRYPT_EMAIL': 'ops@example.com'})
    def test_stopped_container_has_no_route(self):
        self.container.status = 'running'
        self.assertIsNotNone(self.routes())
        self.container.status = 'stopped'
        self.assertIsNone(self.routes())



class TrialTests(BaseTestCase):
    """Test mode of a project: public demo page, its limits, the build and the expiry."""

    def setUp(self):
        super().setUp()
        from .project_models import Project
        self.demos = Project.objects.create(name='BIM demos', owner=self.alice)
        self.alice_project.trial_enabled = True
        self.alice_project.trial_slug = 'bim'
        self.alice_project.trial_target_project = self.demos
        self.alice_project.trial_message = 'Prueba BIM'
        self.alice_project.save()
        self.alice_instance.status = Instance.Status.RUNNING
        self.alice_instance.odoo_version = '18.0'
        self.alice_instance.description = 'Odoo 18 con BIM'
        self.alice_instance.save()
        Instance.objects.create(name='alice-stopped', owner=self.alice, project=self.alice_project, status=Instance.Status.STOPPED)

    @staticmethod
    def captcha(right=True):
        from django.core import signing
        from .services.trials import make_captcha
        _question, token = make_captcha()
        numbers = signing.loads(token, salt='trial-captcha')
        return token, str(numbers['a'] + numbers['b'] + (0 if right else 1))

    def ask(self, email='ana@example.com', **extra):
        token, answer = self.captcha()
        data = {'name': 'Ana', 'email': email, 'company': 'Constructora Sol', 'job_title': 'Jefa de obra',
                'phone': '+34 600 111 222', 'country': 'España', 'instance': self.alice_instance.pk,
                'captcha_token': token, 'captcha_answer': answer, **extra}
        return self.client.post('/bim/', data, REMOTE_ADDR=data.pop('ip', '10.0.0.1'))

    def test_the_form_asks_for_job_title_phone_country_and_a_sum(self):
        from .trial_models import TrialRequest
        response = self.client.get('/bim/')
        self.assertContains(response, 'name="job_title"')
        self.assertContains(response, 'name="country"')
        self.assertContains(response, 'name="captcha_token"')
        self.assertContains(response, 'cuánto es')
        # Missing data or a wrong sum: no demo
        self.assertContains(self.ask(country=''), 'id_country_error')
        token, wrong = self.captcha(right=False)
        self.assertContains(self.ask(captcha_token=token, captcha_answer=wrong), 'La suma no es correcta')
        self.assertContains(self.ask(captcha_token='forged', captcha_answer='4'), 'La suma no es correcta')
        self.assertFalse(TrialRequest.objects.exists())
        # Right: stored with the new data; the same question can't be used twice
        token, answer = self.captcha()
        self.ask(captcha_token=token, captcha_answer=answer)
        trial = TrialRequest.objects.get()
        self.assertEqual((trial.job_title, trial.phone, trial.country), ('Jefa de obra', '+34 600 111 222', 'España'))
        self.assertContains(self.ask(email='otra@example.com', ip='10.0.0.9', captcha_token=token, captcha_answer=answer),
                            'La suma no es correcta')

    def project_form(self, **data):
        from .forms import ProjectForm
        values = {'name': 'Nuevo', 'description': '', 'trial_days': 15, 'trial_max_active': 3, **data}
        return ProjectForm(values, owner=self.alice, user=self.alice)

    def test_form_requires_url_and_sibling_project_in_test_mode(self):
        form = self.project_form(trial_enabled='on')
        self.assertFalse(form.is_valid())
        self.assertIn('trial_slug', form.errors)
        self.assertIn('trial_target_project', form.errors)
        self.assertTrue(self.project_form(trial_enabled='on', trial_slug='erp', trial_target_project=self.demos.pk).is_valid())
        # Only projects of the same owner, and the URL can't be a page of the panel or taken
        self.assertIn('trial_target_project', self.project_form(trial_enabled='on', trial_slug='erp',
                                                                trial_target_project=self.bob_project.pk).errors)
        for slug in ('projects', 'admin', 'static', 'bim'):
            self.assertIn('trial_slug', self.project_form(trial_enabled='on', trial_slug=slug, trial_target_project=self.demos.pk).errors, slug)

    def test_page_lists_running_instances_with_their_description(self):
        response = self.client.get('/bim/')
        self.assertContains(response, 'Prueba BIM')
        self.assertContains(response, 'alice-odoo')
        self.assertContains(response, 'Odoo 18 con BIM')
        self.assertNotContains(response, 'alice-stopped')
        self.assertEqual(self.client.get('/bim').status_code, 301)
        self.alice_project.trial_enabled = False
        self.alice_project.save()
        self.assertEqual(self.client.get('/bim/').status_code, 404)
        self.assertEqual(self.client.get('/nothing-here/').status_code, 404)

    def test_request_queues_the_demo_and_one_per_email_a_month(self):
        from .task_models import Task
        from .trial_models import TrialRequest
        response = self.ask()
        trial = TrialRequest.objects.get()
        self.assertRedirects(response, f'/bim/demo/{trial.token}/', fetch_redirect_response=False)
        self.assertEqual((trial.source, trial.email, trial.version), (self.alice_instance, 'ana@example.com', '18.0'))
        self.assertEqual(trial.task.kind, Task.Kind.TRIAL)
        self.assertEqual(trial.task.params, {'trial': trial.pk})

        response = self.ask(email='ANA@example.com')
        self.assertContains(response, 'Ya pediste una demo este mes')
        self.assertEqual(TrialRequest.objects.count(), 1)
        # A failed one doesn't count
        trial.status = TrialRequest.Status.FAILED
        trial.save()
        self.ask()
        self.assertEqual(TrialRequest.objects.count(), 2)

    def test_no_more_demos_than_the_limit_at_the_same_time(self):
        from .trial_models import TrialRequest
        self.alice_project.trial_max_active = 1
        self.alice_project.save()
        self.ask()
        self.assertContains(self.ask(email='otro@example.com', ip='10.0.0.2'), 'no quedan plazas')
        self.assertEqual(TrialRequest.objects.count(), 1)

    def test_bots_filling_the_hidden_field_are_ignored(self):
        from .trial_models import TrialRequest
        self.ask(website='http://spam')
        self.assertFalse(TrialRequest.objects.exists())

    def test_public_api_lists_the_demos_with_cors(self):
        response = self.client.get('/api/public/demos/bim/')
        self.assertEqual(response['Access-Control-Allow-Origin'], '*')
        data = response.json()
        self.assertEqual((data['slug'], data['days'], data['message'], data['available']), ('bim', 15, 'Prueba BIM', True))
        self.assertTrue(data['url'].endswith('/bim/'))
        self.assertEqual(data['instances'], [{'id': self.alice_instance.pk, 'name': 'alice-odoo', 'version': '18.0',
                                              'description': 'Odoo 18 con BIM'}])
        self.assertEqual(self.client.get('/api/public/demos/nope/').status_code, 404)

    def test_status_shows_progress_and_the_credentials_once_ready(self):
        from .trial_models import TrialRequest
        self.ask()
        trial = TrialRequest.objects.get()
        url = f'/bim/demo/{trial.token}/?format=json'
        trial.task.status, trial.task.progress, trial.task.step = 'running', 0, 'Crear demo · alice-odoo · alice'
        trial.task.save()
        data = self.client.get(url).json()
        self.assertEqual((data['status'], data['step']), ('pending', 'Preparando tu demo'))
        self.assertNotIn('password', data)
        trial.task.progress, trial.task.step = 40, 'Copiando el espacio de trabajo'
        trial.task.save()
        self.assertEqual(self.client.get(url).json()['progress'], 40)
        self.assertContains(self.client.get(f'/bim/demo/{trial.token}/'), 'role="progressbar"')

        from django.utils import timezone
        demo = Instance.objects.create(name='bim-demo', project=self.demos)
        trial.instance, trial.status, trial.admin_login, trial.admin_password = demo, 'ready', 'admin', 's3cret'
        trial.expires_at = timezone.now()
        trial.save()
        data = self.client.get(url).json()
        self.assertEqual((data['status'], data['login'], data['password'], data['url']), ('ready', 'admin', 's3cret', demo.url))
        self.assertEqual(self.client.get('/bim/demo/wrong-token/').status_code, 404)

    def test_build_copies_into_the_sibling_project_with_a_new_admin_password(self):
        from .services.trials import build_demo, request_demo
        trial, _ = request_demo(self.alice_project, self.alice_instance, 'Ana', 'ana@example.com', 'Constructora Sol')
        service = mock.MagicMock()
        service.sanitize_demo.return_value = ['shop: limpia']
        service.copy_instance.side_effect = lambda source, name, **kwargs: Instance.objects.create(name=name, project=kwargs['project'])
        service.set_admin_password.return_value = 'admin'
        with mock.patch('orchestrator.services.DockerService', return_value=service), \
                mock.patch('orchestrator.traefik_service.TraefikService.generate_instance_config', return_value=(True, '')) as routes:
            build_demo(trial.task)
        trial.refresh_from_db()
        self.assertEqual(trial.status, 'ready')
        self.assertTrue(trial.instance.name.startswith('bim-constructora-sol-'))
        self.assertEqual((trial.instance.project, trial.instance.owner), (self.demos, self.alice))
        self.assertEqual(service.copy_instance.call_args.kwargs, {'project': self.demos, 'create_branch': False, 'origin': 'trial',
                                                                  'neutralize': 'mail'})
        self.assertEqual(service.set_admin_password.call_args.args, (trial.instance, trial.admin_password))
        self.assertGreaterEqual(len(trial.admin_password), 12)
        self.assertAlmostEqual((trial.expires_at - trial.created_at).total_seconds(), 15 * 86400, delta=60)
        routes.assert_called_once_with(trial.instance)
        service.sanitize_demo.assert_called_once_with(trial.instance)
        service.restart_instance.assert_called_once_with(trial.instance)
        trial.task.refresh_from_db()
        self.assertEqual(trial.task.instance, trial.instance)

    def test_a_failed_build_removes_the_half_built_copy(self):
        from .services.trials import build_demo, request_demo
        trial, _ = request_demo(self.alice_project, self.alice_instance, 'Ana', 'ana@example.com')
        service = mock.MagicMock()

        def copy(source, name, **kwargs):
            Instance.objects.create(name=name, project=kwargs['project'])
            raise Exception('pg_dumpall failed')
        service.copy_instance.side_effect = copy
        with mock.patch('orchestrator.services.DockerService', return_value=service), self.assertRaises(Exception):
            build_demo(trial.task)
        trial.refresh_from_db()
        self.assertEqual((trial.status, trial.error), ('failed', 'pg_dumpall failed'))
        self.assertFalse(self.demos.instances.exists())

    def test_expired_demos_stop_and_are_deleted_a_week_later(self):
        from datetime import timedelta
        from django.utils import timezone
        from .services.trials import expire_demos
        from .trial_models import TrialRequest
        demo = Instance.objects.create(name='bim-demo', project=self.demos, status=Instance.Status.RUNNING)
        trial = TrialRequest.objects.create(project=self.alice_project, email='a@example.com', name='A', instance=demo,
                                            status='ready', expires_at=timezone.now() + timedelta(days=1))
        service = mock.MagicMock()
        with mock.patch('orchestrator.services.DockerService', return_value=service):
            self.assertEqual(expire_demos(), [])
            expire_demos(timezone.now() + timedelta(days=2))
            service.stop_instance.assert_called_once_with(demo)
            trial.refresh_from_db()
            self.assertEqual(trial.status, 'expired')
            # Expired demos don't take a place any more, and the page says it's over
            self.assertEqual(self.client.get(f'/bim/demo/{trial.token}/?format=json').json()['status'], 'expired')
            expire_demos(timezone.now() + timedelta(days=10))
        self.assertFalse(Instance.objects.filter(pk=demo.pk).exists())
        self.docker.return_value.delete_instance.assert_called_once()

    def test_instance_description_is_editable_by_its_owner(self):
        self.client.force_login(self.bob)
        self.client.post(f'/instance/{self.alice_instance.pk}/update-description/', {'description': 'hack'})
        self.client.force_login(self.alice)
        self.client.post(f'/instance/{self.alice_instance.pk}/update-description/', {'description': ' Nueva '})
        self.alice_instance.refresh_from_db()
        self.assertEqual(self.alice_instance.description, 'Nueva')

    def test_project_page_shows_the_public_url_and_api(self):
        self.client.force_login(self.alice)
        response = self.client.get(f'/project/{self.alice_project.pk}/')
        self.assertContains(response, 'http://testserver/bim/')
        self.assertContains(response, 'http://testserver/api/public/demos/bim/')


class AdminPasswordTests(TestCase):
    def test_hash_is_the_pbkdf2_sha512_odoo_checks(self):
        import base64
        import hashlib
        from .services.docker_service import odoo_password_hash
        scheme, rounds, salt, checksum = odoo_password_hash('s3cret', rounds=1000).split('$')[1:]
        self.assertEqual((scheme, rounds), ('pbkdf2-sha512', '1000'))

        def unab64(text):
            text = text.replace('.', '+')
            return base64.b64decode(text + '=' * (-len(text) % 4))
        self.assertEqual(unab64(checksum), hashlib.pbkdf2_hmac('sha512', b's3cret', unab64(salt), 1000))

    def sql(self, version, has_password_crypt=False):
        from .services.docker_service import DockerService
        instance = Instance(name='demo', odoo_version=version)
        with mock.patch('orchestrator.services.docker_service.docker.from_env'):
            service = DockerService()
        container = mock.Mock()

        def run(command, environment=None):
            sql = command[-1]
            output = b'admin' if sql.startswith('SELECT login') else (b'1' if has_password_crypt and 'information_schema' in sql else b'0')
            return mock.Mock(exit_code=0, output=output)
        container.exec_run.side_effect = run
        with mock.patch.object(service, '_start_db_container', return_value=container), \
                mock.patch.object(service, '_list_user_databases', return_value=['shop']):
            self.assertEqual(service.set_admin_password(instance, 'pw123456'), 'admin')
        return [call.args[0][-1] for call in container.exec_run.call_args_list if call.args[0][-1].startswith('UPDATE')]

    def neutralize_sql(self, version, crons=True):
        from .services.docker_service import DockerService
        with mock.patch('orchestrator.services.docker_service.docker.from_env'):
            service = DockerService()
        container = mock.Mock()
        container.exec_run.return_value = mock.Mock(exit_code=0, output=b'')
        with mock.patch.object(service, '_start_db_container', return_value=container), \
                mock.patch.object(service, '_wait_for_postgres'), \
                mock.patch.object(service, '_list_user_databases', return_value=['shop']):
            notes = service.neutralize_databases(Instance(name='copy', odoo_version=version), crons=crons)
        self.assertEqual(len(notes), 1)
        return ' ; '.join(call.args[0][-1] for call in container.exec_run.call_args_list)

    def test_neutralize_a_copy(self):
        sql = self.neutralize_sql('17.0')
        for fragment in ('UPDATE ir_mail_server SET active = false', 'UPDATE fetchmail_server SET active = false',
                         'DELETE FROM res_users_apikeys', "UPDATE payment_provider SET state = 'disabled'",
                         'UPDATE ir_cron SET active = false', "name = 'autovacuum_job'", 'database.is_neutralized',
                         "key = 'database.uuid'"):
            self.assertIn(fragment, sql)
        # Odoo 12 has no neutralized ribbon; a demo keeps its scheduled actions
        self.assertNotIn('database.is_neutralized', self.neutralize_sql('12.0'))
        self.assertNotIn('ir_cron', self.neutralize_sql('18.0', crons=False))

    def test_admin_password_by_version(self):
        [sql] = self.sql('18.0')
        self.assertRegex(sql, r"^UPDATE res_users SET password = '\$pbkdf2-sha512\$600000\$[^']+' WHERE id = 2$")
        [sql] = self.sql('11.0', has_password_crypt=True)
        self.assertRegex(sql, r"SET password = NULL, password_crypt = '\$pbkdf2-sha512\$.+' WHERE id = 1$")
        self.assertEqual(self.sql('8.0'), ["UPDATE res_users SET password = 'pw123456' WHERE id = 1"])


class SecurityHardeningTests(BaseTestCase):
    """The fixes of the security review (v1.0.47)."""

    def test_api_cannot_write_internal_instance_fields(self):
        self.client.force_login(self.alice)
        url = f'/api/instances/{self.alice_instance.pk}/'
        before = Instance.objects.get(pk=self.alice_instance.pk)
        response = self.client.patch(url, {'data_volume': 'odoo_data_bob-odoo', 'subdomain': 'x`)||Host(`evil',
                                           'master_password': 'mine', 'name': 'renamed', 'ssl_certificate_path': '/etc/shadow',
                                           'description': 'ok'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        after = Instance.objects.get(pk=self.alice_instance.pk)
        self.assertEqual((after.data_volume, after.subdomain, after.master_password, after.name, after.ssl_certificate_path),
                         (before.data_volume, before.subdomain, before.master_password, before.name, before.ssl_certificate_path))
        self.assertEqual(after.description, 'ok')
        self.assertNotIn('data_volume', response.json())

    def test_api_rejects_unsafe_repositories_and_branches(self):
        self.client.force_login(self.alice)
        for repo, branch in (('file:///etc', 'main'), ('ext::sh -c id', 'main'), ('https://github.com/a/b.git', '--upload-pack=id'),
                             ('-uhttps://github.com/a/b', 'main'), ('https://github.com/a/b.git', '../x')):
            response = self.client.post('/api/instances/', {'name': 'repo-test', 'project': self.alice_project.pk,
                                                            'github_repo': repo, 'github_branch': branch}, content_type='application/json')
            self.assertEqual(response.status_code, 400, (repo, branch))
        self.assertFalse(Instance.objects.filter(name='repo-test').exists())

    def test_clients_never_see_the_master_password(self):
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.client.force_login(self.bob)
        data = self.client.get(f'/api/instances/{self.alice_instance.pk}/').json()
        self.assertNotIn('master_password', data)
        self.assertNotContains(self.client.get(f'/instance/{self.alice_instance.pk}/'), self.alice_instance.master_password)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(f'/api/instances/{self.alice_instance.pk}/').json()['master_password'],
                         self.alice_instance.master_password)

    def test_containers_cannot_take_panel_names_or_foreign_volumes(self):
        from .container_service import ContainerService, reserved_container_name
        from .container_models import Container
        for name in ('app', 'db', 'traefik', 'community-sh-app-1', 'odoo-x'):
            self.assertTrue(reserved_container_name(name), name)
        self.assertFalse(reserved_container_name('n8n-acme'))
        self.client.force_login(self.alice)
        response = self.client.post('/api/containers/', {'name': 'app', 'image': 'alpine'}, content_type='application/json')
        self.assertEqual(response.status_code, 400)

        container = Container.objects.create(name='mine', image='alpine', created_by=self.alice, port=31000, container_port=80)
        volume = mock.Mock(attrs={'Labels': {'com.docker.compose.project': 'community-sh'}})
        volume.name = 'mine_x'
        self.assertFalse(ContainerService._volume_is_ours(volume, container))
        volume.attrs, volume.name = {'Labels': {}}, 'odoo_data_bob-odoo'
        self.assertFalse(ContainerService._volume_is_ours(volume, container))
        volume.attrs, volume.name = {'Labels': {'community-sh.container': str(container.pk)}}, 'mine_x'
        self.assertTrue(ContainerService._volume_is_ours(volume, container))
        panel = mock.Mock(id='abc', attrs={'Config': {'Labels': {'com.docker.compose.project': 'community-sh'}}})
        self.assertFalse(ContainerService._container_is_ours(panel, container))

    def test_non_admins_cannot_add_volumes_to_a_template(self):
        from .container_views import _restricted_config_error
        config = {'volumes': {'data': {'host': 'x', 'container': '/data'}, 'postgres_data': {'host': 'y', 'container': '/pg'}}, 'network': 'bridge'}
        self.assertIn('volúmenes', _restricted_config_error(config, 'bridge', {'data'}))
        self.assertIsNone(_restricted_config_error({'volumes': {'data': {'host': 'x', 'container': '/d'}}}, 'bridge', {'data'}))

    def test_demos_get_no_ai_assistant(self):
        import hashlib, hmac, json, time
        from .services.docker_service import admin_login_secret
        self.alice_instance.origin = 'trial'
        self.alice_instance.save()
        body = json.dumps({'db': 'acme', 'model': 'res.partner', 'res_id': 1, 'text': 'hola'}).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(admin_login_secret(self.alice_instance).encode(), timestamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
        with mock.patch('orchestrator.services.ai.get_ai_config', return_value={'key': 'x'}):
            response = self.client.post(f'/odoo-ai/{self.alice_instance.name}/', body, content_type='application/json',
                                        HTTP_X_CSH_TIMESTAMP=timestamp, HTTP_X_CSH_SIGNATURE=signature)
        self.assertEqual(response.status_code, 403)
        # An unknown instance answers like a bad signature
        response = self.client.post('/odoo-ai/does-not-exist/', body, content_type='application/json',
                                    HTTP_X_CSH_TIMESTAMP=timestamp, HTTP_X_CSH_SIGNATURE=signature)
        self.assertEqual((response.status_code, response.json()['message']), (403, 'Firma no válida'))

    def test_client_ip_only_trusts_the_proxy_entry(self):
        from django.test import RequestFactory
        from .permissions import client_ip
        factory = RequestFactory()
        proxied = factory.get('/', REMOTE_ADDR='172.18.0.5', HTTP_X_FORWARDED_FOR='1.2.3.4, 9.9.9.9')
        self.assertEqual(client_ip(proxied), '9.9.9.9')  # Traefik's entry is the last one
        direct = factory.get('/', REMOTE_ADDR='8.8.4.4', HTTP_X_FORWARDED_FOR='1.2.3.4')
        self.assertEqual(client_ip(direct), '8.8.4.4')

    def test_login_lockout_covers_unicode_variants_of_the_username(self):
        for name in ('ａlice', 'ALICE', 'alice', 'aｌice', 'Alice'):
            self.client.post(reverse('login'), {'username': name, 'password': 'wrong'})
        self.client.post(reverse('login'), {'username': 'alice', 'password': 'pass-12345'})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_django_admin_login_goes_through_the_panel_login(self):
        response = self.client.get('/admin/login/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('login'))

    def test_tokens_need_2fa_when_it_is_mandatory(self):
        from .mcp_models import MCPToken, hash_token
        MCPToken.objects.create(user=self.alice, name='t', token_hash=hash_token('csh_secret'))
        self.assertEqual(self.client.get('/api/instances/', HTTP_AUTHORIZATION='Bearer csh_secret').status_code, 200)
        self.config.two_factor_required = True
        self.config.save()
        self.assertEqual(self.client.get('/api/instances/', HTTP_AUTHORIZATION='Bearer csh_secret').status_code, 401)

    def test_disabling_2fa_needs_a_current_code(self):
        import pyotp
        profile = self.alice.profile
        profile.two_factor_enabled, profile.two_factor_secret = True, 'JBSWY3DPEHPK3PXP'
        profile.save()
        self.client.force_login(self.alice)
        self.client.post(reverse('two-factor-setup'), {'action': 'disable'})
        profile.refresh_from_db()
        self.assertTrue(profile.two_factor_enabled)
        # Starting a new setup doesn't replace the active secret until a code of the new one is verified
        self.client.post(reverse('two-factor-setup'), {'action': 'enable', 'current_code': pyotp.TOTP('JBSWY3DPEHPK3PXP').now()})
        profile.refresh_from_db()
        self.assertEqual(profile.two_factor_secret, 'JBSWY3DPEHPK3PXP')
        self.client.post(reverse('two-factor-setup'), {'action': 'disable', 'current_code': pyotp.TOTP('JBSWY3DPEHPK3PXP').now()})
        profile.refresh_from_db()
        self.assertFalse(profile.two_factor_enabled)

    def test_custom_domain_cannot_take_another_resource_subdomain(self):
        from .permissions import domain_in_use
        from .services import domains
        self.config.main_domain = 'example.com'
        self.config.save()
        domains.clear_cache()
        self.addCleanup(domains.clear_cache)
        bob_host = f'{self.bob_instance.subdomain}.example.com'
        self.assertTrue(domain_in_use(bob_host, exclude_instance=self.alice_instance))
        self.assertFalse(domain_in_use(bob_host, exclude_instance=self.bob_instance))
        self.assertFalse(domain_in_use('shop.alice.com'))

    def test_traefik_rules_only_take_host_names(self):
        from .traefik_service import TraefikService
        config = TraefikService._routes('x', ['ok.example.com', 'x`)||Host(`evil.com', 'a b'], 'http://x:1', None)
        rules = [router['rule'] for router in config['http']['routers'].values()]
        self.assertTrue(rules)
        self.assertEqual(set(rules), {'Host(`ok.example.com`)'})

    def test_zip_bombs_and_paths_out_of_the_folder_are_refused(self):
        import io, tempfile, zipfile
        from .services.archives import safe_extractall
        for name, size in (('../evil.py', 10), ('/etc/x', 10), ('big.bin', 3 * 1024 * 1024)):
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(name, b'0' * size)
            with zipfile.ZipFile(data) as zf, self.assertRaises(ValueError):
                safe_extractall(zf, tempfile.mkdtemp(), max_bytes=1024 * 1024)

    def test_odoo_listens_only_on_the_host_with_a_domain_and_https(self):
        from .services.docker_service import published_ip
        with mock.patch('orchestrator.services.domains.main_domain', return_value='example.com'), \
                mock.patch.dict('os.environ', {'LETSENCRYPT_EMAIL': 'a@b.c', 'ODOO_PUBLISH_IP': ''}):
            self.assertEqual(published_ip(), '127.0.0.1')
        with mock.patch('orchestrator.services.domains.main_domain', return_value=''):
            self.assertEqual(published_ip(), '0.0.0.0')

    def test_panel_only_answers_its_own_hosts_once_a_domain_is_set(self):
        from .services import domains
        self.assertEqual(self.client.get('/accounts/login/', HTTP_HOST='anything.test').status_code, 200)
        self.config.main_domain = 'example.com'
        self.config.save()
        domains.clear_cache()
        self.addCleanup(domains.clear_cache)
        self.assertEqual(self.client.get('/accounts/login/', HTTP_HOST='evil.test').status_code, 403)
        self.assertEqual(self.client.get('/accounts/login/', HTTP_HOST='example.com').status_code, 200)

    def test_demo_copy_is_cleaned_before_it_is_handed_over(self):
        from .services.docker_service import DockerService
        instance = Instance(name='demo', odoo_version='18.0')
        with mock.patch('orchestrator.services.docker_service.docker.from_env'):
            service = DockerService()
        container = mock.Mock()
        container.exec_run.return_value = mock.Mock(exit_code=0, output=b'')
        with mock.patch.object(service, '_start_db_container', return_value=container), \
                mock.patch.object(service, '_list_user_databases', return_value=['shop']):
            service.sanitize_demo(instance)
        sql = [call.args[0][-1] for call in container.exec_run.call_args_list]
        self.assertRegex(sql[0], r"^UPDATE res_users SET password = '\$pbkdf2-sha512\$.+' WHERE id <> 2")
        self.assertIn('UPDATE ir_mail_server SET active = false', sql)
        self.assertIn('DELETE FROM res_users_apikeys', sql)
        self.assertTrue(any("'database.secret'" in line for line in sql))

    def test_demo_limits_hold_for_the_whole_server(self):
        from .project_models import Project
        from .services.trials import request_demo
        demos = Project.objects.create(name='demos', owner=self.alice)
        self.alice_project.trial_enabled, self.alice_project.trial_slug = True, 'bim'
        self.alice_project.trial_target_project, self.alice_project.trial_max_active = demos, 10
        self.alice_project.save()
        self.config.trial_max_active_total = 2
        self.config.save()
        results = [request_demo(self.alice_project, self.alice_instance, 'X', f'x{i}@example.com', ip=f'10.0.0.{i}') for i in range(4)]
        self.assertEqual([trial is not None for trial, _ in results], [True, True, False, False])

    def test_demo_status_is_never_cached(self):
        from .project_models import Project
        from .services.trials import request_demo
        demos = Project.objects.create(name='demos', owner=self.alice)
        self.alice_project.trial_enabled, self.alice_project.trial_slug, self.alice_project.trial_target_project = True, 'bim', demos
        self.alice_project.save()
        trial, _ = request_demo(self.alice_project, self.alice_instance, 'X', 'x@example.com')
        response = self.client.get(f'/bim/demo/{trial.token}/?format=json')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')


class DemoExtrasTests(BaseTestCase):
    """Email of the credentials, days left, daily limit, the demo APIs, settings API, KPIs and the dashboard."""

    def setUp(self):
        super().setUp()
        from .project_models import Project
        self.demos = Project.objects.create(name='BIM demos', owner=self.alice)
        self.alice_project.trial_enabled, self.alice_project.trial_slug = True, 'bim'
        self.alice_project.trial_target_project = self.demos
        self.alice_project.save()
        self.alice_instance.status, self.alice_instance.odoo_version = Instance.Status.RUNNING, '18.0'
        self.alice_instance.save()

    def smtp_on(self):
        self.config.smtp_enabled, self.config.smtp_host, self.config.smtp_from_email = True, 'smtp.example.com', 'demos@example.com'
        self.config.save()

    def build(self, trial):
        from .services.trials import build_demo
        service = mock.MagicMock()
        service.copy_instance.side_effect = lambda source, name, **kw: Instance.objects.create(name=name, project=kw['project'])
        service.set_admin_password.return_value = 'admin'
        service.sanitize_demo.return_value = []
        with mock.patch('orchestrator.services.DockerService', return_value=service), \
                mock.patch('orchestrator.traefik_service.TraefikService.generate_instance_config', return_value=(True, '')):
            build_demo(trial.task)
        trial.refresh_from_db()
        return trial

    def test_ready_demo_is_emailed_when_smtp_is_on(self):
        from django.core import mail as outbox
        from .services.trials import request_demo
        trial, _ = request_demo(self.alice_project, self.alice_instance, 'Ana', 'ana@example.com', 'Sol', '+34 600')
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'), \
                mock.patch('orchestrator.services.mail.connection', side_effect=lambda *a, **k: __import__('django.core.mail', fromlist=['get_connection']).get_connection()):
            self.assertIsNone(self.build(trial).emailed_at)  # no SMTP server: nothing sent
            self.assertEqual(len(outbox.outbox), 0)
            self.smtp_on()
            trial2, _ = request_demo(self.alice_project, self.alice_instance, 'Leo', 'leo@example.com', 'Sol', '+34 600', ip='10.0.0.7')
            trial2 = self.build(trial2)
        self.assertIsNotNone(trial2.emailed_at)
        self.assertEqual(outbox.outbox[0].to, ['leo@example.com'])
        self.assertIn(trial2.admin_password, outbox.outbox[0].body)
        self.assertEqual(outbox.outbox[0].from_email, 'Community SH <demos@example.com>')

    def test_days_left_until_stop_and_delete(self):
        from datetime import timedelta
        from django.utils import timezone
        from .trial_models import TrialRequest
        demo = Instance.objects.create(name='bim-x', project=self.demos, owner=self.alice)
        trial = TrialRequest.objects.create(project=self.alice_project, name='A', email='a@example.com', instance=demo,
                                            status='ready', expires_at=timezone.now() + timedelta(days=5, hours=1))
        self.assertEqual((trial.days_until_stop, trial.days_until_delete), (6, 13))
        self.client.force_login(self.alice)
        response = self.client.get(f'/instance/{demo.pk}/')
        self.assertContains(response, 'Se detiene en <strong>6 días</strong>')
        self.assertContains(response, 'Se elimina en <strong>13 días</strong>')

    def test_daily_limit_comes_from_settings(self):
        from .services.trials import request_demo
        self.config.trial_max_per_day = 2
        self.config.save()
        results = [request_demo(self.alice_project, self.alice_instance, 'X', f'x{i}@example.com', ip=f'10.1.0.{i}')
                   for i in range(3)]
        self.assertEqual([error for _, error in results][:2], ['', ''])
        self.assertIn('Hoy ya no', results[2][1])

    def test_public_api_asks_for_a_demo_with_the_captcha(self):
        import json
        from django.core import signing
        from .trial_models import TrialRequest
        captcha = self.client.get('/api/public/demos/bim/captcha/').json()
        numbers = signing.loads(captcha['token'], salt='trial-captcha')
        body = {'name': 'Ana', 'email': 'ana@example.com', 'company': 'Sol', 'job_title': 'CEO', 'phone': '+34 600 111 222',
                'country': 'España', 'instance': self.alice_instance.pk, 'captcha_token': captcha['token'],
                'captcha_answer': numbers['a'] + numbers['b']}
        self.assertEqual(self.client.options('/api/public/demos/bim/')['Access-Control-Allow-Methods'], 'GET, POST, OPTIONS')
        response = self.client.post('/api/public/demos/bim/', json.dumps({**body, 'captcha_answer': 0}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('captcha_answer', response.json()['errors'])
        self.assertIn('question', response.json()['captcha'])
        response = self.client.post('/api/public/demos/bim/', json.dumps(body), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response['Access-Control-Allow-Origin'], '*')
        trial = TrialRequest.objects.get()
        self.assertTrue(response.json()['status_api'].endswith(f'/bim/demo/{trial.token}/?format=json'))
        self.assertEqual(self.client.get(response.json()['status_api'])['Access-Control-Allow-Origin'], '*')

    def test_token_api_asks_for_and_follows_demos(self):
        self.client.force_login(self.alice)
        body = {'project': self.alice_project.pk, 'instance': self.alice_instance.pk, 'name': 'Ana', 'email': 'ana@example.com',
                'company': 'Sol', 'job_title': 'CEO', 'phone': '+34 600 111 222', 'country': 'España'}
        response = self.client.post('/api/demos/', body, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        demo = response.json()
        self.assertEqual((demo['status'], demo['source'], demo['job_title']), ('pending', 'alice-odoo', 'CEO'))
        self.assertEqual(self.client.get(f"/api/demos/{demo['id']}/").json()['email'], 'ana@example.com')
        # Again with the same email: refused by the monthly limit
        self.assertEqual(self.client.post('/api/demos/', body, content_type='application/json').status_code, 429)
        # Someone else's project
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post('/api/demos/', body, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.get('/api/demos/').json(), [])

    def test_projects_api_configures_test_mode(self):
        self.client.force_login(self.alice)
        url = f'/api/projects/{self.demos.pk}/'
        response = self.client.patch(url, {'trial_enabled': True, 'trial_slug': 'erp', 'trial_target_project': self.bob_project.pk},
                                     content_type='application/json')
        self.assertEqual(response.status_code, 400)
        response = self.client.patch(url, {'trial_enabled': True, 'trial_slug': 'projects', 'trial_target_project': self.alice_project.pk},
                                     content_type='application/json')
        self.assertIn('trial_slug', response.json())
        response = self.client.patch(url, {'trial_enabled': True, 'trial_slug': 'erp', 'trial_target_project': self.alice_project.pk,
                                           'trial_days': 7}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['trial_url'].endswith('/erp/'))

    def test_settings_api_is_for_administrators_and_hides_the_password(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get('/api/settings/').status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.patch('/api/settings/', {'smtp_enabled': True, 'smtp_host': 'smtp.example.com', 'smtp_password': 's3cret',
                                                        'smtp_from_email': 'a@example.com', 'trial_max_per_day': 5}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = self.client.get('/api/settings/').json()
        self.assertNotIn('smtp_password', data)
        self.assertTrue(data['smtp_password_set'])
        self.assertEqual(data['trial_max_per_day'], 5)
        self.config.refresh_from_db()
        self.assertEqual(self.config.smtp_password, 's3cret')
        # An empty password keeps it
        self.client.patch('/api/settings/', {'smtp_password': ''}, content_type='application/json')
        self.config.refresh_from_db()
        self.assertEqual(self.config.smtp_password, 's3cret')

    def test_settings_page_saves_email_and_limits_and_tests_the_server(self):
        self.client.force_login(self.admin)
        self.client.post('/settings/', {'section': 'email', 'smtp_enabled': 'on', 'smtp_host': 'smtp.example.com', 'smtp_port': '465',
                                        'smtp_security': 'ssl', 'smtp_from_email': 'demos@example.com', 'smtp_password': 'pw'})
        self.client.post('/settings/', {'section': 'demos', 'trial_max_per_day': '7', 'trial_max_active_total': '2'})
        self.config.refresh_from_db()
        self.assertEqual((self.config.smtp_port, self.config.smtp_security, self.config.smtp_password,
                          self.config.trial_max_per_day, self.config.trial_max_active_total), (465, 'ssl', 'pw', 7, 2))
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=OSError('connection refused')):
            response = self.client.post('/settings/email/test/', {'smtp_host': 'smtp.example.com', 'smtp_port': '465',
                                                                 'smtp_from_email': 'demos@example.com', 'to': 'me@example.com'})
        self.assertIn('connection refused', response.json()['error'])
        with mock.patch('django.core.mail.EmailMessage.send', return_value=1):
            response = self.client.post('/settings/email/test/', {'smtp_host': 'smtp.example.com', 'smtp_port': '465',
                                                                 'smtp_from_email': 'demos@example.com', 'to': 'me@example.com'})
        self.assertTrue(response.json()['ok'])
        self.client.force_login(self.alice)
        self.assertEqual(self.client.post('/settings/email/test/', {}).status_code, 403)

    def test_project_kpis_and_dashboard(self):
        self.client.force_login(self.alice)
        response = self.client.get(f'/project/{self.alice_project.pk}/')
        self.assertContains(response, 'Demos activas')
        self.assertContains(response, 'Instancias en marcha')
        response = self.client.get('/dashboard/')
        self.assertContains(response, 'Instancias en marcha')
        self.assertContains(response, 'Pedidas hoy')
        self.assertNotContains(response, 'Usuarios sin 2FA')  # server KPIs: administrators only
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/dashboard/'), 'Usuarios sin 2FA')


class ProjectContainerTests(BaseTestCase):
    def test_containers_are_created_from_the_project(self):
        from .container_models import Container
        self.client.force_login(self.alice)
        page = self.client.get(f'/project/{self.alice_project.pk}/')
        self.assertContains(page, f'/container/new/?project={self.alice_project.pk}')
        form = self.client.get(f'/container/new/?project={self.alice_project.pk}')
        self.assertContains(form, f'<option value="{self.alice_project.pk}" selected>')
        with mock.patch('orchestrator.container_views.ContainerService') as service:
            service.return_value.create_container.return_value = (True, 'ok')
            self.client.post('/container/new/', {'template': 'custom', 'name': 'web-acme', 'image': 'nginx:alpine',
                                                 'port': '31080', 'container_port': '80', 'project': self.alice_project.pk})
            # Someone else's project is ignored
            self.client.post('/container/new/', {'template': 'custom', 'name': 'web-other', 'image': 'nginx:alpine',
                                                 'port': '31081', 'container_port': '80', 'project': self.bob_project.pk})
        self.assertEqual(Container.objects.get(name='web-acme').project, self.alice_project)
        self.assertIsNone(Container.objects.get(name='web-other').project)
        self.assertContains(self.client.get(f'/project/{self.alice_project.pk}/'), 'web-acme')
        # API: only your own projects
        response = self.client.patch(f"/api/containers/{Container.objects.get(name='web-other').pk}/",
                                     {'project': self.bob_project.pk}, content_type='application/json')
        self.assertEqual(response.status_code, 400)


class BlogTests(TestCase):
    def test_posts_without_author_render(self):
        from .blog_models import BlogPost
        post = BlogPost.objects.create(title='Hola', slug='hola', content='# Hola', published=True, author=None)
        self.assertContains(self.client.get('/blog/'), 'Community SH')
        self.assertContains(self.client.get(f'/blog/{post.slug}/'), 'Community SH')


class GitHubWebhookTests(BaseTestCase):
    """A push to one of an instance's repositories updates it (Modules → automatic update)."""

    def setUp(self):
        super().setUp()
        self.instance = self.alice_instance
        self.instance.github_repo, self.instance.github_branch = 'https://github.com/falconsoft3d/bim20-19.git', 'main'
        self.instance.auto_update = Instance.AutoUpdate.UPDATE_ALL
        self.instance.save()
        self.instance.repositories.create(url='https://github.com/falconsoft3d/module_to_sale_marlon', branch='19.0')

    def push(self, repo='https://github.com/falconsoft3d/bim20-19.git', branch='main', event='push', secret=None, delivery='d1', **extra):
        import hashlib, hmac, json
        body = json.dumps({'ref': f'refs/heads/{branch}', 'after': 'abcdef1234567',
                           'repository': {'clone_url': repo, 'html_url': repo.removesuffix('.git')}, **extra}).encode()
        signature = 'sha256=' + hmac.new((secret or self.instance.webhook_secret).encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(f'/webhooks/github/{self.instance.pk}/', body, content_type='application/json',
                                HTTP_X_HUB_SIGNATURE_256=signature, HTTP_X_GITHUB_EVENT=event, HTTP_X_GITHUB_DELIVERY=delivery)

    def test_signed_push_to_its_branch_queues_pull_and_update_all(self):
        from .task_models import Task
        self.assertEqual(self.push(secret='wrong').status_code, 403)
        self.assertEqual(self.push(event='ping', delivery='p').json()['detail'], 'pong')
        response = self.push()
        self.assertEqual(response.status_code, 202)
        task = Task.objects.get(kind=Task.Kind.PULL_REPOS)
        self.assertEqual((task.instance, task.params['update_all'], task.params['push']), (self.instance, True, 'bim20-19@main abcdef1'))
        # The same delivery again, and another push while it waits: still one task
        self.push()
        self.push(repo='https://github.com/falconsoft3d/module_to_sale_marlon', branch='19.0', delivery='d2')
        self.assertEqual(Task.objects.filter(kind=Task.Kind.PULL_REPOS).count(), 1)

    def test_other_repos_branches_or_disabled_are_ignored(self):
        from .task_models import Task
        self.push(branch='develop', delivery='a')
        self.push(repo='https://github.com/someone/else', delivery='b')
        self.push(deleted=True, delivery='c')
        self.instance.auto_update = ''
        self.instance.save()
        self.assertIn('desactivada', self.push(delivery='d').json()['detail'])
        self.assertFalse(Task.objects.filter(kind=Task.Kind.PULL_REPOS).exists())

    def test_push_updates_every_running_instance_of_that_repository(self):
        from .task_models import Task
        repo = 'https://github.com/falconsoft3d/module_to_sale_marlon'
        def other(name, status=Instance.Status.RUNNING, mode=Instance.AutoUpdate.PULL, branch='19.0'):
            instance = Instance.objects.create(name=name, owner=self.bob, project=self.bob_project, status=status, auto_update=mode)
            instance.repositories.create(url=repo + '.git', branch=branch)
            return instance
        running = other('shared-running')
        other('shared-stopped', status=Instance.Status.STOPPED)
        other('shared-off', mode='')
        other('shared-other-branch', branch='18.0')
        # Its own instance has auto update off: the others are updated all the same
        self.instance.auto_update = ''
        self.instance.save()
        self.assertEqual(self.push(repo=repo, branch='19.0').status_code, 202)
        task = Task.objects.get(kind=Task.Kind.PULL_REPOS)
        self.assertEqual(task.instance, running)
        self.assertEqual((task.params['update_all'], task.params['only_if_changed'], task.params['source']), (False, True, 'webhook'))

    def test_daily_update_once_a_day_from_its_hour(self):
        import datetime
        from .services.webhooks import DAILY_UPDATE_HOUR, queue_daily_updates
        from .task_models import Task
        self.instance.status = Instance.Status.RUNNING
        self.instance.save()
        # On by default: new instances follow their repositories
        self.assertEqual(Instance.objects.create(name='no-repos', owner=self.bob, project=self.bob_project,
                                                 status=Instance.Status.RUNNING).auto_update, Instance.AutoUpdate.PULL)
        day = datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc)
        if DAILY_UPDATE_HOUR:
            self.assertEqual(queue_daily_updates(day.replace(hour=DAILY_UPDATE_HOUR - 1)), [])
        self.assertEqual(queue_daily_updates(day.replace(hour=DAILY_UPDATE_HOUR)), ['alice-odoo'])
        Task.objects.update(status=Task.Status.DONE)
        self.assertEqual(queue_daily_updates(day.replace(hour=23)), [])  # already done today
        self.assertEqual(queue_daily_updates(day.replace(day=8, hour=DAILY_UPDATE_HOUR)), ['alice-odoo'])
        task = Task.objects.filter(kind=Task.Kind.PULL_REPOS).latest('pk')
        self.assertEqual((task.params['source'], task.params['update_all']), ('schedule', True))

    def test_automatic_pull_without_changes_does_not_restart(self):
        import tempfile
        from .services.docker_service import DockerService
        with mock.patch('orchestrator.services.docker_service.docker.from_env'):
            service = DockerService()
        with tempfile.TemporaryDirectory() as base, self.settings(BASE_DIR=base), \
                mock.patch.object(service, '_clone_repo'), \
                mock.patch.object(service, '_sync_extra_repos', return_value=[]), \
                mock.patch.object(service, '_write_odoo_config'), \
                mock.patch.object(service, 'update_all_modules') as update_all, \
                mock.patch.object(service, 'restart_instance') as restart:
            notes = service.pull_repositories(self.instance, update_all=True, only_if_changed=True)
            self.assertFalse(service.changed)
            self.assertIn('Sin cambios', notes[-1])
            update_all.assert_not_called()
            restart.assert_not_called()
            # A manual pull restarts all the same
            service.pull_repositories(self.instance)
            restart.assert_called_once()

    def test_unknown_instance_answers_like_a_bad_signature(self):
        response = self.client.post('/webhooks/github/99999/', b'{}', content_type='application/json',
                                    HTTP_X_HUB_SIGNATURE_256='sha256=00', HTTP_X_GITHUB_EVENT='push')
        self.assertEqual(response.status_code, 403)

    def test_update_all_runs_on_every_database_and_fails_loudly(self):
        from .services.docker_service import DockerService
        with mock.patch('orchestrator.services.docker_service.docker.from_env'):
            service = DockerService()
        odoo = mock.Mock(status='running')
        odoo.exec_run.return_value = mock.Mock(exit_code=0, output=b'done')
        with mock.patch.object(service, '_get_container', return_value=odoo), \
                mock.patch.object(service, '_start_db_container', return_value=mock.Mock()), \
                mock.patch.object(service, '_wait_for_postgres'), \
                mock.patch.object(service, '_list_user_databases', return_value=['shop', 'hotel']):
            notes = service.update_all_modules(self.instance)
            self.assertEqual(len(notes), 2)
            self.assertEqual([c.kwargs['environment'] for c in odoo.exec_run.call_args_list], [{'DB': 'shop'}, {'DB': 'hotel'}])
            self.assertIn('-u all', odoo.exec_run.call_args.args[0][2])
            odoo.exec_run.return_value = mock.Mock(exit_code=1, output=b'ParseError in view')
            with self.assertRaisesMessage(Exception, 'ParseError'):
                service.update_all_modules(self.instance)

    def test_settings_card_and_github_hook_creation(self):
        self.client.force_login(self.alice)
        self.client.post(f'/instance/{self.instance.pk}/auto-update/', {'auto_update': 'pull'})
        self.instance.refresh_from_db()
        self.assertEqual(self.instance.auto_update, 'pull')
        page = self.client.get(f'/instance/{self.instance.pk}/')
        self.assertContains(page, f'/webhooks/github/{self.instance.pk}/')
        GitHubConfig.objects.create(user=self.alice, personal_access_token='ghp_x')
        listing = mock.Mock(status_code=200, json=lambda: [])
        created = mock.Mock(status_code=201)
        with mock.patch('orchestrator.services.webhooks.requests.get', return_value=listing), \
                mock.patch('orchestrator.services.webhooks.requests.post', return_value=created) as post:
            self.client.post(f'/instance/{self.instance.pk}/webhook/github/')
        self.assertEqual(post.call_count, 2)  # main repository and the addons one
        self.assertEqual(post.call_args.kwargs['json']['config']['secret'], self.instance.webhook_secret)
        self.assertIn('/repos/falconsoft3d/module_to_sale_marlon/hooks', post.call_args.args[0])
        # Clients can't see or change it
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get(f'/instance/{self.instance.pk}/'), self.instance.webhook_secret)
        self.assertEqual(self.client.post(f'/instance/{self.instance.pk}/auto-update/', {'auto_update': ''}).status_code, 403)


class ContactTests(BaseTestCase):
    """Who asked for a demo stays in Contacts (one per email and owner, newest details win)."""

    def setUp(self):
        super().setUp()
        from .project_models import Project
        self.demos = Project.objects.create(name='BIM demos', owner=self.alice)
        self.alice_project.trial_enabled, self.alice_project.trial_slug = True, 'bim'
        self.alice_project.trial_target_project = self.demos
        self.alice_project.save()

    def ask(self, email='ana@example.com', **data):
        from .services.trials import request_demo
        values = {'company': 'Sol', 'phone': '+34 600', 'job_title': 'CEO', 'country': 'España', **data}
        return request_demo(self.alice_project, self.alice_instance, data.pop('name', 'Ana'), email,
                            values['company'], values['phone'], ip=data.pop('ip', '10.0.0.1'),
                            job_title=values['job_title'], country=values['country'])

    def test_a_demo_request_creates_or_updates_the_contact(self):
        from .contact_models import Contact
        from .trial_models import TrialRequest
        trial, _ = self.ask()
        contact = Contact.objects.get()
        self.assertEqual((contact.owner, contact.email, contact.company, contact.country), (self.alice, 'ana@example.com', 'Sol', 'España'))
        self.assertEqual(trial.contact, contact)
        # A month later, same email (any case), new company: still one contact, with the newest details
        TrialRequest.objects.update(created_at=trial.created_at - __import__('datetime').timedelta(days=40))
        self.ask(email='ANA@example.com', company='Sol Group', ip='10.0.0.2')
        self.assertEqual(Contact.objects.count(), 1)
        contact.refresh_from_db()
        self.assertEqual((contact.company, contact.trials.count()), ('Sol Group', 2))

    def test_contacts_menu_list_search_export_notes_and_delete(self):
        from .contact_models import Contact
        self.ask()
        self.ask(email='leo@example.com', company='Norte', country='México', ip='10.0.0.3')
        self.client.force_login(self.alice)
        self.assertContains(self.client.get('/dashboard/'), '/contacts/')
        response = self.client.get('/contacts/')
        self.assertContains(response, 'ana@example.com')
        self.assertContains(response, 'leo@example.com')
        response = self.client.get('/contacts/?q=norte')
        self.assertNotContains(response, 'ana@example.com')
        self.assertNotContains(self.client.get('/contacts/?country=México'), 'ana@example.com')
        csv_body = self.client.get('/contacts/export/').content.decode('utf-8-sig')
        self.assertIn('Nombre,Email,Empresa,Cargo', csv_body)
        self.assertIn('leo@example.com,Norte,CEO', csv_body)
        ana = Contact.objects.get(email='ana@example.com')
        self.client.post(f'/contact/{ana.pk}/', {'notes': 'Llamar el lunes'})
        ana.refresh_from_db()
        self.assertEqual(ana.notes, 'Llamar el lunes')
        self.assertContains(self.client.get(f'/contact/{ana.pk}/'), 'alice-odoo')
        self.client.post(f'/contact/{ana.pk}/delete/')
        self.assertFalse(Contact.objects.filter(pk=ana.pk).exists())
        # API
        data = self.client.get('/api/contacts/?q=leo').json()
        self.assertEqual([c['email'] for c in data], ['leo@example.com'])
        self.assertEqual(len(data[0]['demos']), 1)

    def test_only_the_owner_sees_their_contacts(self):
        self.ask()
        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get('/contacts/'), 'ana@example.com')
        self.assertEqual(self.client.get('/api/contacts/').json(), [])
        from .contact_models import Contact
        self.assertEqual(self.client.get(f'/contact/{Contact.objects.get().pk}/').status_code, 404)
        # A client user has no Contacts at all
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.bob.profile.is_client = True
        self.bob.profile.save()
        self.assertEqual(self.client.get('/contacts/').status_code, 403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/contacts/'), 'ana@example.com')


class DockerDeleteAllUnusedTests(BaseTestCase):
    def test_containers_tab_offers_deleting_everything_unused(self):
        from .services import docker_admin
        from .task_models import Task
        plan = {kind: [] for kind in docker_admin.CLEANUP_KINDS}
        plan['volumes'] = [('old_volume', 2048, None)]
        data = {'version': '27', 'containers': [], 'images': [], 'volumes': [], 'networks': [],
                'disk': {'containers': 0, 'images': 0, 'volumes': 0, 'build_cache': 0}, 'cleanup_plan': plan}
        self.client.force_login(self.admin)
        with mock.patch('orchestrator.services.docker_admin.overview', return_value=data):
            page = self.client.get(reverse('docker-overview')).content.decode()
        self.assertIn('Eliminar todo lo no en uso', page)
        for kind in docker_admin.CLEANUP_KINDS:
            self.assertIn(f'name="kinds" value="{kind}"', page)
        # What the modal sends: every kind, with the typed confirmation
        self.client.post(reverse('docker-cleanup'), {'kinds': list(docker_admin.CLEANUP_KINDS), 'confirm': 'BORRAR'})
        task = Task.objects.get(kind=Task.Kind.DOCKER_CLEANUP)
        self.assertEqual(task.params['kinds'], list(docker_admin.CLEANUP_KINDS))


class DemoApiKeyTests(BaseTestCase):
    """A project's own API key lets a website's backend ask for demos without the captcha."""

    def setUp(self):
        super().setUp()
        from .project_models import Project
        self.demos = Project.objects.create(name='BIM demos', owner=self.alice)
        self.alice_project.trial_enabled, self.alice_project.trial_slug = True, 'bim'
        self.alice_project.trial_target_project = self.demos
        self.alice_project.save()
        self.alice_instance.status = Instance.Status.RUNNING
        self.alice_instance.save()

    def ask(self, key=None, email='ana@example.com', **headers):
        import json
        body = {'instance': self.alice_instance.pk, 'name': 'Ana', 'email': email, 'company': 'Sol', 'job_title': 'CEO',
                'phone': '+34 600 111 222', 'country': 'España'}
        if key:
            headers['HTTP_AUTHORIZATION'] = f'Bearer {key}'
        return self.client.post('/api/public/demos/bim/', json.dumps(body), content_type='application/json', **headers)

    def generate(self):
        self.client.force_login(self.alice)
        self.client.post(f'/project/{self.alice_project.pk}/demo-api-key/')
        page = self.client.get(f'/project/{self.alice_project.pk}/').content.decode()
        import re
        key = re.search(r'csh_demo_[A-Za-z0-9_-]{20,}', page).group(0)
        self.client.logout()
        return key, page

    def test_key_is_shown_once_and_skips_the_captcha(self):
        from .trial_models import TrialRequest
        key, page = self.generate()
        self.assertIn('no se vuelve a mostrar', page)
        self.client.force_login(self.alice)
        self.assertNotIn(key, self.client.get(f'/project/{self.alice_project.pk}/').content.decode())
        self.client.logout()
        # Without key or captcha: refused; with the key: created
        self.assertEqual(self.ask().status_code, 400)
        self.assertEqual(self.ask(key='csh_demo_wrong').status_code, 401)
        response = self.ask(key=key)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(TrialRequest.objects.get().job_title, 'CEO')
        # X-Demo-Key works too; the per-address limit doesn't apply (a backend is always one address)
        self.alice_project.refresh_from_db()
        self.alice_project.trial_max_active = 10
        self.alice_project.save()
        self.config.trial_max_active_total = 10
        self.config.save()
        for i in range(4):
            response = self.ask(email=f'p{i}@example.com', HTTP_X_DEMO_KEY=key)
            self.assertEqual(response.status_code, 201, response.content.decode())
        # The monthly limit per email still does
        self.assertEqual(self.ask(key=key).status_code, 429)

    def test_regenerating_invalidates_the_previous_key(self):
        old, _ = self.generate()
        new, _ = self.generate()
        self.assertNotEqual(old, new)
        self.assertEqual(self.ask(key=old).status_code, 401)
        self.assertEqual(self.ask(key=new).status_code, 201)
        self.alice_project.refresh_from_db()
        self.assertEqual(self.alice_project.trial_api_key_hint, new[-4:])
        self.assertNotIn(new, self.alice_project.trial_api_key_hash)

    def test_only_the_owner_manages_the_key(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(f'/project/{self.alice_project.pk}/demo-api-key/').status_code, 404)
        self.alice_project.refresh_from_db()
        self.assertEqual(self.alice_project.trial_api_key_hash, '')


class UsageColourTests(TestCase):
    def test_usage_tones(self):
        from .services.dashboard import usage_tone
        self.assertEqual([usage_tone(v) for v in (95, 90.5, 90, 70, 50, 49.9, 10, None)],
                         ['red', 'red', 'orange', 'orange', 'orange', 'green', 'green', 'default'])


class CrmBoardTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        from .contact_models import Contact
        self.contact = Contact.objects.create(owner=self.alice, name='Ana', email='ana@example.com', company='Sol', stage='demo')

    def test_board_has_the_six_stages_and_cards_move(self):
        self.client.force_login(self.alice)
        page = self.client.get('/contacts/').content.decode()
        for label in ('Contactado', 'Demo', 'Propuesta', 'A la espera', 'Ganado', 'Perdido'):
            self.assertIn(label, page)
        self.assertIn(f'data-id="{self.contact.pk}"', page)
        response = self.client.post(f'/contact/{self.contact.pk}/stage/', {'stage': 'proposal'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.json(), {'ok': True, 'stage': 'proposal', 'label': 'Propuesta'})
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.stage, 'proposal')
        self.assertEqual(self.client.post(f'/contact/{self.contact.pk}/stage/', {'stage': 'nope'}).status_code, 400)
        # The redirect after a form post stays inside the panel
        response = self.client.post(f'/contact/{self.contact.pk}/stage/', {'stage': 'won', 'next': 'https://evil.example/'})
        self.assertEqual(response['Location'], '/contacts/')
        self.assertContains(self.client.get('/contacts/?view=list'), 'Ganado')

    def test_contacts_are_created_and_edited_by_hand(self):
        from .contact_models import Contact
        self.client.force_login(self.alice)
        self.client.post('/contacts/new/', {'name': 'Leo', 'email': 'LEO@example.com', 'stage': 'contacted', 'phone': '+34 611'})
        leo = Contact.objects.get(email='leo@example.com')
        self.assertEqual((leo.owner, leo.stage), (self.alice, 'contacted'))
        self.client.post(f'/contact/{leo.pk}/edit/', {'name': 'Leo Gil', 'email': 'leo@example.com', 'company': 'Norte',
                                                      'job_title': 'CEO', 'stage': 'waiting', 'country': 'México'})
        leo.refresh_from_db()
        self.assertEqual((leo.name, leo.company, leo.stage, leo.country), ('Leo Gil', 'Norte', 'waiting', 'México'))
        # The email of another contact can't be taken
        response = self.client.post(f'/contact/{leo.pk}/edit/', {'name': 'Leo', 'email': 'ana@example.com', 'stage': 'won'})
        self.assertContains(response, 'Ya tienes un contacto con ese email')
        self.assertContains(self.client.get(f'/contact/{leo.pk}/'), 'A la espera')
        # Someone else's contact
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(f'/contact/{leo.pk}/edit/').status_code, 404)
        self.assertEqual(self.client.post(f'/contact/{leo.pk}/stage/', {'stage': 'lost'}).status_code, 404)

    def test_a_demo_request_moves_a_contacted_person_to_demo_but_keeps_later_stages(self):
        from .contact_models import Contact
        from .project_models import Project
        from .services.trials import request_demo
        demos = Project.objects.create(name='D', owner=self.alice)
        self.alice_project.trial_enabled, self.alice_project.trial_slug, self.alice_project.trial_target_project = True, 'bim', demos
        self.alice_project.save()
        Contact.objects.create(owner=self.alice, name='Leo', email='leo@example.com', stage='contacted')
        request_demo(self.alice_project, self.alice_instance, 'Leo', 'leo@example.com', ip='10.0.0.1')
        self.assertEqual(Contact.objects.get(email='leo@example.com').stage, 'demo')
        self.contact.stage = 'won'
        self.contact.save()
        request_demo(self.alice_project, self.alice_instance, 'Ana', 'ana@example.com', ip='10.0.0.2')
        self.assertEqual(Contact.objects.get(email='ana@example.com').stage, 'won')
        self.assertEqual(Contact.objects.create(owner=self.bob, name='X', email='x@example.com').stage, 'contacted')


class InstallNamedModuleTests(BaseTestCase):
    def test_theme_button_and_named_module_queue_the_install(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        page = self.client.get(f'/instance/{self.alice_instance.pk}/')
        self.assertContains(page, 'Instalar el tema Community SH')
        self.client.post(f'/instance/{self.alice_instance.pk}/install-named-module/', {'module': 'community_sh_theme'})
        task = Task.objects.get(kind=Task.Kind.AI_MODULE)
        self.assertEqual((task.instance, task.params['module'], task.params['upgrade']), (self.alice_instance, 'community_sh_theme', False))
        self.client.post(f'/instance/{self.alice_instance.pk}/install-named-module/', {'module': 'sale; rm -rf /'})
        self.client.post(f'/instance/{self.alice_instance.pk}/install-named-module/', {'module': 'sale_management', 'upgrade': '1'})
        self.assertEqual([t.params['module'] for t in Task.objects.order_by('pk')], ['community_sh_theme', 'sale_management'])
        self.assertTrue(Task.objects.order_by('pk').last().params['upgrade'])
        # Clients can't
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(f'/instance/{self.alice_instance.pk}/install-named-module/', {'module': 'x_y'}).status_code, 403)


class MemoryLimitTests(BaseTestCase):
    def test_options_and_live_update(self):
        from .services.docker_service import DockerService, memory_options
        self.assertEqual(memory_options(Instance(memory_limit_mb=1536)), {'mem_limit': '1536m', 'memswap_limit': '1536m'})
        self.assertEqual(memory_options(Instance(memory_limit_mb=0)), {})
        self.assertEqual(Instance.objects.get(pk=self.alice_instance.pk).memory_limit_mb, 1536)
        with mock.patch('orchestrator.services.docker_service.docker.from_env'):
            service = DockerService()
        capped = mock.Mock(attrs={'HostConfig': {'Memory': 1536 * 1024 * 1024}})
        capped.name = 'odoo_alice-odoo'
        loose = mock.Mock(attrs={'HostConfig': {'Memory': 0}})
        loose.name = 'odoo_bob-odoo'
        stranger = mock.Mock(attrs={'HostConfig': {'Memory': 0}})
        stranger.name = 'odoo_unknown'
        loose.stats.return_value = {'memory_stats': {'usage': 400 * 1024 * 1024}}
        service.client.containers.list.return_value = [capped, loose, stranger]
        # Using almost all of it now: not lowered yet
        busy = Instance.objects.create(name='busy-odoo', project=self.alice_project, owner=self.alice)
        heavy = mock.Mock(attrs={'HostConfig': {'Memory': 0}})
        heavy.name = 'odoo_busy-odoo'
        heavy.stats.return_value = {'memory_stats': {'usage': 1500 * 1024 * 1024}}
        service.client.containers.list.return_value.append(heavy)
        self.assertEqual(service.apply_memory_limits(), ['bob-odoo'])
        heavy.update.assert_not_called()
        loose.update.assert_called_once_with(mem_limit=1536 * 1024 * 1024, memswap_limit=1536 * 1024 * 1024)
        capped.update.assert_not_called()
        stranger.update.assert_not_called()

    def test_edit_from_the_page_and_the_api(self):
        url = reverse('instance-update-memory', args=[self.alice_instance.pk])
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(f'/instance/{self.alice_instance.pk}/'), url)
        with mock.patch('orchestrator.views.instances.DockerService') as service:
            self.client.post(url, {'memory_limit_mb': '2048'})
            self.assertEqual(service.return_value.apply_memory_limits.call_args.args[0][0].pk, self.alice_instance.pk)
            self.client.post(url, {'memory_limit_mb': '100'})  # too low: kept
            self.client.post(url, {'memory_limit_mb': 'lots'})
        self.assertEqual(Instance.objects.get(pk=self.alice_instance.pk).memory_limit_mb, 2048)
        api = f'/api/instances/{self.alice_instance.pk}/'
        self.assertEqual(self.client.patch(api, {'memory_limit_mb': 50}, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.patch(api, {'memory_limit_mb': 0}, content_type='application/json').json()['memory_limit_mb'], 0)
        # Clients of the project can't change it
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.client.force_login(self.bob)
        self.assertIn(self.client.post(url, {'memory_limit_mb': '4096'}).status_code, (403, 404))


class TaskSecretsTests(BaseTestCase):
    def test_passwords_are_never_read_back_and_are_dropped_when_the_task_ends(self):
        from .task_models import Task, REDACTED
        from .tasks import HANDLERS, run_task
        self.client.force_login(self.alice)
        response = self.client.post(f'/api/instances/{self.alice_instance.pk}/create-database/', {'name': 'shop', 'password': 'Visible-123'},
                                    content_type='application/json')
        self.assertEqual(response.json()['password'], 'Visible-123')  # who asked for it gets it once
        task = Task.objects.get(pk=response.json()['task_id'])
        self.assertEqual(task.params['password'], 'Visible-123')  # the worker still needs it
        api = self.client.get(f'/api/tasks/{task.pk}/').json()
        self.assertEqual(api['params']['password'], REDACTED)
        self.assertNotIn('Visible-123', self.client.get('/api/tasks/').content.decode())
        with mock.patch.dict(HANDLERS, {Task.Kind.CREATE_DATABASE: lambda task: 'ok'}):
            run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.params, {'name': 'shop', 'password': REDACTED, 'lang': '', 'demo': False})
        # A failed one too
        failed = Task.objects.create(kind=Task.Kind.RESET_ADMIN_PASSWORD, instance=self.alice_instance, params={'password': 'Other-456'})
        with mock.patch.dict(HANDLERS, {Task.Kind.RESET_ADMIN_PASSWORD: mock.Mock(side_effect=Exception('down'))}):
            run_task(failed)
        failed.refresh_from_db()
        self.assertEqual(failed.params['password'], REDACTED)


class AlertsAndHealthTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        self.config.smtp_enabled, self.config.smtp_host, self.config.smtp_from_email = True, 'smtp.example.com', 'panel@example.com'
        self.config.notification_emails = 'ops@example.com'
        self.config.save()

    def test_alert_channels_cooldown_and_switch(self):
        from .services import alerts
        with mock.patch('orchestrator.services.mail.send', return_value=(True, '')) as send, \
                mock.patch('orchestrator.services.alerts.urllib.request.urlopen') as urlopen:
            self.assertTrue(alerts.alert('k', 'Algo pasa', 'detalle'))
            self.assertEqual(send.call_args.args[2], ['ops@example.com'])
            self.assertEqual(send.call_args.args[0], '[Community SH] Algo pasa')
            urlopen.assert_not_called()  # no webhook configured
            self.assertFalse(alerts.alert('k', 'Algo pasa', 'otra vez'))  # cooldown
            alerts.clear('k')
            self.config.alert_webhook_url = 'https://hooks.example.com/x'
            self.config.save()
            self.assertTrue(alerts.alert('k', 'Algo pasa', 'detalle'))
            import json
            payload = json.loads(urlopen.call_args.args[0].data)
            self.assertEqual(payload['subject'], '[Community SH] Algo pasa')
            self.assertIn('detalle', payload['content'])
            self.config.alerts_enabled = False
            self.config.save()
            self.assertFalse(alerts.alert('other', 'x', 'y', cooldown=0))

    def test_failed_tasks_alert(self):
        from .task_models import Task
        from .tasks import HANDLERS, enqueue, run_task
        with mock.patch('orchestrator.services.alerts.alert') as alert, \
                mock.patch.dict(HANDLERS, {Task.Kind.BACKUP: mock.Mock(side_effect=Exception('disco lleno'))}):
            run_task(enqueue(Task.Kind.BACKUP, self.alice_instance, self.alice))
        self.assertIn('alice-odoo', alert.call_args.args[1])
        self.assertIn('disco lleno', alert.call_args.args[2])

    def test_probe(self):
        import urllib.error
        from .services.health import probe
        with mock.patch('orchestrator.services.health.urllib.request.urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            self.assertEqual(probe(self.alice_instance)[0], True)
            self.assertEqual(urlopen.call_args.args[0].full_url, 'http://odoo_alice-odoo:8069/web/login')
            urlopen.side_effect = urllib.error.HTTPError('u', 404, 'nf', {}, None)
            self.assertTrue(probe(self.alice_instance)[0])
            urlopen.side_effect = urllib.error.HTTPError('u', 502, 'bad gateway', {}, None)
            self.assertEqual(probe(self.alice_instance)[::2], (False, 'HTTP 502'))
            urlopen.side_effect = urllib.error.URLError('connection refused')
            self.assertEqual(probe(self.alice_instance), (False, None, 'connection refused'))

    def test_down_after_two_failures_and_back_up(self):
        from .services.health import check_instances
        from .task_models import Task
        Instance.objects.filter(pk=self.alice_instance.pk).update(status=Instance.Status.RUNNING)
        with mock.patch('orchestrator.services.health.probe', return_value=(False, None, 'refused')), \
                mock.patch('orchestrator.services.alerts.alert') as alert:
            self.assertEqual(check_instances(force=True), [])
            alert.assert_not_called()  # one failure is not enough
            self.assertEqual(check_instances(force=True), [('alice-odoo', 'down')])
            self.assertIn('no responde', alert.call_args.args[1])
            check_instances(force=True)
            self.assertEqual(alert.call_count, 1)  # once while it stays down
        self.assertEqual(Instance.objects.get(pk=self.alice_instance.pk).health, 'down')
        self.client.force_login(self.alice)
        self.assertContains(self.client.get('/instances/'), 'No responde')
        with mock.patch('orchestrator.services.health.probe', return_value=(True, 120, '')), \
                mock.patch('orchestrator.services.alerts.alert') as alert:
            self.assertEqual(check_instances(force=True), [('alice-odoo', 'up')])
            self.assertIn('vuelve a responder', alert.call_args.args[1])
        instance = Instance.objects.get(pk=self.alice_instance.pk)
        self.assertEqual((instance.health, instance.health_ms, instance.health_failures), ('up', 120, 0))
        self.assertContains(self.client.get(f'/instance/{instance.pk}/'), 'Responde en 120 ms')
        # An instance with a task in the queue (a deploy...) isn't checked
        Task.objects.create(kind=Task.Kind.DEPLOY, instance=instance)
        with mock.patch('orchestrator.services.health.probe') as probe:
            check_instances(force=True)
            probe.assert_not_called()
        # And it runs at most every few minutes
        self.assertEqual(check_instances(), [])
        Task.objects.all().delete()
        with mock.patch('orchestrator.services.health.probe') as probe:
            check_instances()
            probe.assert_not_called()

    def test_server_usage(self):
        from django.utils import timezone
        from .metrics_models import MetricSample
        from .services import alerts
        with mock.patch('psutil.disk_usage', return_value=mock.Mock(percent=95.0)), \
                mock.patch('orchestrator.services.alerts.alert') as alert:
            alerts.check_server_usage()
            self.assertEqual(alert.call_args.args[0], 'disk-high')
        for minute in range(5):
            MetricSample.objects.create(timestamp=timezone.now() - timezone.timedelta(minutes=minute), cpu_percent=10, memory_percent=93)
        with mock.patch('psutil.disk_usage', return_value=mock.Mock(percent=40.0)), \
                mock.patch('orchestrator.services.alerts.alert') as alert:
            alerts.check_server_usage()
            self.assertEqual([c.args[0] for c in alert.call_args_list], ['memory-high'])

    def test_settings_save_alerts(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('settings'), {'section': 'general', 'alert_webhook_url': 'https://hooks.example.com/a'})
        self.config.refresh_from_db()
        self.assertEqual((self.config.alerts_enabled, self.config.alert_webhook_url), (False, 'https://hooks.example.com/a'))
        self.client.post(reverse('settings'), {'section': 'general', 'alerts_enabled': 'on', 'alert_webhook_url': ''})
        self.config.refresh_from_db()
        self.assertEqual((self.config.alerts_enabled, self.config.alert_webhook_url), (True, ''))


class InstanceUsageTests(BaseTestCase):
    def test_grouped_by_instance_heaviest_first(self):
        from .services.metrics import instance_usage
        Instance.objects.filter(pk=self.bob_instance.pk).update(memory_limit_mb=0)

        def stat(name, cpu, mb):
            return {'name': name, 'cpu_percent': cpu, 'memory_usage_mb': mb}
        rows = instance_usage([stat('odoo_alice-odoo', 10.5, 768), stat('db_alice-odoo', 2.0, 100),
                               stat('odoo_bob-odoo', 1.0, 2000), stat('traefik', 1, 50), stat('odoo_gone', 1, 9999)])
        self.assertEqual([r['name'] for r in rows], ['bob-odoo', 'alice-odoo'])
        alice = rows[1]
        self.assertEqual((alice['cpu_percent'], alice['memory_mb'], alice['odoo_memory_mb'], alice['db_memory_mb']), (12.5, 868, 768, 100))
        self.assertEqual((alice['memory_limit_mb'], alice['limit_percent']), (1536, 50.0))
        self.assertEqual((rows[0]['memory_limit_mb'], rows[0]['limit_percent']), (None, None))

    def test_instance_page_loads_its_usage(self):
        url = reverse('instance-usage', args=[self.alice_instance.pk])
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(f'/instance/{self.alice_instance.pk}/'), url)
        with mock.patch('orchestrator.services.metrics.single_instance_usage', return_value={'memory_mb': 500}):
            self.assertEqual(self.client.get(url).json(), {'usage': {'memory_mb': 500}})
        with mock.patch('orchestrator.services.metrics.single_instance_usage', side_effect=Exception('no docker')):
            self.assertEqual(self.client.get(url).json(), {'usage': None})
        self.client.force_login(self.bob)
        self.assertIn(self.client.get(url).status_code, (403, 404))


class OffsiteBackupTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.config.offsite_enabled = True
        self.config.s3_bucket, self.config.s3_access_key, self.config.s3_secret_key = 'bk', 'AK', 'SK'
        self.config.save()

    def backup(self):
        import tempfile
        path = tempfile.mktemp(suffix='.zip')
        open(path, 'wb').write(b'zip')
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return Backup.objects.create(instance=self.alice_instance, filename='alice.zip', file_path=path, file_size=3)

    def test_upload_marks_the_backup_and_applies_the_retention(self):
        from datetime import timedelta
        from django.utils import timezone
        from .services import offsite
        backup = self.backup()
        s3 = mock.Mock()
        s3.get_paginator.return_value.paginate.return_value = [{'Contents': [
            {'Key': 'community-sh/alice-odoo/old.zip', 'LastModified': timezone.now() - timedelta(days=40)},
            {'Key': 'community-sh/alice-odoo/alice.zip', 'LastModified': timezone.now()}]}]
        with mock.patch('orchestrator.services.offsite.client', return_value=s3):
            notes = offsite.upload([backup])
        s3.upload_file.assert_called_once_with(backup.file_path, 'bk', 'community-sh/alice-odoo/alice.zip')
        s3.delete_objects.assert_called_once_with(Bucket='bk', Delete={'Objects': [{'Key': 'community-sh/alice-odoo/old.zip'}]})
        backup.refresh_from_db()
        self.assertEqual(backup.offsite_key, 'community-sh/alice-odoo/alice.zip')
        self.assertIsNotNone(backup.offsite_at)
        self.assertIn('1 copias', notes[-1])

    def test_a_backup_queues_its_copy(self):
        from .task_models import Task
        from . import tasks
        backup = self.backup()
        task = Task.objects.create(kind=Task.Kind.BACKUP, instance=self.alice_instance, created_by=self.alice)
        with mock.patch('orchestrator.tasks.DockerService') as service:
            service.return_value.backup_all_databases.return_value = [backup]
            self.assertIn('copia fuera del servidor en cola', tasks.backup(task))
        copy = Task.objects.get(kind=Task.Kind.OFFSITE_UPLOAD)
        self.assertEqual(copy.params, {'backups': [backup.pk]})
        with mock.patch('orchestrator.services.offsite.upload', return_value=['ok']) as upload:
            self.assertEqual(tasks.offsite_upload(copy), 'ok')
            self.assertEqual(upload.call_args.args[0], [backup])
        # Switched off: nothing is queued
        self.config.offsite_enabled = False
        self.config.save()
        from .services import offsite
        self.assertIsNone(offsite.queue_upload([backup]))

    def test_settings_keep_the_secret_and_test_the_connection(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('settings'), {'section': 'backups', 'offsite_enabled': 'on', 's3_bucket': 'other',
                                               's3_access_key': 'AK2', 's3_secret_key': '', 'offsite_retention_days': '15'})
        self.config.refresh_from_db()
        self.assertEqual((self.config.s3_bucket, self.config.s3_secret_key, self.config.offsite_retention_days), ('other', 'SK', 15))
        with mock.patch('orchestrator.services.offsite.test_connection', return_value=(True, 'Conexión correcta')) as test:
            response = self.client.post(reverse('offsite-test'), {'s3_bucket': 'tried', 's3_access_key': 'A', 's3_secret_key': ''})
            self.assertEqual(test.call_args.args[0].s3_bucket, 'tried')
            self.assertEqual(test.call_args.args[0].s3_secret_key, 'SK')  # the stored one
        self.assertEqual(response['Location'], reverse('settings') + '#backups')
        self.config.refresh_from_db()
        self.assertEqual(self.config.s3_bucket, 'other')  # testing doesn't save
        self.client.force_login(self.alice)
        self.assertEqual(self.client.post(reverse('offsite-test')).status_code, 403)


class AuditTests(BaseTestCase):
    def test_secrets_shown_are_recorded_and_not_in_the_page(self):
        from .audit_models import AuditEvent
        self.client.force_login(self.alice)
        page = self.client.get(f'/instance/{self.alice_instance.pk}/')
        self.assertNotContains(page, self.alice_instance.master_password)
        url = reverse('instance-secret', args=[self.alice_instance.pk, 'master'])
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)
        self.assertEqual(response.json()['value'], self.alice_instance.master_password)
        self.assertEqual(response['Cache-Control'], 'no-store')
        event = AuditEvent.objects.get(action='secret_master_password')
        self.assertEqual((event.username, event.target, event.ip), ('alice', 'alice-odoo', '127.0.0.1'))
        self.assertEqual(self.client.post(reverse('instance-secret', args=[self.alice_instance.pk, 'other'])).status_code, 404)

    def test_logins_settings_tokens_and_users_are_recorded(self):
        from .audit_models import AuditEvent
        self.client.post(reverse('login'), {'username': 'alice', 'password': 'wrong'})
        self.client.force_login(self.admin)
        self.client.post(reverse('settings'), {'section': 'general'})
        self.client.post(reverse('mcp-token-create'), {'name': 'cli', 'tab': 'api'})
        self.client.post(reverse('instance-update-memory', args=[self.alice_instance.pk]), {'memory_limit_mb': '2048'})
        actions = set(AuditEvent.objects.values_list('action', flat=True))
        self.assertTrue({'login_failed', 'settings', 'token_created', 'instance_memory'} <= actions, actions)
        self.assertEqual(AuditEvent.objects.get(action='login_failed').target, 'alice')
        # The page, with filters, for administrators only
        page = self.client.get(reverse('audit') + '?action=token_created')
        self.assertContains(page, '">Crear token</td>')
        self.assertNotContains(page, '">Inicio de sesión fallido</td>')
        self.assertContains(self.client.get('/dashboard/'), reverse('audit'))
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('audit')).status_code, 403)
        self.assertNotContains(self.client.get('/dashboard/'), reverse('audit'))


class InstancePageLanguageTests(BaseTestCase):
    def test_the_instance_page_in_spanish_and_english(self):
        self.client.force_login(self.alice)
        url = f'/instance/{self.alice_instance.pk}/'
        page = self.client.get(url).content.decode()
        for text in ('Tareas recientes', 'Límite de memoria', 'Restablecer contraseña'):
            self.assertIn(text, page)
        self.client.cookies['django_language'] = 'en'
        page = self.client.get(url).content.decode()
        for text in ('Recent tasks', 'Memory limit', 'Reset password'):
            self.assertIn(text, page)
        self.assertNotIn('Tareas recientes', page)


class InstanceDiskUsageTests(BaseTestCase):
    def test_disk_by_instance_biggest_first(self):
        import tempfile
        from django.core.cache import cache
        from .services.metrics import instance_disk_usage
        cache.clear()
        MB = 1024 * 1024
        Backup.objects.create(instance=self.bob_instance, filename='b.zip', file_path='/x', file_size=300 * MB)
        db = mock.Mock(attrs={'Mounts': [{'Type': 'volume', 'Name': 'anon123'}]})
        db.name = 'db_alice-odoo'
        odoo = mock.Mock(attrs={'Mounts': [{'Type': 'volume', 'Name': 'odoo_data_alice-odoo'}, {'Type': 'bind', 'Name': ''}]})
        odoo.name = 'odoo_alice-odoo'
        client = mock.Mock()
        client.df.return_value = {'Volumes': [{'Name': 'anon123', 'UsageData': {'Size': 500 * MB}},
                                              {'Name': 'odoo_data_alice-odoo', 'UsageData': {'Size': 200 * MB}},
                                              {'Name': 'other', 'UsageData': {'Size': 999 * MB}}]}
        client.containers.list.return_value = [db, odoo]
        with tempfile.TemporaryDirectory() as base, self.settings(BASE_DIR=base):
            os.makedirs(os.path.join(base, 'instances', 'alice-odoo'))
            open(os.path.join(base, 'instances', 'alice-odoo', 'big'), 'wb').write(b'0' * (2 * MB))
            with mock.patch('orchestrator.services.metrics.docker.from_env', return_value=client):
                rows = instance_disk_usage()['rows']
                instance_disk_usage()  # cached: Docker isn't asked again
                self.assertEqual(client.df.call_count, 1)
        alice = next(r for r in rows if r['name'] == 'alice-odoo')
        bob = next(r for r in rows if r['name'] == 'bob-odoo')
        self.assertEqual((alice['data_mb'], alice['code_mb'], alice['backups_mb'], alice['disk_mb']), (700, 2, 0, 702))
        self.assertEqual((bob['data_mb'], bob['backups_mb'], bob['disk_mb']), (0, 300, 300))
        self.assertEqual(rows[0]['name'], 'alice-odoo')

    def test_dashboard_cards_open_the_usage_by_instance(self):
        self.client.force_login(self.admin)
        page = self.client.get('/dashboard/').content.decode()
        for sort in ('cpu', 'memory', 'disk'):
            self.assertIn(f'/metrics/?tab=resources&amp;sort={sort}', page)
        with mock.patch('orchestrator.services.metrics.instance_disk_usage', return_value={'rows': [], 'measured_at': None}) as usage:
            self.assertEqual(self.client.get(reverse('metrics-disk') + '?refresh=1').json()['rows'], [])
            self.assertEqual(usage.call_args.kwargs, {'refresh': True})
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('metrics-disk')).status_code, 403)


class SmokeCheckTests(BaseTestCase):
    def test_main_pages_open_and_a_failing_one_is_reported(self):
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError
        out = StringIO()
        with mock.patch('docker.from_env'), mock.patch('orchestrator.services.metrics.collect_metrics', return_value={}):
            call_command('smoke_check', stdout=out)
        self.assertIn('pages OK', out.getvalue())
        self.assertIn(f'/instance/{self.bob_instance.pk}/', out.getvalue())
        with mock.patch('docker.from_env'), mock.patch('orchestrator.services.metrics.collect_metrics', return_value={}), \
                mock.patch('orchestrator.views.public.render', side_effect=Exception('no such column')):
            with self.assertRaisesMessage(CommandError, '/help/: Exception: no such column'):
                call_command('smoke_check', stdout=StringIO())


class EncryptedSecretsTests(BaseTestCase):
    def raw(self, table, column, pk):
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT {column} FROM {table} WHERE id = %s', [pk])
            return cursor.fetchone()[0]

    def test_secrets_are_encrypted_at_rest_and_read_in_clear(self):
        self.config.smtp_password, self.config.s3_secret_key = 'smtp-Secret-1', 's3-Secret-2'
        self.config.save()
        Instance.objects.filter(pk=self.alice_instance.pk).update(admin_password='Admin-Secret-3', env_vars='API_KEY=xyz')
        stored = self.raw('orchestrator_githubconfig', 'smtp_password', self.config.pk)
        self.assertTrue(stored.startswith('enc:'))
        self.assertNotIn('smtp-Secret-1', stored)
        for column in ('admin_password', 'env_vars', 'master_password'):
            self.assertTrue(self.raw('orchestrator_instance', column, self.alice_instance.pk).startswith('enc:'), column)
        from .config_models import GitHubConfig
        config = GitHubConfig.objects.get(pk=self.config.pk)
        self.assertEqual((config.smtp_password, config.s3_secret_key), ('smtp-Secret-1', 's3-Secret-2'))
        instance = Instance.objects.get(pk=self.alice_instance.pk)
        self.assertEqual((instance.admin_password, instance.env_vars), ('Admin-Secret-3', 'API_KEY=xyz'))
        self.assertEqual(self.raw('orchestrator_githubconfig', 'openai_api_key', self.config.pk), '')  # empty stays empty

    def test_plain_values_from_before_and_a_changed_key(self):
        from django.db import connection
        from .fields import decrypt, encrypt
        with connection.cursor() as cursor:
            cursor.execute('UPDATE orchestrator_githubconfig SET smtp_password = %s WHERE id = %s', ['legacy-plain', self.config.pk])
        from .config_models import GitHubConfig
        self.assertEqual(GitHubConfig.objects.get(pk=self.config.pk).smtp_password, 'legacy-plain')
        token = encrypt('x')
        self.assertEqual(decrypt(token), 'x')
        self.assertEqual(encrypt(token), token)  # never twice
        with mock.patch.dict('os.environ', {'FIELD_ENCRYPTION_KEY': 'A' * 43 + '='}):
            self.assertEqual(decrypt(token), '')  # another key: unreadable, empty rather than garbage


class PanelBackupTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        self.config.offsite_enabled = True
        self.config.s3_bucket, self.config.s3_access_key, self.config.s3_secret_key = 'bk', 'AK', 'SK'
        self.config.save()

    def test_dump_through_the_database_container(self):
        import gzip
        import tempfile
        from .services import offsite
        container = mock.Mock(labels={'com.docker.compose.project': 'community-sh'})
        container.exec_run.return_value = mock.Mock(output=iter([(b'-- PostgreSQL database dump\n' + b'x' * 200, None), (None, b'')]))
        databases = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': 'community_sh', 'USER': 'postgres'}}
        with tempfile.TemporaryDirectory() as target, self.settings(DATABASES=databases), \
                mock.patch('orchestrator.services.offsite._panel_db_container', return_value=container):
            path = offsite.dump_panel_database(target)
            self.assertTrue(gzip.open(path).read().startswith(b'-- PostgreSQL database dump'))
            self.assertEqual(container.exec_run.call_args.args[0], ['pg_dump', '-U', 'postgres', '--no-owner', 'community_sh'])
            container.exec_run.return_value = mock.Mock(output=iter([(None, b'role does not exist')]))
            with self.assertRaisesMessage(Exception, 'role does not exist'):
                offsite.dump_panel_database(target)

    def test_daily_task_uploads_the_dump_and_certificates(self):
        import tempfile
        from .services import offsite
        from .task_models import Task
        self.assertIsNotNone(offsite.queue_daily_panel_backup())
        self.assertIsNone(offsite.queue_daily_panel_backup())  # once a day
        self.assertEqual(Task.objects.filter(kind=Task.Kind.PANEL_BACKUP).count(), 1)
        s3 = mock.Mock()
        s3.get_paginator.return_value.paginate.return_value = []
        with tempfile.TemporaryDirectory() as base, self.settings(BASE_DIR=base):
            os.makedirs(os.path.join(base, 'letsencrypt'))
            open(os.path.join(base, 'letsencrypt', 'acme.json'), 'w').write('{"keys": 1}')
            dump = os.path.join(base, 'panel-daily-x.sql.gz')
            open(dump, 'wb').write(b'dump')
            os.makedirs(os.path.join(base, 'backups', 'panel-db'))
            with mock.patch('orchestrator.services.offsite.dump_panel_database', return_value=dump), \
                    mock.patch('orchestrator.services.offsite.client', return_value=s3):
                notes = offsite.backup_panel()
        keys = [c.args[2] for c in s3.upload_file.call_args_list]
        self.assertEqual(keys, ['community-sh/_panel/panel-daily-x.sql.gz', 'community-sh/_panel/acme.json'])
        self.assertIn('Certificados', notes[1])

    def test_nothing_without_a_bucket(self):
        from .services import offsite
        self.config.offsite_enabled = False
        self.config.save()
        self.assertIsNone(offsite.queue_daily_panel_backup())


class BackupRecoveryTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        self.config.offsite_enabled = True
        self.config.s3_bucket, self.config.s3_access_key, self.config.s3_secret_key = 'bk', 'AK', 'SK'
        self.config.save()

    def panel_zip(self, dump=b'PGDMP' + b'0' * 2000):
        import tempfile
        import zipfile
        path = tempfile.mktemp(suffix='.zip')
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('database.dump', dump)
            zf.writestr('metadata.json', '{}')
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return Backup.objects.create(instance=self.alice_instance, filename=os.path.basename(path), file_path=path,
                                     file_size=os.path.getsize(path))

    def test_list_and_restore_a_copy_from_the_bucket(self):
        from datetime import datetime, timezone as tz
        from .task_models import Task
        s3 = mock.Mock()
        s3.get_paginator.return_value.paginate.return_value = [{'Contents': [
            {'Key': 'community-sh/alice-odoo/a.zip', 'Size': 10, 'LastModified': datetime(2026, 11, 1, tzinfo=tz.utc)},
            {'Key': 'community-sh/alice-odoo/b.zip', 'Size': 20, 'LastModified': datetime(2026, 11, 2, tzinfo=tz.utc)}]}]
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(f'/instance/{self.alice_instance.pk}/'), reverse('instance-offsite', args=[self.alice_instance.pk]))
        with mock.patch('orchestrator.services.offsite.client', return_value=s3):
            copies = self.client.get(reverse('instance-offsite', args=[self.alice_instance.pk])).json()['copies']
        self.assertEqual([c['name'] for c in copies], ['b.zip', 'a.zip'])
        url = reverse('instance-offsite-restore', args=[self.alice_instance.pk])
        self.client.post(url, {'key': 'community-sh/bob-odoo/x.zip'})  # another instance's: refused
        self.assertFalse(Task.objects.filter(kind=Task.Kind.OFFSITE_RESTORE).exists())
        self.client.post(url, {'key': 'community-sh/alice-odoo/b.zip'})
        task = Task.objects.get(kind=Task.Kind.OFFSITE_RESTORE)
        from . import tasks
        with mock.patch('orchestrator.services.offsite.client', return_value=s3), \
                mock.patch('orchestrator.services.docker_service.DockerService') as service:
            tasks.offsite_restore(task)
        self.assertEqual(s3.download_file.call_args.args[:2], ('bk', 'community-sh/alice-odoo/b.zip'))
        downloaded = service.return_value.restore_instance.call_args.args[1]
        self.assertFalse(os.path.exists(downloaded))  # the temporary download is removed

    def test_verification_finds_broken_backups_and_alerts(self):
        from . import tasks
        from .task_models import Task
        good = self.panel_zip()
        with mock.patch('orchestrator.services.offsite.client') as client:
            client.return_value.head_object.return_value = {'ContentLength': good.file_size}
            good.offsite_key = 'community-sh/alice-odoo/x.zip'
            good.save()
            self.assertIn('✓ alice-odoo', tasks.backup_verify(Task(kind=Task.Kind.BACKUP_VERIFY)))
            client.return_value.head_object.return_value = {'ContentLength': 1}
            with mock.patch('orchestrator.services.alerts.alert') as alert:
                with self.assertRaisesMessage(Exception, 'la copia en S3 mide 1 bytes'):
                    tasks.backup_verify(Task(kind=Task.Kind.BACKUP_VERIFY))
                self.assertIn('backups con problemas', alert.call_args.args[1])
        self.panel_zip(dump=b'not a dump' * 200)  # the newest one now
        with mock.patch('orchestrator.services.alerts.alert'), self.assertRaisesMessage(Exception, 'no es un volcado de PostgreSQL'):
            tasks.backup_verify(Task(kind=Task.Kind.BACKUP_VERIFY))

    def test_weekly_and_on_demand(self):
        from .services import offsite
        from .task_models import Task
        self.assertIsNotNone(offsite.queue_weekly_verification())
        self.assertIsNone(offsite.queue_weekly_verification())
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('backups-verify'))['Location'], reverse('settings') + '#backups')
        self.assertEqual(Task.objects.filter(kind=Task.Kind.BACKUP_VERIFY).count(), 2)


class RefreshDataTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.prod = Instance.objects.create(name='acme-prod', owner=self.alice, project=self.alice_project, odoo_version='17.0',
                                            admin_login='admin', admin_password='Prod-pass-1')
        self.staging = Instance.objects.create(name='acme-staging', owner=self.alice, project=self.alice_project,
                                               odoo_version='17.0', copied_from=self.prod)
        Instance.objects.create(name='other-version', owner=self.alice, project=self.alice_project, odoo_version='16.0')

    def test_form_offers_same_version_instances_and_needs_the_name(self):
        from .task_models import Task
        url = reverse('instance-refresh-data', args=[self.staging.pk])
        self.client.force_login(self.alice)
        page = self.client.get(f'/instance/{self.staging.pk}/').content.decode()
        self.assertIn('acme-prod · su original', page)
        self.assertNotIn('other-version', page)
        self.client.post(url, {'source': self.prod.pk, 'confirm': 'wrong', 'neutralize': '1'})
        self.client.post(url, {'source': self.bob_instance.pk, 'confirm': 'acme-staging'})  # not Alice's
        self.assertFalse(Task.objects.filter(kind=Task.Kind.REFRESH_DATA).exists())
        self.client.post(url, {'source': self.prod.pk, 'confirm': 'acme-staging', 'neutralize': '1'})
        task = Task.objects.get(kind=Task.Kind.REFRESH_DATA)
        self.assertEqual((task.instance, task.params), (self.staging, {'source': self.prod.pk, 'neutralize': True}))

    def test_refresh_replaces_databases_and_filestore(self):
        from .services.docker_service import DockerService
        with mock.patch('orchestrator.services.docker_service.docker.from_env'):
            service = DockerService()
        source_db, target_db, odoo = mock.Mock(), mock.Mock(), mock.Mock(status='running')
        source_db.exec_run.return_value = mock.Mock(exit_code=0, output=b'')
        source_db.get_archive.return_value = (iter([b'dump']), {})
        target_db.exec_run.return_value = mock.Mock(exit_code=0, output=b'')
        sql = []
        with mock.patch.object(service, '_start_db_container', side_effect=lambda i: source_db if i.name == 'acme-prod' else target_db), \
                mock.patch.object(service, '_get_container', return_value=odoo), \
                mock.patch.object(service, '_wait_for_postgres'), \
                mock.patch.object(service, '_list_user_databases', return_value=['acme']), \
                mock.patch.object(service, '_psql', side_effect=lambda c, d, q, check=True: sql.append(q)), \
                mock.patch.object(service, 'neutralize_databases', return_value=['acme: neutralizada']) as neutralize, \
                mock.patch.object(service, '_copy_filestore') as copy_filestore, \
                mock.patch.object(service, 'restart_instance') as restart:
            notes = service.refresh_from(self.staging, self.prod)
            with self.assertRaisesMessage(Exception, 'sí misma'):
                service.refresh_from(self.prod, self.prod)
        odoo.stop.assert_called_once()
        self.assertIn('DROP DATABASE "acme"', sql)
        target_db.put_archive.assert_called_once_with('/tmp', b'dump')
        neutralize.assert_called_once_with(self.staging, crons=True)
        copy_filestore.assert_called_once_with('odoo_acme-prod', 'odoo_acme-staging')
        restart.assert_called_once_with(self.staging)
        self.assertIn('acme: neutralizada', notes)
        self.staging.refresh_from_db()
        self.assertEqual(self.staging.admin_password, 'Prod-pass-1')


class PowerSavingTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        Instance.objects.filter(pk=self.alice_instance.pk).update(status=Instance.Status.RUNNING)

    def test_last_login_reads_the_odoo_login_log(self):
        from datetime import datetime, timezone as tz
        from .services import power
        db = mock.Mock(status='running')
        answers = {'shop': '1762000000.5', 'old': ''}

        def psql(container, database, sql, check=True):
            return answers[database] if 'res_users_log' in sql else ('1700000000' if database == 'old' else '')
        with mock.patch('orchestrator.services.docker_service.DockerService') as service:
            service.return_value._get_container.return_value = db
            service.return_value._list_user_databases.return_value = ['shop', 'old']
            service.return_value._psql.side_effect = psql
            self.assertEqual(power.last_login(self.alice_instance), datetime.fromtimestamp(1762000000.5, tz=tz.utc))

    def test_idle_instances_are_warned_then_stopped(self):
        from datetime import timedelta
        from django.core.cache import cache
        from django.utils import timezone
        from .services import power
        Instance.objects.filter(pk=self.alice_instance.pk).update(auto_stop_days=7)
        now = timezone.now()
        with mock.patch('orchestrator.services.power.last_login', return_value=now - timedelta(days=6, hours=1)), \
                mock.patch('orchestrator.services.docker_service.DockerService') as service, \
                mock.patch('orchestrator.services.alerts.alert') as alert:
            self.assertEqual(power.check_idle(now), [])
            self.assertIn('se detendrá mañana', alert.call_args.args[1])
            service.return_value.stop_instance.assert_not_called()
        cache.clear()
        with mock.patch('orchestrator.services.power.last_login', return_value=now - timedelta(days=8)), \
                mock.patch('orchestrator.services.docker_service.DockerService') as service, \
                mock.patch('orchestrator.services.alerts.alert') as alert:
            notes = power.check_idle(now)
            self.assertEqual(power.check_idle(now), [])  # once a day
        self.assertIn('8 días', notes[0])
        self.assertEqual(service.return_value.stop_instance.call_args.args[0].pk, self.alice_instance.pk)
        self.assertIn('detenida por no usarse', alert.call_args.args[1])
        # Instances without it are never touched
        Instance.objects.filter(pk=self.alice_instance.pk).update(auto_stop_days=0)
        cache.clear()
        with mock.patch('orchestrator.services.power.last_login', return_value=now - timedelta(days=99)), \
                mock.patch('orchestrator.services.docker_service.DockerService') as service:
            self.assertEqual(power.check_idle(now), [])

    def test_schedule_starts_and_stops_once_within_the_hour(self):
        from datetime import datetime, time, timezone as tz
        from .services import power
        Instance.objects.filter(pk=self.alice_instance.pk).update(schedule_start=time(7, 0), schedule_stop=time(21, 0))
        with mock.patch('orchestrator.services.docker_service.DockerService') as service:
            self.assertEqual(power.apply_schedules(datetime(2026, 11, 12, 20, 59, tzinfo=tz.utc)), [])
            notes = power.apply_schedules(datetime(2026, 11, 12, 21, 10, tzinfo=tz.utc))
            self.assertEqual(power.apply_schedules(datetime(2026, 11, 12, 21, 11, tzinfo=tz.utc)), [])
            self.assertEqual(service.return_value.stop_instance.call_count, 1)
            self.assertIn('detenida por su horario (21:00 UTC)', notes[0])
            Instance.objects.filter(pk=self.alice_instance.pk).update(status=Instance.Status.STOPPED)
            self.assertIn('arrancada', power.apply_schedules(datetime(2026, 11, 13, 7, 30, tzinfo=tz.utc))[0])
            self.assertEqual(power.apply_schedules(datetime(2026, 11, 13, 9, 0, tzinfo=tz.utc)), [])  # an hour late: skipped

    def test_form(self):
        url = reverse('instance-update-power', args=[self.alice_instance.pk])
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(f'/instance/{self.alice_instance.pk}/'), url)
        self.client.post(url, {'auto_stop_days': '7', 'schedule_start': '08:00', 'schedule_stop': ''})
        instance = Instance.objects.get(pk=self.alice_instance.pk)
        self.assertEqual((instance.auto_stop_days, str(instance.schedule_start), instance.schedule_stop), (7, '08:00:00', None))
        self.client.post(url, {'auto_stop_days': '5'})
        self.client.post(url, {'auto_stop_days': '3', 'schedule_start': '25:99'})
        self.assertEqual(Instance.objects.get(pk=self.alice_instance.pk).auto_stop_days, 7)


class ApiDatabaseAndModuleTests(BaseTestCase):
    def test_duplicates_are_neutralized_unless_unticked(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        page = self.client.get(reverse('instance-duplicate', args=[self.alice_instance.pk]))
        self.assertContains(page, 'name="neutralize" value="1" checked')
        self.client.post(reverse('instance-duplicate', args=[self.alice_instance.pk]), {'new_name': 'copy-a', 'neutralize': '1'})
        self.assertTrue(Task.objects.get(params__new_name='copy-a').params['neutralize'])
        token = self.client.post(reverse('api-token-markdown'))
        import re
        bearer = re.search(r'Bearer (csh_[A-Za-z0-9_-]+)', token.content.decode()).group(1)
        for name, body in (('copy-b', {}), ('copy-c', {'neutralize': False})):
            self.client.post(f'/api/instances/{self.alice_instance.pk}/duplicate/', dict(body, new_name=name),
                             content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {bearer}')
        self.assertTrue(Task.objects.get(params__new_name='copy-b').params['neutralize'])
        self.assertFalse(Task.objects.get(params__new_name='copy-c').params['neutralize'])
        from . import tasks
        with mock.patch('orchestrator.tasks.DockerService') as service:
            service.return_value.copy_instance.side_effect = lambda source, name, **kw: Instance.objects.create(name=name)
            tasks.duplicate(Task.objects.get(params__new_name='copy-b'))
            self.assertEqual(service.return_value.copy_instance.call_args.kwargs, {'neutralize': 'full'})

    def test_create_database_and_install_module_through_the_api(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        url = f'/api/instances/{self.alice_instance.pk}/'
        response = self.client.post(url + 'create-database/', {'name': 'bim18', 'lang': 'es_ES'}, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertEqual((data['database'], data['login']), ('bim18', 'admin'))
        task = Task.objects.get(pk=data['task_id'])
        self.assertEqual((task.kind, task.params['name'], task.params['password'], task.params['demo']),
                         (Task.Kind.CREATE_DATABASE, 'bim18', data['password'], False))
        self.assertEqual(self.client.post(url + 'create-database/', {'name': 'bad name;'}, content_type='application/json').status_code, 400)
        response = self.client.post(url + 'install-module/', {'module': 'community_sh_theme'}, content_type='application/json')
        self.assertEqual(Task.objects.get(pk=response.json()['task_id']).params['module'], 'community_sh_theme')
        self.assertEqual(self.client.post(url + 'install-module/', {'module': 'x; rm'}, content_type='application/json').status_code, 400)
        # Clients of the project can't
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(url + 'install-module/', {'module': 'sale'}, content_type='application/json').status_code, 403)

    def test_create_database_runs_odoo_init_and_sets_the_admin_password(self):
        from .services.docker_service import DockerService
        with mock.patch('orchestrator.services.docker_service.docker.from_env'):
            service = DockerService()
        odoo = mock.Mock()
        odoo.exec_run.return_value = mock.Mock(exit_code=0, output=b'ok')
        listing = iter([['other'], ['other', 'bim18']])
        with mock.patch.object(service, '_get_container', return_value=odoo), \
                mock.patch.object(service, '_start_db_container', return_value=mock.Mock()), \
                mock.patch.object(service, '_wait_for_postgres'), \
                mock.patch.object(service, '_list_user_databases', side_effect=lambda *_: next(listing)), \
                mock.patch.object(service, 'set_admin_password', return_value='admin') as set_password, \
                mock.patch.object(service, 'restart_instance'):
            self.assertEqual(service.create_database(self.alice_instance, 'bim18', 'Secret-123', 'es_ES'), 'admin')
        command = odoo.exec_run.call_args.args[0][2]
        self.assertIn('-i base --without-demo=all --load-language=es_ES --stop-after-init', command)
        self.assertEqual(odoo.exec_run.call_args.kwargs['environment'], {'DB': 'bim18'})
        set_password.assert_called_once_with(self.alice_instance, 'Secret-123', databases=['bim18'])

    def test_the_created_administrator_is_shown_to_who_manages_the_instance(self):
        from .task_models import Task
        from . import tasks
        task = Task.objects.create(kind=Task.Kind.CREATE_DATABASE, instance=self.alice_instance, created_by=self.alice,
                                   params={'name': 'bim18', 'password': 'SharedPass123'})
        with mock.patch('orchestrator.tasks.DockerService') as service:
            service.return_value.create_database.return_value = 'admin'
            tasks.create_database(task)
        instance = Instance.objects.get(pk=self.alice_instance.pk)
        self.assertEqual((instance.admin_login, instance.admin_password, instance.admin_database), ('admin', 'SharedPass123', 'bim18'))
        self.client.force_login(self.alice)
        page = self.client.get(f'/instance/{instance.pk}/')
        self.assertNotContains(page, 'SharedPass123')  # asked when shown or copied, not in the page
        self.assertContains(page, 'base de datos bim18')
        secret = reverse('instance-secret', args=[instance.pk, 'admin'])
        self.assertEqual(self.client.post(secret).json()['value'], 'SharedPass123')
        self.assertEqual(self.client.get(f'/api/instances/{instance.pk}/').json()['admin_password'], 'SharedPass123')
        # Clients of the project don't see it
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get(f'/instance/{instance.pk}/'), 'SharedPass123')
        self.assertNotIn('admin_password', self.client.get(f'/api/instances/{instance.pk}/').json())
        self.assertIn(self.client.post(secret).status_code, (403, 404))

    def test_reset_admin_password_from_the_instance_page(self):
        from .task_models import Task
        from . import tasks
        url = f'/instance/{self.alice_instance.pk}/reset-admin-password/'
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(f'/instance/{self.alice_instance.pk}/'), 'Contraseña desconocida')
        self.client.post(url, {'password': "x' OR 1=1"})
        self.assertFalse(Task.objects.filter(kind=Task.Kind.RESET_ADMIN_PASSWORD).exists())
        self.client.post(url, {'password': 'MyChosen_pass'})
        task = Task.objects.get(kind=Task.Kind.RESET_ADMIN_PASSWORD)
        self.assertEqual(task.params, {'password': 'MyChosen_pass'})
        self.alice_instance.database_name = 'acme'
        self.alice_instance.save()
        with mock.patch('orchestrator.tasks.DockerService') as service:
            service.return_value.set_admin_password.return_value = 'admin@acme.com'
            tasks.reset_admin_password(task)
            service.return_value.set_admin_password.assert_called_once_with(self.alice_instance, 'MyChosen_pass', databases=['acme'])
            # Empty: a random one, in every database when the instance has no fixed one
            self.alice_instance.database_name = None
            self.alice_instance.admin_database = ''
            self.alice_instance.save()
            tasks.reset_admin_password(Task.objects.create(kind=Task.Kind.RESET_ADMIN_PASSWORD, instance=self.alice_instance))
            args = service.return_value.set_admin_password.call_args
            self.assertIsNone(args.kwargs['databases'])
        instance = Instance.objects.get(pk=self.alice_instance.pk)
        self.assertEqual((instance.admin_login, instance.admin_password), ('admin@acme.com', args.args[1]))
        self.assertGreaterEqual(len(instance.admin_password), 12)
        # Clients of the project can't
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get(f'/instance/{instance.pk}/'), 'reset-admin-password')
        self.assertIn(self.client.post(url).status_code, (403, 404))


class ProjectColorTagsMoveTests(BaseTestCase):
    def test_colour_and_tags_from_the_form_and_the_filter(self):
        from .project_models import Project
        self.client.force_login(self.alice)
        self.client.post(f'/project/{self.alice_project.pk}/edit/', {'name': 'ACME', 'color': 'violet', 'tags_text': 'Odoo 20, cliente,  odoo 20 ,demo'})
        project = Project.objects.get(pk=self.alice_project.pk)
        self.assertEqual(project.color, 'violet')
        self.assertEqual(sorted(project.tag_list), ['Odoo 20', 'cliente', 'demo'])
        other = Project.objects.create(name='Otro', owner=self.alice)
        page = self.client.get('/projects/').content.decode()
        self.assertIn('bg-violet-50', page)
        self.assertIn('?tag=cliente', page)
        page = self.client.get('/projects/?tag=CLIENTE').content.decode()
        self.assertIn('ACME', page)
        self.assertNotIn('>Otro<', page)
        # The form shows the current tags and the existing ones as suggestions
        form = self.client.get(f'/project/{other.pk}/edit/').content.decode()
        self.assertIn('<option value="demo">', form)
        # Bob doesn't see Alice's tags
        self.client.force_login(self.bob)
        self.assertNotIn('?tag=cliente', self.client.get('/projects/').content.decode())

    def test_tags_and_colour_through_the_api(self):
        self.client.force_login(self.alice)
        response = self.client.patch(f'/api/projects/{self.alice_project.pk}/', {'color': 'green', 'tag_names': ['erp', 'demo']},
                                     content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()['color'], sorted(response.json()['tag_names'])), ('green', ['demo', 'erp']))

    def test_move_an_instance_to_another_of_your_projects(self):
        from .project_models import Project
        target = Project.objects.create(name='Destino', owner=self.alice)
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(f'/instance/{self.alice_instance.pk}/'), 'Destino')
        subdomain = Instance.objects.get(pk=self.alice_instance.pk).subdomain
        self.client.post(f'/instance/{self.alice_instance.pk}/move/', {'project': target.pk})
        moved = Instance.objects.get(pk=self.alice_instance.pk)
        self.assertEqual((moved.project, moved.subdomain), (target, subdomain))
        # Not into someone else's project
        self.client.post(f'/instance/{self.alice_instance.pk}/move/', {'project': self.bob_project.pk})
        self.assertEqual(Instance.objects.get(pk=self.alice_instance.pk).project, target)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(f'/instance/{self.alice_instance.pk}/move/', {'project': self.bob_project.pk}).status_code, 404)


class InstanceEnvVarsTests(BaseTestCase):
    def test_parse_env(self):
        from .instance_env import parse_env
        text = '# comment\n\nSPM_MY_SITES_TOKEN=abc-123\nexport QUOTED="a b=c"\nEMPTY=\n'
        self.assertEqual(parse_env(text), {'SPM_MY_SITES_TOKEN': 'abc-123', 'QUOTED': 'a b=c', 'EMPTY': ''})
        for bad in ('NOEQUALS', '1BAD=x', 'BAD-NAME=x', 'HOST=other', 'password=x'):
            with self.assertRaises(ValueError):
                parse_env(bad)

    def test_save_from_the_modules_tab_and_redeploy(self):
        from .task_models import Task
        self.client.force_login(self.alice)
        url = f'/instance/{self.alice_instance.pk}/env-vars/'
        response = self.client.post(url, {'env_vars': 'SPM_MY_SITES_TOKEN=secret\r\nOTHER=1', 'redeploy': '1'})
        self.assertEqual(response.status_code, 302)
        self.alice_instance.refresh_from_db()
        self.assertEqual(self.alice_instance.env_vars, 'SPM_MY_SITES_TOKEN=secret\nOTHER=1')
        self.assertTrue(Task.objects.filter(instance=self.alice_instance, kind=Task.Kind.DEPLOY).exists())
        detail = self.client.get(f'/instance/{self.alice_instance.pk}/').content.decode()
        self.assertIn('SPM_MY_SITES_TOKEN', detail)
        # A wrong line saves nothing
        self.client.post(url, {'env_vars': 'USER=root'})
        self.alice_instance.refresh_from_db()
        self.assertIn('SPM_MY_SITES_TOKEN', self.alice_instance.env_vars)
        # Neither someone else nor a client of the project can change or see them
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(url, {'env_vars': 'X=1'}).status_code, 403)
        self.assertNotIn('secret', self.client.get(f'/instance/{self.alice_instance.pk}/').content.decode())

    def test_api_writes_values_and_reads_back_only_the_names(self):
        self.client.force_login(self.alice)
        url = f'/api/instances/{self.alice_instance.pk}/'
        response = self.client.patch(url, {'env_vars': 'B=2\nA=secret'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = self.client.get(url).json()
        self.assertEqual(data['env_keys'], ['A', 'B'])
        self.assertNotIn('env_vars', data)
        self.assertEqual(self.client.patch(url, {'env_vars': 'PORT=1'}, content_type='application/json').status_code, 400)
        self.alice_project.client = self.bob
        self.alice_project.save()
        self.client.force_login(self.bob)
        response = self.client.patch(url, {'env_vars': 'A=hacked'}, content_type='application/json')
        self.assertIn(response.status_code, (400, 403))
        self.alice_instance.refresh_from_db()
        self.assertIn('A=secret', self.alice_instance.env_vars)

    def test_container_environment_keeps_the_database_connection(self):
        from .instance_env import instance_environment
        self.alice_instance.env_vars = 'TOKEN=x'
        self.assertEqual({**instance_environment(self.alice_instance), 'HOST': 'db_alice-odoo'},
                         {'TOKEN': 'x', 'HOST': 'db_alice-odoo'})
        self.alice_instance.env_vars = 'not valid'
        self.assertEqual(instance_environment(self.alice_instance), {})
