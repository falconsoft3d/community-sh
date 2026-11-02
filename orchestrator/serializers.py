from rest_framework import serializers
from .models import Instance
from .permissions import domain_in_use

class InstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instance
        fields = '__all__'
        read_only_fields = ('owner', 'status', 'container_id', 'port', 'created_at', 'updated_at')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        # Every instance belongs to one of the user's projects
        self.fields['project'].required = True
        self.fields['project'].allow_null = False
        if request is not None:
            from .permissions import managed_projects_for
            self.fields['project'].queryset = managed_projects_for(request.user)

    def validate_custom_domain(self, value):
        if value and domain_in_use(value, exclude_instance=self.instance):
            raise serializers.ValidationError('Este dominio ya está en uso.')
        return value


class ProjectSerializer(serializers.ModelSerializer):
    instances = serializers.SlugRelatedField(many=True, read_only=True, slug_field='name')

    class Meta:
        from .project_models import Project
        model = Project
        fields = ['id', 'name', 'client', 'description', 'owner', 'instances', 'created_at', 'updated_at']
        read_only_fields = ['owner', 'instances', 'created_at', 'updated_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        # Assigning a project's client is an admin task, as in the web form
        if request is not None and not request.user.is_superuser:
            self.fields['client'].read_only = True


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
        fields = ['id', 'name', 'template', 'image', 'port', 'container_port', 'environment', 'volumes',
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

    def to_internal_value(self, data):
        # As the web form: names are lowercased before validating them
        if isinstance(data.get('name'), str):
            data = {**data, 'name': data['name'].strip().lower()}
        return super().to_internal_value(data)

    def validate_name(self, value):
        from .models import Instance
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
