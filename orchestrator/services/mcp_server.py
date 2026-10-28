"""
MCP server (Model Context Protocol, Streamable HTTP transport) so Claude can see and operate
the platform. Every tool runs with the permissions of the token's user.
"""
import json

from config.version import VERSION

SUPPORTED_PROTOCOL_VERSIONS = ('2025-06-18', '2025-03-26')

INSTRUCTIONS = (
    "Community SH hosts Odoo instances in Docker. Instances belong to projects (one per client). "
    "Deploys, restarts and backups run in a background worker: tools that start them return a task id; "
    "use get_task to follow it."
)


def _schema(properties=None, required=None):
    return {'type': 'object', 'properties': properties or {}, 'required': required or [], 'additionalProperties': False}


INSTANCE = {'instance': {'type': 'string', 'description': 'Instance name, e.g. "acme-prod"'}}

TOOLS = [
    {'name': 'list_projects', 'description': 'List the projects (clients) the user can see, with their instances.',
     'inputSchema': _schema()},
    {'name': 'list_instances', 'description': 'List Odoo instances with status, version, project and URL.',
     'inputSchema': _schema({'project': {'type': 'string', 'description': 'Optional project name to filter by'}})},
    {'name': 'get_instance', 'description': 'Details of one instance: status, URL, Odoo version, project, repositories and recent tasks.',
     'inputSchema': _schema(INSTANCE, ['instance'])},
    {'name': 'get_instance_logs', 'description': 'Last lines of the Odoo container logs.',
     'inputSchema': _schema({**INSTANCE, 'lines': {'type': 'integer', 'minimum': 1, 'maximum': 1000, 'default': 100}}, ['instance'])},
    {'name': 'deploy_instance', 'description': 'Queue a (re)deploy of the instance. Returns a task id.',
     'inputSchema': _schema(INSTANCE, ['instance'])},
    {'name': 'restart_instance', 'description': 'Restart the Odoo container of the instance.',
     'inputSchema': _schema(INSTANCE, ['instance'])},
    {'name': 'stop_instance', 'description': 'Stop the Odoo container of the instance.',
     'inputSchema': _schema(INSTANCE, ['instance'])},
    {'name': 'create_backup', 'description': 'Queue a backup of the instance (database, and filestore unless disabled). Returns a task id.',
     'inputSchema': _schema({**INSTANCE, 'include_filestore': {'type': 'boolean', 'default': True}}, ['instance'])},
    {'name': 'list_backups', 'description': 'List backups, newest first, optionally for one instance.',
     'inputSchema': _schema({'instance': {'type': 'string', 'description': 'Optional instance name'}})},
    {'name': 'get_task', 'description': 'Status and result of a background task (deploy, backup, restore...).',
     'inputSchema': _schema({'task_id': {'type': 'integer'}}, ['task_id'])},
]


class ToolError(Exception):
    pass


def _instance(user, name):
    from ..permissions import instances_for
    instance = instances_for(user).select_related('project').filter(name=name).first()
    if instance is None:
        raise ToolError(f'Instance "{name}" not found (or not accessible to this user)')
    return instance


def _instance_info(instance):
    return {
        'name': instance.name, 'project': instance.project.name if instance.project else None,
        'odoo_version': instance.odoo_version, 'status': instance.status,
        'url': instance.url if (instance.port or instance.custom_domain) else None,
        'custom_domain': instance.custom_domain, 'database': instance.database_name,
    }


def call_tool(user, name, arguments):
    from ..backup_models import Backup
    from ..permissions import instances_for, projects_for
    from ..services import DockerService
    from ..task_models import Task
    from ..tasks import enqueue

    if name == 'list_projects':
        return [{
            'name': p.name, 'client': p.client_display or None, 'description': p.description,
            'instances': [i.name for i in p.instances.order_by('name')],
        } for p in projects_for(user).order_by('name')]
    if name == 'list_instances':
        instances = instances_for(user).select_related('project').order_by('name')
        if arguments.get('project'):
            instances = instances.filter(project__name=arguments['project'])
        return [_instance_info(i) for i in instances]
    if name == 'get_instance':
        instance = _instance(user, arguments['instance'])
        info = _instance_info(instance)
        info['repositories'] = ([instance.github_repo] if instance.github_repo else []) + [r.url for r in instance.repositories.all()]
        info['recent_tasks'] = [
            {'id': t.id, 'kind': t.kind, 'status': t.status, 'result': t.result[-500:]} for t in instance.tasks.all()[:5]
        ]
        return info
    if name == 'get_instance_logs':
        instance = _instance(user, arguments['instance'])
        return DockerService().get_logs(instance, lines=min(int(arguments.get('lines', 100)), 1000))
    if name in ('deploy_instance', 'create_backup'):
        instance = _instance(user, arguments['instance'])
        if name == 'deploy_instance':
            task = enqueue(Task.Kind.DEPLOY, instance, user)
        else:
            task = enqueue(Task.Kind.BACKUP, instance, user, include_filestore=arguments.get('include_filestore', True))
        return {'task_id': task.id, 'status': task.status}
    if name in ('restart_instance', 'stop_instance'):
        instance = _instance(user, arguments['instance'])
        service = DockerService()
        (service.restart_instance if name == 'restart_instance' else service.stop_instance)(instance)
        instance.refresh_from_db()
        return {'instance': instance.name, 'status': instance.status}
    if name == 'list_backups':
        backups = Backup.objects.filter(instance__in=instances_for(user)).select_related('instance')
        if arguments.get('instance'):
            backups = backups.filter(instance=_instance(user, arguments['instance']))
        return [{
            'id': b.id, 'instance': b.instance.name, 'file': b.filename, 'size_mb': b.file_size_mb,
            'with_filestore': b.include_filestore, 'created_at': b.created_at.isoformat(),
        } for b in backups.order_by('-created_at')[:50]]
    if name == 'get_task':
        task = Task.objects.filter(pk=arguments['task_id'], instance__in=instances_for(user)).first()
        if task is None:
            raise ToolError('Task not found')
        return {'id': task.id, 'kind': task.kind, 'status': task.status, 'instance': task.instance.name if task.instance else None,
                'result': task.result, 'created_at': task.created_at.isoformat(),
                'finished_at': task.finished_at.isoformat() if task.finished_at else None}
    raise ToolError(f'Unknown tool: {name}')


def _result(request_id, result):
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def _error(request_id, code, message):
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}


def handle_message(user, message):
    """Handle one JSON-RPC message. Returns the response dict, or None for notifications."""
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or 'method' not in message:
        return _error(message.get('id') if isinstance(message, dict) else None, -32600, 'Invalid Request')
    method, request_id, params = message['method'], message.get('id'), message.get('params') or {}
    if request_id is None:
        return None  # notifications (e.g. notifications/initialized) need no response

    if method == 'initialize':
        requested = params.get('protocolVersion')
        return _result(request_id, {
            'protocolVersion': requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0],
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': 'community-sh', 'title': 'Community SH', 'version': VERSION},
            'instructions': INSTRUCTIONS,
        })
    if method == 'ping':
        return _result(request_id, {})
    if method == 'tools/list':
        return _result(request_id, {'tools': TOOLS})
    if method == 'tools/call':
        name = params.get('name')
        if name not in {tool['name'] for tool in TOOLS}:
            return _error(request_id, -32602, f'Unknown tool: {name}')
        try:
            output = call_tool(user, name, params.get('arguments') or {})
            text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, indent=2, default=str)
            return _result(request_id, {'content': [{'type': 'text', 'text': text}], 'isError': False})
        except ToolError as e:
            return _result(request_id, {'content': [{'type': 'text', 'text': str(e)}], 'isError': True})
        except Exception as e:  # tool failures are reported to the model, not as protocol errors
            return _result(request_id, {'content': [{'type': 'text', 'text': f'Error: {e}'}], 'isError': True})
    return _error(request_id, -32601, f'Method not found: {method}')
