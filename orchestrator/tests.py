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
        self.alice_instance = Instance.objects.create(name='alice-odoo', owner=self.alice)
        self.bob_instance = Instance.objects.create(name='bob-odoo', owner=self.bob)

        docker_patch = mock.patch('orchestrator.views.DockerService')
        self.docker = docker_patch.start()
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
        response = self.client.post('/api/instances/', {'name': 'alice-two', 'owner': self.bob.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Instance.objects.get(name='alice-two').owner, self.alice)


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
