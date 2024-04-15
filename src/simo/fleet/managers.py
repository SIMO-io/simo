from django.db import models
from simo.core.middleware import get_current_instance


class ColonelsManager(models.Manager):

    def get_queryset(self):
        qs = super().get_queryset()
        instance = get_current_instance()
        if instance:
            qs = qs.filter(instance=instance)
        return qs


class ColonelPinsManager(models.Manager):

    def get_queryset(self):
        qs = super().get_queryset()
        instance = get_current_instance()
        if instance:
            qs = qs.filter(colonel__instance=instance)
        return qs


class InterfacesManager(models.Manager):

    def get_queryset(self):
        qs = super().get_queryset()
        instance = get_current_instance()
        if instance:
            qs = qs.filter(colonel__instance=instance)
        return qs


