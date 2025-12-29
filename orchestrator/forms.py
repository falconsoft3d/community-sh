from django import forms
from .models import Instance
from .config_models import GitHubConfig
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
        fields = ['name', 'odoo_version', 'github_repo', 'github_branch']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'mi-empresa'}),
            'github_branch': forms.TextInput(attrs={'placeholder': 'main'}),
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
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
