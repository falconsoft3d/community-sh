"""
Community SH version: bump the patch number (1.0.1 -> 1.0.2 ...) with every commit or improvement,
and document it here (shown in About) and in CHANGELOG.md, newest first.
"""

VERSION = '1.0.4'

CHANGELOG = [
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
