"""
Live log and progress of the task the worker is running.

While a task runs, everything the worker prints (the services report their steps with print) and every
record of the orchestrator loggers is kept in Task.log with the time, and progress(percent, text) moves its
bar. The task is saved at most once a second, so a chatty step does not write the row on every line.
"""
import contextvars
import logging
import sys
import time
from contextlib import contextmanager

from django.utils import timezone

MAX_LOG_CHARS = 200_000
FLUSH_SECONDS = 1.0

_current = contextvars.ContextVar('task_log', default=None)


class TaskLog:
    def __init__(self, task):
        self.task_id = task.pk
        self.text = task.log or ''
        self.progress = task.progress
        self.step = task.step
        self.partial = ''
        self.dirty = False
        self.flushed_at = 0.0

    def line(self, text):
        for line in str(text).splitlines() or ['']:
            if line.strip():
                self.text += f"{timezone.localtime().strftime('%H:%M:%S')} {line.rstrip()}\n"
        if len(self.text) > MAX_LOG_CHARS:
            # The start and the end are what matter: what was asked and how it ended
            cut = self.text.index('\n', len(self.text) - MAX_LOG_CHARS + 2000) + 1
            self.text = self.text[:2000].rsplit('\n', 1)[0] + '\n… (log recortado) …\n' + self.text[cut:]
        self.dirty = True
        self.flush()

    def write(self, data):
        """Text printed by the worker: whole lines go to the log."""
        self.partial += data
        if '\n' in self.partial:
            complete, self.partial = self.partial.rsplit('\n', 1)
            self.line(complete)

    def set_progress(self, percent=None, text=None):
        if percent is not None:
            # The bar never goes back: a step inside another one (the deploy of a copy) only says what it does
            self.progress = max(self.progress, min(100, int(percent)))
        if text:
            self.step = text[:255]
            self.line(f'▶ {text}')
        self.dirty = True
        self.flush(force=True)

    def flush(self, force=False):
        if not self.dirty or (not force and time.monotonic() - self.flushed_at < FLUSH_SECONDS):
            return
        from .task_models import Task
        token = _current.set(None)  # what saving prints or logs is not part of the task
        try:
            Task.objects.filter(pk=self.task_id).update(log=self.text, progress=self.progress, step=self.step)
        finally:
            _current.reset(token)
        self.dirty = False
        self.flushed_at = time.monotonic()


class _Tee:
    """sys.stdout / sys.stderr: the terminal as always, and the log of the running task."""

    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        written = self.stream.write(data)
        log = _current.get()
        if log is not None:
            log.write(data)
        return written

    def __getattr__(self, name):
        return getattr(self.stream, name)


class _Handler(logging.Handler):
    def emit(self, record):
        log = _current.get()
        if log is not None:
            prefix = '' if record.levelno <= logging.INFO else f'{record.levelname}: '
            log.line(prefix + self.format(record))


_installed = False


def _install():
    global _installed
    if _installed:
        return
    sys.stdout, sys.stderr = _Tee(sys.stdout), _Tee(sys.stderr)
    handler = _Handler(level=logging.INFO)
    handler.setFormatter(logging.Formatter('%(message)s'))
    orchestrator_logger = logging.getLogger('orchestrator')
    orchestrator_logger.addHandler(handler)
    if orchestrator_logger.level == logging.NOTSET or orchestrator_logger.level > logging.INFO:
        orchestrator_logger.setLevel(logging.INFO)
    _installed = True


@contextmanager
def capture(task):
    """Keep what happens during the task in its log."""
    _install()
    log = TaskLog(task)
    token = _current.set(log)
    try:
        yield log
    finally:
        if log.partial.strip():
            log.line(log.partial)
            log.partial = ''
        log.dirty = True
        log.flush(force=True)
        _current.reset(token)


def progress(percent=None, text=None):
    """Move the bar of the running task (0-100) and say what it is doing; nothing outside a task."""
    log = _current.get()
    if log is not None:
        log.set_progress(percent, text)


def line(text):
    """Add a line to the log of the running task; nothing outside a task."""
    log = _current.get()
    if log is not None:
        log.line(text)
