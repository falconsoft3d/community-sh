import docker
from django.conf import settings
import os
from .template_services import get_template_loader

class ContainerService:
    """Service for managing generic Docker containers"""
    
    def __init__(self):
        self.client = docker.from_env()
    
    def create_container(self, container):
        """Create and start a Docker container from a Container model"""
        from .container_models import Container
        
        try:
            container.status = 'creating'
            container.save()
            
            # Prepare volume mounts
            volumes = {}
            for volume_name, volume_config in container.volumes.items():
                # Handle new YAML structure: {volume_name: {host: ..., container: ...}}
                if isinstance(volume_config, dict):
                    host_path = volume_config.get('host', '')
                    container_path = volume_config.get('container', '')
                else:
                    # Fallback for old structure
                    host_path = volume_name
                    container_path = volume_config
                
                if not host_path or not container_path:
                    continue
                    
                if not host_path.startswith('/'):
                    # Create a named Docker volume
                    docker_volume_name = f"{container.name}_{volume_name}"
                    try:
                        self.client.volumes.get(docker_volume_name)
                    except docker.errors.NotFound:
                        self.client.volumes.create(name=docker_volume_name)
                    volumes[docker_volume_name] = {'bind': container_path, 'mode': 'rw'}
                else:
                    # Absolute bind mount (use with caution)
                    volumes[host_path] = {'bind': container_path, 'mode': 'rw'}
            
            # Prepare Traefik labels for automatic routing
            labels = {
                'traefik.enable': 'true',
                f'traefik.http.routers.{container.name}.rule': f'Host(`{container.name}.localhost`)',
                f'traefik.http.routers.{container.name}.entrypoints': 'web',
                f'traefik.http.services.{container.name}.loadbalancer.server.port': str(container.container_port),
            }
            
            # Remove existing container with same name if it exists
            try:
                existing = self.client.containers.get(container.name)
                existing.stop()
                existing.remove()
                print(f"Removed existing container: {container.name}")
            except docker.errors.NotFound:
                pass
            
            # Create network if it doesn't exist
            if container.network and container.network != 'bridge':
                try:
                    self.client.networks.get(container.network)
                except docker.errors.NotFound:
                    self.client.networks.create(container.network, driver="bridge")
                    print(f"Created network: {container.network}")
            
            # Create container
            # Get user from template defaults if available
            loader = get_template_loader()
            template_defaults = loader.get_template_defaults(container.template)
            user_config = template_defaults.get('user', None)

            docker_container = self.client.containers.run(
                image=container.image,
                command=container.command,
                name=container.name,
                ports={f'{container.container_port}/tcp': container.port},
                environment=container.environment,
                volumes=volumes,
                network=container.network,
                labels=labels,
                user=user_config,
                detach=True,
                restart_policy={'Name': 'unless-stopped'}
            )
            
            container.container_id = docker_container.id
            container.status = 'running'
            container.save()
            
            return True, f"Container {container.name} created successfully"
            
        except Exception as e:
            container.status = 'error'
            container.save()
            return False, f"Error creating container: {str(e)}"
    
    def stop_container(self, container):
        """Stop a running container"""
        try:
            docker_container = self.client.containers.get(container.container_id)
            docker_container.stop()
            container.status = 'stopped'
            container.save()
            return True, f"Container {container.name} stopped"
        except Exception as e:
            return False, f"Error stopping container: {str(e)}"
    
    def start_container(self, container):
        """Start a stopped container"""
        try:
            docker_container = self.client.containers.get(container.container_id)
            docker_container.start()
            container.status = 'running'
            container.save()
            return True, f"Container {container.name} started"
        except Exception as e:
            return False, f"Error starting container: {str(e)}"
    
    def restart_container(self, container):
        """Restart a container"""
        try:
            docker_container = self.client.containers.get(container.container_id)
            docker_container.restart()
            container.status = 'running'
            container.save()
            return True, f"Container {container.name} restarted"
        except Exception as e:
            return False, f"Error restarting container: {str(e)}"
    
    def delete_container(self, container):
        """Delete a container and its volumes"""
        try:
            # Stop and remove container only if it has a container_id
            if container.container_id:
                try:
                    docker_container = self.client.containers.get(container.container_id)
                    docker_container.stop()
                    docker_container.remove()
                except docker.errors.NotFound:
                    # Container already deleted from Docker
                    pass
                except docker.errors.APIError as e:
                    # Handle API errors (like invalid container_id)
                    print(f"Docker API error while deleting container: {e}")
                    pass
            
            # Remove Docker named volumes
            for volume_name, volume_config in container.volumes.items():
                if isinstance(volume_config, dict):
                    host_path = volume_config.get('host', '')
                else:
                    host_path = volume_name
                
                if host_path and not host_path.startswith('/'):
                    # Remove named Docker volume
                    docker_volume_name = f"{container.name}_{volume_name}"
                    try:
                        volume = self.client.volumes.get(docker_volume_name)
                        volume.remove()
                    except docker.errors.NotFound:
                        pass
                    except Exception as e:
                        print(f"Error removing volume {docker_volume_name}: {e}")
            
            return True, f"Container {container.name} deleted"
        except Exception as e:
            return False, f"Error deleting container: {str(e)}"
    
    def get_container_logs(self, container, tail=100):
        """Get container logs"""
        try:
            docker_container = self.client.containers.get(container.container_id)
            logs = docker_container.logs(tail=tail, timestamps=True).decode('utf-8')
            return logs
        except Exception as e:
            return f"Error getting logs: {str(e)}"
    
    def get_container_stats(self, container):
        """Get container resource usage stats"""
        try:
            docker_container = self.client.containers.get(container.container_id)
            stats = docker_container.stats(stream=False)
            return stats
        except Exception as e:
            return None
