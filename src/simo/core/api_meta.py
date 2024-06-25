from collections import OrderedDict
from django.urls import reverse
from django.utils.encoding import force_str
from rest_framework.metadata import SimpleMetadata
from rest_framework import serializers
from rest_framework.utils.field_mapping import ClassLookupDict
from simo.core.models import Icon, Instance, Category, Zone
from simo.core.middleware import introduce_instance
from .serializers import (
    HiddenSerializerField, ComponentManyToManyRelatedField,
    TextAreaSerializerField, Component
)


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
        ComponentManyToManyRelatedField: 'many related objects',
        HiddenSerializerField: 'hidden',
        TextAreaSerializerField: 'textarea',
    })

    def determine_metadata(self, request, view):
        self.instance = getattr(view, 'instance', None)
        if not self.instance:
            self.instance = Instance.objects.filter(
                slug=request.resolver_match.kwargs.get('instance_slug')
            ).first()
        if self.instance:
            introduce_instance(self.instance)
        return super().determine_metadata(request, view)


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
            #TODO: Delete these completely once autocomplete fields are fully implemented
            if hasattr(form_field, 'queryset'):
                model = form_field.queryset.model
                field_info['related_object'] = ".".join(
                    [model.__module__, model.__name__]
                )
            if hasattr(form_field, 'filter_by'):
                field_info['filter_by'] = form_field.filter_by

            if hasattr(form_field, 'forward'):
                field_info['autocomplete_url'] = reverse(form_field.url)
                field_info['forward'] = form_field.forward

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

        if form_field and hasattr(form_field, 'queryset'):
            if form_field.queryset.model == Icon:
                return field_info
            elif self.instance:
                if hasattr(form_field.queryset.model, 'instance'):
                    form_field.queryset = form_field.queryset.filter(
                        instance=self.instance
                    )
                elif hasattr(form_field.queryset.model, 'instances'):
                    form_field.queryset = form_field.queryset.filter(
                        instances=self.instance
                    )
                if form_field.queryset.model == Component:
                    form_field.queryset = form_field.queryset.filter(
                        zone__instance=self.instance
                    )

        if not field_info.get('read_only') and hasattr(field, 'choices'):
            field_info['choices'] = [
                {
                    'value': choice_value,
                    'display_name': force_str(choice_name, strings_only=True)
                }
                for choice_value, choice_name in field.choices.items()
            ]

        return field_info