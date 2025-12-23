from unittest import mock

from django.core.management import call_command

from simo.core.models import Category, Component, Gateway, Zone
from simo.users.models import InstanceUser

from .base import BaseSimoTestCase, mk_instance, mk_role, mk_user, mk_instance_user


class RepublishMqttStateCommandTests(BaseSimoTestCase):
    def test_republish_counts_objects_for_instance(self):
        from simo.core.events import ObjMqttAnnouncement

        inst = mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        cat = Category.objects.create(instance=inst, name='C', all=False, icon=None)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        Component.objects.create(
            name='X',
            zone=zone,
            category=cat,
            gateway=gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )
        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)

        with mock.patch.object(ObjMqttAnnouncement, 'publish', autospec=True) as pub:
            call_command('republish_mqtt_state', instance=inst.id)
        # Zone + Category + Component + InstanceUser
        self.assertEqual(pub.call_count, 4)

    def test_republish_filters_only_active_instances(self):
        from simo.core.events import ObjMqttAnnouncement

        inst = mk_instance('inst-a', 'A')
        inst.is_active = False
        inst.save(update_fields=['is_active'])
        Zone.objects.create(instance=inst, name='Z', order=0)

        with mock.patch.object(ObjMqttAnnouncement, 'publish', autospec=True) as pub:
            call_command('republish_mqtt_state')
        self.assertEqual(pub.call_count, 0)

    def test_republish_includes_presence_fields_for_instance_user(self):
        from simo.core.events import ObjectChangeEvent

        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        iu = mk_instance_user(user, inst, role, is_active=True)
        iu.at_home = True
        iu.save(update_fields=['at_home'])

        published = []

        def _pub(self, *args, **kwargs):
            published.append(self.data)

        with mock.patch('simo.core.events.ObjMqttAnnouncement.publish', autospec=True, side_effect=_pub):
            call_command('republish_mqtt_state', instance=inst.id)

        has_iu = [d for d in published if d.get('obj_pk') == iu.pk]
        self.assertTrue(has_iu)
        self.assertIn('at_home', has_iu[0])


class OnHttpStartCommandTests(BaseSimoTestCase):
    def test_on_http_start_auto_creates_gateways_with_defaults(self):
        from django import forms
        from simo.core.models import Gateway

        class F(forms.Form):
            a = forms.IntegerField(initial=1)

            def __init__(self, *args, instance=None, **kwargs):
                super().__init__(*args, **kwargs)

        class Handler:
            name = 'H'
            auto_create = True
            config_form = F

        with (
            mock.patch('simo.core.management.commands.on_http_start.prepare_mosquitto', autospec=True),
            mock.patch('simo.core.management.commands.on_http_start.update_auto_update', autospec=True),
            mock.patch('simo.core.tasks.maybe_update_to_latest.delay', autospec=True),
            mock.patch('simo.core.utils.type_constants.GATEWAYS_MAP', {"x.H": Handler}),
        ):
            call_command('on_http_start')

        gw = Gateway.objects.filter(type='x.H').first()
        self.assertIsNotNone(gw)
        self.assertEqual(gw.config.get('a'), 1)

    def test_on_http_start_skips_handlers_without_auto_create(self):
        from django import forms
        from simo.core.models import Gateway

        class F(forms.Form):
            a = forms.IntegerField(initial=1)

            def __init__(self, *args, instance=None, **kwargs):
                super().__init__(*args, **kwargs)

        class Handler:
            name = 'H'
            auto_create = False
            config_form = F

        Gateway.objects.filter(type='x.H2').delete()
        with (
            mock.patch('simo.core.management.commands.on_http_start.prepare_mosquitto', autospec=True),
            mock.patch('simo.core.management.commands.on_http_start.update_auto_update', autospec=True),
            mock.patch('simo.core.tasks.maybe_update_to_latest.delay', autospec=True),
            mock.patch('simo.core.utils.type_constants.GATEWAYS_MAP', {"x.H2": Handler}),
        ):
            call_command('on_http_start')

        self.assertFalse(Gateway.objects.filter(type='x.H2').exists())
