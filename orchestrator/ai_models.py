import base64
import os

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage
from django.db import models


class AttachmentStorage(FileSystemStorage):
    """<BASE_DIR>/ai_attachments: outside MEDIA_ROOT, so chat attachments are never served publicly."""

    @property
    def base_location(self):
        return os.path.join(str(settings.BASE_DIR), 'ai_attachments')

    @property
    def location(self):
        return os.path.abspath(self.base_location)


attachment_storage = AttachmentStorage()


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
    # On user messages: the checklist the assistant keeps for a long request
    plan = models.JSONField(null=True, blank=True, help_text="[{step, status: pending|in_progress|done}]")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def as_openai(self):
        message = {'role': self.role, 'content': self.content}
        if self.role == self.Role.USER:
            attachments = list(self.attachments.all())
            if attachments:
                message['content'] = [{'type': 'text', 'text': self.content}] + [a.as_openai_part() for a in attachments]
        if self.role == self.Role.ASSISTANT and self.tool_calls:
            message['tool_calls'] = self.tool_calls
        if self.role == self.Role.TOOL:
            message['tool_call_id'] = self.tool_call_id
        return message



class AIAttachment(models.Model):
    """A file the user sent with a message: PDFs and images go to the model as they are."""
    TEXT_EXTENSIONS = ('.txt', '.md', '.csv', '.xml', '.py', '.json', '.js', '.html', '.css', '.po', '.log')

    message = models.ForeignKey(AIMessage, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='%Y/%m/', storage=attachment_storage)
    name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def as_openai_part(self):
        with self.file.open('rb') as f:
            data = f.read()
        if self.content_type == 'application/pdf':
            encoded = base64.b64encode(data).decode()
            return {'type': 'file', 'file': {'filename': self.name, 'file_data': f'data:application/pdf;base64,{encoded}'}}
        if self.content_type.startswith('image/'):
            encoded = base64.b64encode(data).decode()
            return {'type': 'image_url', 'image_url': {'url': f'data:{self.content_type};base64,{encoded}'}}
        return {'type': 'text', 'text': f'[Archivo adjunto {self.name}]\n' + data.decode('utf-8', errors='replace')}


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
