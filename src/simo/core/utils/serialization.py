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
                        'json', val, fields=['pk']
                    ))
                }
            else:
                serialized_data[field_name] = {
                    'model': 'single',
                    'val': json.loads(model_serializers.serialize(
                        'json', [val], fields=['pk']
                    ))
                }
        else:
            serialized_data[field_name] = val
    return serialized_data


def deserialize_form_data(data):
    deserialized_data = {}
    for field_name, val in data.items():
        if isinstance(val, dict) and val.get('model'):
            deserializer_generator = model_serializers.deserialize(
                'json', json.dumps(val['val'])
            )
            if val['model'] == 'single':
                for item in deserializer_generator:
                    deserialized_data[field_name] = item.object
                    deserialized_data[field_name].refresh_from_db()
                    break
            else:
                deserialized_data[field_name] = []
                for item in deserializer_generator:
                    deserialized_data[field_name].append(item.object)
                    deserialized_data[field_name][-1].refresh_from_db()
        else:
            deserialized_data[field_name] = val
    return deserialized_data