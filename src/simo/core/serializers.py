import inspect
import datetime
from collections import OrderedDict
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
from drf_braces.serializers.form_serializer import FormSerializer
from .forms import ComponentAdminForm


class MyModelField(serializers.CharField):

    def to_representation(self, value):
        return value.pk


class ObjectSerializerMethodField(serializers.SerializerMethodField):

    def bind(self, field_name, parent):
        self.field_name = field_name
        super().bind(field_name, parent)

    def to_representation(self, value):
        return getattr(value, self.field_name)


class ComponentSerializer(FormSerializer, serializers.ModelSerializer):
    controller_methods = serializers.SerializerMethodField()
    last_change = TimestampField()
    read_only = serializers.SerializerMethodField()
    app_widget = serializers.SerializerMethodField()
    subcomponents = serializers.SerializerMethodField()
    base_type = ObjectSerializerMethodField()
    alive = ObjectSerializerMethodField()
    value = ObjectSerializerMethodField()
    value_units = ObjectSerializerMethodField()
    config = ObjectSerializerMethodField()
    meta = ObjectSerializerMethodField()
    arm_status = ObjectSerializerMethodField()
    battery_level = ObjectSerializerMethodField()

    class Meta:
        model = Component
        form = ComponentAdminForm
        field_mapping = {
            forms.ModelChoiceField: MyModelField,
            forms.TypedChoiceField: serializers.ChoiceField,
        }

    def get_form(self, data=None, **kwargs):
        form_cls = ComponentAdminForm
        form = form_cls(data=data, **kwargs)
        return form

    def validate(self, data):
        self.form_instance = form = self.get_form(
            data=data, instance=self.instance
        )
        if not form.is_valid():
            _cleaned_data = getattr(form, 'cleaned_data', None) or {}
            raise serializers.ValidationError(form.errors)
        else:
            cleaned_data = form.cleaned_data
        return cleaned_data

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
