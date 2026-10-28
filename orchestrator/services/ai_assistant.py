"""
AI assistant for an Odoo instance: ChatGPT with tools that edit the instance's addons
folder (mounted at /mnt/extra-addons) and install or upgrade modules through the worker.
"""
import json
import os

from django.conf import settings

from .ai import AIError, chat, get_ai_config

MAX_TOOL_ROUNDS = 10
MAX_FILE_BYTES = 200 * 1024
SKIP_DIRS = {'.git', '__pycache__', 'node_modules'}

TOOLS = [
    {'type': 'function', 'function': {
        'name': 'list_files',
        'description': 'List files in the addons folder (or a subfolder of it). Paths are relative to the addons folder; use "repos" or "repos/<repo>/..." for the extra repositories (read-only).',
        'parameters': {'type': 'object', 'properties': {'path': {'type': 'string', 'description': 'Subfolder, e.g. "my_module". Empty for the root.'}}},
    }},
    {'type': 'function', 'function': {
        'name': 'read_file',
        'description': 'Read a text file from the addons folder.',
        'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']},
    }},
    {'type': 'function', 'function': {
        'name': 'write_file',
        'description': 'Create or overwrite a text file in the addons folder. Parent folders are created.',
        'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['path', 'content']},
    }},
    {'type': 'function', 'function': {
        'name': 'delete_file',
        'description': 'Delete a file from the addons folder.',
        'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']},
    }},
    {'type': 'function', 'function': {
        'name': 'undo_last_change',
        'description': 'Undo the file changes made in the previous request (restores the files as they were before it, then upgrades the affected modules). Use it when the user asks to go back.',
        'parameters': {'type': 'object', 'properties': {}},
    }},
    {'type': 'function', 'function': {
        'name': 'install_module',
        'description': 'Queue the installation (or upgrade, if already installed) of a module in the Odoo database, then restart Odoo. Runs in the background; the result appears in the instance tasks.',
        'parameters': {'type': 'object', 'properties': {
            'module': {'type': 'string', 'description': 'Technical name of the module (its folder name)'},
            'upgrade': {'type': 'boolean', 'description': 'true to upgrade an installed module (-u), false to install it (-i)'},
        }, 'required': ['module']},
    }},
]


def addons_dir(instance):
    return os.path.join(settings.BASE_DIR, 'instances', instance.name, 'addons')


def repos_dir(instance):
    return os.path.join(settings.BASE_DIR, 'instances', instance.name, 'repos')


REPOS_PREFIX = 'repos/'


def _safe_path(instance, relative, write=False):
    """
    Resolve a tool path. Plain paths live in the addons folder (read/write); paths starting with
    'repos/<repo>/' point to the extra repositories, which are read-only (re-synced on deploy).
    """
    relative = relative or ''
    if os.path.isabs(relative):
        raise ValueError('La ruta debe estar dentro de la carpeta de addons (usa rutas relativas)')
    if relative == 'repos' or relative.startswith(REPOS_PREFIX):
        if write:
            raise ValueError('Los repositorios son de solo lectura: crea un módulo en addons que los extienda')
        root = os.path.realpath(repos_dir(instance))
        relative = relative[len('repos'):].lstrip('/')
    else:
        root = os.path.realpath(addons_dir(instance))
    target = os.path.realpath(os.path.join(root, relative))
    if target != root and not target.startswith(root + os.sep):
        raise ValueError('La ruta debe estar dentro de la carpeta de addons')
    return root, target


def _read_manifest(module_dir):
    import ast
    for name in ('__manifest__.py', '__openerp__.py'):
        path = os.path.join(module_dir, name)
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8', errors='replace') as f:
                    return ast.literal_eval(f.read())
            except (ValueError, SyntaxError):
                return {}
    return None


def find_custom_modules(instance):
    """Modules found in the instance's addons folder and extra repositories (taggable in the chat)."""
    modules = []
    sources = [('addons', addons_dir(instance), '')]
    if os.path.isdir(repos_dir(instance)):
        for repo in sorted(os.listdir(repos_dir(instance))):
            sources.append((f'repos/{repo}', os.path.join(repos_dir(instance), repo), f'repos/{repo}/'))
    for source, root, prefix in sources:
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            module_dir = os.path.join(root, entry)
            if entry.startswith('.') or not os.path.isdir(module_dir):
                continue
            manifest = _read_manifest(module_dir)
            if manifest is None:
                continue
            modules.append({
                'name': entry, 'title': str(manifest.get('name') or entry), 'source': source,
                'path': prefix + entry, 'editable': source == 'addons',
                'depends': list(manifest.get('depends') or []),
            })
    return modules


def tagged_modules_context(instance, names):
    """Context block describing the modules the user tagged with @name."""
    by_name = {m['name']: m for m in find_custom_modules(instance)}
    blocks = []
    for name in names:
        module = by_name.get(name)
        if not module:
            continue
        _, module_path = _safe_path(instance, module['path'])
        files = []
        for current, dirs, file_names in os.walk(module_path):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            files += [os.path.relpath(os.path.join(current, f), module_path) for f in sorted(file_names)]
        mode = 'editable (addons)' if module['editable'] else 'solo lectura (repositorio): extiéndelo con un módulo nuevo en addons'
        blocks.append(
            f"@{name} — «{module['title']}», ruta para las herramientas: {module['path']} — {mode}. "
            f"Depende de: {', '.join(module['depends']) or 'nada'}. Archivos: {', '.join(files[:80])}"
        )
    return blocks


def _snapshot(turn, relative, path):
    """Remember the file as it was before the first change in this turn."""
    from ..ai_models import AIFileChange
    if turn is None or AIFileChange.objects.filter(turn=turn, path=relative).exists():
        return
    previous = None
    if os.path.isfile(path):
        with open(path, encoding='utf-8', errors='replace') as f:
            previous = f.read()
    AIFileChange.objects.create(turn=turn, path=relative, previous_content=previous)


def revert_turns(instance, user, from_turn):
    """
    Undo the file changes of from_turn and of every later turn (newest first), then queue an
    upgrade of the modules that still exist. Returns a summary.
    """
    from django.utils import timezone
    from ..ai_models import AIFileChange
    from ..task_models import Task
    from ..tasks import enqueue

    changes = AIFileChange.objects.filter(
        turn__instance=instance, turn__id__gte=from_turn.id, reverted_at__isnull=True,
    ).order_by('-turn_id', '-id')
    restored, touched_modules = [], set()
    for change in changes:
        _, path = _safe_path(instance, change.path)
        if change.previous_content is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(change.previous_content)
        restored.append(change.path)
        touched_modules.add(change.path.split('/')[0])
        change.reverted_at = timezone.now()
        change.save(update_fields=['reverted_at'])
    if not restored:
        return 'No había cambios que deshacer'
    upgraded, gone = [], []
    for module in sorted(touched_modules):
        module_dir = os.path.join(addons_dir(instance), module)
        if _read_manifest(module_dir) is not None:
            enqueue(Task.Kind.AI_MODULE, instance, user, module=module, upgrade=True)
            upgraded.append(module)
        else:
            gone.append(module)
    summary = f"Restaurados {len(set(restored))} archivos"
    if upgraded:
        summary += f"; actualización en cola de: {', '.join(upgraded)}"
    if gone:
        summary += (f"; {', '.join(gone)} ya no existe en addons: si llegó a instalarse, desinstálalo desde Aplicaciones en Odoo")
    return summary


def run_tool(instance, user, name, arguments, turn=None):
    """Execute one tool call; returns a short text result for the model."""
    from ..ai_models import AIFileChange
    from ..task_models import Task
    from ..tasks import enqueue

    os.makedirs(addons_dir(instance), exist_ok=True)
    try:
        if name == 'list_files':
            root, base = _safe_path(instance, arguments.get('path', ''))
            files = []
            for current, dirs, names in os.walk(base):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                for file_name in sorted(names):
                    files.append(os.path.relpath(os.path.join(current, file_name), root))
                if len(files) > 500:
                    break
            return '\n'.join(files[:500]) or '(vacío)'
        if name == 'read_file':
            _, path = _safe_path(instance, arguments['path'])
            if os.path.getsize(path) > MAX_FILE_BYTES:
                return 'Error: archivo demasiado grande para leerlo'
            with open(path, encoding='utf-8', errors='replace') as f:
                return f.read()
        if name == 'write_file':
            _, path = _safe_path(instance, arguments['path'], write=True)
            content = arguments.get('content', '')
            if len(content.encode('utf-8')) > MAX_FILE_BYTES:
                return 'Error: contenido demasiado grande'
            _snapshot(turn, arguments['path'], path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f'Escrito {arguments["path"]} ({len(content)} caracteres)'
        if name == 'delete_file':
            _, path = _safe_path(instance, arguments['path'], write=True)
            if not os.path.isfile(path):
                return 'Error: el archivo no existe'
            _snapshot(turn, arguments['path'], path)
            os.remove(path)
            return f'Eliminado {arguments["path"]}'
        if name == 'undo_last_change':
            previous = (AIFileChange.objects.filter(turn__instance=instance, reverted_at__isnull=True)
                        .exclude(turn=turn).order_by('-turn_id').first())
            if previous is None:
                return 'No hay cambios anteriores que deshacer'
            return revert_turns(instance, user, previous.turn)
        if name == 'install_module':
            module = arguments['module'].strip()
            if not module.replace('_', '').isalnum():
                return 'Error: nombre de módulo inválido'
            enqueue(Task.Kind.AI_MODULE, instance, user, module=module, upgrade=bool(arguments.get('upgrade')))
            return f'Instalación de {module} en cola. El resultado aparecerá en las tareas de la instancia.'
        return f'Error: herramienta desconocida {name}'
    except FileNotFoundError:
        return 'Error: el archivo no existe'
    except (ValueError, KeyError, OSError) as e:
        return f'Error: {e}'


def system_prompt(instance, config):
    prompt = (
        f"Eres un desarrollador experto de Odoo {instance.odoo_version}. Trabajas sobre la instancia "
        f"«{instance.name}»{' (base de datos ' + instance.database_name + ')' if instance.database_name else ''}. "
        "Tus herramientas leen y escriben en su carpeta de addons, montada en Odoo en /mnt/extra-addons. "
        "Los repositorios extra están en las rutas repos/<repo>/... y son de solo lectura.\n"
        "- Si el usuario etiqueta módulos con @nombre, céntrate en ellos: modifica directamente los de addons; "
        "para añadir funciones a uno de un repositorio, crea un módulo nuevo en addons que dependa de él y herede sus modelos y vistas.\n"
        "- Para cambiar Odoo crea o modifica módulos; nunca edites el núcleo de Odoo.\n"
        f"- Módulos completos: __init__.py, __manifest__.py (version '{instance.odoo_version}.1.0.0', depends, data), "
        "models, views XML y security/ir.model.access.csv cuando crees modelos.\n"
        f"- Sigue las convenciones de Odoo {instance.odoo_version} (sintaxis de vistas y campos de esa versión).\n"
        "- Antes de modificar algo existente, léelo con las herramientas.\n"
        "- Cuando termines de escribir, instala (o actualiza si ya existía) el módulo con install_module.\n"
        "- Si el usuario pide volver atrás o deshacer, usa undo_last_change.\n"
        "- Responde en el idioma del usuario, de forma breve: qué hiciste y cómo probarlo."
    )
    if instance.github_repo:
        prompt += "\n- La carpeta es un checkout de GitHub: avisa de que los cambios no se suben al repositorio automáticamente."
    if config.ai_instructions:
        prompt += f"\n\nInstrucciones del administrador:\n{config.ai_instructions}"
    return prompt


def ask(instance, user, text, modules=()):
    """Add the user's message, run the model with tools until it answers. Returns the new messages."""
    from ..ai_models import AIMessage

    config = get_ai_config()
    if config is None:
        raise AIError('El asistente de IA no está configurado (Settings → IA)')

    context = tagged_modules_context(instance, modules)
    if context:
        # Kept in the stored message so later turns still know what was tagged
        text = f"{text}\n\n[Módulos etiquetados]\n" + '\n'.join(context)
    user_message = AIMessage.objects.create(instance=instance, user=user, role=AIMessage.Role.USER, content=text)
    new_messages = [user_message]
    history = [{'role': 'system', 'content': system_prompt(instance, config)}]
    history += [m.as_openai() for m in instance.ai_messages.all()]

    for _ in range(MAX_TOOL_ROUNDS):
        reply = chat(config, history, tools=TOOLS)
        tool_calls = reply.get('tool_calls') or []
        assistant = AIMessage.objects.create(
            instance=instance, user=user, role=AIMessage.Role.ASSISTANT,
            content=reply.get('content') or '', tool_calls=tool_calls or None, turn=user_message,
        )
        new_messages.append(assistant)
        history.append(assistant.as_openai())
        if not tool_calls:
            return new_messages
        for call in tool_calls:
            try:
                arguments = json.loads(call['function'].get('arguments') or '{}')
            except ValueError:
                arguments = {}
            result = run_tool(instance, user, call['function']['name'], arguments, turn=user_message)
            tool_message = AIMessage.objects.create(
                instance=instance, user=user, role=AIMessage.Role.TOOL, content=result[:20000], tool_call_id=call['id'],
                turn=user_message,
            )
            new_messages.append(tool_message)
            history.append(tool_message.as_openai())

    new_messages.append(AIMessage.objects.create(
        instance=instance, user=user, role=AIMessage.Role.ASSISTANT, turn=user_message,
        content='He alcanzado el límite de pasos para esta petición. Revisa lo hecho y pídeme que continúe.',
    ))
    return new_messages
