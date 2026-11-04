from rest_framework import serializers
from .models import Instance
from .permissions import domain_in_use

class InstanceSerializer(serializers.ModelSerializer):
    # Explicit list: internal fields (Docker volume, certificate paths, subdomain...) are never written
    # through the API, and the master password is only shown to who manages the instance
    url = serializers.CharField(read_only=True)

    class Meta:
        model = Instance
        fields = ('id', 'name', 'project', 'owner', 'odoo_version', 'status', 'origin', 'github_repo', 'github_branch',
                  'database_name', 'demo_default_db', 'custom_domain', 'ssl_enabled', 'browser', 'subdomain', 'url',
                  'port', 'container_id', 'master_password', 'description', 'auto_update', 'created_at', 'updated_at')
        read_only_fields = ('owner', 'status', 'origin', 'ssl_enabled', 'browser', 'subdomain', 'url', 'port',
                            'container_id', 'master_password', 'created_at', 'updated_at')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        # Every instance belongs to one of the user's projects
        self.fields['project'].required = True
        self.fields['project'].allow_null = False
        if request is not None:
            from .permissions import managed_projects_for
            self.fields['project'].queryset = managed_projects_for(request.user)
        # Renaming moves containers and volumes: it goes through its task (web form), not a PATCH
        if self.instance is not None and not isinstance(self.instance, (list, tuple)) and hasattr(self.instance, 'pk'):
            self.fields['name'].read_only = True

    def to_representation(self, instance):
        from .permissions import can_manage
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request is not None and not can_manage(request.user, instance):
            data.pop('master_password', None)
        return data

    def validate_custom_domain(self, value):
        if value and domain_in_use(value, exclude_instance=self.instance):
            raise serializers.ValidationError('Este dominio ya está en uso.')
        return value


class ProjectSerializer(serializers.ModelSerializer):
    instances = serializers.SlugRelatedField(many=True, read_only=True, slug_field='name')
    trial_url = serializers.SerializerMethodField()

    class Meta:
        from .project_models import Project
        model = Project
        fields = ['id', 'name', 'client', 'description', 'owner', 'instances',
                  'trial_enabled', 'trial_slug', 'trial_days', 'trial_target_project', 'trial_message', 'trial_max_active',
                  'trial_url', 'created_at', 'updated_at']
        read_only_fields = ['owner', 'instances', 'trial_url', 'created_at', 'updated_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        # Assigning a project's client is an admin task, as in the web form
        if request is not None and not request.user.is_superuser:
            self.fields['client'].read_only = True
        # The demos go to another project of the same owner
        if request is not None:
            from .permissions import managed_projects_for
            self.fields['trial_target_project'].queryset = managed_projects_for(request.user)

    def get_trial_url(self, project):
        if not (project.trial_enabled and project.trial_slug):
            return None
        from django.urls import reverse
        request = self.context.get('request')
        path = reverse('trial-page', args=[project.trial_slug])
        return request.build_absolute_uri(path) if request else path

    def validate_trial_slug(self, value):
        from .services.trials import trial_slug_problem
        value = (value or '').strip().lower() or None
        if value:
            problem = trial_slug_problem(value, self.instance)
            if problem:
                raise serializers.ValidationError(problem)
        return value

    def validate(self, attrs):
        from .services.trials import trial_settings_problems
        merged = {field: getattr(self.instance, field) for field in
                  ('trial_enabled', 'trial_slug', 'trial_target_project')} if self.instance else {}
        merged.update(attrs)
        request = self.context.get('request')
        owner = self.instance.owner if self.instance else (request.user if request else None)
        problems = trial_settings_problems(merged, owner, self.instance)
        if problems:
            raise serializers.ValidationError(problems)
        return attrs


class TrialRequestSerializer(serializers.ModelSerializer):
    """A demo asked for (API): who, which instance, its state and, once ready, how to get in."""
    project = serializers.PrimaryKeyRelatedField(read_only=True)
    source = serializers.SlugRelatedField(read_only=True, slug_field='name')
    instance = serializers.SlugRelatedField(read_only=True, slug_field='name')
    url = serializers.SerializerMethodField()
    status_url = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    step = serializers.SerializerMethodField()

    class Meta:
        from .trial_models import TrialRequest
        model = TrialRequest
        fields = ['id', 'project', 'source', 'instance', 'name', 'email', 'company', 'job_title', 'phone', 'country',
                  'version', 'status', 'progress', 'step', 'url', 'admin_login', 'admin_password', 'status_url',
                  'error', 'created_at', 'expires_at', 'days_until_stop', 'delete_at', 'days_until_delete', 'emailed_at']
        read_only_fields = fields

    def get_url(self, trial):
        return trial.instance.url if trial.instance else None

    def get_status_url(self, trial):
        from django.urls import reverse
        request = self.context.get('request')
        path = reverse('trial-status', args=[trial.project.trial_slug or '-', trial.token])
        return request.build_absolute_uri(path) if request else path

    def get_progress(self, trial):
        return 100 if trial.status != 'pending' else (trial.task.progress if trial.task else 0)

    def get_step(self, trial):
        return trial.task.step if trial.status == 'pending' and trial.task else ''


class TrialRequestCreateSerializer(serializers.Serializer):
    """Ask for a demo through the API (a website's backend with a token): the same limits as the public page."""
    project = serializers.IntegerField()
    instance = serializers.IntegerField(help_text='One of the running instances of the project')
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    company = serializers.CharField(max_length=150)
    job_title = serializers.CharField(max_length=100)
    phone = serializers.RegexField(r'^\+?[0-9 ().-]{6,40}$', max_length=40)
    country = serializers.CharField(max_length=80)


class PlatformSettingsSerializer(serializers.ModelSerializer):
    """Settings → Email and Demos through the API (superusers). The SMTP password is write-only."""
    smtp_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    smtp_password_set = serializers.SerializerMethodField()

    class Meta:
        from .config_models import GitHubConfig
        model = GitHubConfig
        fields = ['smtp_enabled', 'smtp_host', 'smtp_port', 'smtp_security', 'smtp_username', 'smtp_password',
                  'smtp_password_set', 'smtp_from_email', 'smtp_from_name', 'trial_max_per_day', 'trial_max_active_total']

    def get_smtp_password_set(self, config):
        return bool(config.smtp_password)

    def validate_trial_max_per_day(self, value):
        return min(value, 1000)

    def validate_trial_max_active_total(self, value):
        return min(value, 100)

    def update(self, instance, validated_data):
        # An empty password keeps the stored one (as the web form)
        if not validated_data.get('smtp_password'):
            validated_data.pop('smtp_password', None)
        return super().update(instance, validated_data)


class BackupSerializer(serializers.ModelSerializer):
    instance = serializers.SlugRelatedField(read_only=True, slug_field='name')

    class Meta:
        from .backup_models import Backup
        model = Backup
        fields = ['id', 'instance', 'filename', 'file_size', 'include_filestore', 'created_at']


class TaskSerializer(serializers.ModelSerializer):
    instance = serializers.SlugRelatedField(read_only=True, slug_field='name')

    class Meta:
        from .task_models import Task
        model = Task
        # log, progress and step: the same as the Activity page, to follow long tasks such as a build
        fields = ['id', 'kind', 'status', 'instance', 'params', 'result', 'log', 'progress', 'step',
                  'created_at', 'started_at', 'finished_at']


class TodoSerializer(serializers.ModelSerializer):
    class Meta:
        from .todo_models import Todo
        model = Todo
        fields = ['id', 'title', 'description', 'status', 'completed_by', 'completion_note', 'completed_in_version',
                  'created_at', 'completed_at']
        read_only_fields = ['completed_by', 'completed_in_version', 'created_at', 'completed_at']


class ContainerSerializer(serializers.ModelSerializer):
    """Generic Docker container. volumes, network and the SSL files are admin-only, as in the web form."""
    url = serializers.CharField(read_only=True)
    port = serializers.IntegerField(required=False)

    class Meta:
        from .container_models import Container
        model = Container
        fields = ['id', 'name', 'project', 'template', 'image', 'port', 'container_port', 'environment', 'volumes',
                  'network', 'command', 'description', 'git_repo', 'git_branch', 'dockerfile',
                  'custom_domain', 'status', 'container_id', 'url', 'created_at', 'updated_at']
        read_only_fields = ['status', 'container_id', 'url', 'created_at', 'updated_at']
        # A template fills in the image (or repository) and the port
        extra_kwargs = {'image': {'required': False}, 'container_port': {'required': False}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is not None and not request.user.is_superuser:
            for field in ('volumes', 'network'):
                self.fields[field].read_only = True
        if request is not None:
            from .permissions import managed_projects_for
            self.fields['project'].queryset = managed_projects_for(request.user)

    def to_internal_value(self, data):
        # As the web form: names are lowercased before validating them
        if isinstance(data.get('name'), str):
            data = {**data, 'name': data['name'].strip().lower()}
        return super().to_internal_value(data)

    def validate_name(self, value):
        from .container_service import reserved_container_name
        from .models import Instance
        if reserved_container_name(value):
            raise serializers.ValidationError(reserved_container_name(value))
        # Its subdomain must not take one of an instance
        if Instance.objects.filter(subdomain=value).exists():
            raise serializers.ValidationError('Ese nombre ya es el subdominio de una instancia.')
        return value

    def validate_custom_domain(self, value):
        if value and domain_in_use(value, exclude_container=self.instance):
            raise serializers.ValidationError('Este dominio ya está en uso.')
        return value or None

    def validate(self, attrs):
        from_template = attrs.get('template') not in (None, '', 'custom')
        if self.instance is None and not from_template and not attrs.get('image') and not attrs.get('git_repo'):
            raise serializers.ValidationError('Indica una imagen (image) o un repositorio para construirla (git_repo).')
        return attrs
