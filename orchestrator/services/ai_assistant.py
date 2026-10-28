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
        'description': 'List files in the addons folder (or a subfolder of it). Paths are relative to the addons folder.',
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


def _safe_path(instance, relative):
    root = os.path.realpath(addons_dir(instance))
    target = os.path.realpath(os.path.join(root, relative or ''))
    if target != root and not target.startswith(root + os.sep):
        raise ValueError('La ruta debe estar dentro de la carpeta de addons')
    return root, target


def run_tool(instance, user, name, arguments):
    """Execute one tool call; returns a short text result for the model."""
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
            _, path = _safe_path(instance, arguments['path'])
            content = arguments.get('content', '')
            if len(content.encode('utf-8')) > MAX_FILE_BYTES:
                return 'Error: contenido demasiado grande'
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f'Escrito {arguments["path"]} ({len(content)} caracteres)'
        if name == 'delete_file':
            _, path = _safe_path(instance, arguments['path'])
            os.remove(path)
            return f'Eliminado {arguments["path"]}'
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
        "Tus herramientas leen y escriben en su carpeta de addons, montada en Odoo en /mnt/extra-addons.\n"
        "- Para cambiar Odoo crea o modifica módulos; nunca edites el núcleo de Odoo.\n"
        f"- Módulos completos: __init__.py, __manifest__.py (version '{instance.odoo_version}.1.0.0', depends, data), "
        "models, views XML y security/ir.model.access.csv cuando crees modelos.\n"
        f"- Sigue las convenciones de Odoo {instance.odoo_version} (sintaxis de vistas y campos de esa versión).\n"
        "- Antes de modificar algo existente, léelo con las herramientas.\n"
        "- Cuando termines de escribir, instala (o actualiza si ya existía) el módulo con install_module.\n"
        "- Responde en el idioma del usuario, de forma breve: qué hiciste y cómo probarlo."
    )
    if instance.github_repo:
        prompt += "\n- La carpeta es un checkout de GitHub: avisa de que los cambios no se suben al repositorio automáticamente."
    if config.ai_instructions:
        prompt += f"\n\nInstrucciones del administrador:\n{config.ai_instructions}"
    return prompt


def ask(instance, user, text):
    """Add the user's message, run the model with tools until it answers. Returns the new messages."""
    from ..ai_models import AIMessage

    config = get_ai_config()
    if config is None:
        raise AIError('El asistente de IA no está configurado (Settings → IA)')

    new_messages = [AIMessage.objects.create(instance=instance, user=user, role=AIMessage.Role.USER, content=text)]
    history = [{'role': 'system', 'content': system_prompt(instance, config)}]
    history += [m.as_openai() for m in instance.ai_messages.all()]

    for _ in range(MAX_TOOL_ROUNDS):
        reply = chat(config, history, tools=TOOLS)
        tool_calls = reply.get('tool_calls') or []
        assistant = AIMessage.objects.create(
            instance=instance, user=user, role=AIMessage.Role.ASSISTANT,
            content=reply.get('content') or '', tool_calls=tool_calls or None,
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
            result = run_tool(instance, user, call['function']['name'], arguments)
            tool_message = AIMessage.objects.create(
                instance=instance, user=user, role=AIMessage.Role.TOOL, content=result[:20000], tool_call_id=call['id'],
            )
            new_messages.append(tool_message)
            history.append(tool_message.as_openai())

    new_messages.append(AIMessage.objects.create(
        instance=instance, user=user, role=AIMessage.Role.ASSISTANT,
        content='He alcanzado el límite de pasos para esta petición. Revisa lo hecho y pídeme que continúe.',
    ))
    return new_messages
