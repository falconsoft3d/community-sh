"""
Source of the UI translations. Templates mix Spanish and English source strings, so each
string gets its translation into the other language; `python locale/translations.py`
fills the .po catalogs (run `manage.py makemessages -l es -l en` first, then
`manage.py compilemessages`).
"""

# Strings written in Spanish in the code -> English
ES_TO_EN = {
    'Filtrar por proyecto': 'Filter by project',
    'Todos los proyectos': 'All projects',
    'Instancia': 'Instance',
    'Archivo': 'File',
    'Contenido': 'Contents',
    'Tamaño': 'Size',
    'Fecha': 'Date',
    'Acciones': 'Actions',
    'BD + filestore': 'DB + filestore',
    'Solo BD': 'DB only',
    'Descargar': 'Download',
    'Restaurar': 'Restore',
    'Eliminar': 'Delete',
    'No hay backups': 'No backups',
    'Crea uno desde la pestaña Backups de una instancia, o activa los automáticos en Settings.':
        "Create one from an instance's Backups tab, or turn on automatic backups in Settings.",
    'Proyectos': 'Projects',
    'Usuarios': 'Users',
    'Mi Perfil': 'My profile',
    'Community SH · Hosting de Odoo open source': 'Community SH · Open source Odoo hosting',
    'Funcionalidades': 'Features',
    'Cómo funciona': 'How it works',
    'Instalación': 'Installation',
    'Idioma': 'Language',
    'Cambiar tema claro/oscuro': 'Toggle light/dark theme',
    'Cerrar sesión': 'Sign out',
    'Ir al panel': 'Go to dashboard',
    'Iniciar sesión': 'Sign in',
    'Open source · Licencia MIT · v%(version)s': 'Open source · MIT license · v%(version)s',
    'Tu propio hosting de Odoo,': 'Your own Odoo hosting,',
    'en tu servidor': 'on your server',
    'Community SH es un panel para desplegar y administrar instancias de Odoo y otras aplicaciones sobre Docker. Cada instancia tiene su propia base de datos, dominio, SSL y backups, y todo se gestiona desde el navegador.':
        'Community SH is a dashboard to deploy and manage Odoo instances and other apps on Docker. Each instance has its own database, domain, SSL and backups, all managed from the browser.',
    'Crear cuenta': 'Create account',
    'Apps listas': 'Ready apps',
    'Licencia': 'License',
    'Instancias': 'Instances',
    'Tareas recientes': 'Recent tasks',
    'Todo lo que necesitas para operar Odoo': 'Everything you need to run Odoo',
    'Del primer despliegue a los backups diarios, sin entrar al servidor.': 'From the first deploy to daily backups, without logging into the server.',
    'Instancias aisladas': 'Isolated instances',
    'Cada Odoo corre con su propio Postgres, red Docker y volumen de datos. Versiones %(first)s a %(last)s, y una contraseña maestra distinta por instancia.':
        'Each Odoo runs with its own Postgres, Docker network and data volume. Versions %(first)s to %(last)s, and a different master password per instance.',
    'GitHub y módulos': 'GitHub and modules',
    'Conecta un repositorio con tus addons: cada instancia tiene su rama. Sube un módulo en ZIP y se añade al repo y se redespliega.':
        'Connect a repository with your addons: each instance gets its own branch. Upload a module as a ZIP and it is added to the repo and redeployed.',
    'Backups y restauración': 'Backups and restore',
    'Respaldos con base de datos y filestore, manuales o programados con retención. Restaura o crea una instancia nueva a partir de cualquier backup.':
        'Backups with database and filestore, manual or scheduled with retention. Restore, or create a new instance from any backup.',
    'Duplicar para pruebas': 'Duplicate for testing',
    'Clona una instancia con sus datos y adjuntos para tener staging o probar una actualización sin tocar producción.':
        'Clone an instance with its data and attachments to get a staging copy or test an upgrade without touching production.',
    'Dominios y SSL': 'Domains and SSL',
    "Asigna un dominio propio a cada instancia o app. Traefik enruta el tráfico y Let's Encrypt genera los certificados HTTPS.":
        "Give each instance or app its own domain. Traefik routes the traffic and Let's Encrypt issues the HTTPS certificates.",
    'Más que Odoo': 'More than Odoo',
    '%(count)s plantillas de apps listas para lanzar junto a tu ERP, o cualquier imagen de Docker como contenedor personalizado.':
        '%(count)s app templates ready to launch next to your ERP, or any Docker image as a custom container.',
    'Seguro por defecto': 'Secure by default',
    'Cada usuario ve solo sus instancias. 2FA opcional u obligatorio, bloqueo por intentos fallidos y registro cerrado salvo que el administrador lo abra.':
        'Each user only sees their own instances. Optional or mandatory 2FA, lockout after failed attempts, and sign-up closed unless the admin opens it.',
    'Tareas en segundo plano': 'Background tasks',
    'Despliegues, backups y restauraciones corren en un worker. El panel responde al instante y te muestra el progreso y el resultado.':
        'Deploys, backups and restores run in a worker. The dashboard responds instantly and shows you the progress and the result.',
    'Consola, logs y métricas': 'Console, logs and metrics',
    'Logs en vivo y consola de cada contenedor, instalación de requirements y métricas de CPU, RAM, disco y Docker del servidor.':
        "Live logs and a console for each container, requirements installation, and the server's CPU, RAM, disk and Docker metrics.",
    'Catálogo': 'Catalog',
    'Apps a un clic': 'One-click apps',
    'Plantillas YAML que puedes ajustar o ampliar en': 'YAML templates you can tweak or extend in',
    'Un servidor, todo en Docker': 'One server, everything in Docker',
    'El panel habla con Docker en tu servidor. No hay servicios externos ni agentes que instalar.':
        'The dashboard talks to Docker on your server. No external services or agents to install.',
    'Recibe el tráfico en los puertos 80/443, aplica el SSL y lo dirige por dominio.':
        'Receives traffic on ports 80/443, terminates SSL and routes it by domain.',
    'Interfaz web y API. Encola las operaciones largas.': 'Web interface and API. Queues long operations.',
    'Despliega, respalda y restaura. Lanza los backups programados.': 'Deploys, backs up and restores. Runs the scheduled backups.',
    'Instancia «mi-empresa»': 'Instance “my-company”',
    'Odoo + Postgres en su propia red, filestore en un volumen.': 'Odoo + Postgres on their own network, filestore in a volume.',
    'La base de datos del panel vive en una red interna a la que las instancias no tienen acceso.':
        "The dashboard's database lives on an internal network that instances cannot reach.",
    'En marcha en minutos': 'Up and running in minutes',
    'Un servidor Linux': 'A Linux server',
    'Con acceso root y los puertos 80 y 443 libres. El instalador se encarga de Docker.':
        'With root access and ports 80 and 443 free. The installer takes care of Docker.',
    'Ejecuta el instalador': 'Run the installer',
    'Genera las claves, configura tu dominio y levanta todos los servicios.': 'It generates the keys, sets up your domain and starts every service.',
    'Crea tu primera instancia': 'Create your first instance',
    'La primera cuenta que se registra es la de administrador. Elige versión de Odoo y despliega.':
        'The first account to sign up becomes the administrator. Pick an Odoo version and deploy.',
    'Instalación rápida': 'Quick install',
    'Copiar': 'Copy',
    'Copiado': 'Copied',
    '¿Prefieres revisarlo antes? Descarga': 'Prefer to review it first? Download',
    'y lee el': 'and read the',
    'Guías y novedades': 'Guides and news',
    'Ver todo': 'View all',
    '%(minutes)s min de lectura': '%(minutes)s min read',
    'Libre, abierto y tuyo': 'Free, open and yours',
    'Community SH es gratuito y de código abierto. Instálalo en tu servidor, adáptalo a tu equipo o contribuye al proyecto.':
        'Community SH is free and open source. Install it on your server, adapt it to your team or contribute to the project.',
    'Reportar un problema': 'Report an issue',
    'Hecho por Marlon Falcón Hernández · Licencia MIT ·': 'Made by Marlon Falcón Hernández · MIT license ·',
    'Documentación': 'Documentation',
    'Origen': 'Origin',
    'Duplicado': 'Duplicate',
    'núcleos': 'cores',
    'Sin cliente': 'No client',
    'Editar': 'Edit',
    'Nueva instancia': 'New instance',
    'Versión': 'Version',
    'Estado': 'Status',
    'Acceso': 'Access',
    'Abrir': 'Open',
    'Este proyecto todavía no tiene instancias.': "This project doesn't have any instances yet.",
    'Desplegar la primera instancia': 'Deploy the first instance',
    'Nuevo': 'New',
    'Editar proyecto': 'Edit project',
    'Nuevo proyecto': 'New project',
    'Cancelar': 'Cancel',
    'Guardar cambios': 'Save changes',
    'Crear proyecto': 'Create project',
    'Cada proyecto agrupa las instancias de un cliente: producción, staging, pruebas…':
        "Each project groups a client's instances: production, staging, testing…",
    'Aún no tienes proyectos': "You don't have any projects yet",
    'Crea un proyecto por cliente y despliega dentro sus instancias de Odoo.': 'Create a project per client and deploy its Odoo instances inside it.',
    'Crear el primer proyecto': 'Create the first project',
    'Recordarme': 'Remember me',
    'Novedades': "What's new",
    'Qué hay de nuevo en cada versión': "What's new in each version",
    'Historial completo': 'Full history',
    'Actual': 'Current',
    'Minimizar o expandir el menú': 'Collapse or expand the menu',
    'Páginas de novedades': 'Release notes pages',
    'Eliminar todo': 'Delete everything',
    'Eliminar el proyecto y todas sus instancias': 'Delete the project and all its instances',
    'Se borrarán de forma permanente los contenedores, bases de datos, filestores, workspaces y backups de:':
        'This permanently deletes the containers, databases, filestores, workspaces and backups of:',
    'Escribe <strong>%(name)s</strong> para confirmar': 'Type <strong>%(name)s</strong> to confirm',
    'Más recientes': 'Newer',
    'Anteriores': 'Older',
    'Página %(page)s de %(pages)s': 'Page %(page)s of %(pages)s',
    'Configura el DNS antes': 'Set up DNS first',
    'Crea un registro A de tu dominio apuntando a la IP del servidor. El instalador te pedirá ese dominio para generar los certificados SSL, y solo funcionan si ya apunta al servidor.':
        "Create an A record for your domain pointing to the server's IP. The installer asks for that domain to issue the SSL certificates, which only works if it already points to the server.",
    'Antes de ejecutarlo, comprueba que tu dominio ya apunta al servidor (por ejemplo con «dig +short tudominio.com»). El instalador lo verifica y te avisa si no es así.':
        'Before running it, check that your domain already points to the server (e.g. with “dig +short yourdomain.com”). The installer checks it and warns you if it does not.',
}

# Strings written in English in the code -> Spanish
EN_TO_ES = {
    'Deploying': 'Desplegando',
    'Running': 'En ejecución',
    'Stopped': 'Detenida',
    'Error': 'Error',
    'Instances': 'Instancias',
    'Containers': 'Contenedores',
    'Metrics': 'Métricas',
    'Settings': 'Configuración',
    'About': 'Acerca de',
    'Logout': 'Cerrar sesión',
    'New Instance': 'Nueva instancia',
    'Name': 'Nombre',
    'Version': 'Versión',
    'Status': 'Estado',
    'Created': 'Creada',
    'Link': 'Enlace',
    'Actions': 'Acciones',
    'Primary': 'Principal',
    'Confirm Action': 'Confirmar acción',
    'Are you sure you want to': '¿Seguro que quieres',
    'the instance': 'la instancia',
    'Cancel': 'Cancelar',
    'Confirm': 'Confirmar',
    'Pagination': 'Paginación',
    'System Metrics': 'Métricas del sistema',
    'Server resource and status monitoring': 'Recursos y estado del servidor',
    'Tabs': 'Pestañas',
    'Overview': 'Resumen',
    'Resource Usage': 'Uso de recursos',
    'CPU Usage': 'Uso de CPU',
    'RAM Usage': 'Uso de RAM',
    'Disk Usage': 'Uso de disco',
    'Active Containers': 'Contenedores activos',
    'total': 'en total',
    'Instance Status': 'Estado de las instancias',
    'Distribution of instances by state': 'Instancias por estado',
    'Docker information': 'Información de Docker',
    'Docker environment details': 'Detalles del entorno Docker',
    'Images': 'Imágenes',
    'Networks': 'Redes',
    'Container Resource Usage': 'Recursos por contenedor',
    'Real-time CPU and memory usage by container': 'CPU y memoria de cada contenedor en tiempo real',
    'Container': 'Contenedor',
    'Memory Usage': 'Memoria',
    'Memory Limit': 'Límite de memoria',
    'Network I/O': 'Red E/S',
    'Start some containers to see their resource usage': 'Inicia algún contenedor para ver su consumo',
    'Enter your credentials to sign in to your account': 'Introduce tus credenciales para entrar',
    'Username': 'Usuario',
    'Password': 'Contraseña',
    'Sign In': 'Iniciar sesión',
    "Don't have an account? Sign Up": '¿No tienes cuenta? Regístrate',
    'Create an account': 'Crear una cuenta',
    'Enter your email below to create your account': 'Introduce tus datos para crear tu cuenta',
    'Create Account': 'Crear cuenta',
    'Already have an account? Sign In': '¿Ya tienes cuenta? Inicia sesión',
}


def fill(po_path, translations):
    """Set msgstr for the given msgids in a .po file (single-line entries as written by makemessages)."""
    import re
    text = open(po_path, encoding='utf-8').read()

    def unescape(s):
        return s.replace('\\"', '"').replace('\\\\', '\\')

    def escape(s):
        return s.replace('\\', '\\\\').replace('"', '\\"')

    def replace(match):
        msgid = unescape(''.join(re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1))))
        if msgid in translations:
            return f'msgid {match.group(1)}msgstr "{escape(translations[msgid])}"\n'
        return match.group(0)

    text = re.sub(r'msgid ((?:"(?:[^"\\]|\\.)*"\n)+)msgstr ""\n(?!")', replace, text)
    # makemessages marks catalogs fuzzy until reviewed
    text = text.replace('#, fuzzy\n', '', 1)
    open(po_path, 'w', encoding='utf-8').write(text)


if __name__ == '__main__':
    import pathlib
    here = pathlib.Path(__file__).parent
    fill(here / 'en' / 'LC_MESSAGES' / 'django.po', ES_TO_EN)
    fill(here / 'es' / 'LC_MESSAGES' / 'django.po', EN_TO_ES)
    print('catalogs filled')
