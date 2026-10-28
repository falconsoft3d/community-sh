"""
AI assistant for an Odoo instance: ChatGPT with tools that edit the instance's addons
folder (mounted at /mnt/extra-addons) and install or upgrade modules through the worker.
"""
import json
import os

from django.conf import settings

from .ai import AIError, chat, get_ai_config

# Long requests run in the AI worker, step by step, so they get many rounds
MAX_TOOL_ROUNDS = 60
MAX_FILE_BYTES = 200 * 1024
PLAN_STATUSES = ('pending', 'in_progress', 'done')
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
        'name': 'odoo_model_info',
        'description': "Fields and main views (with their xml_id) of a model in this instance's running Odoo. Use it "
                       'before adding fields or columns, to inherit the right view and not duplicate fields.',
        'parameters': {'type': 'object', 'properties': {
            'model': {'type': 'string', 'description': 'Technical model name, e.g. "res.partner"'},
            'db': {'type': 'string', 'description': 'Database (optional; the instance one by default)'},
        }, 'required': ['model']},
    }},
    {'type': 'function', 'function': {
        'name': 'update_plan',
        'description': 'Keep the checklist of a request with several steps (long requests, attached documents with many tasks). '
                       'One entry per task of the request or document (each numbered step, each change asked for, plus '
                       'installing or upgrading at the end); never merge them into one. Send the whole list each time: '
                       'first with every step pending, then marking the one you work on as in_progress and finished ones '
                       'as done. The user sees it live.',
        'parameters': {'type': 'object', 'properties': {'steps': {'type': 'array', 'items': {
            'type': 'object', 'properties': {
                'step': {'type': 'string', 'description': 'Short description of the step'},
                'status': {'type': 'string', 'enum': list(PLAN_STATUSES)},
            }, 'required': ['step', 'status']}}}, 'required': ['steps']},
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
    # Models often prefix the folder itself ("addons/my_mod/..." or Odoo's mount point):
    # that would nest the module where Odoo can't find it
    for prefix in ('/mnt/extra-addons/', 'addons/', './'):
        if relative.startswith(prefix):
            relative = relative[len(prefix):]
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


def check_source(instance, path, content):
    """
    Catch what makes Odoo silently skip a module or fail to load it: a manifest that isn't a
    Python literal (e.g. JSON's true/false), Python syntax errors and malformed XML.
    """
    import ast
    from xml.etree import ElementTree
    name = os.path.basename(path)
    if name in ('__manifest__.py', '__openerp__.py'):
        try:
            manifest = ast.literal_eval(content)
        except (ValueError, SyntaxError) as e:
            return f'el manifiesto debe ser un diccionario literal de Python (True/False, no true/false): {e}'
        if not isinstance(manifest, dict):
            return 'el manifiesto debe ser un diccionario'
        return None
    if name.endswith('.py') and int(float(instance.odoo_version)) >= 11:  # 8-10 run Python 2
        try:
            compile(content, path, 'exec')
        except SyntaxError as e:
            return f'error de sintaxis de Python en la línea {e.lineno}: {e.msg}'
    if name.endswith('.xml'):
        try:
            ElementTree.fromstring(content.encode('utf-8'))
        except ElementTree.ParseError as e:
            return f'XML mal formado: {e}'
    return None


INSTALL_WAIT_SECONDS = 900


def install_error_summary(output, limit=1500):
    """The lines of an Odoo install log that say what went wrong, without the traceback frames."""
    keep = [line.strip() for line in output.splitlines()
            if any(word in line for word in ('Error', 'error', 'does not exist', 'no existe', 'Field', 'Invalid', 'invalid', 'line '))
            and not line.lstrip().startswith(('File "', 'raise ', 'return '))]
    lines, size = [], 0
    for line in reversed(list(dict.fromkeys(keep)) or output.splitlines()):
        if size + len(line) > limit and lines:
            break
        lines.insert(0, line[-limit:])
        size += len(line) + 1
    return '\n'.join(lines)


def _wait_for_task(task, timeout=INSTALL_WAIT_SECONDS):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task.refresh_from_db()
        if task.status in (task.Status.DONE, task.Status.FAILED):
            return task
        time.sleep(3)
    return task


def run_tool(instance, user, name, arguments, turn=None, wait_installs=False):
    """Execute one tool call; returns a short text result for the model."""
    from ..ai_models import AIFileChange
    from ..task_models import Task
    from ..tasks import enqueue

    os.makedirs(addons_dir(instance), exist_ok=True)
    try:
        if name == 'update_plan':
            if turn is None:
                return 'Error: no hay una petición en curso'
            steps = [{'step': str(s.get('step', ''))[:300], 'status': s.get('status') if s.get('status') in PLAN_STATUSES else 'pending'}
                     for s in (arguments.get('steps') or [])[:50] if isinstance(s, dict)]
            turn.plan = steps
            turn.save(update_fields=['plan'])
            done = sum(1 for s in steps if s['status'] == 'done')
            return f'Plan actualizado: {done}/{len(steps)} pasos hechos'
        if name == 'odoo_model_info':
            from .odoo_bridge import model_info
            try:
                return model_info(instance, str(arguments['model']), arguments.get('db'))
            except Exception as e:
                return f'Error: no se pudo consultar Odoo ({e}). ¿Está la instancia en marcha?'
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
            problem = check_source(instance, arguments['path'], content)
            if problem:
                return f'Error: no escrito, {problem}. Corrígelo y vuelve a escribirlo.'
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
            task = enqueue(Task.Kind.AI_MODULE, instance, user, module=module, upgrade=bool(arguments.get('upgrade')))
            if not wait_installs:
                return f'Instalación de {module} en cola. El resultado aparecerá en las tareas de la instancia.'
            # In the AI worker: wait for the main worker, so the model can fix what failed
            task = _wait_for_task(task)
            if task.status == Task.Status.DONE:
                return f'Instalado: {task.result}'
            if task.status == Task.Status.FAILED:
                return ('Error al instalar (la base de datos queda como estaba). Corrige los archivos y vuelve a '
                        f'instalar:\n{install_error_summary(task.result)}')
            return f'La instalación de {module} sigue en cola; revisa las tareas de la instancia.'
        return f'Error: herramienta desconocida {name}'
    except FileNotFoundError:
        return 'Error: el archivo no existe'
    except (ValueError, KeyError, OSError) as e:
        return f'Error: {e}'


def system_prompt(instance, config):
    # Odoo 8-9 read the manifest from __openerp__.py
    manifest = '__openerp__.py' if int(float(instance.odoo_version)) <= 9 else '__manifest__.py'
    prompt = (
        f"Eres un desarrollador experto de Odoo {instance.odoo_version}. Trabajas sobre la instancia "
        f"«{instance.name}»{' (base de datos ' + instance.database_name + ')' if instance.database_name else ''}. "
        "Tus herramientas leen y escriben en su carpeta de addons, montada en Odoo en /mnt/extra-addons. "
        "Los repositorios extra están en las rutas repos/<repo>/... y son de solo lectura.\n"
        "- Si el usuario etiqueta módulos con @nombre, céntrate en ellos: modifica directamente los de addons; "
        "para añadir funciones a uno de un repositorio, crea un módulo nuevo en addons que dependa de él y herede sus modelos y vistas.\n"
        "- Para cambiar Odoo crea o modifica módulos; nunca edites el núcleo de Odoo.\n"
        f"- Módulos completos: __init__.py, {manifest} (version '{instance.odoo_version}.1.0.0', depends, data), "
        "models, views XML y security/ir.model.access.csv cuando crees modelos.\n"
        f"- Sigue las convenciones de Odoo {instance.odoo_version} (sintaxis de vistas y campos de esa versión).\n"
        "- Antes de modificar algo existente, léelo con las herramientas.\n"
        "- Cuando termines de escribir, instala (o actualiza si ya existía) el módulo con install_module y espera su "
        "resultado: si falla, lee el error, corrige los archivos y vuelve a instalar hasta que funcione. Si falla por "
        "una dependencia que no está instalada, depende de un módulo que sí lo esté (por ejemplo base o mail) en "
        "vez de preguntar.\n"
        "- Si el usuario pide volver atrás o deshacer, usa undo_last_change.\n"
        "- Obligatorio: si la petición tiene más de dos tareas o trae archivos adjuntos (PDF, imágenes), tu PRIMERA "
        "llamada es update_plan con todos los pasos pendientes. Después trabaja paso a paso: marca el paso en curso, "
        "hazlo y márcalo hecho con otra llamada a update_plan antes de pasar al siguiente. No te detengas hasta "
        "terminarlos todos salvo que necesites algo del usuario.\n"
        "- Responde en el idioma del usuario, de forma breve: qué hiciste y cómo probarlo."
    )
    if instance.github_repo:
        prompt += "\n- La carpeta es un checkout de GitHub: avisa de que los cambios no se suben al repositorio automáticamente."
    if config.ai_instructions:
        prompt += f"\n\nInstrucciones del administrador:\n{config.ai_instructions}"
    return prompt


def start_turn(instance, user, text, modules=(), files=()):
    """Store the user's message (with the tagged-modules context and attachments). Returns it."""
    from ..ai_models import AIAttachment, AIMessage

    context = tagged_modules_context(instance, modules)
    if context:
        # Kept in the stored message so later turns still know what was tagged
        text = f"{text}\n\n[Módulos etiquetados]\n" + '\n'.join(context)
    user_message = AIMessage.objects.create(instance=instance, user=user, role=AIMessage.Role.USER, content=text)
    for upload in files:
        AIAttachment.objects.create(message=user_message, file=upload, name=os.path.basename(upload.name)[:255],
                                    content_type=attachment_type(upload.name), size=upload.size)
    return user_message


def attachment_type(name):
    """Content type the model gets for an attachment, or None if it isn't supported."""
    from ..ai_models import AIAttachment
    extension = os.path.splitext(name.lower())[1]
    images = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif'}
    if extension == '.pdf':
        return 'application/pdf'
    if extension in images:
        return images[extension]
    if extension in AIAttachment.TEXT_EXTENSIONS:
        return 'text/plain'
    return None


def clean_history(messages):
    """
    Drop tool calls left without their results (a turn interrupted by a worker restart):
    the API rejects a history where an assistant tool call isn't followed by its result.
    """
    answered = {m.get('tool_call_id') for m in messages if m['role'] == 'tool'}
    cleaned, kept_calls = [], set()
    for message in messages:
        if message['role'] == 'assistant' and message.get('tool_calls'):
            ids = {call['id'] for call in message['tool_calls']}
            if not ids <= answered:
                message = {'role': 'assistant', 'content': message.get('content') or ''}
                if not message['content']:
                    continue
            else:
                kept_calls |= ids
        if message['role'] == 'tool' and message.get('tool_call_id') not in kept_calls:
            continue
        cleaned.append(message)
    return cleaned


PLAN_TOOL_CHOICE = {'type': 'function', 'function': {'name': 'update_plan'}}


def plan_pending(user_message):
    return any(step['status'] != 'done' for step in user_message.plan or [])


def needs_plan(user_message):
    """Requests with attachments or several tasks start with a plan (models skip it if only asked to)."""
    import re
    text = user_message.content.split('\n\n[Módulos etiquetados]')[0]
    steps = re.findall(r'^\s*(?:\d+[.)-]|[-*•])\s+', text, re.M)
    return user_message.attachments.exists() or len(steps) >= 3 or len(text) > 600


def close_plan(config, history, user_message):
    """
    The model answered while its checklist still has open steps: ask it once for the real
    state of each step. Only the plan is updated; the answer the user sees stays the same.
    """
    messages = history + [{'role': 'user', 'content': 'Actualiza el plan con el estado real de cada paso.'}]
    try:
        reply = chat(config, messages, tools=TOOLS, tool_choice=PLAN_TOOL_CHOICE)
    except AIError:
        return
    for call in reply.get('tool_calls') or []:
        if call['function']['name'] == 'update_plan':
            try:
                arguments = json.loads(call['function'].get('arguments') or '{}')
            except ValueError:
                continue
            run_tool(user_message.instance, user_message.user, 'update_plan', arguments, turn=user_message)


def stop_key(turn_id):
    return f'ai-stop-{turn_id}'


def run_turn(user_message):
    """Run the model with tools until it answers (in the AI worker). Returns the new messages."""
    from django.core.cache import cache
    from ..ai_models import AIMessage

    instance, user = user_message.instance, user_message.user
    config = get_ai_config()
    if config is None:
        raise AIError('El asistente de IA no está configurado (Settings → IA)')
    history = [{'role': 'system', 'content': system_prompt(instance, config)}]
    history += clean_history([m.as_openai() for m in instance.ai_messages.prefetch_related('attachments')])
    new_messages = []

    def say(content):
        message = AIMessage.objects.create(instance=instance, user=user, role=AIMessage.Role.ASSISTANT, turn=user_message, content=content)
        new_messages.append(message)
        return new_messages

    plan_first = needs_plan(user_message)
    for round_number in range(MAX_TOOL_ROUNDS):
        if cache.get(stop_key(user_message.id)):
            cache.delete(stop_key(user_message.id))
            return say('Detenido a petición del usuario. Dime cómo seguir.')
        tool_choice = PLAN_TOOL_CHOICE if plan_first and round_number == 0 else None
        try:
            reply = chat(config, history, tools=TOOLS, tool_choice=tool_choice)
        except AIError as e:
            say(f'Error de la IA: {e}')
            raise
        tool_calls = reply.get('tool_calls') or []
        assistant = AIMessage.objects.create(
            instance=instance, user=user, role=AIMessage.Role.ASSISTANT,
            content=reply.get('content') or '', tool_calls=tool_calls or None, turn=user_message,
        )
        new_messages.append(assistant)
        history.append(assistant.as_openai())
        if not tool_calls:
            if plan_pending(user_message):
                close_plan(config, history, user_message)
            return new_messages
        for call in tool_calls:
            try:
                arguments = json.loads(call['function'].get('arguments') or '{}')
            except ValueError:
                arguments = {}
            result = run_tool(instance, user, call['function']['name'], arguments, turn=user_message, wait_installs=True)
            if call['function']['name'] != 'update_plan' and plan_pending(user_message):
                # Models tend to forget the checklist once they start working
                result += '\n(Actualiza el plan con update_plan: marca hecho lo terminado y en curso lo siguiente.)'
            tool_message = AIMessage.objects.create(
                instance=instance, user=user, role=AIMessage.Role.TOOL, content=result[:20000], tool_call_id=call['id'],
                turn=user_message,
            )
            new_messages.append(tool_message)
            history.append(tool_message.as_openai())

    return say('He alcanzado el límite de pasos para esta petición. Revisa lo hecho y pídeme que continúe.')
