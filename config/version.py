"""
Community SH version: bump the patch number (1.0.1 -> 1.0.2 ...) with every commit or improvement,
and document it here (shown in About) and in CHANGELOG.md, newest first.
"""

VERSION = '1.0.57'

CHANGELOG = [
    {
        'version': '1.0.57',
        'date': '2026-11-04',
        'notes': [
            'Demos: clave de API por proyecto (tarjeta «Modo test» → Generar clave), para que el servidor de tu web pida demos sin captcha con Authorization: Bearer csh_demo_… en POST /api/public/demos/{url}/. Solo sirve para las demos de ese proyecto, se guarda cifrada, se muestra una vez y se puede regenerar (la anterior deja de funcionar). Se mantienen el límite por email al mes, el diario y el de demos a la vez.',
        ],
    },
    {
        'version': '1.0.56',
        'date': '2026-11-04',
        'notes': [
            'Docker → Contenedores: botón «Eliminar todo lo no en uso», que borra de una vez los contenedores detenidos, las imágenes (sin etiqueta y sin usar), la caché de build, las redes y los volúmenes sin uso. Muestra antes qué y cuánto se libera y se confirma escribiendo BORRAR; nunca toca el panel, las instancias (aunque estén paradas), sus filestores y redes, ni los contenedores del panel y sus volúmenes.',
        ],
    },
    {
        'version': '1.0.55',
        'date': '2026-11-04',
        'notes': [
            'Contactos: nuevo menú con las personas que piden una demo (página pública o API): nombre, email, empresa, cargo, teléfono, país, sus demos y notas propias. Un contacto por email que se actualiza con los datos más nuevos y se conserva aunque la demo se elimine; búsqueda, filtros por país y proyecto, exportar a CSV, KPI en el Dashboard y API /api/contacts/. Los contactos de las demos ya pedidas se crean al actualizar.',
        ],
    },
    {
        'version': '1.0.54',
        'date': '2026-11-04',
        'notes': [
            'Instancias: actualización automática al hacer push. En Módulos se elige qué hacer cuando llega un push a la rama de uno de sus repositorios (el principal o los de addons): «Pull y reiniciar Odoo» o «Pull y actualizar todos los módulos (-u all)». Botón «Crear webhook en GitHub» (con el token del dueño) o URL y secreto para añadirlo a mano; los webhooks van firmados, se ignoran otros repositorios y ramas, y varios push seguidos se juntan en una sola actualización.',
        ],
    },
    {
        'version': '1.0.53',
        'date': '2026-11-04',
        'notes': [
            "Despliegue automático: funciona aunque el servidor tenga letsencrypt/acme.json marcado con skip-worktree o assume-unchanged (git se negaba a cambiar de versión: «Entry 'letsencrypt/acme.json' not uptodate»).",
        ],
    },
    {
        'version': '1.0.52',
        'date': '2026-11-04',
        'notes': [
            'Despliegue automático: si falla, el resumen del run muestra el error real del servidor (por ejemplo, que la carpeta no es un repositorio git) en lugar de solo el código de salida.',
        ],
    },
    {
        'version': '1.0.51',
        'date': '2026-11-04',
        'notes': [
            'Despliegue automático: el host, el usuario, el puerto, la ruta y known_hosts valen como secretos o como variables del repositorio, y si falta algo el error dice exactamente qué.',
        ],
    },
    {
        'version': '1.0.50',
        'date': '2026-11-04',
        'notes': [
            'Despliegue automático: los tests y el despliegue corren en Ubuntu 24.04 fijo (GitHub moverá ubuntu-latest a Ubuntu 26).',
        ],
    },
    {
        'version': '1.0.49',
        'date': '2026-11-04',
        'notes': [
            'Despliegue automático: cada push a main pasa los tests en GitHub Actions y, si van bien, despliega en el servidor por SSH (scripts/deploy.sh): espera a las tareas en curso, guarda una copia de la base del panel (si falla, no despliega), conserva .env, instancias, backups y certificados, reconstruye el panel y vuelve a la versión anterior si no responde.',
        ],
    },
    {
        'version': '1.0.48',
        'date': '2026-11-04',
        'notes': [
            'Seguridad (revisión completa): los contenedores genéricos ya no pueden llamarse como los del panel (app, db, traefik…) ni sustituir un contenedor de Docker ajeno; quien no es administrador no puede añadir volúmenes a una plantilla ni montar el de otro recurso (la base del panel, el filestore de una instancia).',
            'API: las instancias exponen una lista fija de campos; el volumen de datos, el subdominio, las rutas de certificados y la contraseña maestra ya no se pueden escribir, y el nombre se cambia solo con «Renombrar». Los clientes ya no ven la contraseña maestra (ni en la ficha ni en la API).',
            'Repositorios y ramas: solo URLs HTTPS y ramas que no empiezan por guion, en el formulario, la API y los repositorios extra; git solo usa HTTPS.',
            'Demos: sin asistente de IA (su visitante es administrador de Odoo); la copia se entrega con el correo desactivado, sin claves API, con contraseñas desconocidas para los demás usuarios y con el secreto de la base regenerado. Las plazas se comprueban de forma atómica, hay un máximo para todo el servidor (TRIAL_MAX_ACTIVE_TOTAL, 4) y no se crea una demo si falta memoria. La IP del visitante es la que añade Traefik y la página de credenciales no se guarda en caché.',
            'Acceso: el bloqueo por intentos fallidos cuenta por usuario normalizado y dirección (5) y por cuenta (20); /admin/login/ pasa por el login del panel (con 2FA); desactivar o cambiar el 2FA pide un código actual; los tokens de la API y de MCP exigen 2FA cuando es obligatorio.',
            'Con dominio y HTTPS: cookies solo por HTTPS, HSTS, el panel solo responde a su dominio y su IP, y el puerto de Odoo y el 8000 del panel escuchan solo en el propio servidor (todo pasa por Traefik). El instalador crea el administrador con una contraseña aleatoria.',
            'Un dominio propio no puede tomar el subdominio de otra instancia o contenedor; Traefik solo recibe nombres de host válidos. Los ZIP subidos (módulos y backups) se comprueban antes de descomprimir (rutas, número de archivos y tamaño). Los iconos (lucide) se cargan en una versión fija.',
            'Manual de usuario en PDF, en español e inglés, con capturas, descargable desde la página principal.',
            'Correo saliente: Configuración → Email (servidor SMTP, seguridad, usuario, remitente) con botón «Enviar prueba». Con él activo, las notificaciones salen por ese servidor y, al crear una demo, el cliente recibe por email su dirección, usuario y contraseña.',
            'Demos: el formulario pide también empresa, cargo, teléfono y país, y tiene un captcha propio (una suma firmada por el servidor, de un solo uso). Configuración → Demos: límite de demos al día (10) y de demos a la vez en todo el servidor (4).',
            'Demos: la ficha de una demo muestra los días que le quedan para detenerse y para eliminarse; también en la ficha del proyecto.',
            'API: pedir una demo desde otra web (POST /api/public/demos/{url}/ con el captcha, o /api/demos/ con token), seguir su estado, configurar el modo test de un proyecto y, para administradores, el correo y los límites (/api/settings/).',
            'Dashboard: nuevo menú con las cifras principales de Community SH (instancias, contenedores, backups, tareas, demos, servidor y seguridad), cada una enlazada a su página. La ficha del proyecto tiene sus propios KPIs.',
            'Proyectos: botón «Nuevo contenedor»; los contenedores pueden pertenecer a un proyecto y aparecen en su ficha.',
            'Arreglo: el blog daba Server Error (500) con artículos cuyo autor se había borrado.',
        ],
    },
    {
        'version': '1.0.47',
        'date': '2026-11-04',
        'notes': [
            'Proyectos: casilla «Modo test». Pide la URL de la página de demos (p. ej. /bim), los días de prueba (15 por defecto), el proyecto hermano donde se crean las demos, el texto para el usuario y cuántas demos puede haber a la vez.',
            'Página pública /url: el visitante elige la versión entre las instancias en marcha del proyecto (con su descripción), deja sus datos y recibe una copia propia en el proyecto hermano con una contraseña nueva para el administrador.',
            'Mientras se crea, la página muestra una barra de progreso con el paso en curso; al terminar, la dirección, el usuario y la contraseña.',
            'Una demo por email al mes (y como mucho 3 al mes desde la misma conexión). Al vencer se detiene y 7 días después se elimina.',
            'Instancias: «Descripción (demos)», editable en su ficha. API pública /api/public/demos/{url}/ (sin token, con CORS) para mostrar las versiones en tu web.',
        ],
    },
    {
        'version': '1.0.46',
        'date': '2026-11-02',
        'notes': [
            "Docker: botón «Limpiar lo no utilizado» y pestaña «Limpieza» con lo que se puede liberar (cuántos y cuánto ocupa): contenedores detenidos, imágenes sin etiqueta, imágenes sin usar, caché de build, redes y volúmenes sin uso. Se elige qué limpiar y corre como tarea con su log en Actividad.",
            "La limpieza nunca toca el panel, las instancias (aunque estén paradas), sus filestores y redes ni los contenedores del panel y sus volúmenes; las imágenes sin usar y los volúmenes hay que marcarlos a mano (los volúmenes, escribiendo BORRAR). No corre mientras se construye un contenedor.",
            "Arreglo: «Eliminar detenidos» borraba también los contenedores de las instancias paradas, y con ellos su base de datos; ahora sigue las mismas reglas.",
        ],
    },
    {
        'version': '1.0.45',
        'date': '2026-11-02',
        'notes': [
            "Contenedores: plantilla ERPSqlite (ERP con API compatible con la de Odoo, para MultiERP Móvil). Se construye desde su repositorio al crearla y arranca sola al terminar.",
            "Las plantillas pueden construirse desde un repositorio (git_repo, dockerfile) y generar claves aleatorias con {secret}, que se ven en la página del contenedor.",
            "API: /api/tasks/{id}/ devuelve también el log, el progreso y el paso en curso, como la página Actividad.",
        ],
    },
    {
        'version': '1.0.44',
        'date': '2026-11-02',
        'notes': [
            "API: contenedores Docker en /api/containers/ (crear, arrancar, detener, recrear, logs y eliminar), con los mismos límites que el formulario para quien no es administrador.",
            "Contenedores construidos desde un repositorio (también privado, con el token del propietario) y un Dockerfile, como tarea con su log en un worker propio (build-worker) para no frenar despliegues ni backups.",
            "Cada contenedor tiene https://nombre.dominio con certificado, como las instancias; parado deja de tener ruta.",
            "API: crear una instancia también la despliega y devuelve el task_id (antes quedaba en «deploying» sin desplegarse hasta llamar a /deploy/).",
            "API: /api/tasks/ muestra también tus tareas sin instancia, como construir un contenedor.",
        ],
    },
    {
        'version': '1.0.43',
        'date': '2026-10-30',
        'notes': [
            "Demos: varias bases en una instancia y un certificado, abiertas con https://dominio/?nombre (Odoo 18 a 20). Se activa con «Base por defecto de las demos».",
            "Copias de seguridad: una instancia con varias bases guarda una copia de cada una.",
        ],
    },
    {
        'version': '1.0.42',
        'date': '2026-10-30',
        'notes': [
            "Repositorio principal: se clona y actualiza con el token del propietario, así que los repositorios privados ya funcionan.",
            "Si no se puede obtener el código, el despliegue falla en lugar de terminar con los módulos vacíos; un fallo al actualizar conserva el código que había.",
        ],
    },
    {
        'version': '1.0.41',
        'date': '2026-10-30',
        'notes': [
            "Dominios: una instancia parada deja de tener ruta en Traefik y no gasta certificados; la recupera al reiniciarla.",
            "La ficha de la instancia avisa cuando falta el certificado y explica por qué (límite semanal de Let's Encrypt, DNS...).",
        ],
    },
    {
        'version': '1.0.40',
        'date': '2026-10-30',
        'notes': [
            "Módulos: botón «Pull» que trae los últimos commits del repositorio principal y de los de módulos y reinicia Odoo, como tarea con su log y barra, sin redesplegar ni actualizar todos los módulos",
        ],
    },
    {
        'version': '1.0.39',
        'date': '2026-10-30',
        'notes': [
            "Módulos: opción «Navegador (WhatsApp Web)» por instancia: instala Google Chrome en el contenedor de Odoo (como root, con su log y barra de progreso) y lo reinstala solo en cada despliegue, porque el contenedor se recrea; la imagen de Odoo no trae navegador y el chromium de Ubuntu es un snap que Docker no puede ejecutar",
        ],
    },
    {
        'version': '1.0.38',
        'date': '2026-10-30',
        'notes': [
            "Restart de una instancia: si su base de datos estaba parada (por ejemplo tras reiniciar el servidor), la arranca antes que Odoo y deja las dos con reinicio automático; «Entrar como admin» dice que la base de datos está parada en vez de «todavía no tiene base de datos»",
        ],
    },
    {
        'version': '1.0.37',
        'date': '2026-10-30',
        'notes': [
            "Reinicios del servidor: la base de datos del panel, las instancias de Odoo y su PostgreSQL vuelven a arrancar solas (antes quedaban paradas y el panel respondía Server Error 500); una instancia parada desde el panel sigue parada",
        ],
    },
    {
        'version': '1.0.36',
        'date': '2026-10-29',
        'notes': [
            "Consola e «Instalar desde requirements.txt»: pip instala los paquetes para el usuario odoo en el volumen de datos (/var/lib/odoo/.local), así funciona en Odoo 17-20 (antes Debian lo rechazaba: «externally-managed-environment») y el paquete se conserva al redesplegar",
        ],
    },
    {
        'version': '1.0.35',
        'date': '2026-10-29',
        'notes': [
            "Actividad: cada tarea (desplegar, respaldar, restaurar, duplicar, instalar módulos, migrar…) guarda su log completo con la hora —lo que imprime el servidor y sus avisos— y una barra de progreso con el paso en curso, que avanzan en directo en la pestaña «Tareas recientes» y en la nueva página «Actividad» del menú (todas las tareas, con filtros por estado, tipo e instancia y el log completo de cada una)",
        ],
    },
    {
        'version': '1.0.34',
        'date': '2026-10-29',
        'notes': [
            "Instancia: «Tareas recientes» pasa a su propia pestaña (con un punto azul mientras hay tareas en curso); la pestaña abierta queda en la URL y se conserva al recargar",
        ],
    },
    {
        'version': '1.0.33',
        'date': '2026-10-29',
        'notes': [
            "Tema: los iconos de las apps vuelven a verse en Odoo 20 (Odoo 20 lee los campos binarios como adjuntos; ahora se sirven por /web/image)",
        ],
    },
    {
        'version': '1.0.32',
        'date': '2026-10-28',
        'notes': [
            "Documentación: cómo crear el token de GitHub para repos privados (clásico y fine-grained) en el README y en Configuración → Ayuda, y qué significa el error 403",
        ],
    },
    {
        'version': '1.0.31',
        'date': '2026-10-28',
        'notes': [
            "Tema: los iconos de la pantalla de inicio van dentro de una tarjeta blanca con margen, como en Odoo Enterprise",
        ],
    },
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
