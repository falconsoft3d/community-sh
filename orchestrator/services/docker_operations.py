"""Day-to-day operations on a running instance: logs, console, pull of its code, module updates, browser and pip. Part of DockerService."""
import docker
import os
import git
from django.conf import settings
from ..task_log import progress
from .docker_helpers import (
    BROWSER_SCRIPT,
    odoo_command,
    pip_user_command,
)


class OperationsMixin:
    def get_logs(self, instance, lines=100):
        if not instance.container_id:
            return "No container ID found."
        try:
            container = self.client.containers.get(instance.container_id)
            # logs returns bytes, need to decode
            return container.logs(tail=lines).decode('utf-8')
        except docker.errors.NotFound:
            return "Container not found."
        except Exception as e:
            return f"Error fetching logs: {str(e)}"
    
    def execute_command(self, instance, command):
        """Execute a command inside the container and return the output"""
        if not instance.container_id:
            return "No container ID found."
        
        try:
            container = self.client.containers.get(instance.container_id)
            
            # Execute command inside container without specifying workdir
            # This allows the command to run from the container's default directory
            exec_result = container.exec_run(
                command,
                stdout=True,
                stderr=True,
                stdin=False,
                tty=False,
                privileged=False,
                user=''
            )
            
            # Decode output
            output = exec_result.output.decode('utf-8')
            exit_code = exec_result.exit_code
            
            if exit_code != 0:
                return f"[Exit Code: {exit_code}]\n{output}"
            return output
            
        except docker.errors.NotFound:
            return "Container not found."
        except docker.errors.APIError as e:
            return f"Docker API Error: {str(e)}"
        except Exception as e:
            return f"Error executing command: {str(e)}"
    
    @staticmethod
    def _code_state(workspace_path):
        """What the instance runs: the commit of each of its repository folders and its Odoo config."""
        folders = [os.path.join(workspace_path, 'addons')]
        repos_root = os.path.join(workspace_path, 'repos')
        if os.path.isdir(repos_root):
            folders += [os.path.join(repos_root, name) for name in sorted(os.listdir(repos_root))]
        state = {}
        for folder in folders:
            try:
                state[folder] = git.Repo(folder).head.commit.hexsha
            except Exception:
                pass
        config_dir = os.path.join(workspace_path, 'conf')
        if os.path.isdir(config_dir):
            for name in sorted(os.listdir(config_dir)):
                try:
                    with open(os.path.join(config_dir, name), 'rb') as f:
                        state[name] = f.read()
                except OSError:
                    pass
        return state

    def pull_repositories(self, instance, update_all=False, only_if_changed=False):
        """The instance's repositories brought to the last commit of their branch, and Odoo restarted to load the
        code: what a deploy does with them, without recreating the container. update_all: also `-u all` on
        every database (new fields, views and data of the modules), as a redeploy does. only_if_changed (the
        automatic updates): neither when no commit nor the config changed. self.changed tells which it was."""
        workspace_path = os.path.join(settings.BASE_DIR, 'instances', instance.name)
        os.makedirs(workspace_path, exist_ok=True)
        self.deploy_notes = []
        before = self._code_state(workspace_path)
        progress(10, 'Actualizando el repositorio principal')
        self._clone_repo(instance, workspace_path)
        progress(40, 'Actualizando los repositorios de módulos')
        extra_repos = self._sync_extra_repos(instance, workspace_path)
        self._write_odoo_config(instance, workspace_path, extra_repos)
        notes = list(self.deploy_notes)
        folders = [('principal', os.path.join(workspace_path, 'addons'))] if instance.github_repo else []
        folders += [(slug, os.path.join(workspace_path, 'repos', slug)) for slug in extra_repos]
        for label, folder in folders:
            try:
                commit = git.Repo(folder).head.commit
                notes.append(f'{label}: {commit.hexsha[:7]} {commit.summary}')
            except Exception:
                pass
        self.changed = self._code_state(workspace_path) != before
        if only_if_changed and not self.changed:
            notes.append('Sin cambios desde la última actualización: Odoo no se reinicia')
            return notes
        if update_all:
            notes += self.update_all_modules(instance)
        progress(90, 'Reiniciando Odoo para cargar el código')
        self.restart_instance(instance)
        return notes

    def update_all_modules(self, instance):
        """`odoo -u all --stop-after-init` on each database of the instance. Returns notes for the task log."""
        odoo_container = self._get_container(f'odoo_{instance.name}')
        db_container = self._start_db_container(instance)
        if odoo_container is None or db_container is None:
            raise Exception('La instancia no está desplegada: despliégala antes de actualizar sus módulos')
        if odoo_container.status != 'running':
            odoo_container.start()
        self._wait_for_postgres(db_container)
        databases = [instance.database_name] if instance.database_name else self._list_user_databases(db_container)
        notes = []
        for index, database in enumerate(databases):
            progress(55 + 30 * index // max(len(databases), 1), f'Actualizando todos los módulos de {database}')
            result = odoo_container.exec_run(
                ['sh', '-c', f'{odoo_command(instance.odoo_version)} -u all -d "$DB" --stop-after-init'],
                environment={'DB': database})
            output = result.output.decode('utf-8', errors='replace')
            print(f"Module update for {database} (exit {result.exit_code}): {output[-3000:]}")
            if result.exit_code != 0:
                raise Exception(f'La actualización de módulos de {database} falló (código {result.exit_code}): {output[-600:]}')
            notes.append(f'{database}: todos los módulos actualizados (-u all)')
        return notes

    def install_browser(self, instance, container=None):
        """Google Chrome in the Odoo container, as root (WhatsApp Web runs it). What it prints goes to the task log."""
        container = container or self.client.containers.get(f'odoo_{instance.name}')
        api = self.client.api
        exec_id = api.exec_create(container.id, ['sh', '-c', BROWSER_SCRIPT], user='root')['Id']
        tail = ''
        for chunk in api.exec_start(exec_id, stream=True):
            text = chunk.decode('utf-8', errors='replace')
            print(text, end='')
            tail = (tail + text)[-3000:]
        exit_code = api.exec_inspect(exec_id)['ExitCode']
        if exit_code != 0:
            raise Exception(f'la instalación terminó con el código {exit_code}:\n{tail[-1500:]}')
        version = [line for line in tail.splitlines() if line.startswith('Google Chrome')]
        return f'Navegador: {version[-1] if version else "Google Chrome instalado"}'

    def pip_install(self, instance, command):
        """Run a `pip install` in the Odoo container so that it works and lasts.

        The Debian of the Odoo 17+ images refuses pip on the system Python (PEP 668), and what root installs lives in
        the container, which every redeploy recreates. So the packages go to the site-packages of the odoo user,
        under /var/lib/odoo: the data volume, kept across redeploys. Returns (ok, output).
        """
        command = pip_user_command(command)
        output = self.execute_command(instance, command)
        if 'no such option: --break-system-packages' in output:
            # pip older than 23 (Odoo up to 16) has no such flag, nor the restriction
            output = self.execute_command(instance, command.replace(' --break-system-packages', ''))
        ok = not output.startswith('[Exit Code:') and not output.startswith(('No container', 'Container not found', 'Docker API Error', 'Error executing'))
        return ok, output
