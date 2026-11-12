# Changelog

Versión actual: **1.0.97**. Cada commit o mejora sube el número de parche (1.0.1 → 1.0.2 → …).

## 1.0.97 — 2026-11-12

- Arreglo: al editar un proyecto, un administrador puede dejar vacías las cuotas (vacío = sin límite); antes el formulario las exigía.

## 1.0.96 — 2026-11-12

- Cuotas por proyecto (solo las ponen los administradores al editar el proyecto; en la API son de solo lectura): máximo de instancias y de RAM reservada (suma de los límites de memoria de sus instancias). Se comprueban al crear una instancia (formulario y API), duplicar, mover, crear desde backup, pedir una demo y subir un límite de memoria. Nueva página Metrics → Uso por proyecto (instancias, RAM reservada frente a la cuota, disco y backups) con CSV para facturar, y resumen por email el día 1 de cada mes. Migración 0077.

## 1.0.95 — 2026-11-12

- Ahorro de memoria por instancia (Information, desactivado por defecto): «Detener si nadie entra en N días» (3, 7, 14 o 30), según el registro de entradas de su Odoo, con alerta el día antes y al detenerla; y un horario diario (UTC) para arrancarla y detenerla, que el worker aplica una vez al día dentro de la hora siguiente. Queda en la Auditoría. Migración 0076.

## 1.0.94 — 2026-11-12

- Staging: «Refrescar datos desde otra instancia» (pestaña Backups) sustituye las bases de datos y los adjuntos de una instancia por los de otra de la misma versión (por defecto, la que copió) sin tocar su código, rama ni configuración; Odoo se detiene mientras, se neutraliza (recomendado) y toma el administrador de la original. Se confirma escribiendo el nombre y queda en la Auditoría. Las copias recuerdan de qué instancia salieron. Migración 0075.

## 1.0.93 — 2026-11-12

- Backups: restaurar desde S3 dentro del panel (pestaña Backups → Copias en S3 → Ver copias → Restaurar, como tarea con su log y en la Auditoría) y comprobación semanal del último backup de cada instancia (ZIP entero, volcado de PostgreSQL válido y misma talla en S3), también a mano con «Comprobar backups ahora»; si algo falla, alerta. Migración 0074.

## 1.0.92 — 2026-11-12

- Copia del panel fuera del servidor: con el bucket S3 configurado, cada día la tarea «Copia del panel fuera (S3)» sube a _panel/ un volcado de la base de datos del panel (pg_dump dentro de su contenedor, comprimido) y los certificados (acme.json); localmente se guardan 15 días y en el bucket rige su retención. El .env no se sube a propósito (tiene la clave que descifra los secretos): hay que guardarlo aparte. Migración 0073.

## 1.0.91 — 2026-11-12

- Tests en CI con PostgreSQL 16, el mismo motor que producción (antes SQLite, que oculta fallos de migraciones y conexiones). Arreglo que lo hizo posible: el worker ya no cierra la conexión a la base de datos dentro de una transacción; en producción no cambia nada y en PostgreSQL 56 tests fallaban por eso.

## 1.0.90 — 2026-11-12

- Seguridad: los secretos se guardan cifrados en la base de datos (Fernet, de la librería cryptography): token de GitHub, secreto del webhook, clave de OpenAI, contraseña SMTP y secret key de S3, y en cada instancia la Master Password, la contraseña del administrador, el secreto de su webhook y sus variables de entorno. Se cifran al guardar y se descifran al leer, sin cambiar nada más; la migración 0072 cifra los valores que ya había. La clave es FIELD_ENCRYPTION_KEY del .env o, sin ella, una derivada de DJANGO_SECRET_KEY: no cambiarla.

## 1.0.89 — 2026-11-12

- Despliegue: tras arrancar, además de comprobar que responde el login, abre como administrador las páginas principales (Dashboard, instancias, proyectos, backups, contenedores, contactos, Todo, Actividad, Metrics, Docker, usuarios, Auditoría, Configuración, Ayuda, Acerca de, una instancia y un proyecto) contra la base real con manage.py smoke_check; si alguna falla, vuelve a la versión anterior. Habría detectado el Error 500 del 12/11.

## 1.0.88 — 2026-11-12

- Logs con tope: cada contenedor que crea el panel (Odoo, su PostgreSQL, las copias y las apps) y los servicios del propio panel (docker-compose) guardan como mucho 20 MB × 3 ficheros de log, para que un error en bucle no llene el disco. Los contenedores existentes lo reciben al recrearse (al redesplegar).

## 1.0.87 — 2026-11-12

- Dashboard: al pulsar CPU, Memoria o Disco se abre Metrics → Recursos con el uso por instancia ordenado por ese recurso (qué instancia consume qué). La tabla se ordena por CPU, RAM o disco pulsando las cabeceras y tiene una columna Disco por instancia (también las paradas): datos (base de datos y adjuntos), código y backups, medido cada 10 minutos o con «Medir el disco ahora».

## 1.0.86 — 2026-11-12

- Despliegue: el disco del servidor se llenó porque cada build copiaba en la imagen del panel todas las carpetas instances/ (el código de cada Odoo con su historial git); al fallar el build, el código nuevo quedaba en disco sin migrar y el panel daba Error 500 de forma intermitente. Ahora instances/, letsencrypt/ (claves de los certificados), ai_attachments/, staticfiles/ y traefik/ quedan fuera de la imagen (se montan al arrancar); el despliegue limpia la caché de build y las imágenes sin etiqueta si quedan menos de 5 GB libres, vuelve al código anterior si el build falla, y el panel no arranca si sus migraciones fallan (así el despliegue vuelve atrás en lugar de dejarlo a medias).

## 1.0.85 — 2026-11-12

- Ficha de la instancia en inglés: con el panel en EN, toda la página (pestañas, etiquetas, botones, ayudas, confirmaciones, el chat de IA y la consola) sale en inglés; en español queda igual que antes. Unos 240 textos nuevos en los catálogos de traducción.

## 1.0.84 — 2026-11-12

- Código: orchestrator/services/docker_service.py (1.780 líneas) dividido por áreas para cambiarlo con menos riesgo: docker_service (desplegar, arrancar, detener, eliminar), docker_databases (crear bases, contraseña del administrador, neutralizar), docker_copies (duplicar, renombrar), docker_backups (backups y restauraciones), docker_operations (logs, consola, pull, módulos, navegador, pip) y docker_helpers (funciones comunes). DockerService sigue siendo la misma clase con los mismos 42 métodos, idénticos; nada cambia para quien la usa.

## 1.0.83 — 2026-11-12

- Auditoría (menú, administradores): registro de quién hizo qué y desde qué IP, con filtros por acción, usuario y texto: inicios y cierres de sesión (también los fallidos), cada vez que se muestra o copia la Master Password o la contraseña del administrador, «Entrar como admin», restablecer la contraseña, cambios de configuración, tokens creados y revocados (también el .md para IA), usuarios creados, editados o eliminados y cambios en instancias (eliminar, renombrar, mover, límite de memoria, variables de entorno). Migración 0071.
- Seguridad: la Master Password y la contraseña del administrador ya no van dentro del HTML de la ficha; se piden al servidor al pulsar mostrar o copiar (y quedan en la Auditoría).

## 1.0.82 — 2026-11-12

- Backups fuera del servidor: en Configuración → Respaldos, con un bucket compatible con S3 (AWS S3, Backblaze B2, Cloudflare R2, Wasabi, MinIO…), cada backup manual o automático se sube también allí como tarea propia («Copiar backup fuera (S3)»), se marca con ☁ S3 en las listas y las copias más antiguas que los días indicados (30 por defecto) se borran del bucket. Botón «Probar conexión» (escribe, lee y borra un objeto de prueba sin guardar nada). La secret key no se muestra y, vacía, conserva la guardada. Nueva dependencia boto3; migración 0070.
- Backups automáticos: si alguno falla, llega una alerta.

## 1.0.81 — 2026-11-12

- Uso por instancia: Metrics → Recursos tiene una tabla con cada instancia (su Odoo y su PostgreSQL juntos), de la que más memoria usa a la que menos, con su CPU y cuánto de su límite de memoria gasta; y la ficha de la instancia muestra su uso ahora en Information (se mide en segundo plano, sin frenar la página).

## 1.0.80 — 2026-11-12

- Disponibilidad: cada 5 minutos el worker pide la página de login de cada instancia en marcha (por la red de Docker, saltando las que tienen una tarea en curso). Tras dos fallos seguidos la marca como «No responde» en la lista y en Information (con el motivo); si responde, muestra el tiempo de respuesta (migración 0069).
- Alertas (Configuración → General, activadas por defecto): tarea fallida, instancia que deja de responder o vuelve, disco por encima del 90 %, memoria 5 minutos por encima del 90 % y falta de certificado HTTPS (revisado cada hora). Por email a los «Emails para notificaciones» o a los administradores, con el SMTP de Configuración → Email, y opcionalmente a un webhook (Slack, Discord, Google Chat, n8n…). La misma alerta no se repite en 6 horas (24 la de certificado).

## 1.0.79 — 2026-11-12

- API y MCP: restablecer la contraseña del administrador de Odoo (POST /api/instances/{id}/reset-admin-password/ y la herramienta reset_admin_password), con la contraseña dada o una aleatoria que se devuelve al momento; solo para quien gestiona la instancia. get_instance del MCP incluye el administrador (usuario y contraseña) para quien gestiona la instancia.

## 1.0.78 — 2026-11-12

- Seguridad: las contraseñas que recibe una tarea (crear una base de datos, restablecer la del administrador) ya no se ven al consultar tareas por la API (/api/tasks/ las muestra como ••••••) y se borran de la tarea en cuanto termina, bien o mal; la del administrador queda en la ficha de la instancia. La migración 0068 las borra de las tareas ya terminadas.

## 1.0.77 — 2026-11-12

- Límite de memoria: no se aplica en marcha a una instancia que ya usa más del 90 % del nuevo tope (el sistema cortaría Odoo); queda pendiente y se reintenta cada minuto, o se aplica en el próximo despliegue.

## 1.0.76 — 2026-11-12

- Límite de memoria por instancia (Information, 1536 MB por defecto; 0 sin límite): tope de RAM del contenedor de Odoo para que una instancia no deje sin memoria al servidor ni a las demás. Se aplica en marcha con docker update, sin reiniciar: al guardarlo y cada minuto desde el worker, también a las instancias que ya estaban desplegadas (migración 0067). También por la API (memory_limit_mb, entre 256 y 32768 MB o 0).

## 1.0.75 — 2026-11-12

- Duplicar: la copia se neutraliza por defecto antes de arrancar su Odoo: servidores de correo entrante y saliente, tareas programadas (salvo la limpieza automática), métodos de pago y claves API desactivados y UUID de la base nuevo; en Odoo 16+ muestra la cinta «neutralizada». Casilla «Neutralizar la copia» en el formulario (marcada) y neutralize en la API (true por defecto). Las demos se neutralizan igual antes de arrancar (antes el correo se apagaba con Odoo ya en marcha), pero conservan sus tareas programadas.

## 1.0.74 — 2026-11-12

- Configuración → API: botón «Generar token y descargar .md» para dárselo a una IA. Crea un token personal nuevo (con el nombre que escribas o «IA» y la fecha) y descarga community-sh-api.md con el token, la URL base, con qué usuario y permisos actúa, cómo seguir las tareas, los errores, todos los endpoints, ejemplos con curl, una receta para dejar una instancia lista y, si el MCP está activo, cómo conectarlo. La tabla de endpoints de la pestaña y la del fichero salen de la misma lista (orchestrator/api_docs.py), que ahora incluye también GET/PATCH de una instancia y la lista de tareas.

## 1.0.73 — 2026-11-12

- Ayuda en inglés: con el panel en EN, el menú dice «Help» y la página se muestra en inglés (misma estructura e índice que la española). El botón «Limpiar» del Dashboard y su confirmación también están traducidos.

## 1.0.72 — 2026-11-12

- Menú «Ayuda» (debajo de «Acerca de»): explica cada proceso de Community SH, desde crear y gestionar instancias, accesos y contraseñas, código y módulos, dominios, backups, demos, contactos, IA, contenedores y limpieza de Docker hasta tareas, API/MCP, usuarios y actualizaciones del panel, con índice. Se actualiza con cada cambio.
- Dashboard: botón «Limpiar» (administradores) antes de «Nueva instancia». Pone en cola la misma limpieza que sigue a cada instancia nueva (contenedores detenidos ajenos, imágenes sin usar, caché de build y redes sin uso; nunca volúmenes), con confirmación; si ya hay una en cola no añade otra.
- Instancias: la etiqueta de la columna Estado («En ejecución») ya no se parte en dos líneas.

## 1.0.71 — 2026-11-12

- Limpieza automática tras crear una instancia: ahora también borra las imágenes etiquetadas que no usa ningún contenedor (por ejemplo odoo:16.0 si ya no queda ninguna instancia 16; las instancias detenidas conservan las suyas). Si luego se crea una instancia de esa versión, el despliegue la descarga otra vez. Los volúmenes siguen sin tocarse.

## 1.0.70 — 2026-11-12

- Limpieza automática de Docker tras crear una instancia (formulario, API/MCP, duplicar, desde respaldo y demos de «Modo test»): al terminar bien la creación se pone en cola una limpieza de contenedores detenidos que no son de ninguna instancia, imágenes sin etiqueta, caché de build y redes sin uso. No toca volúmenes (pueden tener datos; siguen requiriendo BORRAR en la limpieza manual) ni imágenes etiquetadas (la próxima instancia de esa versión tendría que descargarlas otra vez). Una sola limpieza en cola aunque se creen varias instancias seguidas; si hay un contenedor construyéndose se omite. Su resultado aparece en Docker → Limpieza y en Actividad.

## 1.0.69 — 2026-11-12

- Ficha de la instancia → Administrador: botón «Restablecer contraseña» para quien gestiona la instancia. Pone una contraseña nueva al administrador de Odoo (la que se escriba, 8-64 letras, números, «_» o «-», o una aleatoria si se deja vacío) en su base de datos (o en todas si la instancia no tiene una fija) y la guarda para verla y copiarla. Sirve también cuando la base de datos se creó fuera de la plataforma y la contraseña era desconocida. Se ejecuta como tarea (migración 0066).

## 1.0.68 — 2026-11-12

- Ficha de la instancia: nuevo bloque «Administrador» con el usuario y la contraseña del administrador de Odoo que creó la plataforma (base de datos creada desde la API/MCP o demo de «Modo test»), con botones para mostrar y copiar, para compartirlo. Solo lo ve quien gestiona la instancia (como la Master Password), también en la API (admin_login, admin_password, admin_database). Las copias lo heredan y la migración 0065 lo recupera de las bases de datos y demos ya creadas.

## 1.0.67 — 2026-11-07

- Actualización automática activada por defecto («Pull y reiniciar Odoo»): las instancias nuevas la traen puesta y la migración 0064 la activa en las existentes que la tenían desactivada, así todas siguen el último commit de sus ramas (con cada push y en la pasada diaria). Se puede desactivar o pasar a -u all en Módulos → Actualización automática.

## 1.0.66 — 2026-11-07

- Actualización automática: un push a un repositorio actualiza todas las instancias en marcha que usan ese repositorio y rama con la actualización automática activa, aunque el webhook sea de otra instancia (basta un webhook por repositorio). Además, cada día desde las 02:00 UTC (AUTO_UPDATE_HOUR) el worker hace pull de todas ellas, aunque el repositorio no tenga webhook o una entrega fallara. Estas actualizaciones solo hacen -u all y reinician Odoo si cambió algún commit o la configuración.

## 1.0.65 — 2026-11-06

- API y MCP: repositorios de módulos extra de una instancia (OCA, odoo/enterprise…). GET/POST /api/instances/{id}/repositories/ (url HTTPS, branch) y DELETE /api/instances/{id}/repositories/{repo_id}/; en el MCP, add_instance_repository y remove_instance_repository. Mismas validaciones que en la ficha (sin duplicados ni el repositorio principal) y solo para quien gestiona la instancia; se aplican en el próximo despliegue.

## 1.0.64 — 2026-11-04

- Instancias → Modules: «Variables de entorno» del contenedor de Odoo (NOMBRE=valor, una por línea), aplicadas en cada despliegue con la opción de redesplegar al guardar; solo las ve quien gestiona la instancia, HOST/USER/PASSWORD/PORT los pone la plataforma, las copias las heredan y las demos de «Modo test» no. También por la API: PATCH /api/instances/{id}/ con env_vars (se escriben; al leer solo se devuelven sus nombres en env_keys).

## 1.0.63 — 2026-11-04

- Proyectos: color de fondo para su tarjeta (paleta de 9 colores, también en modo oscuro) y etiquetas (separadas por comas, con sugerencias de las que ya existen y un color fijo por etiqueta). En «Proyectos» se filtra por etiqueta, con el número de proyectos de cada una; también por la API (color, tag_names).
- Instancias: «Mover» a otro de tus proyectos desde la ficha (su dirección no cambia).

## 1.0.62 — 2026-11-04

- API: crear una base de datos en una instancia (POST /api/instances/{id}/create-database/: nombre, idioma, sin datos de demostración y con contraseña de admin generada o dada) e instalar o actualizar un módulo en todas sus bases (POST /api/instances/{id}/install-module/), por ejemplo el tema Community SH. Así una instancia se crea, despliega, recibe su base y su tema solo con la API.

## 1.0.61 — 2026-11-04

- Instancias → Modules: botón «Instalar el tema Community SH» y campo para instalar o actualizar (-u) cualquier módulo disponible por su nombre técnico en todas las bases de la instancia, como tarea con su log (si falla, la base queda como estaba).

## 1.0.60 — 2026-11-04

- Página principal: el menú superior va en dos filas (arriba el logo, el idioma, el tema, GitHub y el acceso al panel; debajo las secciones), así cabe todo sin partir textos; en el móvil las secciones se desplazan de lado.

## 1.0.59 — 2026-11-04

- Contactos como CRM: tablero Kanban con las columnas Contactado, Demo, Propuesta, A la espera, Ganado y Perdido; los contactos se arrastran de columna (o se mueven con el selector de su tarjeta). Quien pide una demo entra en «Demo». Se pueden crear contactos a mano y editar todos sus datos; la vista de lista y el CSV incluyen la etapa.

## 1.0.58 — 2026-11-04

- Dashboard: las tarjetas de CPU, memoria y disco se pintan enteras según el uso: rojo por encima del 90 %, naranja entre el 50 y el 90 % y verde por debajo del 50 %.

## 1.0.57 — 2026-11-04

- Demos: clave de API por proyecto (tarjeta «Modo test» → Generar clave), para que el servidor de tu web pida demos sin captcha con Authorization: Bearer csh_demo_… en POST /api/public/demos/{url}/. Solo sirve para las demos de ese proyecto, se guarda cifrada, se muestra una vez y se puede regenerar (la anterior deja de funcionar). Se mantienen el límite por email al mes, el diario y el de demos a la vez.

## 1.0.56 — 2026-11-04

- Docker → Contenedores: botón «Eliminar todo lo no en uso», que borra de una vez los contenedores detenidos, las imágenes (sin etiqueta y sin usar), la caché de build, las redes y los volúmenes sin uso. Muestra antes qué y cuánto se libera y se confirma escribiendo BORRAR; nunca toca el panel, las instancias (aunque estén paradas), sus filestores y redes, ni los contenedores del panel y sus volúmenes.

## 1.0.55 — 2026-11-04

- Contactos: nuevo menú con las personas que piden una demo (página pública o API): nombre, email, empresa, cargo, teléfono, país, sus demos y notas propias. Un contacto por email que se actualiza con los datos más nuevos y se conserva aunque la demo se elimine; búsqueda, filtros por país y proyecto, exportar a CSV, KPI en el Dashboard y API /api/contacts/. Los contactos de las demos ya pedidas se crean al actualizar.

## 1.0.54 — 2026-11-04

- Instancias: actualización automática al hacer push. En Módulos se elige qué hacer cuando llega un push a la rama de uno de sus repositorios (el principal o los de addons): «Pull y reiniciar Odoo» o «Pull y actualizar todos los módulos (-u all)». Botón «Crear webhook en GitHub» (con el token del dueño) o URL y secreto para añadirlo a mano; los webhooks van firmados, se ignoran otros repositorios y ramas, y varios push seguidos se juntan en una sola actualización.

## 1.0.53 — 2026-11-04

- Despliegue automático: funciona aunque el servidor tenga letsencrypt/acme.json marcado con skip-worktree o assume-unchanged (git se negaba a cambiar de versión: «Entry 'letsencrypt/acme.json' not uptodate»).

## 1.0.52 — 2026-11-04

- Despliegue automático: si falla, el resumen del run muestra el error real del servidor (por ejemplo, que la carpeta no es un repositorio git) en lugar de solo el código de salida.

## 1.0.51 — 2026-11-04

- Despliegue automático: el host, el usuario, el puerto, la ruta y known_hosts valen como secretos o como variables del repositorio, y si falta algo el error dice exactamente qué.

## 1.0.50 — 2026-11-04

- Despliegue automático: los tests y el despliegue corren en Ubuntu 24.04 fijo (GitHub moverá ubuntu-latest a Ubuntu 26).

## 1.0.49 — 2026-11-04

- Despliegue automático: cada push a main pasa los tests en GitHub Actions y, si van bien, despliega en el servidor por SSH (scripts/deploy.sh): espera a las tareas en curso, guarda una copia de la base del panel (si falla, no despliega), conserva .env, instancias, backups y certificados, reconstruye el panel y vuelve a la versión anterior si no responde.

## 1.0.48 — 2026-11-04

- Seguridad (revisión completa): los contenedores genéricos ya no pueden llamarse como los del panel (app, db, traefik…) ni sustituir un contenedor de Docker ajeno; quien no es administrador no puede añadir volúmenes a una plantilla ni montar el de otro recurso (la base del panel, el filestore de una instancia).
- API: las instancias exponen una lista fija de campos; el volumen de datos, el subdominio, las rutas de certificados y la contraseña maestra ya no se pueden escribir, y el nombre se cambia solo con «Renombrar». Los clientes ya no ven la contraseña maestra (ni en la ficha ni en la API).
- Repositorios y ramas: solo URLs HTTPS y ramas que no empiezan por guion, en el formulario, la API y los repositorios extra; git solo usa HTTPS.
- Demos: sin asistente de IA (su visitante es administrador de Odoo); la copia se entrega con el correo desactivado, sin claves API, con contraseñas desconocidas para los demás usuarios y con el secreto de la base regenerado. Las plazas se comprueban de forma atómica, hay un máximo para todo el servidor (TRIAL_MAX_ACTIVE_TOTAL, 4) y no se crea una demo si falta memoria. La IP del visitante es la que añade Traefik y la página de credenciales no se guarda en caché.
- Acceso: el bloqueo por intentos fallidos cuenta por usuario normalizado y dirección (5) y por cuenta (20); /admin/login/ pasa por el login del panel (con 2FA); desactivar o cambiar el 2FA pide un código actual; los tokens de la API y de MCP exigen 2FA cuando es obligatorio.
- Con dominio y HTTPS: cookies solo por HTTPS, HSTS, el panel solo responde a su dominio y su IP, y el puerto de Odoo y el 8000 del panel escuchan solo en el propio servidor (todo pasa por Traefik). El instalador crea el administrador con una contraseña aleatoria.
- Un dominio propio no puede tomar el subdominio de otra instancia o contenedor; Traefik solo recibe nombres de host válidos. Los ZIP subidos (módulos y backups) se comprueban antes de descomprimir (rutas, número de archivos y tamaño). Los iconos (lucide) se cargan en una versión fija.
- Manual de usuario en PDF, en español e inglés, con capturas, descargable desde la página principal.
- Correo saliente: Configuración → Email (servidor SMTP, seguridad, usuario, remitente) con botón «Enviar prueba». Con él activo, las notificaciones salen por ese servidor y, al crear una demo, el cliente recibe por email su dirección, usuario y contraseña.
- Demos: el formulario pide también empresa, cargo, teléfono y país, y tiene un captcha propio (una suma firmada por el servidor, de un solo uso). Configuración → Demos: límite de demos al día (10) y de demos a la vez en todo el servidor (4).
- Demos: la ficha de una demo muestra los días que le quedan para detenerse y para eliminarse; también en la ficha del proyecto.
- API: pedir una demo desde otra web (POST /api/public/demos/{url}/ con el captcha, o /api/demos/ con token), seguir su estado, configurar el modo test de un proyecto y, para administradores, el correo y los límites (/api/settings/).
- Dashboard: nuevo menú con las cifras principales de Community SH (instancias, contenedores, backups, tareas, demos, servidor y seguridad), cada una enlazada a su página. La ficha del proyecto tiene sus propios KPIs.
- Proyectos: botón «Nuevo contenedor»; los contenedores pueden pertenecer a un proyecto y aparecen en su ficha.
- Arreglo: el blog daba Server Error (500) con artículos cuyo autor se había borrado.

## 1.0.47 — 2026-11-04

- Proyectos: casilla «Modo test». Pide la URL de la página de demos (p. ej. `/bim`), los días de prueba (15 por defecto), el proyecto hermano donde se crean las demos, el texto para el usuario y cuántas demos puede haber a la vez.
- Página pública `/url`: el visitante elige la versión entre las instancias en marcha del proyecto (con su descripción), deja sus datos y recibe una copia propia en el proyecto hermano con una contraseña nueva para el administrador.
- Mientras se crea, la página muestra una barra de progreso con el paso en curso; al terminar, la dirección, el usuario y la contraseña.
- Una demo por email al mes (y como mucho 3 al mes desde la misma conexión). Al vencer se detiene y 7 días después se elimina.
- Instancias: «Descripción (demos)», editable en su ficha. API pública `/api/public/demos/{url}/` (sin token, con CORS) para mostrar las versiones en tu web.

## 1.0.46 — 2026-11-02

- Docker: botón «Limpiar lo no utilizado» y pestaña «Limpieza» con lo que se puede liberar (cuántos y cuánto ocupa): contenedores detenidos, imágenes sin etiqueta, imágenes sin usar, caché de build, redes y volúmenes sin uso. Se elige qué limpiar y corre como tarea con su log en Actividad.
- La limpieza nunca toca el panel, las instancias (aunque estén paradas), sus filestores y redes ni los contenedores del panel y sus volúmenes; las imágenes sin usar y los volúmenes hay que marcarlos a mano (los volúmenes, escribiendo BORRAR). No corre mientras se construye un contenedor.
- Arreglo: «Eliminar detenidos» borraba también los contenedores de las instancias paradas, y con ellos su base de datos; ahora sigue las mismas reglas.

## 1.0.45 — 2026-11-02

- Contenedores: plantilla ERPSqlite (ERP con API compatible con la de Odoo, para MultiERP Móvil). Se construye desde su repositorio al crearla y arranca sola al terminar.
- Las plantillas pueden construirse desde un repositorio (`git_repo`, `dockerfile`) y generar claves aleatorias con `{secret}`, que se ven en la página del contenedor.
- API: `/api/tasks/{id}/` devuelve también el log, el progreso y el paso en curso, como la página Actividad.

## 1.0.44 — 2026-11-02

- API: contenedores Docker en `/api/containers/` (crear, arrancar, detener, recrear, logs y eliminar), con los mismos límites que el formulario para quien no es administrador.
- Contenedores construidos desde un repositorio (también privado, con el token del propietario) y un Dockerfile, como tarea con su log en un worker propio (`build-worker`) para no frenar despliegues ni backups.
- Cada contenedor tiene `https://nombre.dominio` con certificado, como las instancias; parado deja de tener ruta.
- API: crear una instancia también la despliega y devuelve el `task_id` (antes quedaba en «deploying» sin desplegarse hasta llamar a `/deploy/`).
- API: `/api/tasks/` muestra también tus tareas sin instancia, como construir un contenedor.

## 1.0.43 — 2026-10-30

- Demos: varias bases en una instancia y un certificado, abiertas con `https://dominio/?nombre` (Odoo 18 a 20). Se activa con «Base por defecto de las demos».
- Copias de seguridad: una instancia con varias bases guarda una copia de cada una.

## 1.0.42 — 2026-10-30

- Repositorio principal: se clona y actualiza con el token del propietario, así que los repositorios privados ya funcionan.
- Si no se puede obtener el código, el despliegue falla en lugar de terminar con los módulos vacíos; un fallo al actualizar conserva el código que había.

## 1.0.41 — 2026-10-30

- Dominios: una instancia parada deja de tener ruta en Traefik y no gasta certificados; la recupera al reiniciarla.
- La ficha de la instancia avisa cuando falta el certificado y explica por qué (límite semanal de Let's Encrypt, DNS...).

## 1.0.40 — 2026-10-30

- Módulos: botón «Pull» que trae los últimos commits del repositorio principal y de los de módulos y reinicia Odoo, como tarea con su log y barra, sin redesplegar ni actualizar todos los módulos

## 1.0.39 — 2026-10-30

- Módulos: opción «Navegador (WhatsApp Web)» por instancia: instala Google Chrome en el contenedor de Odoo (como root, con su log y barra de progreso) y lo reinstala solo en cada despliegue, porque el contenedor se recrea; la imagen de Odoo no trae navegador y el chromium de Ubuntu es un snap que Docker no puede ejecutar

## 1.0.38 — 2026-10-30

- Restart de una instancia: si su base de datos estaba parada (por ejemplo tras reiniciar el servidor), la arranca antes que Odoo y deja las dos con reinicio automático; «Entrar como admin» dice que la base de datos está parada en vez de «todavía no tiene base de datos»

## 1.0.37 — 2026-10-30

- Reinicios del servidor: la base de datos del panel, las instancias de Odoo y su PostgreSQL vuelven a arrancar solas (antes quedaban paradas y el panel respondía Server Error 500); una instancia parada desde el panel sigue parada

## 1.0.36 — 2026-10-29

- Consola e «Instalar desde requirements.txt»: pip instala los paquetes para el usuario odoo en el volumen de datos (/var/lib/odoo/.local), así funciona en Odoo 17-20 (antes Debian lo rechazaba: «externally-managed-environment») y el paquete se conserva al redesplegar

## 1.0.35 — 2026-10-29

- Actividad: cada tarea (desplegar, respaldar, restaurar, duplicar, instalar módulos, migrar…) guarda su log completo con la hora —lo que imprime el servidor y sus avisos— y una barra de progreso con el paso en curso, que avanzan en directo en la pestaña «Tareas recientes» y en la nueva página «Actividad» del menú (todas las tareas, con filtros por estado, tipo e instancia y el log completo de cada una)

## 1.0.34 — 2026-10-29

- Instancia: «Tareas recientes» pasa a su propia pestaña (con un punto azul mientras hay tareas en curso); la pestaña abierta queda en la URL y se conserva al recargar

## 1.0.33 — 2026-10-29

- Tema: los iconos de las apps vuelven a verse en Odoo 20 (Odoo 20 lee los campos binarios como adjuntos; ahora se sirven por /web/image)

## 1.0.32 — 2026-10-28

- Documentación: cómo crear el token de GitHub para repos privados (clásico y fine-grained) en el README y en Configuración → Ayuda, y qué significa el error 403

## 1.0.31 — 2026-10-28

- Tema: los iconos de la pantalla de inicio van dentro de una tarjeta blanca con margen, como en Odoo Enterprise

## 1.0.30 — 2026-10-28

- GitHub: los tokens fine-grained (github_pat_) ya clonan repos privados; antes GitHub respondía 403 «Write access to repository not granted»
- Tema: pantalla de inicio clara con bandas diagonales, iconos con sombra suave, búsqueda al empezar a escribir y la versión de Odoo abajo a la izquierda

## 1.0.29 — 2026-10-28

- Botón «Admin» (entrar como admin) también en la lista de instancias

## 1.0.28 — 2026-10-28

- Tema: la barra superior de Odoo 18-20 ya no deja los menús de la app en morado; iconos de la pantalla de inicio menos redondeados

## 1.0.27 — 2026-10-28

- Tema: al entrar en una app desde la pantalla de inicio ya no te devuelve a la cuadrícula (Odoo 18-20 abría la pantalla de inicio otra vez)

## 1.0.26 — 2026-10-28

- Landing: sección «Mis proyectos» antes del pie, leída de TicketPro en el servidor (token en .env, caché de 15 minutos)
- Instalación: los workers ya no intentan descargar la imagen del panel de Docker Hub

## 1.0.25 — 2026-10-28

- README con capturas de la app y la lista de funcionalidades al día

## 1.0.24 — 2026-10-28

- Contadores en el menú lateral: proyectos, instancias, contenedores, Docker, tareas pendientes, backups y usuarios
- Todo: las tareas completadas se ocultan hasta pulsar «Hechas»
- En la landing, el botón «Ir al panel» muestra tu foto cuando has iniciado sesión
- Paginación de 20 filas en todas las listas (proyectos, instancias, backups, usuarios, contenedores, Todo y Docker), conservando los filtros

## 1.0.23 — 2026-10-28

- Odoo 8 y 9: se despliegan, crean base de datos y pasan backup, exportar, importar, duplicar y crear desde backup
- Puertos fijos: Odoo se publica en un puerto explícito que no cambia al reiniciar el contenedor o el servidor, y el worker corrige cada minuto los enlaces de las instancias antiguas
- Chat y notificaciones de Odoo verificados en 8-20: longpolling (8-15) y websocket (16-20), también a través de Traefik
- IA: adjunta PDF, imágenes o archivos de texto; en peticiones largas arma un plan visible que va marcando paso a paso, se puede detener y corre en su propio worker (ai-worker)
- IA desde Odoo: escribe «/ia …» en el chatter de cualquier registro (Odoo 9-20) y la respuesta, con el resultado de la instalación, llega a ese chatter (módulo community_sh_ai, se instala solo)
- IA más fiable: consulta campos y vistas reales de Odoo, valida manifiestos, Python y XML antes de escribir, espera el resultado de la instalación y corrige los errores
- Migrar desde otro Odoo (8+) por XML-RPC a instancias Odoo 14+: contactos, categorías, productos y variantes, ventas, compras, facturas y pagos; se puede repetir sin duplicar
- Tema Community SH para Odoo 15-20: barra clara, formularios como tarjetas y pantalla de inicio con las apps en iconos (diseño propio, sin código de Enterprise)
- Arreglos: duplicar ya no falla si Postgres tarda en arrancar; módulos nuevos de la IA se reconocen en Odoo 8-10

## 1.0.22 — 2026-10-28

- Landing: cabecera con una galaxia animada, cohetes que la cruzan y estrellas que deja el ratón (estática si el sistema pide reducir el movimiento)
- Landing rediseñada: más aire entre secciones, titular con más peso, mockup con profundidad, funcionalidades agrupadas en 4 pilares, sección oscura flotante con bordes suaves y pasos de instalación en azul unidos por una línea

## 1.0.21 — 2026-10-28

- API: botón «Generar token» en la pestaña API de Configuración; el token nuevo se muestra una vez con botón de copiar y los ejemplos (curl, Claude) ya lo incluyen

## 1.0.20 — 2026-10-28

- Todo: KPIs de tareas hechas, sin terminar, en curso y porcentaje completado
- Todo: el formulario de nueva tarea se abre con el botón «Nueva tarea»; las tareas se pueden editar y las completadas muestran su descripción
- Icono de llave en los accesos «Entrar como admin»

## 1.0.19 — 2026-10-28

- Entrar como admin también en Odoo 10 y 11: entra con un administrador propio del panel («Administrador (Community SH)») con contraseña aleatoria; la contraseña del admin no se toca

## 1.0.18 — 2026-10-28

- El instalador deja HTTPS listo: pide el email de Let's Encrypt y Traefik emite y renueva los certificados del panel y de cada instancia
- Cada instancia tiene su subdominio cliente-versión-nombre (p. ej. acme-20-produccion.tudominio.com), cubierto por un único registro DNS *.tudominio.com
- Las rutas de Traefik se regeneran al arrancar y al cambiar el dominio en Settings; Odoo corre con proxy_mode detrás del proxy

## 1.0.17 — 2026-10-28

- Entrar como admin en Odoo 12-20 sin contraseña desde la instancia o el proyecto: enlace firmado, de un solo uso y válido 60 segundos (módulo community_sh_login, cargado como server-wide)

## 1.0.16 — 2026-10-28

- Historial de Metrics con horas y minutos en los ejes y fecha y hora completas en el tooltip

## 1.0.15 — 2026-10-28

- Importar backups del gestor de bases de datos de Odoo (.zip con dump.sql y filestore) y volcados .dump, además de los del panel
- Menú Backups → «Importar un backup y crear una instancia» (detecta la versión de Odoo y la base) y «Restaurar desde un archivo» en cada instancia
- Backups probados en las 11 versiones (10 a 20): crear, exportar, importar, duplicar y crear instancia desde backup
- Si la IA no consigue instalar un módulo, la base queda como estaba (antes Odoo dejaba de ejecutar sus tareas programadas)

## 1.0.14 — 2026-10-28

- Favicon propio en el panel y la página principal

## 1.0.13 — 2026-10-28

- API REST completa con tokens personales (Bearer): proyectos, instancias (desplegar, reiniciar, detener, backup, duplicar), backups (descargar, restaurar), tareas y Todo
- Settings → API: URL base, autenticación, ejemplos con curl y tabla de endpoints

## 1.0.12 — 2026-10-28

- Metrics: gráficas del uso de CPU y RAM del servidor en las últimas 24 horas, 7 días, 30 días y 12 meses (media y pico)
- El worker guarda una muestra por minuto (2 días) y resúmenes por hora (120 días) y por día (sin límite)

## 1.0.11 — 2026-10-28

- Menú Todo: tareas del equipo (por hacer, en curso, completadas) con nota de lo realizado y la versión en que se completó
- Claude puede listar, añadir y completar tareas de Todo desde el servidor MCP

## 1.0.10 — 2026-10-28

- Restaurar un backup ya funciona con Odoo en marcha: se detiene Odoo y se cierran sus conexiones antes de recrear la base (antes el borrado fallaba en silencio y la restauración no hacía nada)
- La restauración informa del error si no puede borrar o crear la base; el filestore restaurado queda con los permisos correctos

## 1.0.9 — 2026-10-28

- Eliminar un proyecto con todo: sus instancias, contenedores, bases de datos, filestores, workspaces y backups (confirmación escribiendo el nombre; lo ejecuta el worker)
- Al borrar una instancia también se borran los archivos de sus backups (antes quedaban huérfanos en disco)

## 1.0.8 — 2026-10-28

- Novedades de la página principal paginadas (3 versiones por página)

## 1.0.7 — 2026-10-28

- Chat de IA: botón «Deshacer estos cambios» en cada respuesta que modificó archivos; restaura los archivos (también los de peticiones posteriores) y actualiza los módulos afectados
- La IA también puede volver atrás cuando se lo pides (herramienta undo_last_change)

## 1.0.6 — 2026-10-28

- Chat de IA: etiqueta módulos propios con @ (autocompletado) para que la IA trabaje sobre ellos
- La IA lee los módulos de los repositorios extra (solo lectura) y los extiende con un módulo nuevo en addons

## 1.0.5 — 2026-10-28

- Menú lateral minimizable: deja solo los iconos (con el nombre al pasar el ratón) y recuerda la preferencia en el navegador

## 1.0.4 — 2026-10-28

- Servidor MCP para Claude (Claude Code, Claude Desktop) en /mcp/: listar proyectos e instancias, ver logs, desplegar, reiniciar, detener, crear y listar backups y seguir tareas
- Settings → MCP (Claude): activación por el administrador, tokens personales (se guardan cifrados con hash, se muestran una sola vez) e instrucciones de conexión
- Claude actúa con los permisos del usuario del token: un cliente solo ve y opera sus proyectos

## 1.0.3 — 2026-10-28

- Documentación: configurar el DNS del dominio antes de instalar (README, guía de despliegue y landing)
- El instalador avisa del registro DNS necesario y comprueba que el dominio apunta al servidor antes de seguir
- El instalador ya lee el dominio con «curl … | sudo bash» (antes la pregunta leía el propio script)

## 1.0.2 — 2026-10-28

- Todas las versiones de Odoo (10 a 20) se despliegan: probadas una a una creando base de datos e iniciando sesión
- Odoo 20: PostgreSQL 16 y escucha en todas las interfaces (antes solo 127.0.0.1)
- PostgreSQL según la versión de Odoo; una base vacía con versión incompatible se recrea sola
- Odoo 10-15 en Mac/servidores ARM: descarga automática de la imagen amd64 (emulada)
- odoo.conf se monta como carpeta (evita fallos de montaje en Docker Desktop) y la carpeta de addons se monta siempre
- Configuración de IA (ChatGPT) en Settings → IA, con prueba de conexión y lista de modelos
- Asistente de IA en cada instancia: crea y modifica módulos en sus addons y los instala en segundo plano
- Varios repositorios de GitHub por instancia (se clonan y se añaden al addons_path; los privados usan el token del dueño)
- Odoo 10: usa odoo.conf (antes arrancaba con la configuración por defecto y la master password no funcionaba)
- Blog accesible con sesión iniciada y dos artículos nuevos; sección Novedades en la página principal
- Barra superior y menú lateral fijos al hacer scroll

## 1.0.1 — 2026-10-28

- Proyectos: cada instancia pertenece a un proyecto y se muestra como proyecto / instancia
- Clientes: el cliente de un proyecto es un usuario; con la casilla "Cliente" solo ve y opera sus proyectos
- Menús Backups (todos los respaldos) y Docker (contenedores, imágenes, volúmenes, redes)
- Despliegues, backups y restauraciones en segundo plano con un worker (sustituye a cron)
- Métricas en tiempo real; modo claro y oscuro; nueva landing; idiomas español e inglés
- Odoo 20.0; PostgreSQL adecuado a cada versión de Odoo; imágenes antiguas (10-15) emuladas en servidores ARM
- Seguridad: API con login, dueños por instancia, 2FA obligatorio real, bloqueo por intentos, contraseña maestra por instancia
- Datos: el filestore ya no se pierde al redesplegar; Postgres vía DATABASE_URL con migración automática desde SQLite

## 1.0.0 — 2025-12-31

- Gestión completa de instancias Odoo (crear, desplegar, detener, reiniciar, eliminar)
- Orquestación de contenedores Docker con PostgreSQL 13
- Soporte multi-versión de Odoo (10.0 - 19.0)
- Integración con repositorios GitHub para módulos personalizados
- Sistema completo de backup y restauración
- Crear nuevas instancias desde backups existentes
- Logs en tiempo real y acceso a consola de contenedores
- Gestión de certificados SSL/TLS con Let's Encrypt
- Configuración de dominios personalizados
- Monitoreo de recursos y métricas de contenedores
- Autenticación de usuarios y gestión de perfiles
- Interfaz con pestañas para detalles de instancia
- Sistema de nomenclatura automática para instancias desde backup (name-copy-N)
- Detección automática de bases de datos
- Respaldo de filestore desde contenedores Docker
