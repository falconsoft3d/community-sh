import docker
from django.conf import settings
import os

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
            for host_path, container_path in container.volumes.items():
                if not host_path.startswith('/'):
                    # Create named volume
                    volume_name = f"{container.name}_{host_path}"
                    try:
                        self.client.volumes.get(volume_name)
                    except docker.errors.NotFound:
                        self.client.volumes.create(name=volume_name)
                    volumes[volume_name] = {'bind': container_path, 'mode': 'rw'}
                else:
                    # Bind mount
                    volumes[host_path] = {'bind': container_path, 'mode': 'rw'}
            
            # Prepare Traefik labels for automatic routing
            labels = {
                'traefik.enable': 'true',
                f'traefik.http.routers.{container.name}.rule': f'Host(`{container.name}.localhost`)',
                f'traefik.http.routers.{container.name}.entrypoints': 'web',
                f'traefik.http.services.{container.name}.loadbalancer.server.port': str(container.container_port),
            }
            
            # Create container
            docker_container = self.client.containers.run(
                image=container.image,
                name=container.name,
                ports={f'{container.container_port}/tcp': container.port},
                environment=container.environment,
                volumes=volumes,
                network=container.network,
                labels=labels,
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
            # Stop and remove container
            try:
                docker_container = self.client.containers.get(container.container_id)
                docker_container.stop()
                docker_container.remove()
            except docker.errors.NotFound:
                pass
            
            # Remove named volumes
            for host_path in container.volumes.keys():
                if not host_path.startswith('/'):
                    volume_name = f"{container.name}_{host_path}"
                    try:
                        volume = self.client.volumes.get(volume_name)
                        volume.remove()
                    except docker.errors.NotFound:
                        pass
            
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
