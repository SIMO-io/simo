import inspect
import datetime
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
        return datetime.fromtimestamp(data)


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
from taggit.forms import TagField


class ComponentSerializer(FormSerializer):
    controller_methods = serializers.SerializerMethodField()
    last_change = TimestampField()
    read_only = serializers.SerializerMethodField()
    app_widget = serializers.SerializerMethodField()
    subcomponents = serializers.SerializerMethodField()

    class Meta:
        #model = Component
        form = ComponentAdminForm
        fields = [
            'id', 'name', 'icon', 'zone',
            'base_type', 'app_widget',
            'category', 'alive',
            'value', 'value_units',
            'config', 'meta', 'controller_methods',
            'alarm_category', 'arm_status', 'last_change',
            'read_only', 'show_in_app', 'battery_level',
            'subcomponents'
        ]
        field_mapping = {
            forms.ModelChoiceField: serializers.ModelField,
            TagField: serializers.CharField,
            forms.TypedChoiceField: serializers.ChoiceField,
        }

    def _get_field_kwargs(self, form_field, serializer_field_class):
        attrs = super()._get_field_kwargs(form_field, serializer_field_class)
        if isinstance(form_field, forms.ModelChoiceField):
            attrs['model_field'] = form_field.to_field_name
        return attrs

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
