# Container Templates

This directory contains YAML templates for Docker containers. The system automatically loads all templates from this directory.

## Template Structure

Each template is a YAML file with the following structure:

```yaml
name: template_name          # Unique identifier (lowercase, no spaces)
display_name: "Display Name" # Human-readable name shown in UI
description: "Description"   # Brief description of the container
icon: "icon_name"           # Lucide icon name (optional)
image: "docker/image:tag"   # Docker image to use
container_port: 8080        # Internal container port
default_port: 8080          # Default host port to expose

environment:                # Environment variables (optional)
  VAR_NAME: "value"
  ANOTHER_VAR: "value"

volumes:                    # Volume mappings (optional)
  volume_name:
    host: "./path/on/host"
    container: "/path/in/container"

network: "network_name"     # Docker network (default: bridge)

command: "custom command"   # Custom command to run (optional)

labels:                     # Docker labels (optional)
  label.name: "value"
```

## Available Templates

- **n8n**: Workflow automation tool
- **pgAdmin**: PostgreSQL administration
- **Portainer**: Docker management UI
- **Redis**: In-memory cache database
- **MongoDB**: NoSQL document database  
- **VS Code**: Code editor in the browser (code-server)
- **Mautic**: Open source marketing automation software
- **Rocket.Chat**: Open source communication platform
- **Chatwoot**: Open-source customer engagement platform
- **Coolify**: Self-hostable Heroku/Netlify alternative
- **Grafana**: Open observability and dashboard platform
- **Prometheus**: Monitoring system and time series database
- **Custom**: Manual configuration template

## Creating a New Template

1. Create a new YAML file in this directory (e.g., `myapp.yaml`)
2. Follow the structure above
3. Restart the application to load the template
4. The template will appear automatically in the container creation page

### Example: Custom Application Template

```yaml
name: myapp
display_name: "My Custom App"
description: "My custom dockerized application"
icon: "rocket"
image: "myorg/myapp:latest"
container_port: 3000
default_port: 3000

environment:
  NODE_ENV: "production"
  API_KEY: "changeme"

volumes:
  app_data:
    host: "./instances/myapp_data"
    container: "/app/data"

network: "traefik"

labels:
  traefik.enable: "true"
  traefik.http.routers.myapp.rule: "Host(`{container_name}.localhost`)"
```

## Template Variables

Some values support template variables:

- `{container_name}`: Will be replaced with the actual container name

## Notes

- Templates are cached for performance. Restart the app to reload templates.
- Template names must be unique and use only lowercase letters, numbers, and underscores.
- The `custom` template is the fallback for manual configuration.

## VS Code Template

The VS Code template (`vscode.yaml`) provides a full IDE in the browser:

- **Default password**: `changeme` (change this!)
- **Projects directory**: `./instances/vscode_projects`
- **Config directory**: `./instances/vscode_config`
- **Access**: `http://{container_name}.localhost`

Make sure to change the default password when deploying to production!
