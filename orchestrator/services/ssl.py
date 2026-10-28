"""Let's Encrypt certificates via certbot."""



class SSLService:
    """Service for managing SSL certificates with Let's Encrypt"""
    
    @staticmethod
    def is_certbot_installed():
        """Check if certbot is installed"""
        import subprocess
        try:
            result = subprocess.run(['which', 'certbot'], capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    @staticmethod
    def is_running_in_docker():
        """Check if the application is running inside Docker"""
        import os
        return os.path.exists('/.dockerenv') or os.environ.get('DOCKER_CONTAINER', False)
    
    @staticmethod
    def install_certbot():
        """Install certbot based on the operating system"""
        import subprocess
        import platform
        
        system = platform.system()
        in_docker = SSLService.is_running_in_docker()
        
        try:
            if system == "Darwin":  # macOS
                subprocess.run(['brew', 'install', 'certbot'], check=True)
            elif system == "Linux":
                # Try apt-get first (Debian/Ubuntu)
                try:
                    if in_docker:
                        # En Docker no usamos sudo
                        subprocess.run(['apt-get', 'update'], check=True)
                        subprocess.run(['apt-get', 'install', '-y', 'certbot'], check=True)
                    else:
                        subprocess.run(['sudo', 'apt-get', 'update'], check=True)
                        subprocess.run(['sudo', 'apt-get', 'install', '-y', 'certbot'], check=True)
                except subprocess.CalledProcessError:
                    # Try yum (RHEL/CentOS)
                    if in_docker:
                        subprocess.run(['yum', 'install', '-y', 'certbot'], check=True)
                    else:
                        subprocess.run(['sudo', 'yum', 'install', '-y', 'certbot'], check=True)
            else:
                raise Exception(f"Unsupported operating system: {system}")
            return True
        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to install certbot: {str(e)}")
    
    @staticmethod
    def generate_certificate(domain, email):
        """
        Generate SSL certificate using Let's Encrypt
        Returns tuple: (success, message, cert_path, key_path)
        """
        import subprocess
        import os
        
        # Check if certbot is installed
        if not SSLService.is_certbot_installed():
            try:
                SSLService.install_certbot()
            except Exception as e:
                return False, f"Certbot no está instalado y falló la instalación automática: {str(e)}", None, None
        
        # Validate domain
        if not domain or '.' not in domain:
            return False, "Dominio inválido. Debe ser un dominio válido (ej: ejemplo.com)", None, None
        
        # Validate email
        if not email or '@' not in email:
            return False, "Email inválido. Se requiere un email válido para Let's Encrypt", None, None
        
        # Check if certificates already exist BEFORE trying to generate new ones
        in_docker = SSLService.is_running_in_docker()
        
        if in_docker:
            letsencrypt_dir = '/opt/community-sh/letsencrypt'
        else:
            from django.conf import settings
            letsencrypt_dir = os.path.join(settings.BASE_DIR, 'letsencrypt')
        
        # Check in live directory first (symlinks)
        live_dir = os.path.join(letsencrypt_dir, 'live', domain)
        cert_path = os.path.join(live_dir, 'fullchain.pem')
        key_path = os.path.join(live_dir, 'privkey.pem')
        
        if os.path.exists(cert_path) and os.path.exists(key_path):
            print(f"Certificates already exist at {cert_path}", flush=True)
            return True, "Certificado SSL ya existe y está vigente", cert_path, key_path
        
        # Check in archive directory
        archive_dir = os.path.join(letsencrypt_dir, 'archive', domain)
        if os.path.exists(archive_dir):
            cert_files = [f for f in os.listdir(archive_dir) if f.startswith('fullchain')]
            if cert_files:
                cert_files.sort()  # Get the latest
                cert_path = os.path.join(archive_dir, cert_files[-1])
                key_path = cert_path.replace('fullchain', 'privkey')
                if os.path.exists(key_path):
                    print(f"Certificates found in archive at {cert_path}", flush=True)
                    return True, "Certificado SSL encontrado en archivo", cert_path, key_path
        
        try:
            # Use certbot standalone mode to generate certificate
            # This requires port 80 to be available
            # We need to stop Traefik temporarily to free port 80
            
            # Stop Traefik container to free port 80
            try:
                stop_cmd = ['docker', 'stop', 'community-sh-traefik-1']
                subprocess.run(stop_cmd, capture_output=True, text=True, timeout=10)
            except:
                pass  # If Traefik is not running, continue anyway
            
            try:
                if in_docker:
                    # Run certbot as a separate Docker container with host network
                    # This gives certbot direct access to port 80 on the host
                    # IMPORTANT: We need to mount the HOST path, not the container path
                    import os as os_module
                    from django.conf import settings
                    
                    # Get the container's internal path
                    container_letsencrypt_dir = os_module.path.join(settings.BASE_DIR, 'letsencrypt')
                    os_module.makedirs(container_letsencrypt_dir, exist_ok=True)
                    
                    # For production, we need the HOST path (not the container path)
                    # In docker-compose, /app maps to /opt/community-sh on the host
                    # So /app/letsencrypt maps to /opt/community-sh/letsencrypt
                    host_letsencrypt_dir = '/opt/community-sh/letsencrypt'
                    
                    # Create subdirectories on the host via docker exec
                    for subdir in ['live', 'archive', 'renewal', 'accounts']:
                        subdir_path = os_module.path.join(host_letsencrypt_dir, subdir)
                        subprocess.run(['mkdir', '-p', subdir_path], capture_output=True)
                        subprocess.run(['chmod', '755', subdir_path], capture_output=True)
                    
                    print(f"Host letsencrypt dir: {host_letsencrypt_dir}", flush=True)
                    
                    cmd = [
                        'docker', 'run', '--rm',
                        '--network', 'host',
                        '-v', f'{host_letsencrypt_dir}:/etc/letsencrypt',
                        '-v', '/var/lib/letsencrypt:/var/lib/letsencrypt',
                        'certbot/certbot', 'certonly',
                        '--standalone',
                        '--non-interactive',
                        '--agree-tos',
                        '--email', email,
                        '-d', domain,
                        '-d', f'www.{domain}',  # Include www subdomain
                        '--preferred-challenges', 'http',
                        '--force-renewal',  # Force renewal to ensure certs are in mounted volume
                        '-v'
                    ]
                else:
                    cmd = [
                        'sudo', 'certbot', 'certonly',
                        '--standalone',
                        '--non-interactive',
                        '--agree-tos',
                        '--email', email,
                        '-d', domain,
                        '--preferred-challenges', 'http',
                        '-v'  # Verbose mode for better error messages
                    ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                
                # Log what files were created after certbot ran
                if in_docker:
                    host_letsencrypt_dir = '/opt/community-sh/letsencrypt'
                    print(f"\n=== Files in host letsencrypt dir after certbot ===", flush=True)
                    list_result = subprocess.run(['find', host_letsencrypt_dir, '-type', 'f'], 
                                                capture_output=True, text=True)
                    print(f"{list_result.stdout}", flush=True)
                    print(f"=== End of file list ===\n", flush=True)
            finally:
                # Always restart Traefik after certbot finishes
                try:
                    start_cmd = ['docker', 'start', 'community-sh-traefik-1']
                    subprocess.run(start_cmd, capture_output=True, text=True, timeout=10)
                except:
                    pass
            
            # Log the full output for debugging
            full_output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
            print(f"Certbot output:\n{full_output}", flush=True)
            
            # Check if certificate already exists
            if "Certificate not yet due for renewal" in result.stdout or "Keeping the existing certificate" in result.stderr:
                # Certificate already exists, find it
                if in_docker:
                    letsencrypt_dir = '/opt/community-sh/letsencrypt'
                else:
                    from django.conf import settings
                    letsencrypt_dir = os.path.join(settings.BASE_DIR, 'letsencrypt')
                
                # Check in archive first (actual files)
                archive_dir = os.path.join(letsencrypt_dir, 'archive', domain)
                if os.path.exists(archive_dir):
                    cert_files = [f for f in os.listdir(archive_dir) if f.startswith('fullchain')]
                    if cert_files:
                        cert_files.sort()  # Get the latest
                        cert_path = os.path.join(archive_dir, cert_files[-1])
                        key_path = cert_path.replace('fullchain', 'privkey')
                        if os.path.exists(key_path):
                            return True, "Certificado SSL ya existe y está vigente", cert_path, key_path
                
                # Check in live (symlinks)
                live_dir = os.path.join(letsencrypt_dir, 'live', domain)
                cert_path = os.path.join(live_dir, 'fullchain.pem')
                key_path = os.path.join(live_dir, 'privkey.pem')
                if os.path.exists(cert_path) and os.path.exists(key_path):
                    return True, "Certificado SSL ya existe y está vigente", cert_path, key_path
                
                return False, "Certificado existe pero no se pudo localizar en el sistema de archivos", None, None
            
            if result.returncode == 0:
                # Certificates are stored in letsencrypt/live/domain/ within the project
                # In Docker, we need to check the HOST path, not the container path
                if in_docker:
                    letsencrypt_dir = '/opt/community-sh/letsencrypt'
                else:
                    from django.conf import settings
                    letsencrypt_dir = os.path.join(settings.BASE_DIR, 'letsencrypt')
                
                # Check all possible locations
                cert_paths_to_check = [
                    os.path.join(letsencrypt_dir, 'live', domain, 'fullchain.pem'),
                    os.path.join(letsencrypt_dir, 'archive', domain, 'fullchain1.pem'),
                ]
                
                cert_path = None
                key_path = None
                
                for check_cert in cert_paths_to_check:
                    check_key = check_cert.replace('fullchain', 'privkey')
                    if os.path.exists(check_cert) and os.path.exists(check_key):
                        cert_path = check_cert
                        key_path = check_key
                        break
                
                if cert_path and key_path:
                    return True, "Certificado SSL generado exitosamente", cert_path, key_path
                else:
                    # List what files actually exist for debugging
                    import subprocess
                    find_result = subprocess.run(
                        ['find', letsencrypt_dir, '-name', '*.pem'],
                        capture_output=True, text=True
                    )
                    files_found = find_result.stdout.strip()
                    return False, f"Certificado generado pero no se encontró en las rutas esperadas. Archivos encontrados:\n{files_found}", None, None
            else:
                error_msg = result.stderr or result.stdout or "Error desconocido"
                
                # Try to read the log file for more details
                log_content = ""
                try:
                    with open('/var/log/letsencrypt/letsencrypt.log', 'r') as f:
                        # Get last 20 lines
                        lines = f.readlines()
                        log_content = ''.join(lines[-20:])
                except:
                    pass
                
                # Extract more useful error information
                if "Timeout" in error_msg or "timeout" in error_msg:
                    return False, "Timeout: El servidor no pudo validar el dominio. Asegúrate de que el puerto 80 esté abierto y el dominio apunte a este servidor.", None, None
                elif "Connection refused" in error_msg or "Connection refused" in log_content:
                    return False, "Conexión rechazada: El puerto 80 puede estar bloqueado o en uso. Certbot no pudo conectarse al puerto 80 para validar el dominio.", None, None
                elif "DNS" in error_msg or "DNS" in log_content:
                    return False, f"Error de DNS: El dominio {domain} no puede ser resuelto. Verifica que el dominio apunte a la IP correcta: {error_msg[:200]}", None, None
                elif "Invalid response" in log_content or "404" in log_content:
                    return False, f"Let's Encrypt no pudo validar el dominio. Asegúrate de que: 1) El dominio {domain} apunte a este servidor, 2) El puerto 80 esté accesible desde internet, 3) No haya firewall bloqueando. Log: {log_content[-500:]}", None, None
                else:
                    full_error = f"{error_msg}\n\nÚltimas líneas del log:\n{log_content[-800:]}" if log_content else error_msg
                    return False, f"Error al generar certificado: {full_error[:1000]}", None, None
                
        except subprocess.TimeoutExpired:
            return False, "Timeout: La generación del certificado tardó demasiado. Verifica que el puerto 80 esté accesible desde internet.", None, None
        except subprocess.CalledProcessError as e:
            return False, f"Error ejecutando certbot: {str(e)}", None, None
        except Exception as e:
            return False, f"Error inesperado: {str(e)}", None, None
                
        except subprocess.TimeoutExpired:
            return False, "Timeout: La generación del certificado tardó demasiado. Verifica que el puerto 80 esté accesible desde internet.", None, None
        except subprocess.CalledProcessError as e:
            return False, f"Error ejecutando certbot: {str(e)}", None, None
        except Exception as e:
            return False, f"Error inesperado: {str(e)}", None, None
    
    @staticmethod
    def renew_certificate(domain):
        """Renew an existing SSL certificate"""
        import subprocess
        
        try:
            in_docker = SSLService.is_running_in_docker()
            if in_docker:
                cmd = ['certbot', 'renew', '--cert-name', domain]
            else:
                cmd = ['sudo', 'certbot', 'renew', '--cert-name', domain]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                return True, "Certificado renovado exitosamente"
            else:
                return False, f"Error al renovar certificado: {result.stderr or result.stdout}"
        except Exception as e:
            return False, f"Error al renovar certificado: {str(e)}"
    
    @staticmethod
    def check_certificate_expiry(cert_path):
        """Check when a certificate expires"""
        import subprocess
        from datetime import datetime
        
        try:
            cmd = ['openssl', 'x509', '-enddate', '-noout', '-in', cert_path]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # Parse output: notAfter=Jan 1 00:00:00 2025 GMT
            date_str = result.stdout.strip().replace('notAfter=', '')
            expiry_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
            
            days_remaining = (expiry_date - datetime.now()).days
            return days_remaining, expiry_date
        except Exception as e:
            return None, None
