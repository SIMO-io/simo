from collections import OrderedDict
from django.utils.encoding import force_str
from rest_framework import serializers
from rest_framework.metadata import SimpleMetadata
from rest_framework.utils.field_mapping import ClassLookupDict
from .serializers import ComponentManyToManyRelatedField


class SIMOAPIMetadata(SimpleMetadata):

    label_lookup = ClassLookupDict({
        serializers.Field: 'field',
        serializers.BooleanField: 'boolean',
        serializers.CharField: 'string',
        serializers.UUIDField: 'string',
        serializers.URLField: 'url',
        serializers.EmailField: 'email',
        serializers.RegexField: 'regex',
        serializers.SlugField: 'slug',
        serializers.IntegerField: 'integer',
        serializers.FloatField: 'float',
        serializers.DecimalField: 'decimal',
        serializers.DateField: 'date',
        serializers.DateTimeField: 'datetime',
        serializers.TimeField: 'time',
        serializers.ChoiceField: 'choice',
        serializers.MultipleChoiceField: 'multiple choice',
        serializers.FileField: 'file upload',
        serializers.ImageField: 'image upload',
        serializers.ListField: 'list',
        serializers.DictField: 'nested object',
        serializers.Serializer: 'nested object',
        serializers.RelatedField: 'related object',
        serializers.ManyRelatedField: 'many related objects',
        ComponentManyToManyRelatedField: 'many related objects'
    })

    def get_field_info(self, field):
        """
        Given an instance of a serializer field, return a dictionary
        of metadata about it.
        """
        field_info = OrderedDict()
        field_info['type'] = self.label_lookup[field]
        field_info['required'] = getattr(field, 'required', False)

        form_field = field.style.get('form_field')
        if form_field:
            if hasattr(form_field, 'queryset'):
                model = form_field.queryset.model
                field_info['related_object'] = ".".join(
                    [model.__module__, model.__name__]
                )
            if hasattr(form_field, 'filter_by'):
                field_info['filter_by'] = form_field.filter_by

        attrs = [
            'read_only', 'label', 'help_text',
            'min_length', 'max_length',
            'min_value', 'max_value',
            'initial'
        ]

        for attr in attrs:
            value = getattr(field, attr, None)
            if value is not None and value != '':
                field_info[attr] = force_str(value, strings_only=True)

        if getattr(field, 'child', None):
            field_info['child'] = self.get_field_info(field.child)
        elif getattr(field, 'fields', None):
            field_info['children'] = self.get_serializer_info(field)

        if not field_info.get('read_only') and hasattr(field, 'choices'):
            add_choices = True
            queryset = getattr(field, 'queryset', None)
            if queryset and queryset.count() > 1000:
                add_choices = False
            if add_choices:
                field_info['choices'] = [
                    {
                        'value': choice_value,
                        'display_name': force_str(choice_name, strings_only=True)
                    }
                    for choice_value, choice_name in field.choices.items()
                ]
        return field_info