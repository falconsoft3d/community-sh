# Container templates with pre-configured settings

CONTAINER_TEMPLATES = {
    'n8n': {
        'name': 'n8n',
        'image': 'n8nio/n8n:latest',
        'port': 5678,
        'container_port': 5678,
        'description': 'n8n - Workflow automation tool',
        'environment': {
            'N8N_BASIC_AUTH_ACTIVE': 'true',
            'N8N_BASIC_AUTH_USER': 'admin',
            'N8N_BASIC_AUTH_PASSWORD': 'changeme',
            'N8N_HOST': '0.0.0.0',
            'N8N_PORT': '5678',
            'N8N_PROTOCOL': 'http',
            'WEBHOOK_URL': 'http://localhost:5678/',
        },
        'volumes': {
            'n8n_data': '/home/node/.n8n'
        },
        'network': 'bridge',
    },
    'pgadmin': {
        'name': 'pgadmin',
        'image': 'dpage/pgadmin4:latest',
        'port': 5050,
        'container_port': 80,
        'description': 'pgAdmin - PostgreSQL administration tool',
        'environment': {
            'PGADMIN_DEFAULT_EMAIL': 'admin@admin.com',
            'PGADMIN_DEFAULT_PASSWORD': 'changeme',
            'PGADMIN_LISTEN_PORT': '80',
        },
        'volumes': {
            'pgadmin_data': '/var/lib/pgadmin'
        },
        'network': 'bridge',
    },
    'portainer': {
        'name': 'portainer',
        'image': 'portainer/portainer-ce:latest',
        'port': 9000,
        'container_port': 9000,
        'description': 'Portainer - Docker management UI',
        'environment': {},
        'volumes': {
            'portainer_data': '/data',
            '/var/run/docker.sock': '/var/run/docker.sock'
        },
        'network': 'bridge',
    },
    'redis': {
        'name': 'redis',
        'image': 'redis:alpine',
        'port': 6379,
        'container_port': 6379,
        'description': 'Redis - In-memory data structure store',
        'environment': {},
        'volumes': {
            'redis_data': '/data'
        },
        'network': 'bridge',
    },
    'mongodb': {
        'name': 'mongodb',
        'image': 'mongo:latest',
        'port': 27017,
        'container_port': 27017,
        'description': 'MongoDB - NoSQL database',
        'environment': {
            'MONGO_INITDB_ROOT_USERNAME': 'admin',
            'MONGO_INITDB_ROOT_PASSWORD': 'changeme',
        },
        'volumes': {
            'mongodb_data': '/data/db'
        },
        'network': 'bridge',
    },
}
