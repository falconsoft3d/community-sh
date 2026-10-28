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

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

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
        return Task.objects.filter(instance__in=instances_for(self.request.user)).select_related('instance').order_by('-created_at')


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
