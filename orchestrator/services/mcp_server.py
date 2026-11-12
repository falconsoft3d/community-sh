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
    {'name': 'get_instance', 'description': 'Details of one instance: status, URL, Odoo version, project, repositories, recent tasks '
                                            'and, for who manages it, the Odoo administrator the platform set up (login and password).',
     'inputSchema': _schema(INSTANCE, ['instance'])},
    {'name': 'get_instance_logs', 'description': 'Last lines of the Odoo container logs.',
     'inputSchema': _schema({**INSTANCE, 'lines': {'type': 'integer', 'minimum': 1, 'maximum': 1000, 'default': 100}}, ['instance'])},
    {'name': 'deploy_instance', 'description': 'Queue a (re)deploy of the instance. Returns a task id.',
     'inputSchema': _schema(INSTANCE, ['instance'])},
    {'name': 'add_instance_repository',
     'description': 'Add an extra addons repository (e.g. OCA or odoo/enterprise) to the instance, cloned next to the main one '
                    'and added to addons_path. Only who manages the instance. Applied on the next deploy (deploy_instance).',
     'inputSchema': _schema({**INSTANCE, 'url': {'type': 'string', 'description': 'HTTPS clone URL, e.g. https://github.com/OCA/web.git'},
                             'branch': {'type': 'string', 'description': 'Branch, e.g. "19.0" (default "main")'}}, ['instance', 'url'])},
    {'name': 'remove_instance_repository',
     'description': 'Remove an extra addons repository from the instance (by its URL). Applied on the next deploy.',
     'inputSchema': _schema({**INSTANCE, 'url': {'type': 'string'}}, ['instance', 'url'])},
    {'name': 'reset_admin_password',
     'description': 'Give the Odoo administrator of the instance a new password (the one given, or a random one) and return it. '
                    'Only who manages the instance. Runs as a task: when get_task says done, get_instance shows the login.',
     'inputSchema': _schema({**INSTANCE, 'password': {'type': 'string', 'description': 'Optional: 8-64 letters, digits, "_" or "-"'}},
                            ['instance'])},
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
    {'name': 'list_todos', 'description': 'List the team to-do items (the "Todo" menu). Filter by status: pending, in_progress or done.',
     'inputSchema': _schema({'status': {'type': 'string', 'enum': ['pending', 'in_progress', 'done']}})},
    {'name': 'add_todo', 'description': 'Add a to-do item.',
     'inputSchema': _schema({'title': {'type': 'string'}, 'description': {'type': 'string'}}, ['title'])},
    {'name': 'update_todo', 'description': 'Change a to-do status. When marking it done, explain what was done in note.',
     'inputSchema': _schema({'todo_id': {'type': 'integer'}, 'status': {'type': 'string', 'enum': ['pending', 'in_progress', 'done']},
                             'note': {'type': 'string', 'description': 'What was done (shown under the item)'}}, ['todo_id', 'status'])},
]


class ToolError(Exception):
    pass


def _instance(user, name):
    from ..permissions import instances_for
    instance = instances_for(user).select_related('project').filter(name=name).first()
    if instance is None:
        raise ToolError(f'Instance "{name}" not found (or not accessible to this user)')
    return instance


def _may(user, instance, permission):
    from ..permissions import may
    if not may(user, instance, permission):
        raise ToolError(f'The project of "{instance.name}" does not let its client do this ({permission})')


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
        from ..permissions import can_manage
        if instance.admin_password and can_manage(user, instance):
            info['administrator'] = {'login': instance.admin_login or 'admin', 'password': instance.admin_password,
                                     'database': instance.admin_database or None}
        return info
    if name == 'get_instance_logs':
        instance = _instance(user, arguments['instance'])
        _may(user, instance, 'logs')
        return DockerService().get_logs(instance, lines=min(int(arguments.get('lines', 100)), 1000))
    if name in ('deploy_instance', 'create_backup'):
        instance = _instance(user, arguments['instance'])
        _may(user, instance, 'operate' if name == 'deploy_instance' else 'backups')
        if name == 'deploy_instance':
            task = enqueue(Task.Kind.DEPLOY, instance, user)
        else:
            task = enqueue(Task.Kind.BACKUP, instance, user, include_filestore=arguments.get('include_filestore', True))
        return {'task_id': task.id, 'status': task.status}
    if name in ('add_instance_repository', 'remove_instance_repository'):
        from ..permissions import can_manage
        from ..repository_models import add_instance_repository, repository_data
        instance = _instance(user, arguments['instance'])
        if not can_manage(user, instance):
            raise ToolError('Only who manages the instance can change its repositories')
        if name == 'add_instance_repository':
            repository, error = add_instance_repository(instance, arguments.get('url'), arguments.get('branch'))
            if error:
                raise ToolError(error)
            return dict(repository_data(repository), note='Added: deploy the instance to apply it')
        repository = instance.repositories.filter(url=(arguments.get('url') or '').strip()).first()
        if repository is None:
            raise ToolError('That repository is not in the instance')
        repository.delete()
        return {'removed': repository.url, 'note': 'Removed: deploy the instance to apply it'}
    if name == 'reset_admin_password':
        from ..permissions import can_manage
        from ..tasks import queue_admin_password_reset
        instance = _instance(user, arguments['instance'])
        if not can_manage(user, instance):
            raise ToolError('Only who manages the instance can change its administrator password')
        try:
            task, password = queue_admin_password_reset(instance, user, arguments.get('password') or '')
        except ValueError as e:
            raise ToolError(str(e))
        return {'task_id': task.id, 'status': task.status, 'password': password,
                'note': 'Applied by the task: follow it with get_task; get_instance then shows the login'}
    if name in ('restart_instance', 'stop_instance'):
        instance = _instance(user, arguments['instance'])
        _may(user, instance, 'operate')
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
    if name in ('list_todos', 'add_todo', 'update_todo'):
        from ..permissions import is_client
        from ..todo_models import Todo
        from ..views.todo import todos_for
        if is_client(user):
            raise ToolError('Clients cannot use the to-do list')
        if name == 'list_todos':
            todos = todos_for(user)
            if arguments.get('status'):
                todos = todos.filter(status=arguments['status'])
            return [{'id': t.id, 'title': t.title, 'description': t.description, 'status': t.status,
                     'completion_note': t.completion_note, 'completed_in_version': t.completed_in_version}
                    for t in todos.order_by('created_at')]
        if name == 'add_todo':
            todo = Todo.objects.create(title=arguments['title'][:200], description=arguments.get('description', ''), created_by=user)
            return {'id': todo.id, 'status': todo.status}
        todo = todos_for(user).filter(pk=arguments['todo_id']).first()
        if todo is None:
            raise ToolError('To-do not found')
        if arguments['status'] not in Todo.Status.values:
            raise ToolError('Invalid status')
        todo.set_status(arguments['status'], by=f'Claude (MCP, {user.username})', note=arguments.get('note', ''))
        return {'id': todo.id, 'status': todo.status, 'completed_in_version': todo.completed_in_version}
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


# What a read-only token may call
READ_ONLY_TOOLS = {'list_projects', 'list_instances', 'get_instance', 'get_instance_logs', 'list_backups', 'get_task',
                   'list_todos'}


def handle_message(user, message, read_only=False):
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
        return _result(request_id, {'tools': [t for t in TOOLS if not read_only or t['name'] in READ_ONLY_TOOLS]})
    if method == 'tools/call':
        name = params.get('name')
        if name not in {tool['name'] for tool in TOOLS}:
            return _error(request_id, -32602, f'Unknown tool: {name}')
        if read_only and name not in READ_ONLY_TOOLS:
            return _result(request_id, {'content': [{'type': 'text', 'text': f'{name}: este token es de solo lectura'}],
                                        'isError': True})
        try:
            output = call_tool(user, name, params.get('arguments') or {})
            text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, indent=2, default=str)
            return _result(request_id, {'content': [{'type': 'text', 'text': text}], 'isError': False})
        except ToolError as e:
            return _result(request_id, {'content': [{'type': 'text', 'text': str(e)}], 'isError': True})
        except Exception as e:  # tool failures are reported to the model, not as protocol errors
            return _result(request_id, {'content': [{'type': 'text', 'text': f'Error: {e}'}], 'isError': True})
    return _error(request_id, -32601, f'Method not found: {method}')
