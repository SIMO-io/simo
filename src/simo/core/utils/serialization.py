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
            if isinstance(val, Iterable):
                serialized_data[field_name] = {
                    'model': 'many',
                    'val': json.loads(model_serializers.serialize(
                        'json', val
                    ))
                }
            else:
                serialized_data[field_name] = {
                    'model': 'single',
                    'val': json.loads(model_serializers.serialize(
                        'json', [val]
                    ))
                }
        else:
            serialized_data[field_name] = val
    return serialized_data


def deserialize_form_data(data):
    deserialized_data = {}
    for field_name, val in data.items():
        if isinstance(val, dict) and val.get('model'):
            deserialized_data[field_name] = model_serializers.deserialize(
                'json', val['val']
            )
            if val['model'] == 'single':
                deserialized_data[field_name] = deserialized_data[field_name][0]
        else:
            deserialized_data[field_name] = val
    return deserialized_data