from django.db import models
from simo.core.middleware import get_current_instance


class ActiveInstanceManager(models.Manager):

    def get_queryset(self):
        qs = super().get_queryset()
        instance = get_current_instance()
        if instance:
            return qs.filter(instance=instance)
        return qs