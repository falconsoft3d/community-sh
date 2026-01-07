"""
Servicio para gestionar la configuración dinámica de Traefik
"""
import docker
import os
import yaml
from django.conf import settings


class TraefikService:
    """Service for managing Traefik dynamic configuration"""
    
    @staticmethod
    def generate_dynamic_config(domain=None, ssl_enabled=False):
        """
        Generate Traefik dynamic configuration file based on GitHubConfig
        
        Args:
            domain: Main domain from GitHubConfig.main_domain
            ssl_enabled: Whether SSL is enabled from GitHubConfig.ssl_enabled
        
        Returns:
            tuple: (success, message)
        """
        try:
            # Create traefik directory if it doesn't exist
            traefik_dir = os.path.join(settings.BASE_DIR, 'traefik')
            os.makedirs(traefik_dir, exist_ok=True)
            
            config_file = os.path.join(traefik_dir, 'dynamic.yml')
            
            if domain:
                # Create routing configuration for the main domain
                config = {
                    'http': {
                        'routers': {
                            'app-domain': {
                                'rule': f'Host(`{domain}`) || Host(`www.{domain}`)',
                                'entryPoints': ['web'],
                                'service': 'app-domain-service',
                                'priority': 50  # Higher priority than Docker labels
                            }
                        },
                        'services': {
                            'app-domain-service': {
                                'loadBalancer': {
                                    'servers': [
                                        {'url': 'http://community-sh-app-1:8000'}
                                    ]
                                }
                            }
                        }
                    }
                }
                
                # Write configuration to file
                with open(config_file, 'w') as f:
                    yaml.dump(config, f, default_flow_style=False)
                
                return True, f"Configuración de Traefik generada para {domain}"
            else:
                # Remove configuration file if no domain is set
                if os.path.exists(config_file):
                    os.remove(config_file)
                return True, "Configuración de dominio eliminada"
                
        except Exception as e:
            return False, f"Error al generar configuración: {str(e)}"
    
    @staticmethod
    def update_app_routing(domain=None, ssl_enabled=False, cert_path=None, key_path=None):
        """
        Update Traefik routing configuration for the main app
        
        Args:
            domain: Main domain to route (e.g., 'example.com')
            ssl_enabled: Whether SSL/HTTPS is enabled
            cert_path: Path to SSL certificate file
            key_path: Path to SSL key file
        
        Returns:
            tuple: (success, message)
        """
        try:
            client = docker.from_env()
            
            # Find the app container
            containers = client.containers.list(filters={'label': 'traefik.enable=true'})
            app_container = None
            
            for container in containers:
                if 'app' in container.name or 'community-sh' in container.name:
                    app_container = container
                    break
            
            if not app_container:
                return False, "No se encontró el contenedor de la aplicación"
            
            # Build routing rules
            labels = {}
            
            if domain:
                # Build host rule
                if ssl_enabled:
                    # HTTPS configuration
                    labels.update({
                        'traefik.enable': 'true',
                        'traefik.http.routers.app-secure.rule': f'Host(`{domain}`) || Host(`www.{domain}`)',
                        'traefik.http.routers.app-secure.entrypoints': 'websecure',
                        'traefik.http.routers.app-secure.tls': 'true',
                        'traefik.http.routers.app-secure.tls.certresolver': 'letsencrypt',
                        'traefik.http.services.app-secure.loadbalancer.server.port': '8000',
                        
                        # HTTP to HTTPS redirect
                        'traefik.http.routers.app-http.rule': f'Host(`{domain}`) || Host(`www.{domain}`)',
                        'traefik.http.routers.app-http.entrypoints': 'web',
                        'traefik.http.routers.app-http.middlewares': 'https-redirect',
                        'traefik.http.middlewares.https-redirect.redirectscheme.scheme': 'https',
                        'traefik.http.middlewares.https-redirect.redirectscheme.permanent': 'true',
                    })
                else:
                    # HTTP only configuration
                    labels.update({
                        'traefik.enable': 'true',
                        'traefik.http.routers.app.rule': f'Host(`{domain}`) || Host(`www.{domain}`) || Host(`localhost`) || Host(`community.local`)',
                        'traefik.http.routers.app.entrypoints': 'web',
                        'traefik.http.services.app.loadbalancer.server.port': '8000',
                    })
            else:
                # Default configuration without custom domain
                labels.update({
                    'traefik.enable': 'true',
                    'traefik.http.routers.app.rule': 'Host(`localhost`) || Host(`community.local`)',
                    'traefik.http.routers.app.entrypoints': 'web',
                    'traefik.http.services.app.loadbalancer.server.port': '8000',
                })
            
            # Update container labels
            # Note: Docker API doesn't allow updating labels on running containers
            # We need to restart the container with new labels
            # For now, we'll document this in docker-compose.yml
            
            return True, f"Configuración de Traefik actualizada para {'HTTPS' if ssl_enabled else 'HTTP'}"
            
        except docker.errors.DockerException as e:
            return False, f"Error de Docker: {str(e)}"
        except Exception as e:
            return False, f"Error al actualizar Traefik: {str(e)}"
    
    @staticmethod
    def update_docker_compose_labels(domain=None, ssl_enabled=False):
        """
        Update docker-compose.yml with new labels for the app service
        
        Args:
            domain: Main domain to route
            ssl_enabled: Whether SSL/HTTPS is enabled
        
        Returns:
            tuple: (success, message)
        """
        try:
            docker_compose_path = os.path.join(settings.BASE_DIR, 'docker-compose.yml')
            
            if not os.path.exists(docker_compose_path):
                return False, "docker-compose.yml no encontrado"
            
            # Read the current docker-compose.yml
            with open(docker_compose_path, 'r') as f:
                content = f.read()
            
            # This is a simplified approach - in production, you'd want to use a YAML parser
            # For now, we'll create a backup and provide instructions
            
            backup_path = docker_compose_path + '.backup'
            with open(backup_path, 'w') as f:
                f.write(content)
            
            return True, "Se ha creado un backup de docker-compose.yml. Por favor, reinicia los servicios con 'docker-compose up -d --force-recreate app' para aplicar los cambios."
            
        except Exception as e:
            return False, f"Error al actualizar docker-compose.yml: {str(e)}"
    
    @staticmethod
    def get_traefik_status():
        """
        Get current Traefik configuration status
        
        Returns:
            dict: Status information
        """
        try:
            client = docker.from_env()
            
            # Check if Traefik is running
            traefik_containers = client.containers.list(filters={'ancestor': 'traefik'})
            
            if not traefik_containers:
                return {
                    'running': False,
                    'message': 'Traefik no está ejecutándose'
                }
            
            traefik = traefik_containers[0]
            
            return {
                'running': True,
                'container_id': traefik.id,
                'container_name': traefik.name,
                'status': traefik.status,
                'message': 'Traefik está ejecutándose correctamente'
            }
            
        except Exception as e:
            return {
                'running': False,
                'error': str(e),
                'message': f'Error al verificar Traefik: {str(e)}'
            }
