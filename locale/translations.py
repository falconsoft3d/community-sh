"""
Source of the UI translations. Templates mix Spanish and English source strings, so each
string gets its translation into the other language; `python locale/translations.py`
fills the .po catalogs (run `manage.py makemessages -l es -l en` first, then
`manage.py compilemessages`).
"""

# Strings written in Spanish in the code -> English
ES_TO_EN = {
    'Entrar como admin': 'Log in as admin',
    'Mis proyectos': 'My projects',
    'Más proyectos de Marlon Falcón': 'More projects by Marlon Falcón',
    'Otras herramientas y webs en las que trabajo.': 'Other tools and websites I work on.',
    'Paginación': 'Pagination',
    '%(start)s–%(end)s de %(total)s': '%(start)s–%(end)s of %(total)s',
    'Primera página': 'First page',
    'Anterior': 'Previous',
    'Página %(number)s de %(pages)s': 'Page %(number)s of %(pages)s',
    'Siguiente': 'Next',
    'Última página': 'Last page',
    'Mostrar u ocultar las tareas completadas': 'Show or hide completed tasks',
    'Ocultar': 'Hide',
    'Ver': 'Show',
    'Odoo %(first)s a %(last)s aislado, con su propio Postgres, red Docker y volumen de datos.':
        'Isolated Odoo %(first)s to %(last)s, with its own Postgres, Docker network and data volume.',
    'Uno o varios repositorios de GitHub por instancia': 'One or more GitHub repositories per instance',
    'Duplica para staging con sus datos y adjuntos': 'Duplicate for staging with its data and attachments',
    'Entra como admin sin escribir la contraseña': 'Log in as admin without typing the password',
    'Tus datos, a salvo': 'Your data, safe',
    'Restaura o crea una instancia desde cualquier backup': 'Restore or create an instance from any backup',
    'Importa los backups nativos de Odoo': "Import Odoo's native backups",
    'Cada usuario ve solo lo suyo; 2FA y bloqueo por intentos': 'Each user sees only their own; 2FA and lockout after failed attempts',
    'Dominios y HTTPS automáticos': 'Automatic domains and HTTPS',
    "Traefik enruta cada dominio y Let's Encrypt emite y renueva los certificados.":
        "Traefik routes every domain and Let's Encrypt issues and renews the certificates.",
    'Un subdominio por instancia: cliente-20-bd.tudominio.com': 'A subdomain per instance: client-20-db.yourdomain.com',
    'Dominios propios para instancias y apps': 'Custom domains for instances and apps',
    '%(count)s apps listas para lanzar junto a tu ERP': '%(count)s apps ready to launch next to your ERP',
    'Automatiza con IA y API': 'Automate with AI and API',
    'Pide cambios a la IA en el chat de cada instancia, conecta Claude por MCP o usa la API REST.':
        "Ask the AI for changes in each instance's chat, connect Claude over MCP or use the REST API.",
    'Módulos y cambios generados por IA, con deshacer': 'AI-generated modules and changes, with undo',
    'Logs, consola y métricas de CPU y RAM': 'Logs, console and CPU and RAM metrics',
    'Tareas en segundo plano con su progreso': 'Background tasks with their progress',
    'Despliega en minutos': 'Deploy in minutes',
    'Crea los registros A de tudominio.com y *.tudominio.com apuntando a la IP del servidor. El instalador te pedirá el dominio y un email, y Traefik genera los certificados HTTPS.':
        "Create A records for yourdomain.com and *.yourdomain.com pointing to the server's IP. The installer asks for the domain and an email, and Traefik issues the HTTPS certificates.",
    'Nueva tarea': 'New task',
    'Hechas': 'Done',
    'Sin terminar': 'Unfinished',
    'Completado': 'Completed',
    'Guardar': 'Save',
    'Ver descripción': 'Show description',
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
    'Actividad': 'Activity',
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
    'Ayuda': 'Help',
    'Auditoría': 'Audit log',
    'Quién hizo qué en el panel: inicios de sesión, contraseñas vistas o copiadas, configuración, tokens, usuarios y cambios en las instancias.':
        'Who did what in the panel: sign-ins, passwords shown or copied, settings, tokens, users and instance changes.',
    'Acción': 'Action',
    'Todas las acciones': 'All actions',
    'Todos los usuarios': 'All users',
    'Instancia, usuario…': 'Instance, user…',
    'Buscar': 'Search',
    'Filtrar': 'Filter',
    'Sobre': 'On',
    'Detalles': 'Details',
    'Sin eventos': 'No events',
    'No responde': 'Not responding',
    'Uso por instancia': 'Usage by instance',
    'Copias en S3': 'Copies in S3',
    'Cargando…': 'Loading…',
    'Los backups de esta instancia guardados fuera del servidor. Restaurar uno sustituye la base de datos y los adjuntos actuales.':
        "This instance's backups stored off the server. Restoring one replaces the current database and attachments.",
    'Ver copias': 'Show copies',
    'No hay copias de esta instancia en el bucket.': 'There are no copies of this instance in the bucket.',
    '¿Restaurar esta copia sobre la instancia? Se sustituyen su base de datos y sus adjuntos actuales.':
        'Restore this copy over the instance? Its current database and attachments are replaced.',
    'Qué instancia consume qué: CPU y RAM de su Odoo y su PostgreSQL ahora, y disco de sus datos, su código y sus backups. Pulsa una cabecera para ordenar.':
        'Which instance uses what: CPU and RAM of its Odoo and PostgreSQL now, and disk of its data, code and backups. Click a header to sort.',
    'Midiendo el disco…': 'Measuring the disk…',
    'Medir el disco ahora': 'Measure the disk now',
    'Disco': 'Disk',
    'detenida': 'stopped',
    'datos': 'data',
    'código': 'code',
    'Disco medido a las': 'Disk measured at',
    'se vuelve a medir cada 10 minutos': 'measured again every 10 minutes',
    'Su Odoo y su PostgreSQL juntos, de la que más memoria usa a la que menos. Útil para saber cuál parar cuando falta memoria.':
        'Its Odoo and its PostgreSQL together, from the one using the most memory to the least. Useful to know which to stop when memory is short.',
    'Odoo / límite': 'Odoo / limit',
    'sin límite': 'no limit',
    'Ninguna instancia en marcha': 'No instance running',
    'Tiempo de respuesta en la última comprobación': 'Response time in the last check',
    'Neutralizar la copia (recomendado)': 'Neutralize the copy (recommended)',
    'Antes de arrancar la copia se desactivan los servidores de correo entrante y saliente, las tareas programadas (salvo la limpieza automática), los métodos de pago y las claves API, y se cambia el UUID de la base. Así una copia de producción no escribe a tus clientes ni cobra. Desmárcalo solo si la copia va a sustituir a la original.':
        "Before the copy starts, its incoming and outgoing mail servers, scheduled actions (except the automatic cleanup), payment methods and API keys are switched off, and the database UUID is changed. That way a copy of production doesn't write to your customers or take payments. Untick it only if the copy will replace the original.",
    'Limpiar': 'Clean up',
    'Libera disco: lo mismo que se hace tras crear cada instancia': 'Frees disk space: the same cleanup that follows every new instance',
    '¿Limpiar lo que Docker no usa? Contenedores detenidos que no son de ninguna instancia, imágenes sin usar, caché de build y redes sin uso. Nunca toca las instancias ni los volúmenes.':
        "Clean up what Docker doesn't use? Stopped containers that belong to no instance, unused images, build cache and unused networks. Instances and volumes are never touched.",
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
    'Tareas del equipo. Claude puede leerlas y completarlas desde el servidor MCP.': 'Team tasks. Claude can read and complete them through the MCP server.',
    'Nueva tarea…': 'New task…',
    'Título': 'Title',
    'Detalles (opcional)': 'Details (optional)',
    'Detalles': 'Details',
    'Añadir': 'Add',
    'Por hacer': 'To do',
    'Marcar como completada': 'Mark as done',
    'En curso': 'In progress',
    'Empezar': 'Start',
    '¿Eliminar esta tarea?': 'Delete this task?',
    'No hay tareas pendientes.': 'No pending tasks.',
    'Completadas': 'Done',
    'Reabrir': 'Reopen',
    'completada por': 'completed by',
    'Historial del servidor': 'Server history',
    'Media por intervalo; el tooltip muestra también el pico.': 'Average per interval; the tooltip also shows the peak.',
    'Rango': 'Range',
    'Uso de CPU en el tiempo': 'CPU usage over time',
    'Uso de RAM en el tiempo': 'RAM usage over time',
    'Aún no hay datos: el worker toma una muestra por minuto.': 'No data yet: the worker takes one sample per minute.',
    '7 días': '7 days',
    '30 días': '30 days',
    '12 meses': '12 months',
    'media': 'avg',
    'pico': 'peak',
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
    # Instance page
    'Abre Odoo con la sesión del administrador (enlace de un solo uso)': 'Opens Odoo with the administrator session (single-use link)',
    'Demo de %(name)s': 'Demo for %(name)s',
    'Se detiene en <strong>%(days)s día%(plural)s</strong>': 'Stops in <strong>%(days)s day%(plural)s</strong>',
    'Vencida y detenida': 'Expired and stopped',
    'Se elimina en <strong>%(days)s día%(plural)s</strong>': 'Deleted in <strong>%(days)s day%(plural)s</strong>',
    'Datos enviados por email': 'Details sent by email',
    'Migrar': 'Migrate',
    'IA': 'AI',
    'en directo; la página se actualizará al terminar': 'live; the page will refresh when it finishes',
    'Toda la actividad': 'All activity',
    'Aún no hay tareas en esta instancia.': 'No tasks on this instance yet.',
    'Solo letras minúsculas, números y guiones': 'Lowercase letters, numbers and hyphens only',
    'URL Principal': 'Main URL',
    'Copiar URL': 'Copy URL',
    'URL Alternativa': 'Alternative URL',
    'Acceso directo por puerto (disponible inmediatamente)': 'Direct access through the port (available immediately)',
    'Proyecto': 'Project',
    '¿Mover la instancia a este proyecto? Su dirección no cambia.': "Move the instance to this project? Its address doesn't change.",
    'Mover': 'Move',
    'Disponibilidad': 'Availability',
    'Responde en %(ms)s ms': 'Responds in %(ms)s ms',
    'Sin comprobar': 'Not checked',
    'comprobado hace %(since)s': 'checked %(since)s ago',
    'El worker pide la página de login de Odoo cada 5 minutos; tras dos fallos seguidos avisa por las alertas de Configuración → General.':
        'The worker requests the Odoo login page every 5 minutes; after two failures in a row it notifies through the alerts in Settings → General.',
    'Demo': 'Demo',
    'Se detiene el %(stop)s y se elimina el %(delete)s (en %(days)s día%(plural)s).':
        'Stops on %(stop)s and is deleted on %(delete)s (in %(days)s day%(plural)s).',
    'Descripción (demos)': 'Description (demos)',
    'Qué incluye esta versión': 'What this version includes',
    'Se muestra junto a la instancia en la página de demos de su proyecto (modo test) y en su API pública.':
        "Shown next to the instance on its project's demo page (test mode) and in its public API.",
    'Mostrar/ocultar': 'Show/hide',
    'Copiar contraseña': 'Copy password',
    'Para el gestor de bases de datos de Odoo (/web/database/manager). Se aplica al redesplegar.':
        "For Odoo's database manager (/web/database/manager). Applied on redeploy.",
    'Uso ahora': 'Usage now',
    'Midiendo…': 'Measuring…',
    'No está en marcha': 'Not running',
    'de su límite': 'of its limit',
    'Sin límite': 'No limit',
    'Límite de memoria en MB': 'Memory limit in MB',
    'Tope de RAM del contenedor de Odoo, para que una instancia no deje sin memoria al servidor ni a las demás. Se aplica en marcha, sin reiniciar; 0 = sin límite (en el próximo despliegue). Si Odoo lo alcanza, el sistema corta el proceso y Docker lo vuelve a arrancar.':
        "RAM cap for the Odoo container, so one instance can't leave the server or the others without memory. Applied live, without a restart; 0 = no limit (from the next deploy). If Odoo reaches it, the system kills the process and Docker starts it again.",
    'Administrador': 'Administrator',
    'Copiar usuario': 'Copy user',
    'El administrador de Odoo que creó la plataforma (base de datos %(database)s), para compartirlo. Si se cambia la contraseña dentro de Odoo, esta deja de valer.':
        'The Odoo administrator the platform created (database %(database)s), to share it. If the password is changed inside Odoo, this one stops working.',
    'El administrador de Odoo que creó la plataforma, para compartirlo. Si se cambia la contraseña dentro de Odoo, esta deja de valer.':
        'The Odoo administrator the platform created, to share it. If the password is changed inside Odoo, this one stops working.',
    'Contraseña desconocida: la base de datos no la creó la plataforma. Restablécela para verla y compartirla.':
        "Unknown password: the database wasn't created by the platform. Reset it to see and share it.",
    'Restablecer contraseña': 'Reset password',
    '¿Cambiar la contraseña del administrador de Odoo? La actual dejará de funcionar y se cerrarán sus sesiones abiertas.':
        "Change the Odoo administrator's password? The current one will stop working and its open sessions will be closed.",
    'Vacío: se genera una aleatoria': 'Empty: a random one is generated',
    'Nueva contraseña del administrador': 'New administrator password',
    '8-64 letras, números, «_» o «-»': '8-64 letters, numbers, “_” or “-”',
    'Restablecer': 'Reset',
    'Se aplica al usuario administrador de la base de datos %(database)s. La instancia tiene que estar desplegada.':
        'Applies to the administrator user of the %(database)s database. The instance has to be deployed.',
    'Se aplica al usuario administrador de todas las bases de datos de la instancia. La instancia tiene que estar desplegada.':
        'Applies to the administrator user of every database in the instance. The instance has to be deployed.',
    'Dominio & SSL': 'Domain & SSL',
    'Configurar dominio personalizado': 'Set up a custom domain',
    'Certificado pendiente': 'Certificate pending',
    "Let's Encrypt ha alcanzado su límite semanal de certificados para este dominio. Se reintenta solo, no antes de %(retry)s UTC.":
        "Let's Encrypt has reached its weekly certificate limit for this domain. It retries automatically, not before %(retry)s UTC.",
    "Let's Encrypt ha alcanzado su límite semanal de certificados para este dominio. Se reintenta solo.":
        "Let's Encrypt has reached its weekly certificate limit for this domain. It retries automatically.",
    "Let's Encrypt no pudo comprobar el dominio: revisa que su DNS apunte a este servidor.":
        "Let's Encrypt couldn't verify the domain: check that its DNS points to this server.",
    "Let's Encrypt no pudo emitir el certificado: revisa el DNS del dominio y los registros de Traefik.":
        "Let's Encrypt couldn't issue the certificate: check the domain's DNS and the Traefik logs.",
    'El certificado se está solicitando.': 'The certificate is being requested.',
    'Mientras tanto la instancia funciona, pero el navegador mostrará un aviso de seguridad.':
        'Meanwhile the instance works, but the browser will show a security warning.',
    'SSL Activo': 'SSL active',
    'Sin SSL': 'No SSL',
    'Generar Certificado SSL': 'Generate SSL certificate',
    'Email para notificaciones': 'Email for notifications',
    'tu@email.com': 'you@email.com',
    'Confirmar y Generar': 'Confirm and generate',
    'Certificado: %(path)s': 'Certificate: %(path)s',
    'Cambiar dominio': 'Change domain',
    'Dominio Personalizado': 'Custom domain',
    'ejemplo.com o www.ejemplo.com': 'example.com or www.example.com',
    'Asegúrate de que tu dominio apunte a este servidor': 'Make sure your domain points to this server',
    'Guardar Dominio': 'Save domain',
    'Navegador (WhatsApp Web)': 'Browser (WhatsApp Web)',
    'Google Chrome dentro del contenedor de Odoo, para los módulos que lo necesitan, como WhatsApp Web. Ocupa unos 450 MB y se reinstala solo en cada despliegue (menos de un minuto más).':
        'Google Chrome inside the Odoo container, for the modules that need it, such as WhatsApp Web. It takes about 450 MB and is reinstalled automatically on every deploy (less than a minute more).',
    'Instalado': 'Installed',
    '¿Dejar de instalar Google Chrome? Desaparece en el próximo despliegue.': 'Stop installing Google Chrome? It goes away on the next deploy.',
    'Quitar': 'Remove',
    'Instalar Google Chrome': 'Install Google Chrome',
    'Repositorios de addons': 'Addons repositories',
    'Cada repositorio se clona y se añade al addons_path de Odoo. «Pull» trae los últimos cambios de todos y reinicia Odoo, sin redesplegar.':
        "Each repository is cloned and added to Odoo's addons_path. “Pull” fetches the latest changes of all of them and restarts Odoo, without redeploying.",
    'Descarga los últimos commits de cada repositorio y reinicia Odoo. Si cambian vistas o datos, actualiza el módulo en Odoo.':
        'Downloads the latest commits of each repository and restarts Odoo. If views or data change, upgrade the module in Odoo.',
    '¿Quitar este repositorio?': 'Remove this repository?',
    'rama %(branch)s · principal (/mnt/extra-addons)': 'branch %(branch)s · main (/mnt/extra-addons)',
    'rama %(branch)s · /mnt/repos/%(slug)s': 'branch %(branch)s · /mnt/repos/%(slug)s',
    'Sin repositorios': 'No repositories',
    'URL del repositorio': 'Repository URL',
    'Rama': 'Branch',
    'Los repos privados usan el token de GitHub del dueño de la instancia (Settings → GitHub).':
        "Private repos use the instance owner's GitHub token (Settings → GitHub).",
    'Actualización automática al hacer push': 'Automatic update on push',
    'Cada push a la rama de uno de los repositorios de esta instancia (el principal o los de addons) la actualiza sola, como tarea con su log en «Tareas recientes». Además, cada noche se actualiza aunque el repositorio no tenga webhook. Solo se reinicia Odoo si el código cambió.':
        "Every push to the branch of one of this instance's repositories (the main one or the addons ones) updates it automatically, as a task with its log in “Recent tasks”. It is also updated every night even if the repository has no webhook. Odoo is only restarted if the code changed.",
    'Activa': 'Active',
    'Al recibir un push': 'When a push arrives',
    '«Actualizar todos los módulos» ejecuta <code class="font-mono">-u all</code> en cada base de datos (campos, vistas y datos nuevos de los módulos) y tarda más; «Pull» solo trae el código y reinicia Odoo.':
        '“Update all modules” runs <code class="font-mono">-u all</code> on each database (new fields, views and data of the modules) and takes longer; “Pull” only fetches the code and restarts Odoo.',
    'Webhook de GitHub': 'GitHub webhook',
    'Crear webhook en GitHub': 'Create webhook on GitHub',
    'Un webhook por repositorio basta: el push actualiza todas las instancias en marcha que usan ese repositorio y rama con la actualización automática activa, aunque el webhook sea de otra instancia. Lo crea en todos los repositorios de la instancia con tu token de GitHub (necesita el permiso <code class="font-mono">admin:repo_hook</code>, o «Webhooks: lectura y escritura» en un token fine-grained). O añádelo a mano en cada repositorio → Settings → Webhooks → Add webhook:':
        "One webhook per repository is enough: a push updates every running instance that uses that repository and branch with automatic update on, even if the webhook belongs to another instance. This creates it on all the instance's repositories with your GitHub token (it needs the <code class=\"font-mono\">admin:repo_hook</code> scope, or “Webhooks: read and write” on a fine-grained token). Or add it by hand in each repository → Settings → Webhooks → Add webhook:",
    'Eventos': 'Events',
    '¿Generar un secreto nuevo? Los webhooks con el actual dejarán de funcionar hasta actualizarlos.':
        'Generate a new secret? Webhooks using the current one will stop working until they are updated.',
    'Generar un secreto nuevo': 'Generate a new secret',
    'Variables de entorno': 'Environment variables',
    'Se pasan al contenedor de Odoo de esta instancia en cada despliegue (los módulos las leen con <code class="font-mono">os.environ</code>). Solo las ve quien gestiona la instancia.':
        "They are passed to this instance's Odoo container on every deploy (modules read them with <code class=\"font-mono\">os.environ</code>). Only those who manage the instance can see them.",
    'Ver y editar': 'View and edit',
    'Redesplegar ahora para aplicarlas': 'Redeploy now to apply them',
    'Una por línea, <code class="font-mono">NOMBRE=valor</code>; se ignoran las líneas vacías y las que empiezan por <code class="font-mono">#</code>. HOST, USER, PASSWORD y PORT los pone la plataforma. Las copias de la instancia las heredan; las demos de «Modo test» no.':
        'One per line, <code class="font-mono">NAME=value</code>; empty lines and lines starting with <code class="font-mono">#</code> are ignored. HOST, USER, PASSWORD and PORT are set by the platform. Copies of the instance inherit them; “Test mode” demos don\'t.',
    'Instalar un módulo disponible': 'Install an available module',
    'Instala o actualiza en todas las bases de datos de la instancia un módulo que ya está en sus addons (el tema, los de tus repositorios o los de Odoo). La instancia necesita tener al menos una base de datos.':
        "Installs or upgrades, on every database of the instance, a module that is already in its addons (the theme, the ones from your repositories or Odoo's own). The instance needs at least one database.",
    'Instalar el tema Community SH': 'Install the Community SH theme',
    'Nombre técnico': 'Technical name',
    'Actualizar (-u) en vez de instalar': 'Upgrade (-u) instead of installing',
    'Instalar': 'Install',
    'Instalar Módulo': 'Install module',
    'Agregar al repositorio y desplegar': 'Add to the repository and deploy',
    'Esta instancia no tiene un repositorio de GitHub configurado. Los módulos solo se pueden instalar en instancias con repositorio.':
        "This instance doesn't have a GitHub repository set up. Modules can only be installed on instances with a repository.",
    'Archivo del Módulo': 'Module file',
    'El módulo se agregará a <strong>%(repo)s</strong> y se desplegará automáticamente':
        'The module will be added to <strong>%(repo)s</strong> and deployed automatically',
    'Subir e Instalar': 'Upload and install',
    'Restaurar desde un archivo': 'Restore from a file',
    'Sustituye la base de datos y el filestore de esta instancia. Acepta backups del panel, del gestor de bases de datos de Odoo (.zip) o un volcado .dump.':
        "Replaces this instance's database and filestore. Accepts backups from the panel, from Odoo's database manager (.zip) or a .dump file.",
    'Se sobrescribirán la base de datos y el filestore actuales. ¿Continuar?':
        'The current database and filestore will be overwritten. Continue?',
    'ADVERTENCIA: Esto sobrescribirá la base de datos y archivos actuales. ¿Estás seguro de que quieres restaurar este backup?':
        'WARNING: This will overwrite the current database and files. Are you sure you want to restore this backup?',
    '¿Estás seguro de que quieres eliminar este backup?': 'Are you sure you want to delete this backup?',
    'Copiado fuera del servidor: %(key)s': 'Copied off the server: %(key)s',
    'Migrar desde otro Odoo': 'Migrate from another Odoo',
    'Copia por XML-RPC los datos de cualquier Odoo (versión 8 o posterior, en tu servidor o en Internet) a esta instancia. Se puede repetir: lo ya copiado no se duplica y continúa donde se quedó.':
        'Copies the data of any Odoo (version 8 or later, on your server or on the Internet) to this instance over XML-RPC. It can be repeated: what was already copied is not duplicated and it carries on where it left off.',
    'URL del Odoo de origen': 'Source Odoo URL',
    'Base de datos': 'Database',
    'Base de datos de origen': 'Source database',
    'Usuario de origen': 'Source user',
    'Contraseña o clave API': 'Password or API key',
    'Contraseña de origen': 'Source password',
    'Destino: %(name)s (Odoo %(version)s)': 'Target: %(name)s (Odoo %(version)s)',
    'Base de datos de destino': 'Target database',
    'Usuario de destino': 'Target user',
    'Contraseña del administrador': 'Administrator password',
    'Contraseña de destino': 'Target password',
    'Instala antes en el destino Ventas, Compras y Facturación si vas a migrar esos datos. Las contraseñas no se guardan: solo se usan durante la migración.':
        'Install Sales, Purchase and Invoicing on the target first if you are going to migrate that data. Passwords are not stored: they are only used during the migration.',
    'Qué migrar': 'What to migrate',
    'Haz un backup de esta instancia antes de migrar. Los impuestos, monedas, países y unidades se buscan por nombre o código en el destino.':
        'Back up this instance before migrating. Taxes, currencies, countries and units are matched by name or code on the target.',
    'La migración escribe en esta instancia con el modelo de facturación de Odoo %(version)s+: crea una instancia de Odoo %(version)s o posterior para migrar a ella (el origen puede ser cualquier versión desde la 8).':
        'The migration writes to this instance with the invoicing model of Odoo %(version)s+: create an Odoo %(version)s or later instance to migrate into (the source can be any version from 8 on).',
    'Última migración · %(source)s': 'Last migration · %(source)s',
    'En cola…': 'Queued…',
    'Consola Interactiva': 'Interactive console',
    'Ejecuta comandos dentro del contenedor.': 'Run commands inside the container.',
    'Instalar desde requirements.txt': 'Install from requirements.txt',
    'Ingresa un comando (ej: pip install requests)': 'Enter a command (e.g. pip install requests)',
    'Ejecutar': 'Run',
    'hechos': 'done',
    'Deshacer estos cambios': 'Undo these changes',
    'archivo': 'file',
    'archivos': 'files',
    'Solo lectura (repositorio): la IA lo extenderá con un módulo nuevo': 'Read-only (repository): the AI will extend it with a new module',
    'Suelta aquí los PDF, imágenes o archivos de texto': 'Drop PDFs, images or text files here',
    'Asistente de IA': 'AI assistant',
    'Crea y modifica módulos de Odoo %(version)s en la carpeta de addons de esta instancia y los instala.':
        "Creates and edits Odoo %(version)s modules in this instance's addons folder and installs them.",
    'Nueva conversación': 'New conversation',
    'Pídele, por ejemplo: «Crea un módulo que añada un campo "Código interno" a los contactos y lo muestre en el formulario».':
        'Ask it, for example: “Create a module that adds an "Internal code" field to contacts and shows it on the form”.',
    'Cambios deshechos': 'Changes undone',
    'Detener': 'Stop',
    'Adjuntar PDF, imágenes o archivos de texto': 'Attach PDFs, images or text files',
    'Adjuntar archivos': 'Attach files',
    'Describe el módulo o el cambio que quieres… Usa @ para etiquetar un módulo': 'Describe the module or the change you want… Use @ to tag a module',
    'Enviar': 'Send',
    'También desde Odoo: un administrador escribe <code class="font-mono">/ia …</code> en el chatter de cualquier registro (p. ej. «/ia añade una columna Obra a esta lista») y la respuesta llega a ese mismo chatter. El módulo <code class="font-mono">community_sh_ai</code> se instala solo al desplegar.':
        'From Odoo too: an administrator types <code class="font-mono">/ia …</code> in the chatter of any record (e.g. “/ia add a Project column to this list”) and the reply arrives in that same chatter. The <code class="font-mono">community_sh_ai</code> module is installed automatically on deploy.',
    'Puedes adjuntar PDF con capturas o especificaciones: en peticiones largas la IA arma un plan y lo va completando paso a paso (puedes cerrar la página, sigue trabajando). La instalación de módulos aparece en la pestaña «Tareas recientes». Haz un backup antes de cambios grandes.':
        'You can attach PDFs with screenshots or specifications: for long requests the AI drafts a plan and completes it step by step (you can close the page, it keeps working). Module installs show up in the “Recent tasks” tab. Back up before big changes.',
    'Adjunta como máximo 5 archivos': 'Attach at most 5 files',
    'supera los 20 MB': 'is over 20 MB',
    'Enviando…': 'Sending…',
    'Pensando y trabajando en los archivos…': 'Thinking and working on the files…',
    'Paso {step} de {total}': 'Step {step} of {total}',
    'Se restaurarán los archivos como estaban antes de esta petición (y se deshacen también las posteriores). ¿Continuar?':
        'The files will be restored to how they were before this request (later requests are undone too). Continue?',
    '¿Borrar la conversación?': 'Clear the conversation?',
    '¿Eliminar Instancia?': 'Delete instance?',
    'Esta acción no se puede deshacer': 'This action cannot be undone',
    'Se eliminará permanentemente:': 'This will be permanently deleted:',
    'El contenedor Docker <strong class="text-foreground">%(name)s</strong>': 'The Docker container <strong class="text-foreground">%(name)s</strong>',
    'Todos los datos y configuraciones': 'All data and settings',
    'Los addons personalizados': 'The custom addons',
    'Continuar': 'Continue',
    'Confirmar Eliminación': 'Confirm deletion',
    'Escribe <strong class="text-foreground">%(name)s</strong> para confirmar:': 'Type <strong class="text-foreground">%(name)s</strong> to confirm:',
    'Escribe el nombre de la instancia': "Type the instance's name",
    'Atrás': 'Back',
    'Ejecutando...': 'Running...',
    '(sin salida)': '(no output)',
    'Error desconocido': 'Unknown error',
    'Error de conexión': 'Connection error',
    'Consola limpiada': 'Console cleared',
    'Instalando dependencias desde': 'Installing dependencies from',
    'Leyendo archivo y ejecutando pip install...': 'Reading the file and running pip install...',
    'Instalación completada': 'Installation completed',
    'Error en la instalación': 'Installation failed',
    'No se pudo obtener': 'Could not retrieve it',
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
    # Instance page
    'Upgrade / Deploy': 'Actualizar / Desplegar',
    'Stop': 'Detener',
    'Restart': 'Reiniciar',
    'Duplicate': 'Duplicar',
    'Information': 'Información',
    'Logs': 'Logs',
    'Console': 'Consola',
    'Domains': 'Dominios',
    'Modules': 'Módulos',
    'Backups': 'Backups',
    'Details about this instance.': 'Detalles de esta instancia.',
    'Master Password': 'Contraseña maestra',
    'Source': 'Origen',
    'Create New Backup': 'Crear un backup',
    'Full Backup (with filestore)': 'Backup completo (con filestore)',
    'Database Only': 'Solo base de datos',
    'Available Backups': 'Backups disponibles',
    'List of all created backups': 'Todos los backups creados',
    'With filestore': 'Con filestore',
    'No backups available': 'No hay backups disponibles',
    'Create a backup using the buttons above': 'Crea un backup con los botones de arriba',
    'Live Logs': 'Logs en vivo',
    'Real-time output from container.': 'Salida del contenedor en tiempo real.',
}


def fill(po_path, translations):
    """
    Set msgstr for the given msgids in a .po file. The dictionary wins over what the catalog
    has, including entries makemessages guessed from an older string (fuzzy).
    """
    import re
    text = open(po_path, encoding='utf-8').read()

    def unescape(s):
        return s.replace('\\"', '"').replace('\\\\', '\\')

    def escape(s):
        return s.replace('\\', '\\\\').replace('"', '\\"')

    def strings(block):
        return unescape(''.join(re.findall(r'"((?:[^"\\]|\\.)*)"', block)))

    entries = text.split('\n\n')
    for index, entry in enumerate(entries):
        match = re.search(r'^msgid ((?:"(?:[^"\\]|\\.)*"\n)+)msgstr ((?:"(?:[^"\\]|\\.)*"\n?)+)$', entry, re.M)
        if not match or entry.startswith('#~'):
            continue
        msgid = strings(match.group(1))
        if not msgid or msgid not in translations:
            continue
        comments = [line for line in entry[:match.start()].splitlines()
                    if not line.startswith('#|') and line != '#, fuzzy']
        comments = [line.replace(', fuzzy', '') if line.startswith('#,') else line for line in comments]
        entries[index] = '\n'.join(comments + [f'msgid {match.group(1)}msgstr "{escape(translations[msgid])}"'])
    # makemessages marks the catalog header fuzzy until reviewed
    entries[0] = entries[0].replace('#, fuzzy\n', '', 1)
    text = '\n\n'.join(entries)
    open(po_path, 'w', encoding='utf-8').write(text if text.endswith('\n') else text + '\n')


if __name__ == '__main__':
    import pathlib
    here = pathlib.Path(__file__).parent
    fill(here / 'en' / 'LC_MESSAGES' / 'django.po', ES_TO_EN)
    fill(here / 'es' / 'LC_MESSAGES' / 'django.po', EN_TO_ES)
    print('catalogs filled')
