import inspect
import datetime
import re
from django import forms
from collections import OrderedDict
from django.conf import settings
from collections.abc import Iterable
from easy_thumbnails.files import get_thumbnailer
from simo.core.middleware import get_current_request
from rest_framework import serializers
from rest_framework.fields import SkipField
from rest_framework.relations import Hyperlink, PKOnlyObject
from actstream.models import Action
from simo.core.forms import HiddenField, FormsetField
from simo.core.form_fields import (
    Select2ListChoiceField, Select2ListChoiceField,
    Select2ModelChoiceField, Select2ListMultipleChoiceField
)
from simo.core.models import Component
from rest_framework.relations import PrimaryKeyRelatedField, ManyRelatedField
from .drf_braces.serializers.form_serializer import (
    FormSerializer, FormSerializerBase, reduce_attr_dict_from_instance,
    FORM_SERIALIZER_FIELD_MAPPING, set_form_partial_validation,
    find_matching_class_kwargs
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
    last_modified = TimestampField(read_only=True)

    class Meta:
        model = Icon
        fields = '__all__'


class CategorySerializer(serializers.ModelSerializer):
    header_image_thumb = serializers.SerializerMethodField()
    last_modified = TimestampField(read_only=True)

    class Meta:
        model = Category
        fields = (
            'id', 'name', 'all', 'icon',
            'header_image', 'header_image_thumb',
            'last_modified'
        )


    def get_header_image_thumb(self, obj):
        if obj.header_image:
            thumbnailer = get_thumbnailer(obj.header_image.path)
            thumb = thumbnailer.get_thumbnail(
                {'size': (830, 430), 'crop': True}
            )
            url = '/' + thumb.path.strip(settings.VAR_DIR)
            request = get_current_request()
            if request:
                url = request.build_absolute_uri(url)
            return url
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

class HiddenSerializerField(serializers.CharField):
    pass


class TextAreaSerializerField(serializers.CharField):
    pass


class ComponentFormsetField(FormSerializer):

    class Meta:
        # fake form, but it is necessary for FormSerializer
        # we set it to proper formset form on __init__
        form = forms.Form
        field_mapping = {
            HiddenField: HiddenSerializerField,
            Select2ListChoiceField: serializers.ChoiceField,
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

        attrs = find_matching_class_kwargs(form_field, serializer_field_class)
        if 'choices' in attrs:
            kwargs['choices'] = attrs['choices']

        return kwargs

    def to_representation(self, instance):
        """
        Object instance -> Dict of primitive datatypes.
        """
        ret = OrderedDict()
        fields = self._readable_fields

        for field in fields:
            try:
                attribute = field.get_attribute(instance)
            except SkipField:
                continue
            except:
                ret[field.field_name] = None
                continue

            check_for_none = attribute.pk if isinstance(
                attribute, PKOnlyObject
            ) else attribute
            if check_for_none is None:
                ret[field.field_name] = None
            else:
                ret[field.field_name] = field.to_representation(attribute)

        return ret

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
        return [obj.pk for obj in value.all()]

    def to_internal_value(self, data):
        if data == [] and self.allow_blank:
            return []
        return self.queryset.filter(pk__in=data)


class ComponentSerializer(FormSerializer):
    id = ObjectSerializerMethodField()
    last_change = TimestampField(read_only=True)
    last_modified = TimestampField(read_only=True)
    read_only = serializers.SerializerMethodField()
    app_widget = serializers.SerializerMethodField()
    slaves = serializers.SerializerMethodField()
    base_type = ObjectSerializerMethodField()
    show_in_app = ObjectSerializerMethodField()
    controller_uid = ObjectSerializerMethodField()
    alive = ObjectSerializerMethodField()
    error_msg = ObjectSerializerMethodField()
    value = ObjectSerializerMethodField()
    value_units = ObjectSerializerMethodField()
    config = ObjectSerializerMethodField()
    meta = ObjectSerializerMethodField()
    alarm_category = ObjectSerializerMethodField()
    arm_status = ObjectSerializerMethodField()
    battery_level = ObjectSerializerMethodField()
    controller_methods = serializers.SerializerMethodField()
    info = serializers.SerializerMethodField()
    masters_only = serializers.SerializerMethodField()

    class Meta:
        form = ComponentAdminForm
        field_mapping = {
            HiddenField: HiddenSerializerField,
            forms.TypedChoiceField: serializers.ChoiceField,
            forms.FloatField: serializers.FloatField,
            forms.SlugField: serializers.CharField,
            forms.ModelChoiceField: ComponentPrimaryKeyRelatedField,
            Select2ModelChoiceField: ComponentPrimaryKeyRelatedField,
            forms.ModelMultipleChoiceField: ComponentManyToManyRelatedField,
            Select2ListMultipleChoiceField: ComponentManyToManyRelatedField,
            FormsetField: ComponentFormsetField,
        }



    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set proper instance for OPTIONS request
        if not self.instance:
            res = re.findall(
                r'.*\/core\/components\/(?P<component_id>[0-9]+)\/',
                self.context['request'].path
            )
            if res:
                self.instance = Component.objects.filter(id=res[0]).first()

    def get_fields(self):

        self.set_form_cls()

        ret = OrderedDict()

        field_mapping = reduce_attr_dict_from_instance(
            self,
            lambda i: getattr(getattr(i, 'Meta', None), 'field_mapping', {}),
            FORM_SERIALIZER_FIELD_MAPPING
        )

        if not self.instance or isinstance(self.instance, Iterable):
            form = self.get_form()
        else:
            form = self.get_form(instance=self.instance)

        for field_name in form.fields:
            # if field is specified as excluded field
            if field_name in getattr(self.Meta, 'exclude', []):
                continue

            # # if field is already defined via declared fields
            # # skip mapping it from forms which then honors
            # # the custom validation defined on the DRF declared field
            # if field_name in ret:
            #     continue

            form_field = form[field_name]

            cls = form_field.field.__class__
            if field_name == 'notes':
                serializer_field_class = TextAreaSerializerField
            else:
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

        for name, field in super(FormSerializerBase, self).get_fields().items():
            if name in ret:
                continue
            ret[name] = field

        return ret

    def _get_field_kwargs(self, form_field, serializer_field_class):
        kwargs = super()._get_field_kwargs(form_field, serializer_field_class)
        kwargs['style'] = {'form_field': form_field}
        if serializer_field_class in (
            ComponentPrimaryKeyRelatedField, ComponentManyToManyRelatedField
        ):
            qs = form_field.queryset
            if hasattr(qs.model, 'instance'):
                qs = qs.filter(instance=self.context['instance'])
            elif hasattr(qs.model, 'instances'):
                qs = qs.filter(instances=self.context['instance'])
            elif qs.model == Component:
                qs = qs.filter(zone__instance=self.context['instance'])
            kwargs['queryset'] = qs

        elif serializer_field_class == ComponentFormsetField:
            kwargs['formset_field'] = form_field
            kwargs['many'] = True

        attrs = find_matching_class_kwargs(form_field, serializer_field_class)
        if 'choices' in attrs:
            kwargs['choices'] = form_field.choices

        return kwargs

    def set_form_cls(self):
        self.Meta.form = ComponentAdminForm
        if not isinstance(self.instance, Iterable):
            from .utils.type_constants import CONTROLLER_TYPES_MAP
            if not self.instance:
                controller = CONTROLLER_TYPES_MAP.get(
                    #'simo.generic.controllers.AlarmClock'
                    self.context['request'].META.get('HTTP_CONTROLLER')
                )
                if controller:
                    self.Meta.form = controller.add_form
            else:
                controller = CONTROLLER_TYPES_MAP.get(
                    self.instance.controller_uid
                )
                if controller:
                    self.Meta.form = controller.config_form

    def get_form(self, data=None, instance=None, **kwargs):
        if 'forms' not in self.context:
            self.context['forms'] = {}
        form_key = None
        if not data:
            form_key = 0
            if instance:
                form_key = instance.id
        if form_key in self.context['forms']:
            return self.context['forms'][form_key]

        self.set_form_cls()
        if not self.instance or isinstance(self.instance, Iterable):
            #controller_uid = 'simo.generic.controllers.AlarmClock'
            controller_uid = self.context['request'].META.get('HTTP_CONTROLLER')
        else:
            controller_uid = self.instance.controller_uid
        form = self.Meta.form(
            data=data, request=self.context['request'],
            controller_uid=controller_uid, instance=instance,
            **kwargs
        )
        # only masters and superusers can fully manage components via app
        # others can only change basic fields
        if not self.context['request'].user.is_master:
            user_role = self.context['request'].user.get_role(
                self.context['instance']
            )
            if not user_role.is_superuser:
                for field_name in list(form.fields.keys()):
                    if field_name not in form.basic_fields:
                        del form.fields[field_name]

        if form_key is not None:
            self.context['forms'][form_key] = form

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
                return form.save(commit=False)
            return form.save(commit=True)
        raise serializers.ValidationError(form.errors)

    def get_controller_methods(self, obj):
        c_methods = [m[0] for m in inspect.getmembers(
            obj.controller, predicate=inspect.ismethod
        ) if not m[0].startswith('_')]
        if obj.alarm_category:
            c_methods.extend(['arm', 'disarm'])
        return c_methods

    def get_info(self, obj):
        if obj.controller:
            return obj.controller.info()

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

    def get_masters_only(self, obj):
        if not obj.controller:
            return False
        return obj.controller.masters_only


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


class ActionSerializer(serializers.ModelSerializer):
    timestamp = TimestampField()
    actor = serializers.SerializerMethodField()
    target = serializers.SerializerMethodField()
    action_type = serializers.SerializerMethodField()
    value = serializers.SerializerMethodField()

    class Meta:
        model = Action
        fields = (
            'id', 'timestamp', 'actor', 'target', 'verb',
            'action_type', 'value'
        )

    def get_actor(self, obj):
        if obj.actor:
            return str(obj.actor)

    def get_target(self, obj):
        if obj.target:
            return str(obj.target)


    def get_action_type(self, obj):
        return obj.data.get('action_type')

    def get_value(self, obj):
        return obj.data.get('value')

