"""Uso por proyecto: instances, reserved RAM against its quota, disk and backups (administrators), also as CSV."""
import csv

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from ..permissions import superuser_required
from ..project_models import Project
from ..quotas import project_usage


@login_required
@superuser_required
def usage_list(request):
    rows = project_usage(Project.objects.select_related('client', 'owner').prefetch_related('instances'))
    if request.GET.get('format') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="uso-por-proyecto.csv"'
        writer = csv.writer(response)
        writer.writerow(['Proyecto', 'Cliente', 'Instancias', 'En marcha', 'Cuota instancias', 'RAM reservada (MB)',
                         'Cuota RAM (MB)', 'Disco (MB)', 'Backups (MB)'])
        for row in rows:
            project = row['project']
            writer.writerow([project.name, project.client_display or '', row['instances'], row['running'],
                             row['max_instances'] or '', row['memory_mb'], row['max_memory_mb'] or '',
                             '' if row['disk_mb'] is None else row['disk_mb'], '' if row['backups_mb'] is None else row['backups_mb']])
        return response
    return render(request, 'orchestrator/usage_list.html', {'rows': rows})
