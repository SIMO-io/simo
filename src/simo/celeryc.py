import os
import logging
from celery import Celery
from celery.loaders.app import AppLoader
from celery.loaders.base import BaseLoader, find_related_module
from django.conf import settings


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
os.environ.setdefault('CELERY_BROKER_URL', settings.CELERY_BROKER_URL)

logger = logging.getLogger(__name__)

_RACE_PROTECTION = False

def autodiscover_tasks(packages, related_name='tasks'):
    global _RACE_PROTECTION

    if _RACE_PROTECTION:
        return ()
    _RACE_PROTECTION = True
    try:
        modules = []
        for pkg in packages:
            try:
                modules.append(find_related_module(pkg, related_name))
            except Exception as e:
                logger.exception('')
        return modules
    finally:
        _RACE_PROTECTION = False


class SIMOCeleryAppLoader(AppLoader):

    # We override default loader tasks autodiscovery in a way that
    # if there is wrong in any of tasks.py files it would not break
    # entire autodiscover process, only log error about that exact problem.
    def autodiscover_tasks(self, packages, related_name='tasks'):
        self.task_modules.update(
            mod.__name__ for mod in autodiscover_tasks(packages or (),
                                                       related_name) if mod)


celery_app = Celery('celery', loader='simo.celeryc:SIMOCeleryAppLoader')
celery_app.config_from_object('django.conf:settings', namespace='CELERY')
celery_app.autodiscover_tasks()
