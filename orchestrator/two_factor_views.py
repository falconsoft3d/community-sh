from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
import pyotp
import qrcode
import io
import base64

@login_required
def two_factor_setup(request):
    """Setup two-factor authentication for user"""
    user = request.user
    profile = user.profile
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'enable':
            # Generate new secret
            secret = pyotp.random_base32()
            profile.two_factor_secret = secret
            profile.save()
            
            # Generate QR code
            totp = pyotp.TOTP(secret)
            provisioning_uri = totp.provisioning_uri(
                name=user.email or user.username,
                issuer_name='Community SH'
            )
            
            # Create QR code image
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(provisioning_uri)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Convert to base64
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            img_str = base64.b64encode(buffer.getvalue()).decode()
            
            return render(request, 'orchestrator/two_factor_setup.html', {
                'secret': secret,
                'qr_code': img_str,
                'step': 'verify'
            })
        
        elif action == 'verify':
            code = request.POST.get('code', '').strip()
            secret = request.POST.get('secret')
            
            totp = pyotp.TOTP(secret)
            if totp.verify(code, valid_window=1):
                profile.two_factor_secret = secret
                profile.two_factor_enabled = True
                profile.save()
                messages.success(request, 'Autenticación de dos factores activada correctamente')
                return redirect('user-profile')
            else:
                messages.error(request, 'Código inválido. Inténtalo de nuevo.')
                return render(request, 'orchestrator/two_factor_setup.html', {
                    'secret': secret,
                    'step': 'verify',
                    'error': True
                })
        
        elif action == 'disable':
            profile.two_factor_enabled = False
            profile.two_factor_secret = ''
            profile.save()
            messages.success(request, 'Autenticación de dos factores desactivada')
            return redirect('user-profile')
    
    return render(request, 'orchestrator/two_factor_setup.html', {
        'two_factor_enabled': profile.two_factor_enabled
    })

def two_factor_verify(request):
    """Verify two-factor authentication code during login"""
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        user_id = request.session.get('2fa_user_id')
        
        if not user_id:
            messages.error(request, 'Sesión expirada. Inicia sesión nuevamente.')
            return redirect('login')
        
        from django.contrib.auth.models import User
        try:
            user = User.objects.get(id=user_id)
            profile = user.profile
            
            if profile.two_factor_enabled and profile.two_factor_secret:
                totp = pyotp.TOTP(profile.two_factor_secret)
                if totp.verify(code, valid_window=1):
                    # Code is valid, complete login
                    from django.contrib.auth import login
                    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                    
                    # Clear 2FA session
                    del request.session['2fa_user_id']
                    del request.session['2fa_required']
                    
                    messages.success(request, f'¡Bienvenido {user.username}!')
                    return redirect('instance-list')
                else:
                    messages.error(request, 'Código inválido. Inténtalo de nuevo.')
            else:
                messages.error(request, '2FA no está configurado correctamente.')
                return redirect('login')
        except User.DoesNotExist:
            messages.error(request, 'Usuario no encontrado.')
            return redirect('login')
    
    return render(request, 'orchestrator/two_factor_verify.html')
