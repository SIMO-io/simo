from django.db import models
from simo.core.models import Instance
from simo.core.utils.helpers import get_random_string
from simo.core.middleware import get_current_instance


def get_new_token():
    token = get_random_string(size=20)
    instance = get_current_instance()
    if InstanceAccessToken.objects.filter(
        instance=instance, token=token
    ).first():
        return get_new_token()
    return token


class InstanceAccessToken(models.Model):
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE)
    date_created = models.DateTimeField(auto_now_add=True, db_index=True)
    token = models.CharField(
        max_length=20, unique=True, db_index=True, default=get_new_token
    )
    date_expired = models.DateTimeField(null=True, blank=True, db_index=True)
    user = models.ForeignKey(
        'users.User', null=True, blank=True, on_delete=models.SET_NULL
    )
    issuer = models.CharField(db_index=True, editable=False, null=True)