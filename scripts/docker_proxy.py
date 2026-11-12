#!/usr/bin/env python3
"""
Filtering proxy between the panel's web container (app) and the Docker daemon.

The web container needs Docker (instance logs and console, start/stop/restart, the Docker page,
generic containers), but the raw socket is root on the server: a single bug in a page would be
enough to start a privileged container that mounts the host. The web container talks to this
proxy instead (DOCKER_HOST=tcp://docker-proxy:2375 on an internal network) and the workers keep
the socket. Every request is checked before it reaches the daemon:

- Containers can't be created privileged, with extra capabilities, devices, host namespaces
  (pid, ipc, uts, userns, cgroup, network), other security options or another runtime, and they
  can only mount host folders under the allowed paths (the instances' folders by default; more
  in DOCKER_PROXY_ALLOWED_BINDS) and named volumes that aren't the panel's.
- The panel's own containers (its docker compose project, plus any privileged container or one
  with the Docker socket) can be listed, read, started, stopped and restarted, but not entered
  (exec, attach, files in or out), removed, renamed or reconnected.
- The panel's internal networks (database, this proxy) can't be joined; its volumes can't be removed.
- Swarm, plugins, secrets, image builds, loads and imports, registry logins: refused.

One request per connection (Connection: close), so nothing can ride on a connection after its
first request was checked. Only the standard library: it runs from the image, not the mounted code.
"""
import asyncio
import json
import logging
import os
import posixpath
import re
import sys
from urllib.parse import parse_qs, unquote, urlsplit

SOCKET = os.environ.get('DOCKER_PROXY_SOCKET', '/var/run/docker.sock')
PORT = int(os.environ.get('DOCKER_PROXY_PORT', '2375'))
MAX_HEADERS = 64 * 1024
MAX_BODY = 8 * 1024 * 1024
DOCKER_SOCKETS = ('/var/run/docker.sock', '/run/docker.sock')
# Networks of the panel's compose project nobody else may join
PROTECTED_NETWORKS = {n.strip() for n in os.environ.get('DOCKER_PROXY_PROTECTED_NETWORKS', 'backend,docker-api').split(',') if n.strip()}
HIJACK = re.compile(r'/(exec/[^/]+/start|containers/[^/]+/attach)')
SAFE_ON_PANEL = {'start', 'stop', 'restart', 'kill', 'pause', 'unpause', 'wait', 'resize'}
CLEANUP = {'/containers/prune', '/images/prune', '/volumes/prune', '/networks/prune', '/build/prune'}
HOST_MODES = ('PidMode', 'IpcMode', 'UTSMode', 'UsernsMode', 'CgroupnsMode')

logger = logging.getLogger('docker-proxy')


class Denied(Exception):
    pass


def allowed_bind_prefixes():
    prefixes = []
    workdir = os.environ.get('HOST_WORKDIR', '').rstrip('/')
    if workdir:
        prefixes += [f'{workdir}/instances', f'{workdir}/orchestrator/odoo_addons']
    prefixes += [p.strip().rstrip('/') for p in os.environ.get('DOCKER_PROXY_ALLOWED_BINDS', '').split(',') if p.strip()]
    return [posixpath.normpath(p) for p in prefixes if p.startswith('/')]


def normalize_path(raw):
    """The API path without the version prefix, the query or a trailing slash."""
    parts = urlsplit(raw)
    path = unquote(parts.path)
    path = re.sub(r'^/v\d+(\.\d+)?(?=/)', '', path)
    if '..' in path.split('/') or '//' in path or '\\' in path or '\x00' in path:
        raise Denied('Ruta no válida')
    return path.rstrip('/') or '/', parse_qs(parts.query)


class Policy:
    """
    lookup(kind, ident) -> dict or None: the daemon's inspect of a container, volume or network.
    project: the panel's docker compose project (its containers, volumes and networks are protected).
    """

    def __init__(self, lookup, project, bind_prefixes):
        self.lookup = lookup
        self.project = project
        self.bind_prefixes = bind_prefixes

    # -- what is the panel's ----------------------------------------------------------------------
    def _ours(self, attrs):
        labels = (attrs or {}).get('Labels') or ((attrs or {}).get('Config') or {}).get('Labels') or {}
        return bool(self.project) and labels.get('com.docker.compose.project') == self.project

    async def _check_container(self, ident, action):
        if not ident:
            return
        attrs = await self.lookup('containers', ident)
        if attrs is None:
            return  # the daemon answers 404 itself
        host = attrs.get('HostConfig') or {}
        mounts = attrs.get('Mounts') or []
        if self._ours(attrs):
            raise Denied(f'{action}: es un contenedor del propio panel')
        if host.get('Privileged') or any(m.get('Source') in DOCKER_SOCKETS for m in mounts):
            raise Denied(f'{action}: el contenedor tiene acceso al servidor (privilegiado o con el socket de Docker)')

    async def _check_network(self, ident):
        attrs = await self.lookup('networks', ident)
        if attrs is not None and self._ours(attrs) and (attrs.get('Labels') or {}).get('com.docker.compose.network') in PROTECTED_NETWORKS:
            raise Denied('Red interna del panel')

    async def _check_volume_name(self, name):
        attrs = await self.lookup('volumes', name)
        if attrs is not None and self._ours(attrs):
            raise Denied(f'El volumen {name} es del propio panel')

    def _check_host_path(self, source):
        path = posixpath.normpath(source)
        # The instances' folders are mounted read-only in this container at their host path: a symlink
        # planted there (instances/x -> /) resolves outside the allowed folders and is refused
        try:
            real = os.path.realpath(path, strict=True)
        except FileNotFoundError:
            real = os.path.realpath(path)  # Docker creates what is missing: no symlink can be in that part
        except OSError:
            raise Denied(f'No se puede comprobar la ruta del host {path}')
        if path in DOCKER_SOCKETS or real in DOCKER_SOCKETS:
            raise Denied('No se puede montar el socket de Docker')
        inside = lambda candidate: any(candidate == p or candidate.startswith(p + '/') for p in self.bind_prefixes)
        if not (inside(path) and inside(real)):
            raise Denied(f'No se puede montar la ruta del host {path} (permitidas: {", ".join(self.bind_prefixes) or "ninguna"}; '
                         'añade más en DOCKER_PROXY_ALLOWED_BINDS del .env)')

    async def _check_create(self, body):
        if not isinstance(body, dict):
            raise Denied('Petición no válida')
        host = body.get('HostConfig') or {}
        if host.get('Privileged'):
            raise Denied('No se pueden crear contenedores privilegiados')
        for key in ('CapAdd', 'Devices', 'DeviceCgroupRules', 'VolumesFrom'):
            if host.get(key):
                raise Denied(f'{key} no está permitido')
        if any(opt != 'no-new-privileges' and not opt.startswith('no-new-privileges:') for opt in host.get('SecurityOpt') or []):
            raise Denied('SecurityOpt no está permitido')
        if host.get('CgroupParent'):
            raise Denied('CgroupParent no está permitido')
        if host.get('Runtime') not in (None, '', 'runc'):
            raise Denied('Solo se permite el runtime por defecto')
        for key in HOST_MODES + ('NetworkMode',):
            value = str(host.get(key) or '')
            if value == 'host' or value.startswith('container:'):
                raise Denied(f'{key}={value} no está permitido')
        networks = [host.get('NetworkMode') or ''] + list(((body.get('NetworkingConfig') or {}).get('EndpointsConfig') or {}).keys())
        for network in networks:
            if network and network not in ('default', 'bridge', 'none'):
                await self._check_network(network)
        for bind in host.get('Binds') or []:
            source = str(bind).split(':', 1)[0]
            if source.startswith('/'):
                self._check_host_path(source)
            else:
                await self._check_volume_name(source)
        for mount in host.get('Mounts') or []:
            kind = (mount.get('Type') or 'volume').lower()
            if kind == 'bind':
                self._check_host_path(mount.get('Source') or '')
            elif kind == 'volume':
                if (mount.get('VolumeOptions') or {}).get('DriverConfig'):
                    raise Denied('Volúmenes con driver propio no permitidos')
                if mount.get('Source'):
                    await self._check_volume_name(mount['Source'])
            elif kind != 'tmpfs':
                raise Denied(f'Montajes de tipo {kind} no permitidos')

    # -- the rules --------------------------------------------------------------------------------
    async def check(self, method, raw_path, body=None):
        path, query = normalize_path(raw_path)
        if method in ('GET', 'HEAD'):
            m = re.fullmatch(r'/containers/([^/]+)/(archive|export|attach/ws)', path)
            if m:
                await self._check_container(m[1], 'Leer archivos')
            return
        if method == 'POST':
            if path == '/containers/create':
                return await self._check_create(body)
            m = re.fullmatch(r'/containers/([^/]+)/([a-z]+)', path)
            if m and m[2] in SAFE_ON_PANEL:
                return
            if m and m[2] in ('exec', 'attach', 'update', 'rename'):
                await self._check_container(m[1], m[2])
                if m[2] == 'exec' and isinstance(body, dict) and body.get('Privileged'):
                    raise Denied('exec privilegiado no permitido')
                return
            if re.fullmatch(r'/exec/[^/]+/(start|resize)', path) or path in CLEANUP or path == '/networks/create':
                return
            if path == '/images/create':
                if query.get('fromSrc'):
                    raise Denied('Importar imágenes no está permitido')
                return
            m = re.fullmatch(r'/networks/([^/]+)/(connect|disconnect)', path)
            if m:
                await self._check_network(m[1])
                await self._check_container((body or {}).get('Container', '') if isinstance(body, dict) else '', 'Cambiar sus redes')
                return
            if path == '/volumes/create':
                if not isinstance(body, dict) or (body.get('Driver') or 'local') != 'local' or body.get('DriverOpts'):
                    raise Denied('Solo volúmenes locales sin opciones')
                return
        elif method == 'DELETE':
            m = re.fullmatch(r'/containers/([^/]+)', path)
            if m:
                return await self._check_container(m[1], 'Eliminar')
            if re.fullmatch(r'/images/.+', path):
                return
            m = re.fullmatch(r'/volumes/([^/]+)', path)
            if m:
                return await self._check_volume_name(m[1])
            m = re.fullmatch(r'/networks/([^/]+)', path)
            if m:
                return await self._check_network(m[1])
        elif method == 'PUT':
            m = re.fullmatch(r'/containers/([^/]+)/archive', path)
            if m:
                return await self._check_container(m[1], 'Copiar archivos')
        raise Denied(f'{method} {path} no está permitido desde el panel web')

    @staticmethod
    def needs_body(method, raw_path):
        path = normalize_path(raw_path)[0]
        return method == 'POST' and (path == '/containers/create' or path == '/volumes/create'
                                     or bool(re.fullmatch(r'/containers/[^/]+/exec|/networks/[^/]+/(connect|disconnect)|/exec/[^/]+/start', path)))


# -- talking to the daemon ------------------------------------------------------------------------
async def _read_headers(reader):
    data = await reader.readuntil(b'\r\n\r\n')
    if len(data) > MAX_HEADERS:
        raise Denied('Cabeceras demasiado grandes')
    return data


def _parse_headers(block):
    lines = block.decode('latin-1').split('\r\n')
    first, headers = lines[0], []
    for line in lines[1:]:
        if not line:
            continue
        if line[0] in ' \t' or ':' not in line:
            raise Denied('Cabecera no válida')
        name, value = line.split(':', 1)
        headers.append((name.strip(), value.strip()))
    return first, headers


def _header(headers, name):
    name = name.lower()
    return next((v for k, v in headers if k.lower() == name), None)


async def _read_chunked(reader, limit=None):
    body = bytearray()
    while True:
        size = int((await reader.readuntil(b'\r\n')).split(b';')[0].strip(), 16)
        if size == 0:
            while (await reader.readuntil(b'\r\n')) != b'\r\n':
                pass
            return bytes(body)
        body += await reader.readexactly(size)
        await reader.readexactly(2)
        if limit and len(body) > limit:
            raise Denied('Cuerpo demasiado grande')


async def lookup(kind, ident):
    """GET /<kind>/<ident>/json (volumes: /volumes/<name>) on the socket; None when it doesn't exist."""
    from urllib.parse import quote
    path = f'/{kind}/{quote(ident, safe="")}' + ('' if kind == 'volumes' else '/json')
    reader, writer = await asyncio.open_unix_connection(SOCKET)
    try:
        writer.write(f'GET {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n'.encode())
        await writer.drain()
        first, headers = _parse_headers(await _read_headers(reader))
        status = int(first.split()[1])
        if (_header(headers, 'Transfer-Encoding') or '').lower() == 'chunked':
            body = await _read_chunked(reader)
        else:
            length = _header(headers, 'Content-Length')
            body = await (reader.readexactly(int(length)) if length else reader.read())
    finally:
        writer.close()
    if status == 404:
        return None
    if status != 200:
        raise Denied(f'No se pudo comprobar {kind}/{ident} ({status})')
    return json.loads(body)


async def own_project():
    """The compose project of this proxy (its own container's label), retried while Docker starts."""
    if os.environ.get('DOCKER_PROXY_PROJECT'):
        return os.environ['DOCKER_PROXY_PROJECT']
    for _ in range(30):
        try:
            attrs = await lookup('containers', os.environ.get('HOSTNAME', ''))
            if attrs:
                return (attrs.get('Config') or {}).get('Labels', {}).get('com.docker.compose.project', '')
        except Exception as e:
            logger.warning('Waiting for Docker: %s', e)
        await asyncio.sleep(2)
    return ''


def _reply(writer, status, message):
    body = json.dumps({'message': f'Bloqueado por el proxy de Docker de Community SH: {message}'}).encode()
    writer.write(f'HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n'
                 f'Connection: close\r\n\r\n'.encode() + body)


async def _pipe(reader, writer, eof=True):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
        if eof and writer.can_write_eof():
            writer.write_eof()
    except (ConnectionError, asyncio.CancelledError):
        pass


async def handle(client_reader, client_writer, policy):
    daemon_writer = None
    try:
        try:
            first, headers = _parse_headers(await _read_headers(client_reader))
            method, raw_path, _ = first.split(' ', 2)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
            return
        length = _header(headers, 'Content-Length')
        chunked = (_header(headers, 'Transfer-Encoding') or '').lower() == 'chunked'
        if length is not None and chunked:
            raise Denied('Content-Length y Transfer-Encoding a la vez')
        body, parsed = None, None
        if Policy.needs_body(method, raw_path):
            if chunked:
                body = await _read_chunked(client_reader, MAX_BODY)
            elif length:
                if int(length) > MAX_BODY:
                    raise Denied('Cuerpo demasiado grande')
                body = await client_reader.readexactly(int(length))
            else:
                body = b''
            try:
                parsed = json.loads(body) if body else {}
            except ValueError:
                raise Denied('JSON no válido')
        await policy.check(method, raw_path, parsed)

        hijack = method == 'POST' and HIJACK.fullmatch(normalize_path(raw_path)[0]) is not None
        if hijack and isinstance(parsed, dict) and parsed.get('Detach'):
            hijack = False
        upgrade = hijack and _header(headers, 'Upgrade') is not None
        drop = {'connection', 'keep-alive', 'proxy-connection', 'upgrade', 'expect', 'te', 'trailer'}
        if body is not None:
            drop |= {'content-length', 'transfer-encoding'}
        out = [f'{method} {raw_path} HTTP/1.1'] + [f'{k}: {v}' for k, v in headers if k.lower() not in drop]
        if body is not None:
            out.append(f'Content-Length: {len(body)}')
        out += ['Connection: Upgrade', f'Upgrade: {_header(headers, "Upgrade")}'] if upgrade else ['Connection: close']

        daemon_reader, daemon_writer = await asyncio.open_unix_connection(SOCKET, limit=MAX_HEADERS)
        daemon_writer.write(('\r\n'.join(out) + '\r\n\r\n').encode('latin-1'))
        if body is not None:
            daemon_writer.write(body)
        elif chunked:
            # Re-emitted as it arrives, chunk by chunk, so only this request's body reaches the daemon
            while True:
                size_line = await client_reader.readuntil(b'\r\n')
                size = int(size_line.split(b';')[0].strip(), 16)
                daemon_writer.write(size_line)
                if size == 0:
                    while True:
                        line = await client_reader.readuntil(b'\r\n')
                        daemon_writer.write(line)
                        if line == b'\r\n':
                            break
                    break
                daemon_writer.write(await client_reader.readexactly(size + 2))
                await daemon_writer.drain()
        elif length:
            remaining = int(length)
            while remaining:
                data = await client_reader.read(min(65536, remaining))
                if not data:
                    break
                daemon_writer.write(data)
                remaining -= len(data)
                await daemon_writer.drain()
        await daemon_writer.drain()

        # The answer: a hijacked stream (exec/attach) is piped both ways; anything else one way
        response_head = await _read_headers(daemon_reader)
        status_line, response_headers = _parse_headers(response_head)
        client_writer.write(response_head)
        await client_writer.drain()
        content_type = (_header(response_headers, 'Content-Type') or '').lower()
        streamed = status_line.split()[1] == '101' or content_type.startswith('application/vnd.docker.')
        if hijack and streamed:
            await asyncio.gather(_pipe(client_reader, daemon_writer), _pipe(daemon_reader, client_writer))
        else:
            response_length = _header(response_headers, 'Content-Length')
            if response_length is not None and upgrade:
                client_writer.write(await daemon_reader.readexactly(int(response_length)))
            else:
                # The daemon closes after the answer (Connection: close); a client that goes away ends it
                sender = asyncio.ensure_future(_pipe(daemon_reader, client_writer, eof=False))
                watcher = asyncio.ensure_future(client_reader.read(1))
                await asyncio.wait({sender, watcher}, return_when=asyncio.FIRST_COMPLETED)
                sender.cancel()
                watcher.cancel()
        await client_writer.drain()
    except Denied as e:
        logger.warning('Denied: %s', e)
        _reply(client_writer, '403 Forbidden', str(e))
        try:
            await client_writer.drain()
        except ConnectionError:
            pass
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError, ValueError) as e:
        logger.info('Connection ended: %s', e)
    except Exception:
        logger.exception('Proxy error')
    finally:
        for writer in (daemon_writer, client_writer):
            if writer is not None:
                try:
                    writer.close()
                except Exception:
                    pass


async def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    project = await own_project()
    policy = Policy(lookup, project, allowed_bind_prefixes())
    logger.info('Docker proxy on :%s (project %r, host folders %s)', PORT, project, policy.bind_prefixes)
    if not project:
        logger.warning('Compose project unknown: the panel containers are only protected by the other rules')
    server = await asyncio.start_server(lambda r, w: handle(r, w, policy), '0.0.0.0', PORT, limit=MAX_HEADERS)
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
