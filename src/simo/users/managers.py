from django.db import models


class ActiveInstanceManager(models.Manager):

    def get_queryset(self):
        return super().get_queryset().filter(instance__is_active=True)