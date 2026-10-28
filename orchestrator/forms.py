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
        fields = ['project', 'name', 'odoo_version', 'github_repo', 'github_branch', 'database_name', 'custom_domain']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'mi-empresa'}),
            'github_branch': forms.TextInput(attrs={'placeholder': 'main'}),
            'database_name': forms.TextInput(attrs={'placeholder': 'Dejar vacío para auto-detección'}),
            'custom_domain': forms.TextInput(attrs={'placeholder': 'ejemplo.midominio.com'}),
        }
        labels = {
            'project': 'Proyecto',
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
    class Meta:
        model = Project
        fields = ['name', 'client', 'description']
        labels = {'name': 'Nombre', 'client': 'Cliente (usuario)', 'description': 'Descripción'}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Implantación ACME'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, owner=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner or getattr(self.instance, 'owner', None)
        # Assigning client users is an admin task (clients are managed in the Clients menu)
        if user is not None and user.is_superuser:
            # Any active non-admin user can be the project's client
            self.fields['client'].queryset = User.objects.filter(is_active=True, is_superuser=False).select_related('profile').order_by('username')
            self.fields['client'].empty_label = '-- Sin cliente --'
            self.fields['client'].label_from_instance = lambda u: f"{u.profile.company or u.get_full_name() or u.username} ({u.username})"
        else:
            del self.fields['client']
        for field in self.fields.values():
            field.widget.attrs['class'] = (
                'flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background '
                'placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring '
                'focus-visible:ring-offset-2' + (' h-10' if not isinstance(field.widget, forms.Textarea) else '')
            )

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        duplicates = Project.objects.filter(owner=self.owner, name__iexact=name).exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError('Ya tienes un proyecto con ese nombre.')
        return name


INPUT_CLASS = (
    'flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background '
    'placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring '
    'focus-visible:ring-offset-2'
)


class ClientForm(forms.Form):
    """A client is a user account flagged as client; it sees and operates its projects."""
    company = forms.CharField(label='Empresa', max_length=150)
    first_name = forms.CharField(label='Nombre de contacto', max_length=150, required=False)
    last_name = forms.CharField(label='Apellidos', max_length=150, required=False)
    email = forms.EmailField(label='Email', required=False)
    username = forms.CharField(label='Usuario para entrar al panel', max_length=150)
    password = forms.CharField(
        label='Contraseña', required=False, widget=forms.PasswordInput(render_value=False),
        help_text='Déjala vacía para generar una aleatoria (se muestra una sola vez)',
    )
    projects = forms.ModelMultipleChoiceField(
        label='Proyectos', queryset=Project.objects.none(), required=False,
        widget=forms.SelectMultiple(attrs={'size': 6}),
        help_text='Proyectos que este cliente podrá ver y operar',
    )

    def __init__(self, *args, client=None, **kwargs):
        self.client = client
        if client is not None:
            kwargs.setdefault('initial', {}).update({
                'company': client.profile.company,
                'first_name': client.first_name,
                'last_name': client.last_name,
                'email': client.email,
                'username': client.username,
                'projects': client.client_projects.all(),
            })
        super().__init__(*args, **kwargs)
        self.fields['projects'].queryset = Project.objects.order_by('name')
        self.fields['projects'].label_from_instance = lambda p: f"{p.name} ({p.owner.username})"
        if client is not None:
            self.fields['password'].help_text = 'Déjala vacía para mantener la actual'
        for field in self.fields.values():
            field.widget.attrs['class'] = INPUT_CLASS + (' h-auto' if isinstance(field.widget, forms.SelectMultiple) else '')

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        taken = User.objects.filter(username__iexact=username)
        if self.client is not None:
            taken = taken.exclude(pk=self.client.pk)
        if taken.exists():
            raise forms.ValidationError('Ese usuario ya existe.')
        return username

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            from django.contrib.auth.password_validation import validate_password
            validate_password(password)
        return password

    def save(self):
        """Create or update the client user. Returns (user, generated_password or None)."""
        import secrets
        data = self.cleaned_data
        user = self.client or User(is_staff=False, is_superuser=False)
        user.username = data['username']
        user.first_name = data['first_name']
        user.last_name = data['last_name']
        user.email = data['email']
        generated = None
        if data['password']:
            user.set_password(data['password'])
        elif self.client is None:
            generated = secrets.token_urlsafe(12)
            user.set_password(generated)
        user.save()
        profile = user.profile
        profile.is_client = True
        profile.company = data['company']
        profile.save()
        # Assignments replace the previous ones
        Project.objects.filter(client=user).exclude(pk__in=[p.pk for p in data['projects']]).update(client=None)
        Project.objects.filter(pk__in=[p.pk for p in data['projects']]).update(client=user)
        return user, generated
