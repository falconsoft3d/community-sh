"""Community SH version. Bump it with every change and add an entry to CHANGELOG (newest first)."""

VERSION = '2.0.0'

CHANGELOG = [
    {
        'version': '2.0.0',
        'date': '2026-10-28',
        'notes': [
            'Proyectos: cada instancia pertenece a un proyecto y se muestra como proyecto / instancia',
            'Clientes: usuarios que ven y operan las instancias de sus proyectos',
            'Menú Backups con todos los respaldos y menú Docker (contenedores, imágenes, volúmenes, redes)',
            'Despliegues, backups y restauraciones en segundo plano con un worker (sustituye a cron)',
            'Métricas en tiempo real; modo claro y oscuro; nueva landing',
            'Odoo 20.0; imágenes antiguas (10-15) funcionan en servidores ARM mediante emulación',
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
