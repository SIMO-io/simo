from django.db import models
from simo.core.middleware import get_current_instance


class ActiveInstanceManager(models.Manager):

    def get_queryset(self):
        instance = get_current_instance()
        return super().get_queryset().filter(
            instance__is_active=True, instance=instance
        )