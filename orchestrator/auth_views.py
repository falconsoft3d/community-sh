from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from .config_models import GitHubConfig

def custom_login(request):
    """Custom login view with 2FA support"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            # Check if 2FA is required globally or for this user
            try:
                admin_config = GitHubConfig.objects.filter(user__is_superuser=True).first()
                two_factor_required = admin_config and admin_config.two_factor_required
            except:
                two_factor_required = False
            
            profile = user.profile
            
            # If 2FA is required globally or enabled for user
            if (two_factor_required or profile.two_factor_enabled) and profile.two_factor_secret:
                # Store user ID in session and redirect to 2FA verification
                request.session['2fa_user_id'] = user.id
                request.session['2fa_required'] = True
                return redirect('two-factor-verify')
            else:
                # Login normally without 2FA
                login(request, user)
                messages.success(request, f'¡Bienvenido {user.username}!')
                return redirect('instance-list')
        else:
            messages.error(request, 'Usuario o contraseña incorrectos')
    
    return render(request, 'registration/login.html')

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
