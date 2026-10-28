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
    # The user message that started this turn (set on assistant/tool messages)
    turn = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='turn_messages')
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



class AIFileChange(models.Model):
    """Content a file had before the assistant changed it in a turn, so the turn can be undone."""
    turn = models.ForeignKey(AIMessage, on_delete=models.CASCADE, related_name='file_changes')
    path = models.CharField(max_length=500, help_text="Path as given to the tools (relative to the addons folder)")
    previous_content = models.TextField(null=True, blank=True, help_text="None if the file did not exist")
    created_at = models.DateTimeField(auto_now_add=True)
    reverted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['id']
        constraints = [models.UniqueConstraint(fields=['turn', 'path'], name='one_snapshot_per_file_and_turn')]
