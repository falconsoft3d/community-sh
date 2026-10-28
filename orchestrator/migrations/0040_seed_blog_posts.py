from django.db import migrations

POSTS = [
    {
        'slug': 'proyectos-y-clientes-en-community-sh',
        'title': 'Proyectos y clientes: organiza tus instancias de Odoo',
        'excerpt': 'Agrupa las instancias de cada cliente en un proyecto y dale acceso para que vea y opere solo lo suyo.',
        'content': """Cuando gestionas Odoo para varios clientes, las instancias se multiplican: producción, staging, pruebas de actualización... Community SH las organiza en **proyectos**.

## Un proyecto por cliente

Cada instancia pertenece a un proyecto y se muestra siempre como `proyecto / instancia`. Desde el menú **Proyectos** ves cuántas instancias tiene cada uno y cuántas están en ejecución, y desde el detalle del proyecto creas instancias nuevas ya asignadas a él.

Ejemplo típico:

- `ACME / produccion` — Odoo 18 con dominio propio y backups diarios
- `ACME / staging` — duplicada de producción para probar cambios
- `ACME / v19-prueba` — creada desde un backup para ensayar la migración

## El cliente es un usuario

En el formulario del proyecto eliges qué **usuario** es su cliente. Ese usuario, al entrar al panel, ve el proyecto y sus instancias y puede **operarlas**: abrir Odoo, ver logs y la master password, reiniciar, desplegar y crear o descargar backups.

Si además marcas la casilla **Cliente** en Usuarios, no podrá crear, borrar, duplicar ni renombrar nada, ni usar la consola o restaurar backups. Así el cliente tiene autonomía sin riesgo para su producción.

## Backups por proyecto

El menú **Backups** reúne todos los respaldos y se filtra por proyecto: en un vistazo sabes qué hay de cada cliente y lo descargas o restauras desde ahí.
""",
    },
    {
        'slug': 'novedades-community-sh-1-0-2',
        'title': 'Novedades de Community SH 1.0.2: de Odoo 10 a Odoo 20',
        'excerpt': 'Todas las versiones de Odoo probadas una a una, PostgreSQL adecuado a cada versión y un asistente de IA que escribe módulos.',
        'content': """La versión 1.0.2 se centra en que **todas las versiones de Odoo funcionen**, y añade un asistente de IA.

## Odoo 10 a 20, probados uno a uno

Hemos desplegado cada versión, creado una base de datos e iniciado sesión como administrador. Por el camino se corrigieron varios problemas:

- **PostgreSQL según la versión**: Odoo 20 exige PostgreSQL 16 y las versiones antiguas no funcionan con los más nuevos. Cada instancia recibe ahora el Postgres adecuado (10, 12, 13, 15 o 16).
- **Odoo 20 escuchaba solo en 127.0.0.1**: ahora escucha en todas las interfaces, así que es accesible por su puerto y por su dominio.
- **Servidores ARM** (como los Mac con Apple Silicon): las imágenes de Odoo 10 a 15 solo existen para amd64; el panel las descarga y las ejecuta emuladas automáticamente.
- **Configuración más robusta**: `odoo.conf` se monta como carpeta, lo que evita fallos de montaje en Docker Desktop.

## Asistente de IA

Configura tu clave de OpenAI en **Settings → IA** (el botón *Probar conexión* te muestra los modelos disponibles) y en cada instancia aparecerá la pestaña **IA**. Pídele, por ejemplo:

> Crea un módulo que añada un campo "Código interno" a los contactos y lo muestre en el formulario.

El asistente escribe el módulo en la carpeta de addons de la instancia y lo instala en segundo plano. Puedes seguir el progreso en *Tareas recientes*.

## Y además

Varios repositorios de GitHub por instancia, métricas en tiempo real, modo claro y oscuro, español e inglés, y el número de versión visible en la web. Consulta todas las novedades en la sección *Novedades* de la página principal.
""",
    },
]


def create_posts(apps, schema_editor):
    db = schema_editor.connection.alias
    BlogPost = apps.get_model('orchestrator', 'BlogPost')
    User = apps.get_model('auth', 'User')
    author = User.objects.using(db).filter(is_superuser=True).order_by('id').first()
    for post in POSTS:
        BlogPost.objects.using(db).get_or_create(slug=post['slug'], defaults={
            **post, 'author': author, 'published': True, 'featured': True,
        })


class Migration(migrations.Migration):

    dependencies = [
        ('orchestrator', '0039_blog_author_optional'),
        migrations.swappable_dependency('auth.User'),
    ]

    operations = [
        migrations.RunPython(create_posts, migrations.RunPython.noop),
    ]
