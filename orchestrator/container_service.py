import docker
from django.conf import settings
import os
from .template_services import get_template_loader
from .services.docker_helpers import log_config

# Docker names a user container must never take: the panel's own services (Docker DNS on the
# shared "web" network would send them part of the panel's traffic) and its compose project
RESERVED_CONTAINER_NAMES = {'app', 'db', 'traefik', 'worker', 'build-worker', 'ai-worker', 'postgres', 'localhost', 'web'}
OWNER_LABEL = 'community-sh.container'


def reserved_container_name(name):
    """Why a user container can't be called like this ('' when it can)."""
    if name in RESERVED_CONTAINER_NAMES or name.startswith(('community-sh', 'odoo', 'db-')):
        return f'«{name}» está reservado para el panel: elige otro nombre.'
    return ''


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
                        existing_volume = self.client.volumes.get(docker_volume_name)
                        if not self._volume_is_ours(existing_volume, container):
                            raise PermissionError(f"El volumen {docker_volume_name} pertenece a otro recurso")
                    except docker.errors.NotFound:
                        self.client.volumes.create(name=docker_volume_name, labels={OWNER_LABEL: str(container.pk)})
                    volumes[docker_volume_name] = {'bind': container_path, 'mode': 'rw'}
                else:
                    # Absolute bind mounts expose the host: admins only
                    if not container.created_by.is_superuser:
                        raise PermissionError(f"Host bind mount not allowed: {host_path}")
                    volumes[host_path] = {'bind': container_path, 'mode': 'rw'}
            
            # Prepare Traefik labels for automatic routing
            # Use custom domain if set, otherwise use container.name.localhost
            domain = container.custom_domain if container.custom_domain else f"{container.name}.localhost"
            
            if reserved_container_name(container.name):
                raise PermissionError(reserved_container_name(container.name))
            labels = {
                OWNER_LABEL: str(container.pk),
                'traefik.enable': 'true',
                'traefik.docker.network': 'community-sh_web',
                f'traefik.http.routers.{container.name}.rule': f'Host(`{domain}`)',
                f'traefik.http.routers.{container.name}.entrypoints': 'web',
                f'traefik.http.routers.{container.name}.priority': '100',
                f'traefik.http.services.{container.name}.loadbalancer.server.port': str(container.container_port),
            }
            
            # Remove an old copy of this same container (never someone else's: the panel, an instance...)
            try:
                existing = self.client.containers.get(container.name)
                if not self._container_is_ours(existing, container):
                    raise PermissionError(f"Ya hay otro contenedor de Docker llamado {container.name}: elige otro nombre")
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

            # Start on Traefik's network and join the template's network afterwards, so the
            # published port survives (see DockerService.deploy_instance)
            try:
                self.client.networks.get("community-sh_web")
                start_network = "community-sh_web"
            except docker.errors.NotFound:
                print("Warning: community-sh_web network not found. Traefik routing may not work.")
                start_network = None
            extra_network = container.network if start_network and container.network not in ('', 'bridge', start_network) else None
            
            docker_container = self.client.containers.run(
                image=container.image,
                command=container.command,
                name=container.name,
                ports={f'{container.container_port}/tcp': container.port},
                environment=container.environment,
                volumes=volumes,
                network=start_network or container.network,
                labels=labels,
                user=user_config,
                detach=True,
                restart_policy={'Name': 'unless-stopped'},
                log_config=log_config(),
            )
            
            if extra_network:
                self.client.networks.get(extra_network).connect(docker_container)
            
            container.container_id = docker_container.id
            container.status = 'running'
            container.save()
            self._route(container)
            
            return True, f"Container {container.name} created successfully"
            
        except Exception as e:
            container.status = 'error'
            container.save()
            return False, f"Error creating container: {str(e)}"
    
    @staticmethod
    def _container_is_ours(docker_container, container):
        labels = (docker_container.attrs.get('Config') or {}).get('Labels') or {}
        if OWNER_LABEL in labels:
            return labels[OWNER_LABEL] == str(container.pk)
        # Created before the label existed: only the one the panel recorded for it
        return bool(container.container_id) and docker_container.id == container.container_id \
            and 'com.docker.compose.project' not in labels

    @staticmethod
    def _volume_is_ours(volume, container):
        """A volume of this container, never one of the panel (compose), an instance or another container."""
        labels = (volume.attrs.get('Labels') or {}) if isinstance(volume.attrs, dict) else {}
        if OWNER_LABEL in labels:
            return labels[OWNER_LABEL] == str(container.pk)
        if 'com.docker.compose.project' in labels or volume.name.startswith('odoo_data_'):
            return False
        from .models import Instance
        return not Instance.objects.filter(data_volume=volume.name).exists()

    def stop_container(self, container):
        """Stop a running container"""
        try:
            docker_container = self.client.containers.get(container.container_id)
            docker_container.stop()
            container.status = 'stopped'
            container.save()
            self._route(container)
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
            self._route(container)
            return True, f"Container {container.name} started"
        except Exception as e:
            return False, f"Error starting container: {str(e)}"
    
    def restart_container(self, container):
        """Restart a container by recreating it with updated configuration"""
        try:
            # Stop and remove existing container
            if container.container_id:
                try:
                    docker_container = self.client.containers.get(container.container_id)
                    docker_container.stop()
                    docker_container.remove()
                except docker.errors.NotFound:
                    pass
            
            # Recreate container with updated configuration
            return self.create_container(container)
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
                        if not self._volume_is_ours(volume, container):
                            continue
                        volume.remove()
                    except docker.errors.NotFound:
                        pass
                    except Exception as e:
                        print(f"Error removing volume {docker_volume_name}: {e}")
            
            from .traefik_service import TraefikService
            TraefikService.remove_container_config(container.name)
            return True, f"Container {container.name} deleted"
        except Exception as e:
            return False, f"Error deleting container: {str(e)}"
    
    @staticmethod
    def _route(container):
        """HTTPS route under the platform domain, like the instances."""
        from .traefik_service import TraefikService
        ok, message = TraefikService.generate_container_config(container)
        if not ok:
            print(message)

    def build_image(self, container, log=print):
        """
        Clone container.git_repo (with the owner's GitHub token, so private repos work)
        and build its Dockerfile as container.built_image. Returns the image tag.
        """
        import shutil
        import tempfile
        import git
        from .config_models import GitHubConfig
        from .services.github import authed_url
        config = GitHubConfig.objects.filter(user=container.created_by).first()
        token = config.personal_access_token if config and config.personal_access_token else ''
        clean = lambda text: str(text).replace(token, '***') if token else str(text)  # noqa: E731
        workdir = tempfile.mkdtemp(prefix=f'csh-build-{container.name}-')
        try:
            branch = container.git_branch or 'main'
            log(f'Clonando {container.git_repo} ({branch})')
            try:
                git.Repo.clone_from(authed_url(container.git_repo, token), workdir, branch=branch, depth=1)
            except git.exc.GitCommandError as error:
                raise Exception(f'No se pudo clonar {container.git_repo}: {clean(error)[-300:]}')
            dockerfile = container.dockerfile or 'Dockerfile'
            if not os.path.exists(os.path.join(workdir, dockerfile)):
                raise Exception(f'El repositorio no tiene {dockerfile}')
            log(f'Construyendo la imagen con {dockerfile}')
            output = self.client.api.build(path=workdir, dockerfile=dockerfile, tag=container.built_image,
                                           rm=True, forcerm=True, pull=True, decode=True)
            for chunk in output:
                if 'error' in chunk:
                    raise Exception(chunk['error'].strip())
                line = (chunk.get('stream') or '').strip()
                if line:
                    log(line)
            return container.built_image
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

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
