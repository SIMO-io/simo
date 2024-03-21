import inspect
import datetime
import json
from django import forms
from django.forms.utils import ErrorDict
from collections.abc import Iterable
from easy_thumbnails.files import get_thumbnailer
from simo.core.middleware import get_current_request
from rest_framework import serializers
from simo.core.forms import FormsetField
from rest_framework.relations import PrimaryKeyRelatedField, ManyRelatedField
from .drf_braces.serializers.form_serializer import (
    FormSerializer, FormSerializerBase, reduce_attr_dict_from_instance,
    FORM_SERIALIZER_FIELD_MAPPING, set_form_partial_validation
)
from .forms import ComponentAdminForm
from .models import Category, Zone, Icon, ComponentHistory


class TimestampField(serializers.Field):

    def to_representation(self, value):
        if value:
            return value.timestamp()
        return value

    def to_internal_value(self, data):
        return datetime.datetime.fromtimestamp(data)


class IconSerializer(serializers.ModelSerializer):
    last_modified = TimestampField()

    class Meta:
        model = Icon
        fields = '__all__'


class CategorySerializer(serializers.ModelSerializer):
    header_image_thumb = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = (
            'id', 'name', 'all', 'icon', 'header_image', 'header_image_thumb'
        )

    def get_header_image_thumb(self, obj):
        if obj.header_image:
            url = get_thumbnailer(obj.header_image).get_thumbnail(
                {'size': (830, 430), 'crop': True}
            ).url
            request = get_current_request()
            if request:
                url = request.build_absolute_uri(url)
            return {
                'url': url,
                'last_change': obj.header_image_last_change.timestamp()
            }
        return



class ObjectSerializerMethodField(serializers.SerializerMethodField):

    def bind(self, field_name, parent):
        self.field_name = field_name
        super().bind(field_name, parent)

    def to_representation(self, value):
        return getattr(value, self.field_name)


class FormsetPrimaryKeyRelatedField(PrimaryKeyRelatedField):

    def get_attribute(self, instance):
        return self.queryset.model.objects.filter(
            pk=instance.get(self.source_attrs[0], -1)
        ).first()




# TODO: if form field has initial value and is required, it is serialized as not required field, howerver when trying to submit it fails with a message, that field is required.


class ComponentFormsetField(FormSerializer):

    class Meta:
        # fake form, but it is necessary for FormSerializer
        # we set it to proper formset form on __init__
        form = forms.Form
        field_mapping = {
            forms.ModelChoiceField: FormsetPrimaryKeyRelatedField,
            forms.TypedChoiceField: serializers.ChoiceField,
            forms.FloatField: serializers.FloatField,
            forms.SlugField: serializers.CharField
        }

    def __init__(self, formset_field, *args, **kwargs):
        self.Meta.form = formset_field.formset_cls.form
        super().__init__(*args, **kwargs)

    def get_fields(self):
        ret = super(FormSerializerBase, self).get_fields()

        field_mapping = reduce_attr_dict_from_instance(
            self,
            lambda i: getattr(getattr(i, 'Meta', None), 'field_mapping', {}),
            FORM_SERIALIZER_FIELD_MAPPING
        )

        form = self.Meta.form
        for field_name, form_field in getattr(form, 'all_base_fields', form.base_fields).items():

            if field_name in getattr(self.Meta, 'exclude', []):
                continue

            if field_name in ret:
                continue

            cls_type = form_field.__class__
            try:
                serializer_field_class = field_mapping[cls_type]
            except KeyError:
                try:
                    serializer_field_class = field_mapping[cls_type.__bases__[0]]
                except KeyError:
                    raise TypeError(
                        "{field} is not mapped to a serializer field. "
                        "Please add {field} to {serializer}.Meta.field_mapping. "
                        "Currently mapped fields: {mapped}".format(
                            field=form_field.__class__.__name__,
                            serializer=self.__class__.__name__,
                            mapped=', '.join(sorted([i.__name__ for i in field_mapping.keys()]))
                        )
                    )

            ret[field_name] = self._get_field(form_field, serializer_field_class)

        return ret

    def _get_field_kwargs(self, form_field, serializer_field_class):
        kwargs = super()._get_field_kwargs(form_field, serializer_field_class)
        kwargs['style'] = {'form_field': form_field}
        if serializer_field_class == FormsetPrimaryKeyRelatedField:
            kwargs['queryset'] = form_field.queryset
        return kwargs

    def to_representation(self, instance):
        return super(FormSerializerBase, self).to_representation(instance)

    def get_form(self, data=None, **kwargs):
        form = super().get_form(data=data, **kwargs)
        form.prefix = ''
        return form

    def create(self, validated_data):
        return validated_data


class ComponentPrimaryKeyRelatedField(PrimaryKeyRelatedField):

    def get_attribute(self, instance):
        if self.queryset.model in (Icon, Zone, Category):
            return super().get_attribute(instance)
        return self.queryset.model.objects.filter(
            pk=instance.config.get(self.source_attrs[0])
        ).first()


class ComponentManyToManyRelatedField(serializers.Field):

    def __init__(self, *args, **kwargs):
        self.queryset = kwargs.pop('queryset')
        self.choices = {obj.pk: str(obj) for obj in self.queryset}
        self.allow_blank = kwargs.pop('allow_blank', False)
        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        return [obj.pk for obj in value]

    def to_internal_value(self, data):
        if data == [] and self.allow_blank:
            return []
        return self.queryset.filter(pk__in=data)


class ComponentSerializer(FormSerializer):
    id = ObjectSerializerMethodField()
    controller_methods = serializers.SerializerMethodField()
    last_change = TimestampField(read_only=True)
    read_only = serializers.SerializerMethodField()
    app_widget = serializers.SerializerMethodField()
    slaves = serializers.SerializerMethodField()
    base_type = ObjectSerializerMethodField()
    controller_uid = ObjectSerializerMethodField()
    alive = ObjectSerializerMethodField()
    value = ObjectSerializerMethodField()
    config = ObjectSerializerMethodField()
    meta = ObjectSerializerMethodField()
    arm_status = ObjectSerializerMethodField()
    battery_level = ObjectSerializerMethodField()

    class Meta:
        form = ComponentAdminForm
        exclude = ('instance_methods', )
        field_mapping = {
            forms.TypedChoiceField: serializers.ChoiceField,
            forms.FloatField: serializers.FloatField,
            forms.SlugField: serializers.CharField,
            forms.ModelChoiceField: ComponentPrimaryKeyRelatedField,
            forms.ModelMultipleChoiceField: ComponentManyToManyRelatedField,
            FormsetField: ComponentFormsetField,
        }

    def get_fields(self):
        self.set_form_cls()

        ret = super(FormSerializerBase, self).get_fields()

        field_mapping = reduce_attr_dict_from_instance(
            self,
            lambda i: getattr(getattr(i, 'Meta', None), 'field_mapping', {}),
            FORM_SERIALIZER_FIELD_MAPPING
        )

        if not self.instance or isinstance(self.instance, Iterable):
            form = self.Meta.form()
        else:
            form = self.Meta.form(instance=self.instance)
        for field_name in form.fields:
            # if field is specified as excluded field
            if field_name in getattr(self.Meta, 'exclude', []):
                continue

            # if field is already defined via declared fields
            # skip mapping it from forms which then honors
            # the custom validation defined on the DRF declared field
            if field_name in ret:
                continue

            form_field = form[field_name]

            cls = form_field.field.__class__
            try:
                serializer_field_class = field_mapping[cls]
            except KeyError:
                cls = form_field.field.__class__.__bases__[0]
                try:
                    serializer_field_class = field_mapping[cls]
                except KeyError:
                    raise TypeError(
                        "{field} is not mapped to a serializer field. "
                        "Please add {field} to {serializer}.Meta.field_mapping. "
                        "Currently mapped fields: {mapped}".format(
                            field=form_field.field.__class__.__name__,
                            serializer=self.__class__.__name__,
                            mapped=', '.join(sorted([i.__name__ for i in field_mapping.keys()]))
                        )
                    )

            ret[field_name] = self._get_field(
                form_field.field, serializer_field_class
            )
            ret[field_name].initial = form_field.initial
            ret[field_name].default = form_field.initial

        return ret

    def _get_field_kwargs(self, form_field, serializer_field_class):
        kwargs = super()._get_field_kwargs(form_field, serializer_field_class)
        kwargs['style'] = {'form_field': form_field}
        if serializer_field_class == ComponentPrimaryKeyRelatedField:
            kwargs['queryset'] = form_field.queryset
        elif serializer_field_class == ComponentManyToManyRelatedField:
            kwargs['queryset'] = form_field.queryset
        elif serializer_field_class == ComponentFormsetField:
            kwargs['formset_field'] = form_field
            kwargs['many'] = True

        return kwargs

    def set_form_cls(self):
        self.Meta.form = ComponentAdminForm
        if not isinstance(self.instance, Iterable):
            from .utils.type_constants import get_controller_types_map
            controllers_map = get_controller_types_map()
            if not self.instance:
                controller = controllers_map.get(
                    #'simo.generic.controllers.AlarmClock'
                    self.context['request'].META.get('HTTP_CONTROLLER')
                )
                if controller:
                    self.Meta.form = controller.add_form
            else:
                controller = controllers_map.get(
                    self.instance.controller_uid
                )
                if controller:
                    self.Meta.form = controller.config_form

    def get_form(self, data=None, **kwargs):
        self.set_form_cls()
        if not self.instance:
            #controller_uid = 'simo.generic.controllers.AlarmClock'
            controller_uid = self.context['request'].META.get('HTTP_CONTROLLER')
        else:
            controller_uid = self.instance.controller_uid
        form = self.Meta.form(
            data=data, request=self.context['request'],
            controller_uid=controller_uid,
            **kwargs
        )
        return form

    def accomodate_formsets(self, form, data):
        new_data = {}
        field_types = {}
        for field_name in form.fields:
            field_types[field_name] = form[field_name]
        for key, val in data.items():
            if isinstance(field_types.get(key).field, FormsetField):
                new_data[f'{key}-TOTAL_FORMS'] = len(val)
                new_data[f'{key}-INITIAL_FORMS'] = len(val)
                new_data[f'{key}-MIN_NUM_FORMS'] = 0
                new_data[f'{key}-MAX_NUM_FORMS'] = len(val)
                for i, item in enumerate(val):
                    for k, v in item.items():
                        new_data[f'{key}-{i}-{k}'] = v
            else:
                new_data[key] = val
        return new_data

    def validate(self, data):
        if not self.instance:
            try:
                self.context['request'].META['HTTP_CONTROLLER']
            except:
                raise serializers.ValidationError(
                    ["Controller header is not supplied!"]
                )
        form = self.get_form(instance=self.instance)
        a_data = self.accomodate_formsets(form, data)
        form = self.get_form(
            data=a_data, instance=self.instance
        )
        if not form.is_valid():
            raise serializers.ValidationError(form.errors)
        return data

    def to_representation(self, instance):
        return super(FormSerializerBase, self).to_representation(instance)

    def update(self, instance, validated_data):
        form = self.get_form(instance=instance)
        a_data = self.accomodate_formsets(form, validated_data)
        form = self.get_form(instance=instance, data=a_data)
        if form.is_valid():
            instance = form.save(commit=True)
            return instance
        raise serializers.ValidationError(form.errors)

    def create(self, validated_data):
        form = self.get_form()
        a_data = self.accomodate_formsets(form, validated_data)
        form = self.get_form(data=a_data)
        if form.is_valid():
            if form.controller.is_discoverable:
                form.controller.init_discovery(form.cleaned_data)
                return {'discovery': 'started'}
            instance = form.save(commit=True)
            return instance
        raise serializers.ValidationError(form.errors)

    def get_controller_methods(self, obj):
        c_methods = [m[0] for m in inspect.getmembers(
            obj.controller, predicate=inspect.ismethod
        ) if not m[0].startswith('_')]
        if obj.alarm_category:
            c_methods.extend(['arm', 'disarm'])
        return c_methods

    def get_read_only(self, obj):
        user = self.context.get('user')
        if not user:
            user = self.context.get('request').user
        if user.is_superuser:
            return False
        instance = self.context.get('instance')
        return not bool(
            user.get_role(instance).component_permissions.filter(
                component=obj, write=True
            )
        )

    def get_app_widget(self, obj):
        try:
            app_widget = obj.controller.app_widget
        except:
            return {}
        return {'type': app_widget.uid, 'size': app_widget.size}

    def get_slaves(self, obj):
        return [c['id'] for c in obj.slaves.all().values('id')]


class ZoneSerializer(serializers.ModelSerializer):
    components = serializers.SerializerMethodField()

    class Meta:
        model = Zone
        fields = ['id', 'name', 'components']

    def get_components_qs(self, obj):
        qs = obj.components.all()
        if self.context['request'].user.is_superuser:
            return qs
        user = self.context.get('request').user
        instance = self.context.get('instance')
        c_ids = [
            cp.component.id for cp in
            user.get_role(instance).component_permissions.filter(
                read=True
            ).select_related('component')
        ]
        qs = qs.filter(id__in=c_ids)
        return qs

    def get_components(self, obj):
        return [comp.id for comp in self.get_components_qs(obj)]


class ComponentHistorySerializer(serializers.ModelSerializer):
    date = TimestampField()
    user = serializers.StringRelatedField()

    class Meta:
        model = ComponentHistory
        fields = '__all__'
