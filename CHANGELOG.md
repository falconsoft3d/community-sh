# Changelog

Versión actual: **1.0.17**. Cada commit o mejora sube el número de parche (1.0.1 → 1.0.2 → …).

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
