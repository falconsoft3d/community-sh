# Guía de Instalación y Uso de WAL & PITR

## 🚀 Instalación

### 1. Aplicar Migraciones de Base de Datos

```bash
# Activar entorno virtual
source venv/bin/activate

# Crear migraciones para los nuevos modelos WAL
python manage.py makemigrations orchestrator

# Aplicar migraciones
python manage.py migrate
```

### 2. Crear Directorios Necesarios

```bash
# Crear directorio para archivos WAL
mkdir -p backups/wal
mkdir -p backups/recovery_temp

# Dar permisos
chmod -R 755 backups/
```

### 3. Reiniciar Instancias Existentes (Opcional)

Para habilitar WAL en instancias ya creadas, necesitas recrearlas:

```bash
# Desde la interfaz web:
# 1. Ir a la instancia
# 2. Hacer backup completo
# 3. Detener la instancia
# 4. Eliminar contenedores manualmente (o desde la interfaz)
# 5. Volver a desplegar (Deploy)
```

---

## 📖 Cómo Usar desde la Interfaz Web

### 1. Acceder a WAL & PITR

1. Ve a tu instancia en el dashboard
2. Verás una nueva tarjeta azul **"WAL & PITR"** 
3. Haz clic en **"Gestionar Puntos de Restauración"**

### 2. Crear un Punto de Restauración

**¿Cuándo crear uno?**
- Antes de actualizar módulos
- Antes de hacer cambios importantes en la configuración
- Antes de importar datos masivos
- Antes de deploy de código nuevo

**Pasos:**
1. En la sección "Crear Punto de Restauración"
2. Ingresa un nombre descriptivo (ej: "antes-actualizar-modulos")
3. Opcionalmente agrega una descripción
4. Haz clic en "💾 Crear Punto de Restauración"

✅ **Resultado:** Se crea un punto de restauración al que puedes volver en cualquier momento.

### 3. Restaurar a un Punto de Restauración

**Escenario:** Actualizaste módulos y algo salió mal.

**Pasos:**
1. Ve a la sección "Puntos de Restauración Disponibles"
2. Encuentra el punto que creaste antes del cambio
3. Haz clic en "🔄 Restaurar Aquí"
4. Confirma la operación

⚠️ **Importante:** 
- La instancia se detendrá durante 1-2 minutos
- La base de datos volverá al estado exacto de ese punto
- Los cambios posteriores se perderán

### 4. Restaurar a Fecha/Hora Específica (PITR)

**Escenario:** Necesitas volver a las 10:30 AM de hoy (antes de que un usuario borrara datos).

**Pasos:**
1. Ve a la sección "Restaurar a Fecha/Hora Específica (PITR)"
2. Selecciona la fecha y hora exacta
3. Haz clic en "⏰ Restaurar a esta Fecha/Hora"
4. Confirma (lee las advertencias)

⏱️ **Precisión:** Puedes restaurar con precisión de segundos.

### 5. Verificar un Punto de Restauración

Para asegurarte que un punto sigue siendo válido:

1. Encuentra el punto en la lista
2. Haz clic en "🔍 Verificar"
3. El sistema verificará que los archivos WAL necesarios existen

### 6. Limpiar Archivos WAL Antiguos

Los archivos WAL se acumulan con el tiempo. Para liberar espacio:

1. Ve a la sección "Archivos WAL Recientes"
2. Selecciona cuántos días mantener (3, 7, 14, 30)
3. Haz clic en "🗑️ Limpiar Antiguos"

⚠️ **Nota:** Los archivos referenciados por puntos de restauración NO se eliminan.

---

## 🎯 Casos de Uso Comunes

### Caso 1: Actualización Segura de Módulos

```
1. Crear punto: "antes-actualizar-modulos-v2.0"
2. Instalar/actualizar módulos
3. Probar cambios
4. Si algo falla → Restaurar al punto
5. Si todo funciona → Crear nuevo punto "despues-actualizar-ok"
```

### Caso 2: Recuperación de Datos Borrados

```
Usuario borró facturas a las 3:30 PM
Tú te das cuenta a las 4:00 PM

1. Ir a PITR
2. Seleccionar fecha: Hoy 3:29 PM
3. Restaurar
4. Datos recuperados ✅
```

### Caso 3: Rollback de Deploy

```
Hiciste deploy de código nuevo a las 2:00 PM
Encuentras bugs críticos a las 2:30 PM

Opción A - Si creaste punto antes:
1. Restaurar al punto "pre-deploy-2pm"

Opción B - Si no creaste punto:
1. Usar PITR para volver a las 1:59 PM
```

### Caso 4: Testing Destructivo

```
Necesitas probar migraciones de datos

1. Crear punto: "antes-test-migracion"
2. Ejecutar script de migración
3. Revisar resultados
4. Si no te gusta → Restaurar
5. Ajustar script y repetir
```

---

## 📊 Monitoreo del Sistema

### Ver Estado del WAL

En la página de WAL verás:

- **LSN Actual:** Posición actual en el log de transacciones
- **Archivos WAL:** Cuántos archivos hay y su tamaño total
- **Estado:** Si el archivado está funcionando correctamente

### Indicadores de Salud

✅ **Verde (Saludable):**
- Archivos WAL se están generando
- El archivado funciona
- Puedes hacer PITR

❌ **Rojo (Error):**
- Algo está mal con PostgreSQL
- No se pueden crear puntos de restauración
- Revisar logs del contenedor

---

## 🔧 Solución de Problemas

### Error: "No se puede crear punto de restauración"

**Posibles causas:**
1. PostgreSQL no está corriendo
2. WAL no está habilitado (instancia antigua)

**Solución:**
```bash
# Verificar que el contenedor está corriendo
docker ps | grep db_<nombre-instancia>

# Verificar logs
docker logs db_<nombre-instancia>

# Si es instancia antigua, recrear:
1. Hacer backup completo
2. Detener y eliminar contenedores
3. Volver a desplegar
```

### Error: "Restauración fallida"

**Posibles causas:**
1. Archivos WAL no disponibles
2. Rango de tiempo inválido

**Solución:**
1. Verificar que el punto de restauración existe
2. Verificar que los archivos WAL están en `/backups/wal/<instancia>/`
3. Usar punto de restauración en lugar de PITR si hay problemas

### Espacio en Disco Lleno

**Síntomas:**
- Muchos archivos WAL acumulados
- Disco lleno

**Solución:**
```bash
# Desde la interfaz:
1. Ir a "Limpiar Archivos WAL"
2. Mantener solo últimos 3-7 días

# Manualmente:
cd backups/wal/<instancia>
ls -lh  # Ver tamaño
# Eliminar manualmente archivos antiguos si es necesario
```

---

## ⚙️ Configuración Avanzada

### Cambiar Frecuencia de Archivado WAL

Por defecto, PostgreSQL archiva cada 30 segundos o 16MB.

Para cambiar esto, edita [orchestrator/services.py](orchestrator/services.py) línea ~50:

```python
# Cambiar archive_timeout de 30 a otro valor (en segundos)
"-c", "archive_timeout=60",  # Archivar cada 60 segundos
```

### Crear Puntos de Restauración Automáticos

Puedes crear puntos automáticamente antes de cada deploy:

1. Edita [orchestrator/services.py](orchestrator/services.py)
2. En el método `deploy_instance`, antes de desplegar:

```python
# Importar WALService
from .wal_service import WALService

def deploy_instance(self, instance):
    # ... código existente ...
    
    # Crear punto de restauración automático antes de deploy
    try:
        wal_service = WALService()
        wal_service.create_restore_point(
            instance=instance,
            name=f"pre-deploy-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            description="Punto automático antes de deploy",
            user=None
        )
    except Exception as e:
        print(f"No se pudo crear punto de restauración: {e}")
    
    # ... continuar con deploy ...
```

---

## 📈 Mejoras Futuras Recomendadas

1. **Backup Remoto de WAL:** Copiar archivos WAL a S3/Azure
2. **Alertas:** Notificar si el archivado WAL falla
3. **Programación:** Crear puntos de restauración automáticos cada X horas
4. **Dashboard:** Gráfica de timeline de puntos de restauración
5. **Comparación:** Ver diferencias entre dos puntos de restauración

---

## 🎓 Conceptos Clave

### ¿Qué es WAL?
Write-Ahead Logging: PostgreSQL registra TODAS las transacciones en archivos de log antes de escribir a disco.

### ¿Qué es LSN?
Log Sequence Number: Posición única en el log de transacciones. Como un "marcador" en el tiempo.

### ¿Qué es PITR?
Point-in-Time Recovery: Capacidad de restaurar a cualquier momento exacto en el tiempo, no solo a backups programados.

### Diferencia con Backups Normales

| Característica | Backup Normal | WAL + PITR |
|----------------|---------------|------------|
| Frecuencia | Manual o cada X horas | Continuo (cada 30 seg) |
| Pérdida máxima | Horas | Segundos |
| Flexibilidad | Solo puntos de backup | Cualquier momento |
| Espacio | Alto (completos) | Medio (incremental) |
| Complejidad | Baja | Media |

---

## 💡 Mejores Prácticas

1. ✅ **Crear puntos antes de cambios importantes**
2. ✅ **Verificar puntos periódicamente**
3. ✅ **Limpiar archivos WAL antiguos mensualmente**
4. ✅ **Mantener al menos 7 días de WAL**
5. ✅ **Probar restauración en ambiente de prueba**
6. ✅ **Documentar puntos de restauración con buenas descripciones**
7. ⚠️ **NO eliminar archivos WAL manualmente sin verificar**
8. ⚠️ **NO hacer PITR en producción sin avisar a usuarios**

---

## 🆘 Soporte

Si tienes problemas:

1. Revisa los logs de PostgreSQL: `docker logs db_<instancia>`
2. Verifica archivos WAL: `ls -lh backups/wal/<instancia>/`
3. Consulta esta documentación
4. Revisa el código en [orchestrator/wal_service.py](orchestrator/wal_service.py)

---

**¡WAL & PITR está listo para usar! 🎉**

Empieza creando tu primer punto de restauración ahora mismo.
