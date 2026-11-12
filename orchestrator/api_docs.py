"""
REST API documentation: one list of endpoints for the table in Settings → API and for the Markdown file
handed to an AI (token + documentation). Add new endpoints here and both stay current.
"""
from django.utils import timezone

# (method, path, what it does)
API_ENDPOINTS = [
    ('GET', '/api/projects/', 'Proyectos que puedes ver'),
    ('POST', '/api/projects/', 'Crear proyecto (name, description; también color y tag_names)'),
    ('PATCH', '/api/projects/{id}/', 'Editar un proyecto; también el modo test: trial_enabled, trial_slug, trial_days, '
                                     'trial_target_project, trial_message, trial_max_active'),
    ('GET', '/api/instances/', 'Instancias (estado, versión, proyecto, URL)'),
    ('POST', '/api/instances/', 'Crear y desplegar instancia (name, odoo_version, project; opcionales github_repo, github_branch, '
                                'database_name, custom_domain, description); devuelve task_id'),
    ('GET · PATCH', '/api/instances/{id}/', 'Ver o editar una instancia (description, github_branch, auto_update, memory_limit_mb: tope de RAM en MB, 0 sin límite, '
                                            'env_vars: NOMBRE=valor por línea, se aplican en el próximo despliegue)'),
    ('POST', '/api/instances/{id}/deploy/', 'Desplegar (devuelve task_id)'),
    ('POST', '/api/instances/{id}/restart/', 'Reiniciar'),
    ('POST', '/api/instances/{id}/stop/', 'Detener'),
    ('POST', '/api/instances/{id}/backup/', 'Crear backup (include_filestore)'),
    ('POST', '/api/instances/{id}/duplicate/', 'Duplicar (new_name)'),
    ('POST', '/api/instances/{id}/create-database/', 'Crear una base de datos (name, password opcional, lang como es_ES, demo); '
                                                      'devuelve task_id, usuario y contraseña del admin'),
    ('POST', '/api/instances/{id}/reset-admin-password/', 'Nueva contraseña para el administrador de Odoo (password opcional: '
                                                           'sin ella se genera); devuelve task_id y la contraseña, y la ficha la '
                                                           'muestra al terminar'),
    ('POST', '/api/instances/{id}/install-module/', 'Instalar o actualizar un módulo en todas sus bases (module, upgrade), '
                                                     'p. ej. community_sh_theme; devuelve task_id'),
    ('GET · POST', '/api/instances/{id}/repositories/', 'Repositorios de módulos extra (OCA, enterprise…); POST añade uno '
                                                         '(url HTTPS, branch). Se aplica en el próximo despliegue'),
    ('DELETE', '/api/instances/{id}/repositories/{repo_id}/', 'Quitar un repositorio de módulos extra (se aplica en el próximo despliegue)'),
    ('DELETE', '/api/instances/{id}/', 'Eliminar instancia'),
    ('GET', '/api/backups/?instance=nombre', 'Backups'),
    ('GET', '/api/backups/{id}/download/', 'Descargar ZIP'),
    ('POST', '/api/backups/{id}/restore/', 'Restaurar en su instancia'),
    ('GET', '/api/containers/', 'Contenedores Docker (estado, imagen, URL)'),
    ('POST', '/api/containers/', 'Crear contenedor: desde una imagen (name, image, container_port) o construido desde un '
                                 'repositorio (git_repo, git_branch, dockerfile; devuelve task_id). Tiene https://nombre.dominio'),
    ('POST', '/api/containers/{id}/start/ · stop/ · restart/', 'Arrancar, detener o recrear'),
    ('POST', '/api/containers/{id}/build/', 'Volver a construir desde el repositorio (task_id)'),
    ('GET', '/api/containers/{id}/logs/?tail=200', 'Logs del contenedor'),
    ('DELETE', '/api/containers/{id}/', 'Eliminar contenedor'),
    ('GET', '/api/tasks/', 'Tus tareas en segundo plano, las más recientes primero'),
    ('GET', '/api/tasks/{id}/', 'Estado de una tarea: status, progreso, paso en curso, resultado y log'),
    ('GET', '/api/public/demos/{url}/', 'Pública, sin token y con CORS: instancias que se pueden probar en un proyecto en modo '
                                        'test (nombre, versión, descripción), su texto y sus días'),
    ('GET', '/api/public/demos/{url}/captcha/', 'Pública: una suma nueva para pedir una demo ({question, token})'),
    ('POST', '/api/public/demos/{url}/', 'Pública (CORS): pedir una demo desde tu web: instance, name, email, company, job_title, '
                                         'phone, country, captcha_token y captcha_answer. Con la clave de API del proyecto '
                                         '(Authorization: Bearer csh_demo_…, se genera en su tarjeta «Modo test») no hace falta '
                                         'captcha. Devuelve status_page y status_api'),
    ('GET', '/{url}/demo/{token}/?format=json', 'Estado de una demo: progreso, paso y, al terminar, dirección, usuario, '
                                                'contraseña y días que le quedan'),
    ('GET · POST', '/api/demos/', 'Demos de tus proyectos; POST pide una (project, instance, name, email, company, job_title, '
                                  'phone, country) con los mismos límites, sin captcha'),
    ('GET', '/api/demos/{id}/', 'Una demo: estado, progreso, credenciales, vencimiento y días hasta detenerse y eliminarse'),
    ('GET', '/api/contacts/?q=', 'Contactos: quienes pidieron una demo (nombre, email, empresa, cargo, teléfono, país, notas y sus demos)'),
    ('GET · PATCH', '/api/settings/', 'Administradores: correo saliente (smtp_*; la contraseña solo se escribe) y límites de demos '
                                      '(trial_max_per_day, trial_max_active_total)'),
    ('POST', '/api/settings/test-email/', 'Administradores: enviar un correo de prueba ({to})'),
    ('GET · POST', '/api/todos/', 'Tareas del menú Todo'),
    ('PATCH', '/api/todos/{id}/', 'Cambiar estado (status, completion_note)'),
]


def _odoo_versions():
    from .models import Instance
    return [value for value, _ in Instance._meta.get_field('odoo_version').choices]


def api_markdown(user, base_url, token, token_name, mcp_url=''):
    """Markdown for an AI assistant: who it acts as, the token and how to use every endpoint."""
    api = base_url.rstrip('/')               # https://host/api
    host = api[:-len('/api')] if api.endswith('/api') else api
    versions = ', '.join(_odoo_versions())
    rows = '\n'.join(f'| {method} | `{path}` | {text.replace("|", "/")} |' for method, path, text in API_ENDPOINTS)
    role = 'administrador (ve y gestiona todo)' if user.is_superuser else 'usuario (sus proyectos e instancias)'
    mcp = (f'''
## MCP (Claude)

El mismo token sirve para el servidor MCP en `{mcp_url}` (transporte HTTP, cabecera `Authorization: Bearer {token}`).
Por ejemplo, en Claude Code:

```bash
claude mcp add --transport http community-sh {mcp_url} --header "Authorization: Bearer {token}"
```
''' if mcp_url else '')
    return f'''# Community SH — API REST

Documento generado el {timezone.localtime():%d/%m/%Y %H:%M} para dárselo a un asistente de IA.
Contiene un token personal: trátalo como una contraseña y no lo publiques.

## Acceso

- **URL base:** `{api}/`
- **Token:** `{token}` (nombre «{token_name}»)
- **Cabecera en cada llamada:** `Authorization: Bearer {token}`
- **Actúa como:** `{user.get_username()}`, {role}. Cada llamada tiene exactamente los permisos de ese usuario.
- **Revocarlo:** {host}/settings/#api → Tus tokens → Revocar.

## Cómo trabajar con esta API

- Peticiones y respuestas en JSON (`Content-Type: application/json`). Las listas devuelven un array, sin paginación.
- Las operaciones largas (crear o desplegar una instancia, backup, restaurar, duplicar, crear una base de datos,
  instalar un módulo, construir un contenedor) responden `202` con `task_id`: consulta `GET {api}/tasks/{{task_id}}/`
  cada pocos segundos hasta que `status` sea `done` o `failed`; `result` y `log` explican qué pasó.
- Errores: `400` con el campo y el motivo, `401` token inválido, revocado o caducado, `403` sin permiso (p. ej. clientes
  de un proyecto, que no gestionan sus instancias, o un token de solo lectura en un POST/PATCH/DELETE), `404` no existe o
  no es tuyo, `429` demasiadas peticiones (600 por minuto y usuario; espera los segundos de `Retry-After`).
- Versiones de Odoo válidas (`odoo_version`): {versions}.
- Cada instancia queda en su propia URL (campo `url`) con HTTPS.

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
{rows}

## Ejemplos

```bash
TOKEN="{token}"
API="{api}"

# Proyectos e instancias
curl -H "Authorization: Bearer $TOKEN" $API/projects/
curl -H "Authorization: Bearer $TOKEN" $API/instances/

# Crear y desplegar una instancia Odoo 19 en el proyecto 3 → {{"id": 42, ..., "task_id": 345}}
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
     -d '{{"name": "acme-prod", "odoo_version": "19.0", "project": 3}}' $API/instances/

# Esperar a la tarea
curl -H "Authorization: Bearer $TOKEN" $API/tasks/345/

# Crear su base de datos en español (devuelve usuario y contraseña del admin) e instalar el tema
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
     -d '{{"name": "acme", "lang": "es_ES"}}' $API/instances/42/create-database/
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
     -d '{{"module": "community_sh_theme"}}' $API/instances/42/install-module/

# Backup con filestore
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
     -d '{{"include_filestore": true}}' $API/instances/42/backup/
```

## Receta: instancia nueva lista para usar

1. `POST /api/instances/` con `name`, `odoo_version` y `project` → guarda `id` y `task_id`.
2. Espera a que la tarea termine (`done`).
3. `POST /api/instances/{{id}}/create-database/` → espera su tarea; la respuesta trae el usuario y la contraseña del administrador.
4. Opcional: `POST /api/instances/{{id}}/install-module/` con los módulos que necesites (uno por llamada).
5. Abre la `url` de la instancia.
{mcp}
## Navegable

Con sesión iniciada en el panel, {api}/ muestra la API navegable de Django REST framework.
'''
