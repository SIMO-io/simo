import inspect
import datetime
import six
from collections import OrderedDict
from collections.abc import Iterable
from easy_thumbnails.files import get_thumbnailer
from simo.core.middleware import get_current_request
from rest_framework import serializers
from django.utils import timezone
from .models import Category, Zone, Component, Icon, ComponentHistory


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


from django import forms
from simo.core.forms import FormsetField
from rest_framework.relations import PrimaryKeyRelatedField
from drf_braces.serializers.form_serializer import (
    FormSerializer, FormSerializerBase, reduce_attr_dict_from_instance,
    FORM_SERIALIZER_FIELD_MAPPING
)



from .forms import ComponentAdminForm, DimmerConfigForm


class MyModelField(serializers.CharField):

    def to_representation(self, value):
        return value.pk


class ObjectSerializerMethodField(serializers.SerializerMethodField):

    def bind(self, field_name, parent):
        self.field_name = field_name
        super().bind(field_name, parent)

    def to_representation(self, value):
        return getattr(value, self.field_name)


class ComponentPrimaryKeyRelatedField(PrimaryKeyRelatedField):

    def get_attribute(self, instance):
        if self.queryset.model in (Icon, Zone, Category):
            return super().get_attribute(instance)
        obj = self.queryset.model.objects.filter(
            pk=instance.config.get(self.source_attrs[0])
        ).first()
        return obj


class ComponentFormsetField(FormSerializer):

    class Meta:
        form = ComponentAdminForm
        exclude = ('instance_methods', )
        field_mapping = {
            forms.ModelChoiceField: PrimaryKeyRelatedField,
            forms.TypedChoiceField: serializers.ChoiceField,
            forms.FloatField: serializers.FloatField,
        }

    def __init__(self, formset_field, *args, **kwargs):
        self.Meta.form = formset_field.formset_cls.form
        super().__init__(*args, **kwargs)

    def _get_field_kwargs(self, form_field, serializer_field_class):
        kwargs = super()._get_field_kwargs(form_field, serializer_field_class)
        if serializer_field_class == ComponentPrimaryKeyRelatedField:
            kwargs['queryset'] = form_field.queryset
        return kwargs

    def to_representation(self, instance):
        return super(FormSerializerBase, self).to_representation(instance)


    # def get_attribute(self, instance):
    #     return instance.config.get(self.source_attrs[0], [])



class ComponentSerializer(FormSerializer):
    id = ObjectSerializerMethodField()
    controller_methods = serializers.SerializerMethodField()
    last_change = TimestampField(read_only=True)
    read_only = serializers.SerializerMethodField()
    app_widget = serializers.SerializerMethodField()
    subcomponents = serializers.SerializerMethodField()
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
            forms.ModelChoiceField: ComponentPrimaryKeyRelatedField,
            forms.TypedChoiceField: serializers.ChoiceField,
            forms.FloatField: serializers.FloatField,
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

            try:
                serializer_field_class = field_mapping[form_field.field.__class__]
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
            else:
                ret[field_name] = self._get_field(
                    form_field.field, serializer_field_class
                )
                ret[field_name].initial = form_field.initial

        return ret

    def _get_field_kwargs(self, form_field, serializer_field_class):
        kwargs = super()._get_field_kwargs(form_field, serializer_field_class)
        if serializer_field_class == ComponentPrimaryKeyRelatedField:
            kwargs['queryset'] = form_field.queryset
        if serializer_field_class == ComponentFormsetField:
            kwargs['formset_field'] = form_field
            kwargs['many'] = True
        return kwargs

    def set_form_cls(self):
        if not isinstance(self.instance, Iterable):
            from .utils.type_constants import get_controller_types_map
            controllers_map = get_controller_types_map()
            if not self.instance:
                controller = controllers_map.get(
                    self.context['request'].META.get('CONTROLLER')
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
        controller_uid = None
        if not self.instance:
            controller_uid = self.context['request'].META.get('CONTROLLER')
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
        self.form_instance = form = self.get_form(
            data=data, instance=self.instance
        )
        data = self.accomodate_formsets(form, data)
        self.form_instance = form = self.get_form(
            data=data, instance=self.instance
        )
        if not form.is_valid():
            _cleaned_data = getattr(form, 'cleaned_data', None) or {}
            raise serializers.ValidationError(form.errors)
        else:
            cleaned_data = form.cleaned_data
        return cleaned_data

    def to_representation(self, instance):
        return super(FormSerializerBase, self).to_representation(instance)

    def update(self, instance, validated_data):
        form = self.get_form(instance=instance, data=validated_data)
        data = self.accomodate_formsets(form, validated_data)
        form = self.get_form(instance=instance, data=data)
        if form.is_valid():
            instance = form.save(commit=True)
        return instance

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

    def get_subcomponents(self, obj):
        from simo.users.utils import get_system_user
        return ComponentSerializer(
            obj.subcomponents.all(), many=True, context={
                'user': get_system_user()
            }
        ).data


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
