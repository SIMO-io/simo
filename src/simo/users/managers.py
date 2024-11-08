from django.db import models
from simo.core.middleware import get_current_instance


class ActiveInstanceManager(models.Manager):

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(instance__is_active=True)
