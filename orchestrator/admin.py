from django.contrib import admin
from .models import Instance
from .config_models import GitHubConfig
from .backup_models import Backup
from .blog_models import BlogPost

@admin.register(Instance)
class InstanceAdmin(admin.ModelAdmin):
    list_display = ['name', 'odoo_version', 'status', 'created_at']
    list_filter = ['status', 'odoo_version']
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
