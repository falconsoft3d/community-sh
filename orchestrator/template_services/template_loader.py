# -*- coding: utf-8 -*-
"""
Template loader service for container templates
Reads YAML files from container_templates directory
"""

import os
import yaml
from pathlib import Path
from django.conf import settings


class ContainerTemplateLoader:
    """Load and manage container templates from YAML files"""
    
    def __init__(self):
        # Get templates directory from BASE_DIR
        base_dir = Path(settings.BASE_DIR)
        self.templates_dir = base_dir / 'container_templates'
        self._templates_cache = None
    
    def get_templates_directory(self):
        """Get the templates directory path"""
        return str(self.templates_dir)
    
    def load_templates(self, force_reload=False):
        """
        Load all templates from YAML files
        
        Args:
            force_reload: Force reload from disk (bypass cache)
            
        Returns:
            dict: Dictionary of templates keyed by template name
        """
        # Return cached templates if available and not forcing reload
        if self._templates_cache is not None and not force_reload:
            return self._templates_cache
        
        templates = {}
        
        # Check if templates directory exists
        if not self.templates_dir.exists():
            print(f"Warning: Templates directory not found: {self.templates_dir}")
            return templates
        
        # Load all YAML files in the directory
        for template_file in self.templates_dir.glob('*.yaml'):
            try:
                with open(template_file, 'r', encoding='utf-8') as f:
                    template_data = yaml.safe_load(f)
                    
                    if template_data and 'name' in template_data:
                        template_name = template_data['name']
                        templates[template_name] = template_data
                        print(f"Loaded template: {template_name}")
                    else:
                        print(f"Warning: Invalid template file (missing 'name'): {template_file}")
                        
            except Exception as e:
                print(f"Error loading template {template_file}: {e}")
        
        # Cache the templates
        self._templates_cache = templates
        return templates
    
    def get_template(self, template_name):
        """
        Get a specific template by name
        
        Args:
            template_name: Name of the template
            
        Returns:
            dict: Template data or None if not found
        """
        templates = self.load_templates()
        return templates.get(template_name)
    
    def get_template_choices(self):
        """
        Get template choices for Django model field
        
        Returns:
            list: List of tuples (template_name, display_name)
        """
        templates = self.load_templates()
        choices = []
        
        for name, data in templates.items():
            display_name = data.get('display_name', name.title())
            choices.append((name, display_name))
        
        # Sort by display name
        choices.sort(key=lambda x: x[1])
        
        return choices
    
    def get_template_defaults(self, template_name):
        """
        Get default configuration for a template
        
        Args:
            template_name: Name of the template
            
        Returns:
            dict: Dictionary with default values
        """
        template = self.get_template(template_name)
        
        if not template:
            return {}
        
        return {
            'image': template.get('image', ''),
            'container_port': template.get('container_port', 8000),
            'default_port': template.get('default_port', 8000),
            'environment': template.get('environment', {}),
            'volumes': template.get('volumes', {}),
            'network': template.get('network', 'bridge'),
            'labels': template.get('labels', {}),
            'description': template.get('description', ''),
            'command': template.get('command', ''),
        }

    def get_template_raw(self, template_name):
        """Get the raw YAML content of a template"""
        template_file = self.templates_dir / f"{template_name}.yaml"
        if template_file.exists():
            with open(template_file, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    def list_available_templates(self):
        """
        Get list of all available templates with metadata
        
        Returns:
            list: List of dictionaries with template metadata
        """
        templates = self.load_templates()
        template_list = []
        
        for name, data in templates.items():
            template_list.append({
                'name': name,
                'display_name': data.get('display_name', name.title()),
                'description': data.get('description', ''),
                'icon': data.get('icon', 'box'),
                'image': data.get('image', ''),
                'default_port': data.get('default_port', 8000),
            })
        
        # Sort by display name
        template_list.sort(key=lambda x: x['display_name'])
        
        return template_list


# Singleton instance
_template_loader = None

def get_template_loader():
    """Get singleton instance of ContainerTemplateLoader"""
    global _template_loader
    if _template_loader is None:
        _template_loader = ContainerTemplateLoader()
    return _template_loader
