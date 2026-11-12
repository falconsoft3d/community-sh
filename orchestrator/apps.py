from django.apps import AppConfig


class OrchestratorConfig(AppConfig):
    name = 'orchestrator'

    def ready(self):
        from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
        from .audit import record

        def logged_in(sender, request, user, **kwargs):
            record(request, 'login', user=user)

        def logged_out(sender, request, user, **kwargs):
            if user is not None:
                record(request, 'logout', user=user)

        def login_failed(sender, credentials, request=None, **kwargs):
            record(request, 'login_failed', target=(credentials or {}).get('username', ''))

        user_logged_in.connect(logged_in, dispatch_uid='audit-login')
        user_logged_out.connect(logged_out, dispatch_uid='audit-logout')
        user_login_failed.connect(login_failed, dispatch_uid='audit-login-failed')
