from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib import messages
from .config_models import GitHubConfig

def custom_login(request):
    """Custom login view with 2FA support"""
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            
            # Check if 2FA is required globally or for this user
            try:
                admin_config = GitHubConfig.objects.filter(user__is_superuser=True).first()
                two_factor_required = admin_config and admin_config.two_factor_required
            except:
                two_factor_required = False
            
            # Helper to get or create profile safely
            try:
                profile = user.profile
            except Exception:
                # Auto-heal: Create profile if it doesn't exist (e.g. old users)
                from .models import UserProfile
                profile = UserProfile.objects.create(user=user)
            
            # If 2FA is required globally or enabled for user
            has_2fa_setup = profile.two_factor_enabled and profile.two_factor_secret
            
            if (two_factor_required or has_2fa_setup) and profile.two_factor_secret:
                # Store user ID in session and redirect to 2FA verification
                request.session['2fa_user_id'] = user.id
                request.session['2fa_required'] = True
                return redirect('two-factor-verify')
            else:
                # Login normally without 2FA
                login(request, user)
                
                # Remember me logic
                if request.POST.get('remember_me'):
                    request.session.set_expiry(1209600) # 2 weeks
                else:
                    request.session.set_expiry(0) # Session expires when browser closes

                messages.success(request, f'¡Bienvenido {user.username}!')
                return redirect('instance-list')
        else:
            messages.error(request, 'Usuario o contraseña incorrectos')
    else:
        form = AuthenticationForm()
    
    # Check if registration is enabled
    try:
        from django.contrib.auth.models import User
        # If there are no users, always allow registration (for first user setup)
        if not User.objects.exists():
            registration_enabled = True
        else:
            # Try to get config from superuser first, then any user
            admin_config = GitHubConfig.objects.filter(user__is_superuser=True).first()
            if not admin_config:
                admin_config = GitHubConfig.objects.first()
            registration_enabled = admin_config.registration_enabled if admin_config else True
    except:
        registration_enabled = True
    
    return render(request, 'registration/login.html', {
        'form': form,
        'registration_enabled': registration_enabled
    })

def register(request):
    # Check if registration is enabled (check first admin user's config)
    try:
        from django.contrib.auth.models import User
        # If there are no users, always allow registration (for first user setup)
        if not User.objects.exists():
            registration_enabled = True
        else:
            # Try to get config from superuser first, then any user
            admin_config = GitHubConfig.objects.filter(user__is_superuser=True).first()
            if not admin_config:
                admin_config = GitHubConfig.objects.first()
            registration_enabled = admin_config.registration_enabled if admin_config else True
    except Exception:
        registration_enabled = True  # Allow registration if no config exists yet
    
    if not registration_enabled:
        messages.error(request, 'El registro de nuevos usuarios está deshabilitado.')
        return redirect('login')
    
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('instance-list')
    else:
        form = UserCreationForm()
    return render(request, 'registration/register.html', {'form': form})
