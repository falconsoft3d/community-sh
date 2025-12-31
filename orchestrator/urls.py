from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    InstanceViewSet, 
    InstanceListView, 
    InstanceCreateView, 
    InstanceDetailView,
    instance_deploy,
    instance_stop,
    instance_restart,
    instance_logs_api,
    instance_console_exec,
    instance_install_requirements,
    instance_configure_domain,
    instance_generate_ssl,
    instance_install_module,
    instance_update_name,
    instance_delete,
    instance_duplicate,
    metrics_view,
    settings_view,
    generate_ssl_certificate,
    instance_backup,
    instance_restore,
    instance_backups_list,
    backup_download,
    backup_delete,
    backup_restore_action,
    backup_create_instance,
    user_list,
    user_create,
    user_edit,
    user_delete,
    user_profile,
    user_change_password,
    run_manual_backup,
    install_backup_cron,
    home,
    dashboard,
    blog_list,
    blog_detail
)
from .auth_views import register
from .container_views import (
    container_list,
    container_create,
    container_detail,
    container_start,
    container_stop,
    container_restart,
    container_delete
)

router = DefaultRouter()
router.register(r'api/instances', InstanceViewSet, basename='api-instance')

urlpatterns = [
    path('accounts/register/', register, name='register'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', home, name='home'),
    path('blog/', blog_list, name='blog-list'),
    path('blog/<slug:slug>/', blog_detail, name='blog-detail'),
    
    # Dashboard routes (protected area)
    path('dashboard/instances/', InstanceListView.as_view(), name='instance-list'),
    path('dashboard/instance/new/', InstanceCreateView.as_view(), name='instance-create'),
    path('dashboard/instance/<int:pk>/', InstanceDetailView.as_view(), name='instance-detail'),
    path('dashboard/instance/<int:pk>/deploy/', instance_deploy, name='instance-deploy'),
    path('dashboard/instance/<int:pk>/stop/', instance_stop, name='instance-stop'),
    path('dashboard/instance/<int:pk>/restart/', instance_restart, name='instance-restart'),
    path('dashboard/instance/<int:pk>/delete/', instance_delete, name='instance-delete'),
    path('dashboard/instance/<int:pk>/duplicate/', instance_duplicate, name='instance-duplicate'),
    path('dashboard/instance/<int:pk>/backup/', instance_backup, name='instance-backup'),
    path('dashboard/instance/<int:pk>/backups/', instance_backups_list, name='instance-backups'),
    path('dashboard/instance/<int:pk>/restore/', instance_restore, name='instance-restore'),
    path('dashboard/backup/<int:backup_id>/download/', backup_download, name='backup-download'),
    path('dashboard/backup/<int:backup_id>/delete/', backup_delete, name='backup-delete'),
    path('dashboard/backup/<int:backup_id>/restore_action/', backup_restore_action, name='backup-restore-action'),
    path('dashboard/backup/<int:backup_id>/create-instance/', backup_create_instance, name='backup-create-instance'),
    path('dashboard/instance/<int:pk>/logs/', instance_logs_api, name='instance-logs-api'),
    path('dashboard/instance/<int:pk>/console/', instance_console_exec, name='instance-console-exec'),
    path('dashboard/instance/<int:pk>/install-requirements/', instance_install_requirements, name='instance-install-requirements'),
    path('dashboard/instance/<int:pk>/configure-domain/', instance_configure_domain, name='instance-configure-domain'),
    path('dashboard/instance/<int:pk>/generate-ssl/', instance_generate_ssl, name='instance-generate-ssl'),
    path('dashboard/instance/<int:pk>/install-module/', instance_install_module, name='instance-install-module'),
    path('dashboard/instance/<int:pk>/update-name/', instance_update_name, name='instance-update-name'),
    path('dashboard/metrics/', metrics_view, name='metrics'),
    path('dashboard/settings/', settings_view, name='settings'),
    path('dashboard/settings/generate-ssl/', generate_ssl_certificate, name='generate-ssl'),
    path('dashboard/settings/run-backup/', run_manual_backup, name='run-manual-backup'),
    path('dashboard/users/', user_list, name='user-list'),
    path('dashboard/users/new/', user_create, name='user-create'),
    path('dashboard/users/<int:user_id>/edit/', user_edit, name='user-edit'),
    path('dashboard/users/<int:user_id>/delete/', user_delete, name='user-delete'),
    path('dashboard/profile/', user_profile, name='user-profile'),
    path('dashboard/profile/change-password/', user_change_password, name='change-password'),
    
    # Backup cron job installation
    path('dashboard/settings/install-cron/', install_backup_cron, name='install-backup-cron'),
    
    # Container management routes
    path('dashboard/containers/', container_list, name='container-list'),
    path('dashboard/containers/new/', container_create, name='container-create'),
    path('dashboard/containers/<int:pk>/', container_detail, name='container-detail'),
    path('dashboard/containers/<int:pk>/start/', container_start, name='container-start'),
    path('dashboard/containers/<int:pk>/stop/', container_stop, name='container-stop'),
    path('dashboard/containers/<int:pk>/restart/', container_restart, name='container-restart'),
    path('dashboard/containers/<int:pk>/delete/', container_delete, name='container-delete'),
    
    path('', include(router.urls)),
]
