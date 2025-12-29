from rest_framework import serializers
from .models import Instance

class InstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instance
        fields = '__all__'
        read_only_fields = ('status', 'container_id', 'port', 'created_at', 'updated_at')
