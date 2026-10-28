"""
Community SH version: bump the patch number (1.0.1 -> 1.0.2 ...) with every commit or improvement,
and document it here (shown in About) and in CHANGELOG.md, newest first.
"""

VERSION = '1.0.15'

CHANGELOG = [
    {
        'version': '1.0.15',
        'date': '2026-10-28',
        'notes': [
            "Importar backups del gestor de bases de datos de Odoo (.zip con dump.sql y filestore) y volcados .dump, además de los del panel",
            "Menú Backups → «Importar un backup y crear una instancia» (detecta la versión de Odoo y la base) y «Restaurar desde un archivo» en cada instancia",
            "Backups probados en las 11 versiones (10 a 20): crear, exportar, importar, duplicar y crear instancia desde backup",
            "Si la IA no consigue instalar un módulo, la base queda como estaba (antes Odoo dejaba de ejecutar sus tareas programadas)",
        ],
    },
    {
        'version': '1.0.14',
        'date': '2026-10-28',
        'notes': [
            "Favicon propio en el panel y la página principal",
        ],
    },
    {
        'version': '1.0.13',
        'date': '2026-10-28',
        'notes': [
            "API REST completa con tokens personales (Bearer): proyectos, instancias (desplegar, reiniciar, detener, backup, duplicar), backups (descargar, restaurar), tareas y Todo",
            "Settings → API: URL base, autenticación, ejemplos con curl y tabla de endpoints",
        ],
    },
    {
        'version': '1.0.12',
        'date': '2026-10-28',
        'notes': [
            "Metrics: gráficas del uso de CPU y RAM del servidor en las últimas 24 horas, 7 días, 30 días y 12 meses (media y pico)",
            "El worker guarda una muestra por minuto (2 días) y resúmenes por hora (120 días) y por día (sin límite)",
        ],
    },
    {
        'version': '1.0.11',
        'date': '2026-10-28',
        'notes': [
            "Menú Todo: tareas del equipo (por hacer, en curso, completadas) con nota de lo realizado y la versión en que se completó",
            "Claude puede listar, añadir y completar tareas de Todo desde el servidor MCP",
        ],
    },
    {
        'version': '1.0.10',
        'date': '2026-10-28',
        'notes': [
            "Restaurar un backup ya funciona con Odoo en marcha: se detiene Odoo y se cierran sus conexiones antes de recrear la base (antes el borrado fallaba en silencio y la restauración no hacía nada)",
            "La restauración informa del error si no puede borrar o crear la base; el filestore restaurado queda con los permisos correctos",
        ],
    },
    {
        'version': '1.0.9',
        'date': '2026-10-28',
        'notes': [
            "Eliminar un proyecto con todo: sus instancias, contenedores, bases de datos, filestores, workspaces y backups (confirmación escribiendo el nombre; lo ejecuta el worker)",
            "Al borrar una instancia también se borran los archivos de sus backups (antes quedaban huérfanos en disco)",
        ],
    },
    {
        'version': '1.0.8',
        'date': '2026-10-28',
        'notes': [
            "Novedades de la página principal paginadas (3 versiones por página)",
        ],
    },
    {
        'version': '1.0.7',
        'date': '2026-10-28',
        'notes': [
            "Chat de IA: botón «Deshacer estos cambios» en cada respuesta que modificó archivos; restaura los archivos (también los de peticiones posteriores) y actualiza los módulos afectados",
            "La IA también puede volver atrás cuando se lo pides (herramienta undo_last_change)",
        ],
    },
    {
        'version': '1.0.6',
        'date': '2026-10-28',
        'notes': [
            'Chat de IA: etiqueta módulos propios con @ (autocompletado) para que la IA trabaje sobre ellos',
            'La IA lee los módulos de los repositorios extra (solo lectura) y los extiende con un módulo nuevo en addons',
        ],
    },
    {
        'version': '1.0.5',
        'date': '2026-10-28',
        'notes': [
            'Menú lateral minimizable: deja solo los iconos (con el nombre al pasar el ratón) y recuerda la preferencia en el navegador',
        ],
    },
    {
        'version': '1.0.4',
        'date': '2026-10-28',
        'notes': [
            'Servidor MCP para Claude (Claude Code, Claude Desktop) en /mcp/: listar proyectos e instancias, ver logs, desplegar, reiniciar, detener, crear y listar backups y seguir tareas',
            'Settings → MCP (Claude): activación por el administrador, tokens personales (se guardan cifrados con hash, se muestran una sola vez) e instrucciones de conexión',
            'Claude actúa con los permisos del usuario del token: un cliente solo ve y opera sus proyectos',
        ],
    },
    {
        'version': '1.0.3',
        'date': '2026-10-28',
        'notes': [
            'Documentación: configurar el DNS del dominio antes de instalar (README, guía de despliegue y landing)',
            'El instalador avisa del registro DNS necesario y comprueba que el dominio apunta al servidor antes de seguir',
            'El instalador ya lee el dominio con «curl … | sudo bash» (antes la pregunta leía el propio script)',
        ],
    },
    {
        'version': '1.0.2',
        'date': '2026-10-28',
        'notes': [
            'Todas las versiones de Odoo (10 a 20) se despliegan: probadas una a una creando base de datos e iniciando sesión',
            'Odoo 20: PostgreSQL 16 y escucha en todas las interfaces (antes solo 127.0.0.1)',
            'PostgreSQL según la versión de Odoo; una base vacía con versión incompatible se recrea sola',
            'Odoo 10-15 en Mac/servidores ARM: descarga automática de la imagen amd64 (emulada)',
            'odoo.conf se monta como carpeta (evita fallos de montaje en Docker Desktop) y la carpeta de addons se monta siempre',
            'Configuración de IA (ChatGPT) en Settings → IA, con prueba de conexión y lista de modelos',
            'Asistente de IA en cada instancia: crea y modifica módulos en sus addons y los instala en segundo plano',
            'Varios repositorios de GitHub por instancia (se clonan y se añaden al addons_path; los privados usan el token del dueño)',
            'Odoo 10: usa odoo.conf (antes arrancaba con la configuración por defecto y la master password no funcionaba)',
            'Blog accesible con sesión iniciada y dos artículos nuevos; sección Novedades en la página principal',
            'Barra superior y menú lateral fijos al hacer scroll',
        ],
    },
    {
        'version': '1.0.1',
        'date': '2026-10-28',
        'notes': [
            'Proyectos: cada instancia pertenece a un proyecto y se muestra como proyecto / instancia',
            'Clientes: el cliente de un proyecto es un usuario; con la casilla "Cliente" solo ve y opera sus proyectos',
            'Menús Backups (todos los respaldos) y Docker (contenedores, imágenes, volúmenes, redes)',
            'Despliegues, backups y restauraciones en segundo plano con un worker (sustituye a cron)',
            'Métricas en tiempo real; modo claro y oscuro; nueva landing; idiomas español e inglés',
            'Odoo 20.0; PostgreSQL adecuado a cada versión de Odoo; imágenes antiguas (10-15) emuladas en servidores ARM',
            'Seguridad: API con login, dueños por instancia, 2FA obligatorio real, bloqueo por intentos, contraseña maestra por instancia',
            'Datos: el filestore ya no se pierde al redesplegar; Postgres vía DATABASE_URL con migración automática desde SQLite',
        ],
    },
    {
        'version': '1.0.0',
        'date': '2025-12-31',
        'notes': [
            'Gestión completa de instancias Odoo (crear, desplegar, detener, reiniciar, eliminar)',
            'Orquestación de contenedores Docker con PostgreSQL 13',
            'Soporte multi-versión de Odoo (10.0 - 19.0)',
            'Integración con repositorios GitHub para módulos personalizados',
            'Sistema completo de backup y restauración',
            'Crear nuevas instancias desde backups existentes',
            'Logs en tiempo real y acceso a consola de contenedores',
            "Gestión de certificados SSL/TLS con Let's Encrypt",
            'Configuración de dominios personalizados',
            'Monitoreo de recursos y métricas de contenedores',
            'Autenticación de usuarios y gestión de perfiles',
            'Interfaz con pestañas para detalles de instancia',
            'Sistema de nomenclatura automática para instancias desde backup (name-copy-N)',
            'Detección automática de bases de datos',
            'Respaldo de filestore desde contenedores Docker',
        ],
    },
]
