import json
from django.core import serializers as model_serializers
from django.db import models
from collections.abc import Iterable



def serialize_form_data(data):
    serialized_data = {}
    for field_name, val in data.items():
        is_model = False
        if isinstance(val, Iterable):
            for v in val:
                if isinstance(v, models.Model):
                    is_model = True
                    break
        elif isinstance(val, models.Model):
            is_model = True
        if is_model:
            serialized_data[field_name] = model_serializers.serialize(
                'json', val
            )
