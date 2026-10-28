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
            from .permissions import projects_for
            self.fields['project'].queryset = projects_for(request.user)

    def validate_custom_domain(self, value):
        if value and domain_in_use(value, exclude_instance=self.instance):
            raise serializers.ValidationError('Este dominio ya está en uso.')
        return value
