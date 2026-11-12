from django import forms
from .models import Instance
from .config_models import GitHubConfig
from django.contrib.auth.models import User
from .permissions import domain_in_use, managed_projects_for
from .project_models import Project
import requests

class InstanceForm(forms.ModelForm):
    github_repo = forms.ChoiceField(
        required=False,
        label="Repositorio de GitHub (opcional)",
        help_text="Selecciona un repositorio para clonar módulos personalizados"
    )
    github_branch = forms.CharField(
        required=False,
        initial='main',
        label="Rama de GitHub",
        help_text="Rama del repositorio a utilizar"
    )
    
    class Meta:
        model = Instance
        fields = ['project', 'name', 'odoo_version', 'github_repo', 'github_branch', 'database_name', 'demo_default_db', 'custom_domain', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'mi-empresa'}),
            'github_branch': forms.TextInput(attrs={'placeholder': 'main'}),
            'database_name': forms.TextInput(attrs={'placeholder': 'Dejar vacío para auto-detección'}),
            'demo_default_db': forms.TextInput(attrs={'placeholder': 'Dejar vacío si no es una instancia de demos'}),
            'custom_domain': forms.TextInput(attrs={'placeholder': 'ejemplo.midominio.com'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Qué incluye esta versión (se muestra en la página de demos)'}),
        }
        labels = {
            'project': 'Proyecto',
            'description': 'Descripción para las demos (opcional)',
            'demo_default_db': 'Base por defecto de las demos (opcional)',
            'custom_domain': 'Dominio Personalizado (opcional)',
        }
        help_texts = {
            'custom_domain': 'Dominio personalizado para acceder a esta instancia (ej: sh.midominio.local)',
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Every instance lives in one of the user's projects
        self.fields['project'].required = True
        self.fields['project'].empty_label = '-- Selecciona un proyecto --'
        self.fields['project'].help_text = 'Cliente o proyecto al que pertenece la instancia'
        if user:
            self.fields['project'].queryset = managed_projects_for(user)

    def clean_project(self):
        from .quotas import quota_problem
        project = self.cleaned_data.get('project')
        problem = quota_problem(project) if not self.instance.pk else None
        if problem:
            raise forms.ValidationError(problem)
        return project
        
        # Get repositories from GitHub
        repos = [('', '-- Ninguno --')]
        
        if user:
            try:
                github_config = GitHubConfig.objects.get(user=user)
                if github_config.personal_access_token:
                    headers = {
                        'Authorization': f'token {github_config.personal_access_token}',
                        'Accept': 'application/vnd.github.v3+json'
                    }
                    
                    # Get user repos
                    response = requests.get(
                        'https://api.github.com/user/repos',
                        headers=headers,
                        params={'per_page': 100, 'sort': 'updated'}
                    )
                    
                    if response.status_code == 200:
                        for repo in response.json():
                            repos.append((repo['clone_url'], f"{repo['full_name']}"))
            except GitHubConfig.DoesNotExist:
                pass
            except Exception as e:
                print(f"Error fetching GitHub repos: {e}")
        
        self.fields['github_repo'].choices = repos
        
        # Update widget classes for Shadcn styling
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.update({
                    'class': 'flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2'
                })
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update({
                    'class': 'flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2'
                })
            elif isinstance(field.widget, forms.TextInput):
                field.widget.attrs.update({
                    'class': 'flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2'
                })

    def clean_name(self):
        return (self.cleaned_data.get('name') or '').strip().lower()

    def clean_custom_domain(self):
        domain = (self.cleaned_data.get('custom_domain') or '').strip().lower()
        if domain and domain_in_use(domain, exclude_instance=self.instance if self.instance.pk else None):
            raise forms.ValidationError('Este dominio ya está en uso.')
        return domain or None


class ProjectForm(forms.ModelForm):
    TRIAL_FIELDS = ('trial_slug', 'trial_days', 'trial_target_project', 'trial_message', 'trial_max_active')

    class Meta:
        model = Project
        fields = ['name', 'client', 'description', 'max_instances', 'max_memory_mb', 'color', 'trial_enabled', 'trial_slug', 'trial_days',
                  'trial_target_project', 'trial_message', 'trial_max_active']
        labels = {
            'name': 'Nombre', 'client': 'Cliente (usuario)', 'description': 'Descripción', 'color': 'Color de la tarjeta',
            'max_instances': 'Cuota: instancias', 'max_memory_mb': 'Cuota: RAM (MB)',
            'trial_enabled': 'Modo test',
            'trial_slug': 'URL de la página de demos',
            'trial_days': 'Días de prueba',
            'trial_target_project': 'Proyecto donde se crean las demos',
            'trial_message': 'Texto para el usuario',
            'trial_max_active': 'Demos a la vez',
        }
        help_texts = {
            'max_instances': 'Máximo de instancias del proyecto (0: sin límite). Solo lo cambian los administradores.',
            'max_memory_mb': 'Suma máxima de los límites de memoria de sus instancias (0: sin límite). Solo lo cambian los administradores.',
            'trial_enabled': 'Página pública donde cualquiera pide una demo de las instancias de este proyecto. Cada demo es una copia completa de la instancia elegida: usa plantillas sin datos reales de clientes. Al copiarla se desactivan el correo, las claves API y las contraseñas de los demás usuarios, y el asistente de IA no funciona en las demos.',
            'trial_slug': 'Por ejemplo bim: la página queda en https://tudominio/bim',
            'trial_days': 'Al vencer la demo se detiene, y se elimina 7 días después',
            'trial_target_project': 'Un proyecto hermano (tuyo): ahí se crea la copia de la instancia elegida',
            'trial_message': 'Se muestra arriba de la página de demos',
            'trial_max_active': 'Máximo de demos funcionando al mismo tiempo: cada una es un Odoo con su PostgreSQL',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Implantación ACME'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'trial_slug': forms.TextInput(attrs={'placeholder': 'bim'}),
            'trial_message': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Prueba gratis nuestro Odoo para la construcción durante 15 días...'}),
        }

    tags_text = forms.CharField(label='Etiquetas', required=False, max_length=400,
                                help_text='Separadas por comas, p. ej. «cliente, odoo 20, demo»')

    def __init__(self, *args, owner=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner or getattr(self.instance, 'owner', None)
        if self.instance.pk:
            self.fields['tags_text'].initial = ', '.join(self.instance.tags.values_list('name', flat=True))
        self.fields['tags_text'].widget.attrs['list'] = 'project-tags'
        from .project_models import ProjectTag
        self.existing_tags = list(ProjectTag.objects.filter(owner=self.owner).values_list('name', flat=True)) if self.owner else []
        # Assigning client users is an admin task (clients are managed in the Clients menu)
        if user is not None and user.is_superuser:
            # Any active non-admin user can be the project's client
            self.fields['client'].queryset = User.objects.filter(is_active=True, is_superuser=False).select_related('profile').order_by('username')
            self.fields['client'].empty_label = '-- Sin cliente --'
            self.fields['client'].label_from_instance = lambda u: f"{u.profile.company or u.get_full_name() or u.username} ({u.username})"
        else:
            del self.fields['client']
            # Quotas are set by an administrator, never by who uses them
            del self.fields['max_instances']
            del self.fields['max_memory_mb']
        # The demos go to another project of the same owner
        siblings = Project.objects.filter(owner=self.owner) if self.owner else Project.objects.none()
        if self.instance.pk:
            siblings = siblings.exclude(pk=self.instance.pk)
        self.fields['trial_target_project'].queryset = siblings.order_by('name')
        self.fields['trial_target_project'].empty_label = '-- Selecciona un proyecto --'
        # Empty (or not sent): the default of the model
        for name in ('trial_days', 'trial_max_active'):
            self.fields[name].required = False
        self.fields['trial_days'].widget.attrs.update({'min': 1, 'max': 365})
        self.fields['trial_max_active'].widget.attrs.update({'min': 1, 'max': 50})
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'h-4 w-4 rounded border-input accent-primary'
                continue
            field.widget.attrs['class'] = (
                'flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background '
                'placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring '
                'focus-visible:ring-offset-2' + (' h-10' if not isinstance(field.widget, forms.Textarea) else '')
            )

    @property
    def main_fields(self):
        return [self[name] for name in self.fields if not name.startswith('trial_') and name not in ('color', 'tags_text')]

    def clean_tags_text(self):
        names = []
        for raw in (self.cleaned_data.get('tags_text') or '').split(','):
            name = ' '.join(raw.split())[:40]
            if name and name.lower() not in [n.lower() for n in names]:
                names.append(name)
        if len(names) > 12:
            raise forms.ValidationError('Como mucho 12 etiquetas por proyecto.')
        return names

    def save(self, commit=True):
        project = super().save(commit=commit)
        if commit:
            self.save_tags(project)
        return project

    def save_tags(self, project):
        from .project_models import ProjectTag
        tags = []
        for name in self.cleaned_data.get('tags_text') or []:
            tag = ProjectTag.objects.filter(owner=project.owner, name__iexact=name).first() \
                or ProjectTag.objects.create(owner=project.owner, name=name)
            tags.append(tag)
        project.tags.set(tags)

    @property
    def trial_fields(self):
        return [self[name] for name in self.TRIAL_FIELDS]

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        duplicates = Project.objects.filter(owner=self.owner, name__iexact=name).exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError('Ya tienes un proyecto con ese nombre.')
        return name

    def clean_trial_slug(self):
        from .services.trials import trial_slug_problem
        slug = (self.cleaned_data.get('trial_slug') or '').strip().lower()
        if not slug:
            return None
        # /<slug>/ must not be a page of the panel (projects, instances, admin...)
        problem = trial_slug_problem(slug, self.instance)
        if problem:
            raise forms.ValidationError(problem)
        return slug

    def clean(self):
        data = super().clean()
        for name in ('trial_days', 'trial_max_active'):
            if name not in self.errors and not data.get(name):
                data[name] = Project._meta.get_field(name).default
        from .services.trials import trial_settings_problems
        for field, message in trial_settings_problems(data, self.owner, self.instance).items():
            if field not in self.errors:
                self.add_error(field, message)
        return data


class ContactForm(forms.ModelForm):
    """A CRM contact, created by hand or edited (its demos come from the demo requests)."""

    class Meta:
        from .contact_models import Contact
        model = Contact
        fields = ['name', 'email', 'company', 'job_title', 'phone', 'country', 'stage', 'notes']
        labels = {'name': 'Nombre y apellidos', 'email': 'Email', 'company': 'Empresa', 'job_title': 'Cargo',
                  'phone': 'Teléfono', 'country': 'País', 'stage': 'Etapa', 'notes': 'Notas'}
        widgets = {'notes': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Llamadas, interés, próximo paso…'})}

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner or getattr(self.instance, 'owner', None)
        for field in self.fields.values():
            field.widget.attrs['class'] = (
                'flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm'
                + ('' if isinstance(field.widget, forms.Textarea) else ' h-10'))

    def clean_email(self):
        from .contact_models import Contact
        email = self.cleaned_data['email'].strip().lower()
        if Contact.objects.filter(owner=self.owner, email=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ya tienes un contacto con ese email.')
        return email
