"""REST API."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from ..serializers import InstanceSerializer
from ..services import DockerService
from ..task_models import Task
from ..tasks import enqueue

from ..permissions import (
    IsOwnerOrSuperuser,
    instances_for,
)


# API ViewSet
class InstanceViewSet(viewsets.ModelViewSet):
    serializer_class = InstanceSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrSuperuser]

    def get_queryset(self):
        return instances_for(self.request.user)

    def create(self, request, *args, **kwargs):
        """Create and deploy, as the web form: the response carries the deploy task_id."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(owner=request.user)
        task = enqueue(Task.Kind.DEPLOY, instance, request.user)
        data = dict(self.get_serializer(instance).data, task_id=task.pk)
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def deploy(self, request, pk=None):
        instance = self.get_object()
        task = enqueue(Task.Kind.DEPLOY, instance, request.user)
        return Response({'task_id': task.pk, 'status': task.status}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        instance = self.get_object()
        service = DockerService()
        service.stop_instance(instance)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class InstanceActionsMixin:
    """Extra instance actions; clients may run the operate ones (see IsOwnerOrSuperuser)."""

    @action(detail=True, methods=['post'])
    def restart(self, request, pk=None):
        instance = self.get_object()
        DockerService().restart_instance(instance)
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def backup(self, request, pk=None):
        instance = self.get_object()
        include_filestore = str(request.data.get('include_filestore', 'true')).lower() != 'false'
        task = enqueue(Task.Kind.BACKUP, instance, request.user, include_filestore=include_filestore)
        return Response({'task_id': task.pk, 'status': task.status}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        from django.core.exceptions import ValidationError
        from ..models import Instance
        from ..permissions import validate_resource_name
        instance = self.get_object()
        new_name = str(request.data.get('new_name', '')).strip().lower()
        try:
            validate_resource_name(new_name)
        except ValidationError as e:
            return Response({'new_name': e.messages}, status=status.HTTP_400_BAD_REQUEST)
        if Instance.objects.filter(name=new_name).exists():
            return Response({'new_name': ['Already exists']}, status=status.HTTP_400_BAD_REQUEST)
        task = enqueue(Task.Kind.DUPLICATE, instance, request.user, new_name=new_name)
        return Response({'task_id': task.pk, 'status': task.status}, status=status.HTTP_202_ACCEPTED)


class InstanceAPIViewSet(InstanceActionsMixin, InstanceViewSet):
    pass


class ProjectViewSet(viewsets.ModelViewSet):
    from ..serializers import ProjectSerializer
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrSuperuser]

    def get_queryset(self):
        from ..permissions import projects_for
        return projects_for(self.request.user).prefetch_related('instances')

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def destroy(self, request, *args, **kwargs):
        project = self.get_object()
        if project.instances.exists():
            return Response({'detail': 'The project has instances: delete them first (or use the web UI "Eliminar todo")'},
                            status=status.HTTP_409_CONFLICT)
        return super().destroy(request, *args, **kwargs)


class BackupViewSet(viewsets.ReadOnlyModelViewSet):
    from ..serializers import BackupSerializer
    serializer_class = BackupSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        from ..backup_models import Backup
        queryset = Backup.objects.filter(instance__in=instances_for(self.request.user)).select_related('instance')
        if self.request.query_params.get('instance'):
            queryset = queryset.filter(instance__name=self.request.query_params['instance'])
        return queryset.order_by('-created_at')

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        import os
        from django.http import FileResponse
        backup = self.get_object()
        if not os.path.exists(backup.file_path):
            return Response({'detail': 'File not found'}, status=status.HTTP_404_NOT_FOUND)
        return FileResponse(open(backup.file_path, 'rb'), as_attachment=True, filename=backup.filename)

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        from ..permissions import can_manage
        backup = self.get_object()
        if not can_manage(request.user, backup.instance):
            return Response({'detail': 'Only the owner can restore'}, status=status.HTTP_403_FORBIDDEN)
        task = enqueue(Task.Kind.RESTORE, backup.instance, request.user, file_path=backup.file_path, label=backup.filename)
        return Response({'task_id': task.pk, 'status': task.status}, status=status.HTTP_202_ACCEPTED)


class TaskViewSet(viewsets.ReadOnlyModelViewSet):
    from ..serializers import TaskSerializer
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Also the user's own tasks without an instance, like building a container
        from django.db.models import Q
        mine = Q(instance__in=instances_for(self.request.user)) | Q(instance=None, created_by=self.request.user)
        return Task.objects.filter(mine).select_related('instance').order_by('-created_at')


class TodoViewSet(viewsets.ModelViewSet):
    from ..serializers import TodoSerializer
    serializer_class = TodoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        from rest_framework.exceptions import PermissionDenied
        from ..permissions import is_client
        from .todo import todos_for
        if is_client(self.request.user):
            raise PermissionDenied
        return todos_for(self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        todo = serializer.save()
        # Keep the completion metadata consistent with the status
        todo.set_status(todo.status, by=self.request.user.get_full_name() or self.request.user.username,
                        note=self.request.data.get('completion_note', ''))


def _free_container_port():
    """A host port not used by another container or instance."""
    from ..container_models import Container
    from ..models import Instance
    used = set(Container.objects.values_list('port', flat=True)) | set(
        Instance.objects.exclude(port=None).values_list('port', flat=True))
    port = 40000
    while port in used:
        port += 1
    return port


class ContainerViewSet(viewsets.ModelViewSet):
    """
    Generic Docker containers, from an image or built from a repository (git_repo +
    dockerfile, cloned with the owner's GitHub token). Each one gets
    https://<name>.<platform domain>. Building runs as a task: the response has task_id.
    """
    from ..serializers import ContainerSerializer
    serializer_class = ContainerSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'patch', 'delete']

    def get_queryset(self):
        from ..container_models import Container
        return Container.objects.filter(created_by=self.request.user).order_by('-id')

    def _service(self):
        from ..container_service import ContainerService
        return ContainerService()

    def create(self, request, *args, **kwargs):
        from ..permissions import is_client
        from ..template_services import get_template_loader
        if is_client(request.user):
            return Response({'detail': 'Los clientes no pueden crear contenedores'}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        template = values.get('template') or 'custom'
        if template != 'custom':
            # The template fills in what the request leaves out
            defaults = get_template_loader().get_template_defaults(template)
            values.setdefault('image', defaults.get('image', ''))
            values.setdefault('container_port', defaults.get('container_port'))
            values.setdefault('environment', defaults.get('environment', {}))
            values.setdefault('command', defaults.get('command', ''))
            if defaults.get('git_repo'):
                values.setdefault('git_repo', defaults['git_repo'])
                values.setdefault('git_branch', defaults.get('git_branch', 'main'))
                values.setdefault('dockerfile', defaults.get('dockerfile', 'Dockerfile'))
            if request.user.is_superuser:
                values.setdefault('volumes', defaults.get('volumes', {}))
                values.setdefault('network', defaults.get('network', 'bridge'))
        if not values.get('container_port'):
            return Response({'container_port': ['Obligatorio sin plantilla.']}, status=status.HTTP_400_BAD_REQUEST)
        values.setdefault('port', _free_container_port())
        from ..template_services import with_secrets
        values['environment'] = with_secrets(values.get('environment'))
        if values.get('git_repo'):
            values['image'] = ''
        container = serializer.save(created_by=request.user, **values)
        if container.git_repo:
            task = enqueue(Task.Kind.BUILD_CONTAINER, None, request.user, container=container.pk,
                           label=container.name)
            data = dict(self.get_serializer(container).data, task_id=task.pk)
            return Response(data, status=status.HTTP_202_ACCEPTED)
        ok, message = self._service().create_container(container)
        if not ok:
            container.delete()
            return Response({'detail': message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(container).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        container = serializer.save()
        if container.status == 'running':
            self._service().restart_container(container)

    def destroy(self, request, *args, **kwargs):
        container = self.get_object()
        ok, message = self._service().delete_container(container)
        if not ok:
            return Response({'detail': message}, status=status.HTTP_400_BAD_REQUEST)
        container.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _act(self, method):
        container = self.get_object()
        ok, message = getattr(self._service(), method)(container)
        if not ok:
            return Response({'detail': message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(container).data)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        return self._act('start_container')

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        return self._act('stop_container')

    @action(detail=True, methods=['post'])
    def restart(self, request, pk=None):
        return self._act('restart_container')

    @action(detail=True, methods=['post'])
    def build(self, request, pk=None):
        """Pull the repository again and rebuild the image (git_repo containers)."""
        container = self.get_object()
        if not container.git_repo:
            return Response({'detail': 'El contenedor no se construye desde un repositorio'},
                            status=status.HTTP_400_BAD_REQUEST)
        task = enqueue(Task.Kind.BUILD_CONTAINER, None, request.user, container=container.pk, label=container.name)
        return Response({'task_id': task.pk, 'status': task.status}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        tail = min(int(request.query_params.get('tail', 200)), 5000)
        return Response({'logs': self._service().get_container_logs(self.get_object(), tail=tail)})
