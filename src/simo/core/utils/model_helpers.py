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


def dirty_fields_to_current_values(instance, dirty_fields):
    """Return mapping of dirty field names to their current values.

    Avoids extra queries by reading values directly from the instance. When a
    field is a relation, the helper emits the underlying ``<field>_id`` so the
    result remains JSON-serializable and stable for payloads such as MQTT.
    """
    if not dirty_fields:
        return {}

    current = {}
    for field_name in dirty_fields.keys():
        try:
            model_field = instance._meta.get_field(field_name)
            if getattr(model_field, 'many_to_many', False):
                continue
            if getattr(model_field, 'is_relation', False) and hasattr(instance, f"{field_name}_id"):
                current[field_name] = getattr(instance, f"{field_name}_id")
            else:
                current[field_name] = getattr(instance, field_name, None)
        except (LookupError, AttributeError):
            current[field_name] = getattr(instance, field_name, None)
    return current
