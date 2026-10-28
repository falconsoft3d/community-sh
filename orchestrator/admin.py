from django.contrib import admin
from .models import Instance
from .config_models import GitHubConfig
from .backup_models import Backup
from .blog_models import BlogPost
from .task_models import Task
from .project_models import Project
from .todo_models import Todo

@admin.register(Instance)
class InstanceAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'owner', 'odoo_version', 'status', 'created_at']
    list_filter = ['status', 'odoo_version', 'owner', 'project']
    search_fields = ['name']

@admin.register(GitHubConfig)
class GitHubConfigAdmin(admin.ModelAdmin):
    list_display = ['user', 'default_organization', 'registration_enabled', 'created_at']
    list_filter = ['registration_enabled']

@admin.register(Backup)
class BackupAdmin(admin.ModelAdmin):
    list_display = ['instance', 'filename', 'file_size_mb', 'include_filestore', 'created_at']
    list_filter = ['include_filestore', 'created_at']
    search_fields = ['instance__name', 'filename']

@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ['title', 'author', 'published', 'featured', 'created_at']
    list_filter = ['published', 'featured', 'created_at']
    search_fields = ['title', 'content']
    prepopulated_fields = {'slug': ('title',)}
    
    fieldsets = (
        ('Content', {
            'fields': ('title', 'slug', 'content', 'excerpt')
        }),
        ('Metadata', {
            'fields': ('author', 'published', 'featured')
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not obj.pk:  # If creating new post
            obj.author = request.user
        super().save_model(request, obj, form, change)

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['id', 'kind', 'status', 'instance', 'created_by', 'created_at', 'finished_at']
    list_filter = ['status', 'kind']
    readonly_fields = ['created_at', 'started_at', 'finished_at']

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'client', 'owner', 'created_at']
    list_filter = ['owner']
    search_fields = ['name', 'client']

@admin.register(Todo)
class TodoAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'created_by', 'completed_by', 'completed_in_version', 'created_at']
    list_filter = ['status']
    search_fields = ['title', 'description']
