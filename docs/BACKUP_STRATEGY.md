# Estrategia Avanzada de Backups con Docker

## Situación Actual

Tu sistema actualmente implementa backups manuales que incluyen:
- Dump de base de datos PostgreSQL (formato comprimido)
- Filestore de Odoo (opcional)
- Metadata en formato JSON

**Limitaciones actuales:**
- No hay backups automáticos programados
- No hay versionado incremental
- No hay point-in-time recovery (PITR)
- Los backups son solo completos (full backups)

---

## Soluciones Propuestas con Docker

### 1. 🎯 **Recomendación Principal: Docker Volumes con Backups Incrementales**

#### Tecnologías a Implementar:

##### A) **Restic + Docker Volumes** (Recomendado)
Restic es una herramienta moderna de backups que soporta:
- Backups incrementales eficientes (deduplicación)
- Snapshots con recuperación a cualquier punto en el tiempo
- Encriptación nativa
- Múltiples backends (local, S3, Azure, etc.)

**Implementación:**

```yaml
# docker-compose.yml - Agregar servicio de backups
services:
  # ... tus servicios existentes ...
  
  backup-manager:
    image: restic/restic:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./backups:/backups
      - restic-cache:/cache
      - restic-data:/data
    environment:
      - RESTIC_REPOSITORY=/data
      - RESTIC_PASSWORD=${BACKUP_PASSWORD}
      - BACKUP_SCHEDULE=0 */4 * * *  # Cada 4 horas
    networks:
      - web
    command: |
      sh -c "
      restic init || true
      restic backup /backups
      restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6
      "

volumes:
  restic-cache:
  restic-data:
```

**Ventajas:**
- ✅ Backups automáticos programados
- ✅ Recuperación a cualquier snapshot
- ✅ Deduplicación (ahorra espacio)
- ✅ Verificación de integridad
- ✅ Soporte para múltiples destinos

---

##### B) **PostgreSQL WAL-E / WAL-G para PITR**

Para bases de datos críticas, implementar Write-Ahead Logging archiving:

```yaml
services:
  postgres-pitr:
    image: postgres:13
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      PGDATA: /var/lib/postgresql/data/pgdata
      # Configuración WAL
      POSTGRES_INITDB_ARGS: "-c wal_level=replica -c archive_mode=on -c archive_command='wal-g wal-push %p'"
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./wal-archive:/wal-archive
      - ./backups/pg:/backups
    command: |
      postgres
      -c wal_level=replica
      -c archive_mode=on
      -c archive_command='test ! -f /wal-archive/%f && cp %p /wal-archive/%f'
      -c restore_command='cp /wal-archive/%f %p'
```

**Recuperación a fecha específica:**
```bash
# Restaurar a un punto específico en el tiempo
docker exec -it db_instance psql -U odoo -c "
  SELECT pg_create_restore_point('before_migration');
"

# Para restaurar
# 1. Detener PostgreSQL
# 2. Crear recovery.conf con:
restore_command = 'cp /wal-archive/%f %p'
recovery_target_time = '2025-12-31 10:30:00'
```

---

##### C) **ZFS Snapshots** (Avanzado)

Si usas ZFS, puedes crear snapshots instantáneos:

```bash
# Crear snapshot
zfs snapshot tank/docker/volumes@snapshot-$(date +%Y%m%d-%H%M%S)

# Listar snapshots
zfs list -t snapshot

# Restaurar desde snapshot
zfs rollback tank/docker/volumes@snapshot-20251231-103000
```

---

### 2. 🔄 **Sistema de Backups Automatizado para tu Aplicación**

#### Implementación en Django

**Nuevo archivo: `orchestrator/backup_scheduler.py`**

```python
from django_celery_beat.models import PeriodicTask, CrontabSchedule
import json

def setup_backup_schedule(instance, schedule='0 2 * * *'):
    """
    Configura backups automáticos para una instancia
    schedule: crontab expression (default: diario a las 2 AM)
    """
    schedule_obj, _ = CrontabSchedule.objects.get_or_create(
        minute='0',
        hour='2',
        day_of_week='*',
        day_of_month='*',
        month_of_year='*',
    )
    
    PeriodicTask.objects.create(
        crontab=schedule_obj,
        name=f'backup-{instance.name}',
        task='orchestrator.tasks.create_backup',
        args=json.dumps([instance.id, True]),  # include_filestore=True
    )

def create_incremental_backup(instance):
    """
    Crea backup incremental usando rsync
    """
    import subprocess
    from datetime import datetime
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = f"/backups/{instance.name}"
    current_backup = f"{backup_dir}/current"
    snapshot_dir = f"{backup_dir}/snapshots/{timestamp}"
    
    # Crear backup incremental con hard links
    subprocess.run([
        'rsync', '-av', '--delete',
        '--link-dest', current_backup,
        f'/instances/{instance.name}/',
        snapshot_dir
    ])
    
    # Actualizar link a current
    subprocess.run(['ln', '-nsf', snapshot_dir, current_backup])
```

---

### 3. 📦 **Docker Volume Backup con Duplicati**

Duplicati es una solución completa con UI web:

```yaml
services:
  duplicati:
    image: lscr.io/linuxserver/duplicati:latest
    container_name: backup-duplicati
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/Mexico_City
    volumes:
      - ./duplicati-config:/config
      - ./backups:/backups
      - /var/lib/docker/volumes:/source:ro  # Acceso a todos los volumes
    ports:
      - 8200:8200
    restart: unless-stopped
```

**Características:**
- ✅ Interfaz web para configuración
- ✅ Backups programados
- ✅ Soporte para S3, Azure, Google Drive
- ✅ Restauración point-in-time
- ✅ Encriptación AES-256

---

### 4. 🔍 **Sistema de Snapshots para tu Aplicación**

**Nuevo modelo: `orchestrator/snapshot_models.py`**

```python
from django.db import models
from .models import Instance

class Snapshot(models.Model):
    """Model for instance snapshots"""
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    snapshot_type = models.CharField(
        max_length=20,
        choices=[
            ('manual', 'Manual'),
            ('automatic', 'Automatic'),
            ('pre-deploy', 'Pre-Deployment'),
        ]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Metadata
    volume_snapshots = models.JSONField(default=dict)
    database_wal_position = models.CharField(max_length=100, blank=True)
    git_commit = models.CharField(max_length=40, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['instance', '-created_at']),
        ]
```

**Servicio de Snapshots: `orchestrator/snapshot_service.py`**

```python
class SnapshotService:
    def __init__(self):
        self.client = docker.from_env()
    
    def create_snapshot(self, instance, name, description=''):
        """Crea un snapshot completo de la instancia"""
        snapshot = Snapshot.objects.create(
            instance=instance,
            name=name,
            description=description,
            snapshot_type='manual'
        )
        
        # 1. Crear snapshot de volumes
        volume_snapshots = {}
        for volume in self._get_instance_volumes(instance):
            snapshot_id = self._snapshot_volume(volume)
            volume_snapshots[volume.name] = snapshot_id
        
        # 2. Guardar posición WAL de PostgreSQL
        db_container = self.client.containers.get(f"db_{instance.name}")
        wal_position = self._get_wal_position(db_container)
        
        # 3. Guardar commit de Git
        git_commit = self._get_git_commit(instance)
        
        snapshot.volume_snapshots = volume_snapshots
        snapshot.database_wal_position = wal_position
        snapshot.git_commit = git_commit
        snapshot.save()
        
        return snapshot
    
    def restore_snapshot(self, snapshot):
        """Restaura una instancia a un snapshot específico"""
        instance = snapshot.instance
        
        # 1. Detener instancia
        self.stop_instance(instance)
        
        # 2. Restaurar volumes
        for volume_name, snapshot_id in snapshot.volume_snapshots.items():
            self._restore_volume(volume_name, snapshot_id)
        
        # 3. Restaurar base de datos a punto específico
        if snapshot.database_wal_position:
            self._restore_database_pitr(instance, snapshot.database_wal_position)
        
        # 4. Restaurar código a commit específico
        if snapshot.git_commit:
            self._restore_git_commit(instance, snapshot.git_commit)
        
        # 5. Reiniciar instancia
        self.start_instance(instance)
    
    def _snapshot_volume(self, volume):
        """Crea snapshot de un volume usando rsync o ZFS"""
        # Implementación específica según tecnología
        pass
    
    def _get_wal_position(self, db_container):
        """Obtiene la posición actual del WAL"""
        result = db_container.exec_run(
            "psql -U odoo -c 'SELECT pg_current_wal_lsn()'"
        )
        return result.output.decode('utf-8').strip()
```

---

### 5. 🎬 **Plan de Implementación**

#### Fase 1: Backups Automáticos (1-2 días)
1. ✅ Instalar Celery y django-celery-beat
2. ✅ Configurar tareas periódicas de backup
3. ✅ Agregar retención de backups (eliminar antiguos)

```python
# requirements.txt
celery==5.3.4
django-celery-beat==2.5.0
redis==5.0.1

# settings.py
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_BEAT_SCHEDULE = {
    'backup-all-instances': {
        'task': 'orchestrator.tasks.backup_all_instances',
        'schedule': crontab(hour=2, minute=0),  # 2 AM diario
    },
}
```

#### Fase 2: Sistema de Snapshots (2-3 días)
1. ✅ Implementar modelo Snapshot
2. ✅ Agregar vistas para crear/restaurar snapshots
3. ✅ Integrar con Docker volumes

#### Fase 3: PITR con WAL (3-5 días)
1. ✅ Configurar archivado WAL en PostgreSQL
2. ✅ Implementar servicio de restauración PITR
3. ✅ Agregar UI para seleccionar fecha de restauración

#### Fase 4: Restic o Duplicati (2-3 días)
1. ✅ Configurar contenedor de backups
2. ✅ Integrar con almacenamiento remoto (S3, Azure)
3. ✅ Configurar políticas de retención

---

### 6. 📊 **UI Mejorada para Backups**

**Vista de Timeline de Backups:**

```html
<!-- templates/orchestrator/instance_backups.html -->
<div class="backup-timeline">
    {% for snapshot in snapshots %}
    <div class="timeline-item">
        <div class="timeline-marker"></div>
        <div class="timeline-content">
            <h4>{{ snapshot.name }}</h4>
            <p>{{ snapshot.created_at }}</p>
            <div class="actions">
                <button onclick="restoreToPoint('{{ snapshot.id }}')">
                    🔄 Restaurar a este punto
                </button>
                <button onclick="viewDetails('{{ snapshot.id }}')">
                    📊 Ver detalles
                </button>
            </div>
        </div>
    </div>
    {% endfor %}
</div>

<div class="pitr-selector">
    <h3>Restaurar a fecha específica</h3>
    <input type="datetime-local" id="pitr-datetime">
    <button onclick="restoreToPITR()">Restaurar</button>
</div>
```

---

### 7. 📈 **Monitoreo y Alertas**

```python
# orchestrator/monitoring.py
import smtplib
from django.core.mail import send_mail

def check_backup_health():
    """Verifica que los backups estén actualizados"""
    from datetime import datetime, timedelta
    
    for instance in Instance.objects.filter(status='running'):
        last_backup = Backup.objects.filter(
            instance=instance
        ).order_by('-created_at').first()
        
        if not last_backup:
            alert_no_backup(instance)
        elif last_backup.created_at < datetime.now() - timedelta(hours=24):
            alert_backup_outdated(instance, last_backup)

def alert_no_backup(instance):
    send_mail(
        subject=f'⚠️ Sin backups para {instance.name}',
        message=f'La instancia {instance.name} no tiene backups',
        from_email='alerts@community-sh.com',
        recipient_list=['admin@community-sh.com'],
    )
```

---

## 🎯 Recomendación Final

Para tu caso específico, te recomiendo implementar en este orden:

1. **Corto plazo (esta semana):**
   - Backups automáticos con Celery
   - Retención de backups (mantener últimos 7 días + 4 semanales)

2. **Mediano plazo (próximo mes):**
   - Sistema de Snapshots con Docker
   - Implementar Restic para backups incrementales

3. **Largo plazo (3 meses):**
   - PostgreSQL PITR con WAL archiving
   - Integración con S3/Azure para backups remotos
   - Dashboard de monitoreo de backups

---

## 📚 Recursos Adicionales

- [Restic Documentation](https://restic.readthedocs.io/)
- [PostgreSQL PITR](https://www.postgresql.org/docs/current/continuous-archiving.html)
- [Docker Volume Backup Best Practices](https://docs.docker.com/storage/volumes/)
- [Duplicati Manual](https://duplicati.readthedocs.io/)

---

## 🚀 Siguiente Paso

¿Quieres que implemente alguna de estas soluciones? Puedo empezar con:
1. Sistema de backups automáticos con Celery
2. Modelo de Snapshots
3. Configuración de Restic
4. PostgreSQL PITR

**¿Por cuál empezamos?** 🤔
