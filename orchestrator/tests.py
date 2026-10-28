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
        self.instance.refresh_from_db()
        self.assertEqual(self.instance.data_volume, 'odoo_data_acme')
        # Published on an explicit port (kept across restarts), stored on the instance
        self.assertEqual(odoo_call.kwargs['ports'], {'8069/tcp': self.instance.port})
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
        self.assertEqual(self.service.return_value.backup_instance.call_count, 1)

        self.config.refresh_from_db()
        self.config.last_auto_backup_at = timezone.now() - timedelta(hours=6, minutes=1)
        self.config.save()
        self.run_command()
        self.assertEqual(self.service.return_value.backup_instance.call_count, 2)

    def test_disabled_does_nothing(self):
        self.config.auto_backup_enabled = False
        self.config.save()
        self.run_command()
        self.service.return_value.backup_instance.assert_not_called()


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
        self.docker.return_value.backup_instance.side_effect = Exception('disk full')

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

        self.docker.return_value.copy_instance.side_effect = lambda source, name: Instance.objects.create(name=name)
        self.run_worker()

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
        self.assertEqual(clone.call_args.args[0], 'https://ghp_secret@github.com/OCA/web.git')
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
        # A second request while the first runs is turned away with a message
        self.assertIn('trabajando', self.signed_post(request).json()['message'])

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
