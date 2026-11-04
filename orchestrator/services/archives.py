"""Extracting uploaded ZIP files (modules, backups) without trusting what they say they hold."""
import os
import shutil

GB = 1024 ** 3


def safe_extractall(zip_file, destination, max_bytes, max_files=50_000):
    """
    extractall() after checking every entry: no absolute paths or "..", no more than max_files
    entries, and no more than max_bytes once unpacked (a small "zip bomb" can fill the disk), which
    must also fit in the free space of the destination.
    """
    entries = zip_file.infolist()
    if len(entries) > max_files:
        raise ValueError(f'El archivo tiene demasiados ficheros ({len(entries)}; máximo {max_files})')
    total = 0
    for entry in entries:
        name = entry.filename.replace('\\', '/')
        if name.startswith('/') or ':' in name.split('/')[0] or '..' in name.split('/'):
            raise ValueError(f'Ruta no permitida dentro del archivo: {entry.filename}')
        total += entry.file_size
    if total > max_bytes:
        raise ValueError(f'El archivo descomprimido ocuparía {total // 1024 ** 2} MB (máximo {max_bytes // 1024 ** 2} MB)')
    os.makedirs(destination, exist_ok=True)
    if total > shutil.disk_usage(destination).free * 0.9:
        raise ValueError('No hay espacio libre en el disco para descomprimir el archivo')
    zip_file.extractall(destination)
    return total
