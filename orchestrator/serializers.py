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
        fields = ['id', 'kind', 'status', 'instance', 'params', 'result', 'created_at', 'started_at', 'finished_at']


class TodoSerializer(serializers.ModelSerializer):
    class Meta:
        from .todo_models import Todo
        model = Todo
        fields = ['id', 'title', 'description', 'status', 'completed_by', 'completion_note', 'completed_in_version',
                  'created_at', 'completed_at']
        read_only_fields = ['completed_by', 'completed_in_version', 'created_at', 'completed_at']
