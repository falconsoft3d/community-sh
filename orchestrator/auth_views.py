from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib import messages
from .permissions import is_registration_enabled

def custom_login(request):
    """Custom login view with 2FA support"""
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            
            # Helper to get or create profile safely
            try:
                profile = user.profile
            except Exception:
                # Auto-heal: Create profile if it doesn't exist (e.g. old users)
                from .models import UserProfile
                profile = UserProfile.objects.create(user=user)
            
            # Users with 2FA must verify; if 2FA is required globally but not set up yet,
            # TwoFactorEnforcementMiddleware sends them to the setup page after login
            has_2fa_setup = profile.two_factor_enabled and profile.two_factor_secret
            
            if has_2fa_setup:
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
    
    return render(request, 'registration/login.html', {
        'form': form,
        'registration_enabled': is_registration_enabled()
    })

def register(request):
    if not is_registration_enabled():
        messages.error(request, 'El registro de nuevos usuarios está deshabilitado.')
        return redirect('login')
    
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            from django.contrib.auth.models import User
            is_first_user = not User.objects.exists()
            user = form.save()
            # The first account administers the platform
            if is_first_user:
                user.is_superuser = True
                user.is_staff = True
                user.save()
            login(request, user)
            return redirect('instance-list')
    else:
        form = UserCreationForm()
    return render(request, 'registration/register.html', {'form': form})
