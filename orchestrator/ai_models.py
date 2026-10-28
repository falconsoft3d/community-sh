from django.contrib.auth.models import User
from django.db import models


class AIMessage(models.Model):
    """One message of an instance's AI assistant conversation, in OpenAI chat format."""

    class Role(models.TextChoices):
        USER = 'user', 'User'
        ASSISTANT = 'assistant', 'Assistant'
        TOOL = 'tool', 'Tool'

    instance = models.ForeignKey('Instance', on_delete=models.CASCADE, related_name='ai_messages')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices)
    content = models.TextField(blank=True)
    tool_calls = models.JSONField(null=True, blank=True, help_text="Assistant tool calls (OpenAI format)")
    tool_call_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def as_openai(self):
        message = {'role': self.role, 'content': self.content}
        if self.role == self.Role.ASSISTANT and self.tool_calls:
            message['tool_calls'] = self.tool_calls
        if self.role == self.Role.TOOL:
            message['tool_call_id'] = self.tool_call_id
        return message
