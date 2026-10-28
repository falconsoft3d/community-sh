"""Install Odoo modules from uploaded ZIP files."""
import os
import git
from django.conf import settings
from .docker_service import DockerService



class OdooModuleService:
    """Service for installing Odoo modules from ZIP files"""
    
    @staticmethod
    def install_module_from_zip(instance, zip_file):
        """
        Installs a module from an uploaded ZIP file by adding it to GitHub repo.
        
        Args:
            instance: Instance object
            zip_file: Uploaded ZIP file (Django UploadedFile)
            
        Returns:
            tuple: (success: bool, message: str, module_name: str or None)
        """
        import zipfile
        import tempfile
        
        try:
            # 1. Verify instance has GitHub repo configured
            if not instance.github_repo:
                return False, "Esta instancia no tiene un repositorio de GitHub configurado", None
            
            # 2. Save uploaded file to temporary location
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
                for chunk in zip_file.chunks():
                    tmp_file.write(chunk)
                tmp_zip_path = tmp_file.name
            
            # 3. Extract to temporary directory first
            temp_extract_path = tempfile.mkdtemp()
            print(f"Extrayendo módulo temporalmente en: {temp_extract_path}")
            
            with zipfile.ZipFile(tmp_zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_extract_path)
            
            # Clean up zip file
            os.unlink(tmp_zip_path)
            
            # 4. Find the actual module directory name
            extracted_module_name = None
            module_temp_path = None
            
            for item in os.listdir(temp_extract_path):
                item_path = os.path.join(temp_extract_path, item)
                if os.path.isdir(item_path):
                    if os.path.exists(os.path.join(item_path, '__manifest__.py')) or \
                       os.path.exists(os.path.join(item_path, '__openerp__.py')):
                        extracted_module_name = item
                        module_temp_path = item_path
                        break
            
            if not extracted_module_name:
                import shutil
                shutil.rmtree(temp_extract_path)
                return False, "No se pudo identificar el módulo en el ZIP. Asegúrate de que contiene __manifest__.py", None
            
            # 5. Copy module to GitHub repo addons directory
            workspace_path = os.path.join(settings.BASE_DIR, 'instances', instance.name)
            addons_path = os.path.join(workspace_path, 'addons')
            os.makedirs(addons_path, exist_ok=True)
            
            module_dest_path = os.path.join(addons_path, extracted_module_name)
            
            # Copy module to repo
            import shutil
            if os.path.exists(module_dest_path):
                shutil.rmtree(module_dest_path)
            shutil.copytree(module_temp_path, module_dest_path)
            
            # Clean up temp directory
            shutil.rmtree(temp_extract_path)
            
            print(f"Módulo copiado a: {module_dest_path}")
            
            # 6. Commit and push to GitHub
            try:
                repo = git.Repo(workspace_path)
                
                # Add the new module
                repo.index.add([os.path.join('addons', extracted_module_name)])
                
                # Commit
                commit_message = f"Add module {extracted_module_name}"
                repo.index.commit(commit_message)
                
                # Push to remote
                origin = repo.remote(name='origin')
                origin.push()
                
                print(f"Módulo {extracted_module_name} agregado al repositorio y pusheado")
                
            except Exception as e:
                print(f"Error en Git: {str(e)}")
                return False, f"Error al hacer commit/push al repositorio: {str(e)}", extracted_module_name
            
            # 7. Deploy/upgrade the instance (this will update all modules)
            docker_service = DockerService()
            try:
                docker_service.deploy_instance(instance)
                
                return True, f"Módulo '{extracted_module_name}' agregado al repositorio y desplegado exitosamente", extracted_module_name
                
            except Exception as e:
                return False, f"Módulo agregado al repo pero error en deploy: {str(e)}", extracted_module_name
            
        except zipfile.BadZipFile:
            return False, "El archivo no es un ZIP válido", None
        except Exception as e:
            return False, f"Error inesperado: {str(e)}", None
