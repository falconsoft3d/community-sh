"""
Public demo pages of the projects in test mode: /<slug>/ to ask for one, its status page (with the
build progress and, at the end, the credentials) and a public JSON API of what can be tried.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ..permissions import client_ip, get_instance_for_user
from ..project_models import Project
from ..services.trials import check_captcha, demo_instances, make_captcha, public_catalog, request_demo
from ..trial_models import TrialRequest

INPUT = ('flex h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 '
         'focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30 '
         'dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100')


# Suggested in the country field (any other can be typed)
COUNTRIES = [
    'España', 'México', 'Argentina', 'Colombia', 'Chile', 'Perú', 'Ecuador', 'Venezuela', 'Uruguay', 'Paraguay',
    'Bolivia', 'Cuba', 'República Dominicana', 'Puerto Rico', 'Guatemala', 'Honduras', 'El Salvador', 'Nicaragua',
    'Costa Rica', 'Panamá', 'Estados Unidos', 'Canadá', 'Brasil', 'Portugal', 'Francia', 'Italia', 'Alemania',
    'Reino Unido', 'Irlanda', 'Países Bajos', 'Bélgica', 'Suiza', 'Austria', 'Andorra', 'Marruecos', 'Guinea Ecuatorial',
]


class DemoForm(forms.Form):
    name = forms.CharField(label='Nombre y apellidos', max_length=150)
    email = forms.EmailField(label='Email')
    company = forms.CharField(label='Empresa', max_length=150)
    job_title = forms.CharField(label='Cargo', max_length=100)
    phone = forms.RegexField(label='Teléfono', max_length=40, regex=r'^\+?[0-9 ().-]{6,40}$',
                             error_messages={'invalid': 'Escribe un teléfono válido (números, espacios y +).'})
    country = forms.CharField(label='País', max_length=80)
    instance = forms.ChoiceField(label='Versión', widget=forms.RadioSelect)
    captcha_answer = forms.CharField(label='Resultado', max_length=4)
    captcha_token = forms.CharField(widget=forms.HiddenInput)
    website = forms.CharField(required=False)  # honeypot: people don't see it, bots fill it

    VISIBLE = ('name', 'email', 'company', 'job_title', 'phone', 'country')

    def __init__(self, *args, instances=(), captcha=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not captcha:
            # Asked with the project's API key: the key already says who calls
            del self.fields['captcha_answer'], self.fields['captcha_token']
        self.instances = {str(instance.pk): instance for instance in instances}
        self.fields['instance'].choices = [(pk, instance.name) for pk, instance in self.instances.items()]
        if len(self.instances) == 1:
            self.fields['instance'].initial = next(iter(self.instances))
        for name in self.VISIBLE:
            self.fields[name].widget.attrs['class'] = INPUT
        autocomplete = {'name': 'name', 'email': 'email', 'company': 'organization', 'job_title': 'organization-title',
                        'phone': 'tel', 'country': 'country-name'}
        for name, value in autocomplete.items():
            self.fields[name].widget.attrs['autocomplete'] = value
        self.fields['phone'].widget.input_type = 'tel'
        self.fields['phone'].widget.attrs.update({'inputmode': 'tel', 'placeholder': '+34 600 000 000'})
        self.fields['country'].widget.attrs['list'] = 'countries'
        if 'captcha_answer' in self.fields:
            self.fields['captcha_answer'].widget.attrs.update({
                'class': INPUT.replace('w-full', 'w-24'), 'inputmode': 'numeric', 'autocomplete': 'off', 'pattern': '[0-9]{1,3}'})
        self.new_captcha()

    def new_captcha(self):
        """A new sum each time the page is shown (also after an error: each question is used once)."""
        self.captcha_question, self.captcha_signed = make_captcha()

    @property
    def visible_fields_list(self):
        return [self[name] for name in self.VISIBLE]

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Solicitud no válida')
        return ''

    def clean(self):
        data = super().clean()
        if 'captcha_answer' in self.fields and 'captcha_answer' in data \
                and not check_captcha(data.get('captcha_token'), data['captcha_answer']):
            self.add_error('captcha_answer', 'La suma no es correcta (o caducó): prueba con la nueva.')
        return data


def _demo_project(slug):
    return get_object_or_404(Project.objects.select_related('trial_target_project'), trial_enabled=True, trial_slug=slug)


def trial_page(request, slug):
    """Public page: choose a version, leave your details and get a demo."""
    project = _demo_project(slug)
    instances = demo_instances(project)
    form = DemoForm(request.POST or None, instances=instances)
    error = ''
    from ..ratelimit import TRIAL_POSTS_PER_HOUR, hit
    if request.method == 'POST' and hit(f'trial:{client_ip(request)}', TRIAL_POSTS_PER_HOUR, 3600):
        error = 'Demasiadas peticiones desde tu dirección: inténtalo dentro de una hora.'
    elif request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        if project.trial_target_project is None:
            error = 'Las demos no están disponibles ahora mismo.'
        else:
            trial, error = request_demo(project, form.instances[data['instance']], data['name'], data['email'],
                                        data['company'], data['phone'], client_ip(request),
                                        job_title=data['job_title'], country=data['country'])
            if trial is not None:
                return redirect('trial-status', slug=slug, token=trial.token)
    return render(request, 'orchestrator/trial_page.html', {
        'project': project,
        'instances': instances,
        'form': form,
        'error': error,
        'selected': form['instance'].value(),
        'countries': COUNTRIES,
    })


def _status(trial):
    """What the status page shows (and polls): no internal names, the credentials only once it's ready."""
    task = trial.task
    data = {'status': trial.status, 'version': trial.version, 'progress': 0, 'step': ''}
    if trial.status == TrialRequest.Status.PENDING and task is not None:
        if task.status == task.Status.PENDING:
            ahead = type(task).objects.filter(status__in=[task.Status.PENDING, task.Status.RUNNING],
                                              created_at__lt=task.created_at).exclude(kind__in=['ai_chat', 'odoo_migration', 'build_container']).count()
            data['step'] = f'En cola: {ahead} tarea{"s" if ahead != 1 else ""} por delante' if ahead else 'Empezando…'
        else:
            data['progress'] = task.progress
            # Step 0 names the task, the instance and who runs it: not for the public
            data['step'] = task.step if task.progress else 'Preparando tu demo'
    elif trial.status == TrialRequest.Status.READY and trial.instance is not None:
        data.update(progress=100, url=trial.instance.url, login=trial.admin_login, password=trial.admin_password,
                    expires_at=timezone.localtime(trial.expires_at).strftime('%d/%m/%Y'),
                    days_left=trial.days_until_stop, emailed=bool(trial.emailed_at))
    elif trial.status == TrialRequest.Status.READY:
        data['status'] = TrialRequest.Status.EXPIRED
    return data


@never_cache
def trial_status(request, slug, token):
    """It shows the credentials: never cached, and the token never leaves in a Referer."""
    project = _demo_project(slug)
    trial = get_object_or_404(TrialRequest.objects.select_related('task', 'instance', 'source'), project=project, token=token)
    if request.GET.get('format') == 'json':
        # Followed from the website that asked for it (the token in the URL is the key)
        response = _cors(JsonResponse(_status(trial)))
    else:
        response = render(request, 'orchestrator/trial_status.html', {
            'project': project, 'trial': trial, 'status': _status(trial),
        })
    response['Referrer-Policy'] = 'no-referrer'
    return response


def _cors(response, methods='GET, OPTIONS'):
    """Any website can call the public demo API from the browser (no cookies are involved)."""
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Methods'] = methods
    response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Demo-Key'
    response['Access-Control-Max-Age'] = '3600'
    return response


def _captcha_json(form):
    return {'question': form.captcha_question, 'token': form.captcha_signed}


@csrf_exempt
@require_http_methods(['GET', 'POST', 'OPTIONS'])
def trial_api(request, slug):
    """
    Public JSON API of a demo page (for your website), CORS open to any origin:
    GET lists what can be tried; POST asks for a demo with the same data and limits as the page,
    including the sum (captcha) from GET .../captcha/. Answers with the status URLs to follow it.
    """
    methods = 'GET, POST, OPTIONS'
    if request.method == 'OPTIONS':
        return _cors(HttpResponse(status=204), methods)
    try:
        project = _demo_project(slug)
    except Http404:
        return _cors(JsonResponse({'detail': 'No existe una página de demos con esa URL'}, status=404), methods)
    if request.method == 'GET':
        response = JsonResponse(public_catalog(project, request), json_dumps_params={'ensure_ascii': False})
        response['Cache-Control'] = 'public, max-age=60'
        return _cors(response, methods)

    import json
    try:
        data = json.loads(request.body or b'{}') if request.content_type == 'application/json' else request.POST.dict()
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        return _cors(JsonResponse({'detail': 'JSON no válido'}, status=400), methods)
    data = {key: str(value) for key, value in data.items() if value is not None}
    # With the project's API key (a website's backend): no captcha and no per-address limit
    authorization = request.headers.get('Authorization', '')
    key = authorization[7:].strip() if authorization.startswith('Bearer ') else request.headers.get('X-Demo-Key', '').strip()
    from ..ratelimit import TRIAL_POSTS_PER_HOUR, hit
    valid_key = bool(key) and project.trial_api_key_ok(key)
    # A website's backend with the key sends all its visitors from one address: only the others are limited
    if not valid_key and hit(f'trial:{client_ip(request)}', TRIAL_POSTS_PER_HOUR, 3600):
        return _cors(JsonResponse({'detail': 'Demasiadas peticiones desde tu dirección: inténtalo dentro de una hora.'}, status=429), methods)
    if key and not valid_key:
        return _cors(JsonResponse({'detail': 'Clave de API no válida'}, status=401), methods)
    with_key = bool(key)
    form = DemoForm(data, instances=demo_instances(project), captcha=not with_key)
    if not form.is_valid():
        body = {'errors': {field: [str(message) for message in messages_] for field, messages_ in form.errors.items()}}
        if not with_key:
            body['captcha'] = _captcha_json(form)
        return _cors(JsonResponse(body, status=400), methods)
    if project.trial_target_project is None:
        return _cors(JsonResponse({'detail': 'Las demos no están disponibles ahora mismo.'}, status=503), methods)
    cleaned = form.cleaned_data
    trial, error = request_demo(project, form.instances[cleaned['instance']], cleaned['name'], cleaned['email'],
                                cleaned['company'], cleaned['phone'], client_ip(request),
                                job_title=cleaned['job_title'], country=cleaned['country'], check_ip=not with_key)
    if trial is None:
        body = {'detail': error}
        if not with_key:
            body['captcha'] = _captcha_json(form)
        return _cors(JsonResponse(body, status=429), methods)
    from django.urls import reverse
    page = request.build_absolute_uri(reverse('trial-status', args=[slug, trial.token]))
    return _cors(JsonResponse({'status': trial.status, 'status_page': page, 'status_api': f'{page}?format=json'},
                              status=201), methods)


@require_GET
def trial_captcha(request, slug):
    """A new sum for a POST to the public API: {question: "7 + 4", token}."""
    _demo_project(slug)
    question, token = make_captcha()
    response = JsonResponse({'question': question, 'token': token})
    response['Cache-Control'] = 'no-store'
    return _cors(response)


@login_required
@require_POST
def instance_update_description(request, pk):
    """The public description of an instance (demo page of its project)."""
    instance = get_instance_for_user(request.user, pk, manage=True)
    instance.description = request.POST.get('description', '').strip()[:2000]
    instance.save(update_fields=['description'])
    messages.success(request, 'Descripción actualizada')
    return redirect('instance-detail', pk=pk)


@login_required
@require_POST
def project_trial_key(request, pk):
    """A new demo API key for the project, shown once on its page (the previous one stops working)."""
    from ..permissions import get_project_for_user
    project = get_project_for_user(request.user, pk, manage=True)
    request.session['new_trial_api_key'] = {'project': project.pk, 'key': project.new_trial_api_key()}
    messages.success(request, 'Clave de API nueva: cópiala ahora, no se vuelve a mostrar. La anterior ya no funciona.')
    from django.urls import reverse
    return redirect(reverse('project-detail', args=[project.pk]) + '#demo-api')
