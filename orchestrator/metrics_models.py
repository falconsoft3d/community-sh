from django.db import models


class MetricSample(models.Model):
    """Server CPU/RAM sampled every minute by the worker (kept 2 days)."""
    timestamp = models.DateTimeField(db_index=True)
    cpu_percent = models.FloatField()
    memory_percent = models.FloatField()

    class Meta:
        ordering = ['timestamp']


class MetricRollup(models.Model):
    """Hourly (kept 120 days) and daily (kept forever) averages and peaks."""

    class Period(models.TextChoices):
        HOUR = 'hour', 'Hour'
        DAY = 'day', 'Day'

    period = models.CharField(max_length=10, choices=Period.choices)
    start = models.DateTimeField()
    cpu_avg = models.FloatField()
    cpu_max = models.FloatField()
    memory_avg = models.FloatField()
    memory_max = models.FloatField()

    class Meta:
        ordering = ['start']
        constraints = [models.UniqueConstraint(fields=['period', 'start'], name='one_rollup_per_period_start')]
