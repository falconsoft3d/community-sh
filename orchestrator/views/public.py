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
    featured_posts = BlogPost.objects.filter(published=True, featured=True)[:3]
    return render(request, 'orchestrator/home.html', {'featured_posts': featured_posts})


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
    return render(request, 'orchestrator/blog_list.html', {'posts': posts})


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
    
    return render(request, 'orchestrator/blog_detail.html', {'post': post})


@login_required
def about(request):
    """About page with version history"""
    versions = [
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
                'Gestión de certificados SSL/TLS con Let\'s Encrypt',
                'Configuración de dominios personalizados',
                'Monitoreo de recursos y métricas de contenedores',
                'Autenticación de usuarios y gestión de perfiles',
                'Interfaz con pestañas para detalles de instancia',
                'Sistema de nomenclatura automática para instancias desde backup (name-copy-N)',
                'Detección automática de bases de datos',
                'Respaldo de filestore desde contenedores Docker',
            ]
        }
    ]
    
    return render(request, 'orchestrator/about.html', {
        'current_version': '1.0.0',
        'versions': versions
    })
