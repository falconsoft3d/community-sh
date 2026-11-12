"""Public website: landing page, blog and about."""

from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from ..permissions import (
    get_global_config,
)


# Home view
def home(request):
    """Home/landing page"""
    from django.shortcuts import redirect
    
    # Check if public website is enabled
    try:
        config = get_global_config()
        if config and not config.public_website_enabled:
            # If user is already authenticated, go to dashboard
            if request.user.is_authenticated:
                return redirect('instance-list')
            # Otherwise redirect to login
            return redirect('login')
    except:
        pass
    
    from ..blog_models import BlogPost
    from ..models import Instance
    from ..permissions import is_registration_enabled
    from ..template_services import get_template_loader
    
    featured_posts = BlogPost.objects.filter(published=True, featured=True)[:3]
    # App catalog comes from container_templates/*.yaml ("n8n - Workflow Automation" -> "n8n")
    apps = [
        template['display_name'].split(' - ')[0]
        for template in get_template_loader().list_available_templates()
        if template['name'] != 'custom'
    ]
    odoo_versions = [value for value, _label in Instance._meta.get_field('odoo_version').choices]
    from django.core.paginator import Paginator
    from config.version import CHANGELOG
    releases = Paginator(CHANGELOG, 3).get_page(request.GET.get('novedades'))
    from ..services.showcase import my_projects
    return render(request, 'orchestrator/home.html', {
        'my_projects': my_projects(exclude_host=request.get_host().split(':')[0]),
        'changelog': releases,
        'featured_posts': featured_posts,
        'apps': apps,
        'odoo_versions': odoo_versions,
        'registration_enabled': is_registration_enabled(),
        'manual_topics': [
            ('folder-kanban', 'Proyectos'), ('server', 'Instancias de Odoo'), ('archive', 'Copias de seguridad'),
            ('flask-conical', 'Demos para clientes'), ('code', 'API pública'), ('shield-check', 'Seguridad'),
        ],
    })


def blog_list(request):
    """Blog list page"""
    from django.shortcuts import redirect
    
    # Check if public website is enabled
    try:
        config = get_global_config()
        if config and not config.public_website_enabled:
            if request.user.is_authenticated:
                return redirect('instance-list')
            return redirect('login')
    except:
        pass
    
    from ..blog_models import BlogPost
    posts = BlogPost.objects.filter(published=True)
    return render(request, 'orchestrator/blog_list.html', {'posts': posts, 'public_page': True})


def blog_detail(request, slug):
    """Blog post detail page"""
    from django.shortcuts import redirect
    
    # Check if public website is enabled
    try:
        config = get_global_config()
        if config and not config.public_website_enabled:
            if request.user.is_authenticated:
                return redirect('instance-list')
            return redirect('login')
    except:
        pass
    
    from ..blog_models import BlogPost
    post = get_object_or_404(BlogPost, slug=slug, published=True)
    
    # Render markdown to HTML
    import markdown
    
    md = markdown.Markdown(extensions=[
        'extra',
        'codehilite',
        'fenced_code',
        'tables',
        'toc'
    ])
    post.html_content = md.convert(post.content)
    
    return render(request, 'orchestrator/blog_detail.html', {'post': post, 'public_page': True})


@login_required
def about(request):
    """About page with version history"""
    from config.version import CHANGELOG, VERSION
    return render(request, 'orchestrator/about.html', {
        'current_version': VERSION,
        'versions': CHANGELOG,
    })


# Sections of the Ayuda page (anchor, Spanish title, English title), in order: add one here when
# help.html and help_en.html get a new section
HELP_SECTIONS = [
    ('conceptos', 'Conceptos y permisos', 'Concepts and permissions'),
    ('crear-instancia', 'Crear una instancia', 'Create an instance'),
    ('gestionar', 'Gestionar una instancia', 'Manage an instance'),
    ('acceso', 'Acceso a Odoo y contraseñas', 'Odoo access and passwords'),
    ('codigo', 'Código y módulos', 'Code and modules'),
    ('dominios', 'Dominios y HTTPS', 'Domains and HTTPS'),
    ('backups', 'Backups', 'Backups'),
    ('demos', 'Demos (Modo test)', 'Demos (Test mode)'),
    ('contactos', 'Contactos (CRM)', 'Contacts (CRM)'),
    ('ia', 'IA y migraciones', 'AI and migrations'),
    ('contenedores', 'Contenedores', 'Containers'),
    ('limpieza', 'Docker y limpieza', 'Docker and cleanup'),
    ('tareas', 'Tareas y Actividad', 'Tasks and Activity'),
    ('panel', 'Dashboard, Metrics y Todo', 'Dashboard, Metrics and Todo'),
    ('api', 'API y MCP', 'API and MCP'),
    ('cuenta', 'Usuarios y configuración', 'Users and settings'),
    ('actualizaciones', 'Actualizaciones del panel', 'Panel updates'),
]


@login_required
def help_page(request):
    """Ayuda / Help: how every process of the platform works (kept current with every change), in the panel's language."""
    from django.utils.translation import get_language
    english = (get_language() or '').startswith('en')
    sections = [(anchor, en if english else es) for anchor, es, en in HELP_SECTIONS]
    return render(request, 'orchestrator/help_en.html' if english else 'orchestrator/help.html', {'sections': sections})
