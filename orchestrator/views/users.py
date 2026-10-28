"""User management and profiles."""

from django.shortcuts import redirect, get_object_or_404, render
from django.contrib.auth.decorators import login_required


# User Management Views
@login_required
def user_list(request):
    """List all users (admin only)"""
    from django.contrib.auth.models import User
    from django.contrib import messages
    
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para acceder a esta página')
        return redirect('instance-list')
    
    from ..pagination import paginate
    users = User.objects.all().order_by('-date_joined')
    return render(request, 'orchestrator/user_list.html', {'users': paginate(request, users)})


@login_required
def user_create(request):
    """Create a new user (admin only)"""
    from django.contrib.auth.models import User
    from django.contrib import messages
    
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para acceder a esta página')
        return redirect('instance-list')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        is_superuser = request.POST.get('is_superuser') == 'on'
        is_staff = request.POST.get('is_staff') == 'on'
        
        # Validation
        if not username or not password:
            messages.error(request, 'Usuario y contraseña son requeridos')
            return render(request, 'orchestrator/user_create.html')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, f'El usuario "{username}" ya existe')
            return render(request, 'orchestrator/user_create.html')
        
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        user.is_superuser = is_superuser
        user.is_staff = is_staff
        user.save()
        # A client only sees and operates the projects assigned to it
        user.profile.is_client = request.POST.get('is_client') == 'on' and not is_superuser
        user.profile.company = request.POST.get('company', '').strip()
        user.profile.save()
        
        messages.success(request, f'Usuario "{username}" creado exitosamente')
        return redirect('user-list')
    
    return render(request, 'orchestrator/user_create.html')


@login_required
def user_edit(request, user_id):
    """Edit user (admin only)"""
    from django.contrib.auth.models import User
    from django.contrib import messages
    
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para acceder a esta página')
        return redirect('instance-list')
    
    user_to_edit = get_object_or_404(User, pk=user_id)
    
    if request.method == 'POST':
        email = request.POST.get('email')
        is_superuser = request.POST.get('is_superuser') == 'on'
        is_staff = request.POST.get('is_staff') == 'on'
        is_active = request.POST.get('is_active') == 'on'
        new_password = request.POST.get('new_password')
        
        user_to_edit.email = email
        user_to_edit.is_superuser = is_superuser
        user_to_edit.is_staff = is_staff
        user_to_edit.is_active = is_active
        
        if new_password:
            user_to_edit.set_password(new_password)
        
        user_to_edit.save()
        user_to_edit.profile.is_client = request.POST.get('is_client') == 'on' and not is_superuser
        user_to_edit.profile.company = request.POST.get('company', '').strip()
        user_to_edit.profile.save()
        
        messages.success(request, f'Usuario "{user_to_edit.username}" actualizado exitosamente')
        return redirect('user-list')
    
    return render(request, 'orchestrator/user_edit.html', {'user_to_edit': user_to_edit})


@login_required
def user_delete(request, user_id):
    """Delete user (admin only)"""
    from django.contrib.auth.models import User
    from django.contrib import messages
    
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para acceder a esta página')
        return redirect('instance-list')
    
    user_to_delete = get_object_or_404(User, pk=user_id)
    
    if request.method == 'POST':
        if user_to_delete == request.user:
            messages.error(request, 'No puedes eliminar tu propio usuario')
            return redirect('user-list')
        
        username = user_to_delete.username
        user_to_delete.delete()
        messages.success(request, f'Usuario "{username}" eliminado exitosamente')
    
    return redirect('user-list')


# User Profile Views
@login_required
def user_profile(request):
    """View and edit current user's profile"""
    from django.contrib import messages
    from ..models import UserProfile
    
    # Ensure profile exists
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        # Update user info
        request.user.first_name = request.POST.get('first_name', '')
        request.user.last_name = request.POST.get('last_name', '')
        request.user.email = request.POST.get('email', '')
        request.user.save()
        
        # Update profile
        profile.bio = request.POST.get('bio', '')
        profile.phone = request.POST.get('phone', '')
        
        # Handle avatar upload
        if 'avatar' in request.FILES:
            profile.avatar = request.FILES['avatar']
        
        profile.save()
        
        messages.success(request, 'Perfil actualizado exitosamente')
        return redirect('user-profile')
    
    return render(request, 'orchestrator/user_profile.html', {'profile': profile})


@login_required
def user_change_password(request):
    """Change current user's password"""
    from django.contrib.auth import update_session_auth_hash
    from django.contrib import messages
    
    if request.method == 'POST':
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        # Validate current password
        if not request.user.check_password(current_password):
            messages.error(request, 'La contraseña actual es incorrecta')
            return redirect('user-profile')
        
        # Validate new passwords match
        if new_password != confirm_password:
            messages.error(request, 'Las contraseñas nuevas no coinciden')
            return redirect('user-profile')
        
        # Validate password strength
        if len(new_password) < 8:
            messages.error(request, 'La contraseña debe tener al menos 8 caracteres')
            return redirect('user-profile')
        
        # Change password
        request.user.set_password(new_password)
        request.user.save()
        
        # Keep user logged in
        update_session_auth_hash(request, request.user)
        
        messages.success(request, 'Contraseña cambiada exitosamente')
    
    return redirect('user-profile')
