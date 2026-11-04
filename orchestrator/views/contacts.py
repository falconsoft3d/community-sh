"""Contacts: the people who asked for a demo (public page or API), with their details and their demos."""
import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..contact_models import Contact
from ..pagination import paginate
from ..permissions import management_required


def contacts_for(user):
    contacts = Contact.objects.all() if user.is_superuser else Contact.objects.filter(owner=user)
    return contacts.select_related('first_project')


def _filtered(request):
    contacts = contacts_for(request.user).annotate(demo_count=Count('trials'), last_demo=Max('trials__created_at'))
    search = request.GET.get('q', '').strip()
    if search:
        contacts = contacts.filter(Q(name__icontains=search) | Q(email__icontains=search) | Q(company__icontains=search)
                                   | Q(job_title__icontains=search) | Q(phone__icontains=search))
    if request.GET.get('country'):
        contacts = contacts.filter(country=request.GET['country'])
    if request.GET.get('project', '').isdigit():
        contacts = contacts.filter(trials__project_id=request.GET['project']).distinct()
    return contacts.order_by('-last_request_at', '-created_at')


@login_required
@management_required
def contact_list(request):
    from ..permissions import managed_projects_for
    contacts = _filtered(request)
    mine = contacts_for(request.user)
    return render(request, 'orchestrator/contact_list.html', {
        'contacts': paginate(request, contacts),
        'total': mine.count(),
        'countries': mine.exclude(country='').values_list('country', flat=True).distinct().order_by('country'),
        'projects': managed_projects_for(request.user).filter(trial_enabled=True).order_by('name'),
        'search': request.GET.get('q', ''),
        'selected_country': request.GET.get('country', ''),
        'selected_project': request.GET.get('project', ''),
    })


@login_required
@management_required
def contact_export(request):
    """The contacts of the list (with its filters) as CSV, for a spreadsheet or a CRM."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="contactos.csv"'
    response.write('﻿')  # Excel opens UTF-8 with accents correctly
    writer = csv.writer(response)
    writer.writerow(['Nombre', 'Email', 'Empresa', 'Cargo', 'Teléfono', 'País', 'Demos', 'Primera demo', 'Última demo', 'Notas'])
    for contact in _filtered(request):
        writer.writerow([contact.name, contact.email, contact.company, contact.job_title, contact.phone, contact.country,
                         contact.demo_count, contact.created_at.strftime('%Y-%m-%d'),
                         contact.last_request_at.strftime('%Y-%m-%d') if contact.last_request_at else '', contact.notes])
    return response


@login_required
@management_required
def contact_detail(request, pk):
    contact = get_object_or_404(contacts_for(request.user), pk=pk)
    if request.method == 'POST':
        contact.notes = request.POST.get('notes', '').strip()[:5000]
        contact.save(update_fields=['notes'])
        messages.success(request, 'Notas guardadas')
        return redirect('contact-detail', pk=pk)
    trials = contact.trials.select_related('project', 'source', 'instance').order_by('-created_at')
    return render(request, 'orchestrator/contact_detail.html', {'contact': contact, 'trials': trials})


@login_required
@management_required
@require_POST
def contact_delete(request, pk):
    """Forget a contact (their demos stay, without the link)."""
    contact = get_object_or_404(contacts_for(request.user), pk=pk)
    name = contact.name
    contact.delete()
    messages.success(request, f'Contacto «{name}» eliminado')
    return redirect('contact-list')
