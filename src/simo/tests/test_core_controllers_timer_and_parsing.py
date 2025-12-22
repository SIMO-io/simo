from unittest import mock

from django.core.exceptions import ValidationError

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class TimerMixinTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        from simo.generic.controllers import SwitchGroup

        self.comp = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

    def test_set_timer_defaults_to_toggle_on_unknown_event(self):
        with mock.patch('simo.core.controllers.time.time', autospec=True, return_value=100):
            self.comp.controller.set_timer(110, event='no_such_method')

        self.comp.refresh_from_db()
        self.assertEqual(self.comp.meta.get('timer_to'), 110)
        self.assertEqual(self.comp.meta.get('timer_event'), 'toggle')
        self.assertEqual(self.comp.meta.get('timer_start'), 100)
        self.assertTrue(self.comp.controller.timer_engaged())

    def test_set_timer_rejects_past_timestamp(self):
        with mock.patch('simo.core.controllers.time.time', autospec=True, return_value=100):
            with self.assertRaises(ValidationError):
                self.comp.controller.set_timer(99)

    def test_pause_and_resume_timer(self):
        with mock.patch('simo.core.controllers.time.time', autospec=True, return_value=100):
            self.comp.controller.set_timer(130)

        with mock.patch('simo.core.controllers.time.time', autospec=True, return_value=110):
            self.comp.controller.pause_timer()
        self.comp.refresh_from_db()
        self.assertEqual(self.comp.meta.get('timer_to'), 0)
        self.assertEqual(self.comp.meta.get('timer_left'), 20)

        with mock.patch('simo.core.controllers.time.time', autospec=True, return_value=200):
            self.comp.controller.resume_timer()
        self.comp.refresh_from_db()
        self.assertEqual(self.comp.meta.get('timer_left'), 0)
        self.assertEqual(self.comp.meta.get('timer_to'), 220)

    def test_pause_timer_raises_when_not_set(self):
        with mock.patch('simo.core.controllers.time.time', autospec=True, return_value=100):
            with self.assertRaises(ValidationError):
                self.comp.controller.pause_timer()

    def test_resume_timer_raises_when_not_paused(self):
        with mock.patch('simo.core.controllers.time.time', autospec=True, return_value=100):
            with self.assertRaises(ValidationError):
                self.comp.controller.resume_timer()


class ValueParsingTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

    def test_string_to_vals_parses_boolean_switch_values(self):
        from simo.generic.controllers import SwitchGroup

        comp = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        vals = comp.controller._string_to_vals('[0, 1, false, true, off, on]')
        self.assertEqual(vals, [False, True, False, True, False, True])

    def test_string_to_vals_parses_numeric_dimmer_values(self):
        from simo.generic.controllers import DimmableLightsGroup

        comp = Component.objects.create(
            name='D',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='dimmer',
            controller_uid=DimmableLightsGroup.uid,
            config={'min': 0.0, 'max': 100.0, 'inverse': False},
            meta={},
            value=0,
        )
        vals = comp.controller._string_to_vals('(1, 2, 3)')
        self.assertEqual(vals, [1, 2, 3])
