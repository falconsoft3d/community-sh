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
        response = self.client.get('/api/instances/')
        self.assertEqual(response.status_code, 403)

        response = self.client.post('/api/instances/', {'name': 'evil'})
        self.assertEqual(response.status_code, 403)
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
        self.assertEqual(volumes['/srv/csh/instances/acme/odoo.conf']['bind'], '/etc/odoo/odoo.conf')

        with open(f'{self.tmp}/instances/acme/odoo.conf') as f:
            self.assertIn(f'admin_passwd = {self.instance.master_password}', f.read())
        self.instance.refresh_from_db()
        self.assertEqual(self.instance.data_volume, 'odoo_data_acme')
        self.assertEqual(self.instance.port, 32768)

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
        import os
        with zipfile.ZipFile(path, 'w') as zf:
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
        self.assertEqual(self.service._ensure_image('odoo:10.0'), 'linux/amd64')
        self.client.images.pull.assert_called_with('odoo', tag='10.0', platform='linux/amd64')

    def test_other_pull_errors_are_reported(self):
        import docker
        self.client.images.pull.side_effect = docker.errors.APIError('manifest unknown')
        with self.assertRaisesMessage(Exception, 'No se pudo descargar la imagen odoo:99.0'):
            self.service._ensure_image('odoo:99.0')


class ClientTests(BaseTestCase):
    def make_client(self, **extra):
        self.client.force_login(self.admin)
        data = {'company': 'Veolia', 'username': 'veolia', 'first_name': 'Ana', 'email': 'ana@veolia.example',
                'projects': [self.alice_project.pk], **extra}
        response = self.client.post(reverse('client-create'), data)
        return User.objects.get(username='veolia'), response

    def test_admin_creates_client_with_generated_password(self):
        client_user, response = self.make_client()
        self.assertTrue(client_user.profile.is_client)
        self.assertEqual(client_user.profile.company, 'Veolia')
        self.alice_project.refresh_from_db()
        self.assertEqual(self.alice_project.client, client_user)
        shown = [str(m) for m in response.wsgi_request._messages]
        self.assertTrue(any('Contraseña inicial de veolia' in m for m in shown))

    def test_clients_menu_is_admin_only(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('client-list')).status_code, 403)

    def test_client_sees_and_operates_but_cannot_manage(self):
        client_user, _ = self.make_client()
        self.client.force_login(client_user)
        pk = self.alice_instance.pk
        self.assertContains(self.client.get(reverse('project-list')), 'ACME')
        self.assertEqual(self.client.get(reverse('instance-detail', args=[pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('instance-detail', args=[self.bob_instance.pk])).status_code, 404)
        # Operate
        self.client.post(reverse('instance-deploy', args=[pk]))
        self.client.post(reverse('instance-backup', args=[pk]))
        from .task_models import Task
        self.assertEqual(set(Task.objects.values_list('kind', flat=True)), {'deploy', 'backup'})
        # Manage: forbidden
        for name in ('instance-delete', 'instance-duplicate', 'instance-console-exec', 'instance-update-name', 'instance-restore'):
            self.assertEqual(self.client.post(reverse(name, args=[pk])).status_code, 403, name)
        self.assertEqual(self.client.post(reverse('project-edit', args=[self.alice_project.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('instance-create')).status_code, 403)
        self.assertEqual(self.client.get(reverse('project-create')).status_code, 403)
        self.assertEqual(self.client.get(reverse('container-create')).status_code, 403)
        self.assertTrue(Instance.objects.filter(pk=pk).exists())

    def test_client_api_is_read_and_operate_only(self):
        client_user, _ = self.make_client()
        self.client.force_login(client_user)
        self.assertEqual([i['name'] for i in self.client.get('/api/instances/').json()], ['alice-odoo'])
        self.assertEqual(self.client.post(f'/api/instances/{self.alice_instance.pk}/deploy/').status_code, 202)
        self.assertEqual(self.client.delete(f'/api/instances/{self.alice_instance.pk}/').status_code, 403)
        self.assertEqual(self.client.post('/api/instances/', {'name': 'x', 'project': self.alice_project.pk}).status_code, 403)

    def test_deactivated_client_cannot_log_in(self):
        client_user, _ = self.make_client(password='Cl1ent-pass-2026')
        self.client.post(reverse('client-toggle-active', args=[client_user.pk]))
        self.client.logout()
        self.client.post(reverse('login'), {'username': 'veolia', 'password': 'Cl1ent-pass-2026'})
        self.assertNotIn('_auth_user_id', self.client.session)


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
