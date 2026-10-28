"""
Community SH version: bump the patch number (1.0.1 -> 1.0.2 ...) with every commit or improvement,
and document it here (shown in About) and in CHANGELOG.md, newest first.
"""

VERSION = '1.0.30'

CHANGELOG = [
    {
        'version': '1.0.30',
        'date': '2026-10-28',
        'notes': [
            "GitHub: los tokens fine-grained (github_pat_) ya clonan repos privados; antes GitHub respondía 403 «Write access to repository not granted»",
            "Tema: pantalla de inicio clara con bandas diagonales, iconos con sombra suave, búsqueda al empezar a escribir y la versión de Odoo abajo a la izquierda",
        ],
    },
    {
        'version': '1.0.29',
        'date': '2026-10-28',
        'notes': [
            "Botón «Admin» (entrar como admin) también en la lista de instancias",
        ],
    },
    {
        'version': '1.0.28',
        'date': '2026-10-28',
        'notes': [
            "Tema: la barra superior de Odoo 18-20 ya no deja los menús de la app en morado; iconos de la pantalla de inicio menos redondeados",
        ],
    },
    {
        'version': '1.0.27',
        'date': '2026-10-28',
        'notes': [
            "Tema: al entrar en una app desde la pantalla de inicio ya no te devuelve a la cuadrícula (Odoo 18-20 abría la pantalla de inicio otra vez)",
        ],
    },
    {
        'version': '1.0.26',
        'date': '2026-10-28',
        'notes': [
            "Landing: sección «Mis proyectos» antes del pie, leída de TicketPro en el servidor (token en .env, caché de 15 minutos)",
            "Instalación: los workers ya no intentan descargar la imagen del panel de Docker Hub",
        ],
    },
    {
        'version': '1.0.25',
        'date': '2026-10-28',
        'notes': [
            "README con capturas de la app y la lista de funcionalidades al día",
        ],
    },
    {
        'version': '1.0.24',
        'date': '2026-10-28',
        'notes': [
            "Contadores en el menú lateral: proyectos, instancias, contenedores, Docker, tareas pendientes, backups y usuarios",
            "Todo: las tareas completadas se ocultan hasta pulsar «Hechas»",
            "En la landing, el botón «Ir al panel» muestra tu foto cuando has iniciado sesión",
            "Paginación de 20 filas en todas las listas (proyectos, instancias, backups, usuarios, contenedores, Todo y Docker), conservando los filtros",
        ],
    },
    {
        'version': '1.0.23',
        'date': '2026-10-28',
        'notes': [
            "Odoo 8 y 9: se despliegan, crean base de datos y pasan backup, exportar, importar, duplicar y crear desde backup",
            "Puertos fijos: Odoo se publica en un puerto explícito que no cambia al reiniciar el contenedor o el servidor, y el worker corrige cada minuto los enlaces de las instancias antiguas",
            "Chat y notificaciones de Odoo verificados en 8-20: longpolling (8-15) y websocket (16-20), también a través de Traefik",
            "IA: adjunta PDF, imágenes o archivos de texto; en peticiones largas arma un plan visible que va marcando paso a paso, se puede detener y corre en su propio worker (ai-worker)",
            "IA desde Odoo: escribe «/ia …» en el chatter de cualquier registro (Odoo 9-20) y la respuesta, con el resultado de la instalación, llega a ese chatter (módulo community_sh_ai, se instala solo)",
            "IA más fiable: consulta campos y vistas reales de Odoo, valida manifiestos, Python y XML antes de escribir, espera el resultado de la instalación y corrige los errores",
            "Migrar desde otro Odoo (8+) por XML-RPC a instancias Odoo 14+: contactos, categorías, productos y variantes, ventas, compras, facturas y pagos; se puede repetir sin duplicar",
            "Tema Community SH para Odoo 15-20: barra clara, formularios como tarjetas y pantalla de inicio con las apps en iconos (diseño propio, sin código de Enterprise)",
            "Arreglos: duplicar ya no falla si Postgres tarda en arrancar; módulos nuevos de la IA se reconocen en Odoo 8-10",
        ],
    },
    {
        'version': '1.0.22',
        'date': '2026-10-28',
        'notes': [
            "Landing: cabecera con una galaxia animada, cohetes que la cruzan y estrellas que deja el ratón (estática si el sistema pide reducir el movimiento)",
            "Landing rediseñada: más aire entre secciones, titular con más peso, mockup con profundidad, funcionalidades agrupadas en 4 pilares, sección oscura flotante con bordes suaves y pasos de instalación en azul unidos por una línea",
        ],
    },
    {
        'version': '1.0.21',
        'date': '2026-10-28',
        'notes': [
            "API: botón «Generar token» en la pestaña API de Configuración; el token nuevo se muestra una vez con botón de copiar y los ejemplos (curl, Claude) ya lo incluyen",
        ],
    },
    {
        'version': '1.0.20',
        'date': '2026-10-28',
        'notes': [
            "Todo: KPIs de tareas hechas, sin terminar, en curso y porcentaje completado",
            "Todo: el formulario de nueva tarea se abre con el botón «Nueva tarea»; las tareas se pueden editar y las completadas muestran su descripción",
            "Icono de llave en los accesos «Entrar como admin»",
        ],
    },
    {
        'version': '1.0.19',
        'date': '2026-10-28',
        'notes': [
            "Entrar como admin también en Odoo 10 y 11: entra con un administrador propio del panel («Administrador (Community SH)») con contraseña aleatoria; la contraseña del admin no se toca",
        ],
    },
    {
        'version': '1.0.18',
        'date': '2026-10-28',
        'notes': [
            "El instalador deja HTTPS listo: pide el email de Let's Encrypt y Traefik emite y renueva los certificados del panel y de cada instancia",
            "Cada instancia tiene su subdominio cliente-versión-nombre (p. ej. acme-20-produccion.tudominio.com), cubierto por un único registro DNS *.tudominio.com",
            "Las rutas de Traefik se regeneran al arrancar y al cambiar el dominio en Settings; Odoo corre con proxy_mode detrás del proxy",
        ],
    },
    {
        'version': '1.0.17',
        'date': '2026-10-28',
        'notes': [
            "Entrar como admin en Odoo 12-20 sin contraseña desde la instancia o el proyecto: enlace firmado, de un solo uso y válido 60 segundos (módulo community_sh_login, cargado como server-wide)",
        ],
    },
    {
        'version': '1.0.16',
        'date': '2026-10-28',
        'notes': [
            "Historial de Metrics con horas y minutos en los ejes y fecha y hora completas en el tooltip",
        ],
    },
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
