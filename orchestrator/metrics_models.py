from django.db import models


class MetricSample(models.Model):
    """Server CPU/RAM sampled by the worker (kept 2 days): the panel's every minute, each node's every 5 minutes."""
    # Empty: the panel's server; a node's CPU is its load over its CPUs
    server = models.ForeignKey('Server', on_delete=models.CASCADE, null=True, blank=True, related_name='metric_samples')
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

    server = models.ForeignKey('Server', on_delete=models.CASCADE, null=True, blank=True, related_name='metric_rollups')
    period = models.CharField(max_length=10, choices=Period.choices)
    start = models.DateTimeField()
    cpu_avg = models.FloatField()
    cpu_max = models.FloatField()
    memory_avg = models.FloatField()
    memory_max = models.FloatField()

    class Meta:
        ordering = ['start']
        # NULL never collides in a unique index: one constraint for the panel's rows, another for the nodes'
        constraints = [
            models.UniqueConstraint(fields=['period', 'start'], condition=models.Q(server=None), name='one_rollup_per_period_start'),
            models.UniqueConstraint(fields=['server', 'period', 'start'], condition=models.Q(server__isnull=False),
                                    name='one_node_rollup_per_period_start'),
        ]
