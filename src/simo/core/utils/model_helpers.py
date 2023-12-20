import os
from django.db import models
from django.conf import settings
from django.contrib.contenttypes.models import ContentType


def get_log_file_path(obj):
    assert isinstance(obj, models.Model)
    ct = ContentType.objects.get_for_model(obj)
    dir = os.path.join(
        settings.LOG_DIR, '%d-%s' % (ct.id, obj.__class__.__name__)
    )
    if not os.path.exists(dir):
        os.makedirs(dir)
    path = os.path.join(dir, '%s.log' % str(obj.pk))
    if not os.path.exists(path):
        with open(path, 'w') as f:
            f.write('')
    return path


def count_zones():
    from simo.core.models import Zone
    return Zone.objects.all().count()

def count_categories():
    from simo.core.models import Category
    return Category.objects.all().count()

def count_components():
    from simo.core.models import Component
    return Component.objects.all().count()

