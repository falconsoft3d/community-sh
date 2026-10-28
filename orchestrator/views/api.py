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
