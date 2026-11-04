from django.contrib.auth.models import User
from django.db import models


class Contact(models.Model):
    """
    Someone who asked for a demo (public page or API): one per email and panel user (the owner of the
    project). Kept with their latest details even after their demos expire and are deleted.
    """
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contacts')
    email = models.EmailField()
    name = models.CharField(max_length=150)
    company = models.CharField(max_length=150, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    country = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True, help_text="Your own notes about this contact")
    first_project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                      help_text="Project of the first demo they asked for")
    created_at = models.DateTimeField(auto_now_add=True)
    last_request_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-last_request_at', '-created_at']
        constraints = [models.UniqueConstraint(fields=['owner', 'email'], name='unique_contact_email_per_owner')]

    def __str__(self):
        return f'{self.name} <{self.email}>'


def save_contact(trial):
    """Create or bring up to date the contact of a demo request (its newest details win)."""
    from django.utils import timezone
    project = trial.project
    contact, created = Contact.objects.get_or_create(
        owner=project.owner, email=trial.email.lower(),
        defaults={'name': trial.name, 'first_project': project})
    for field in ('name', 'company', 'job_title', 'phone', 'country'):
        value = getattr(trial, field)
        if value:
            setattr(contact, field, value)
    contact.last_request_at = timezone.now()
    contact.save()
    return contact
