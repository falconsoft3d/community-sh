from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from .config_models import GitHubConfig

def register(request):
    # Check if registration is enabled (check first admin user's config)
    try:
        admin_config = GitHubConfig.objects.filter(user__is_superuser=True).first()
        if admin_config and not admin_config.registration_enabled:
            messages.error(request, 'User registration is currently disabled')
            return redirect('login')
    except:
        pass  # Allow registration if no config exists yet
    
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('instance-list')
    else:
        form = UserCreationForm()
    return render(request, 'registration/register.html', {'form': form})
