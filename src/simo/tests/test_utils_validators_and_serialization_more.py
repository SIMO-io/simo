from __future__ import annotations

import io
import tempfile
import os
from unittest import mock

from django.core.exceptions import ValidationError
from django import forms
from django.test import SimpleTestCase, override_settings

from simo.core.models import Component, Gateway, Zone
from simo.fleet.models import Colonel

from .base import BaseSimoTestCase, mk_instance


class TestValidators(SimpleTestCase):
    def test_validate_svg_accepts_valid_svg_and_resets_pointer(self):
        from simo.core.utils.validators import validate_svg

        content = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        )
        f = io.BytesIO(content)
        f.seek(len(content))
        validate_svg(f)
        self.assertEqual(f.tell(), 0)

    def test_validate_svg_rejects_non_svg(self):
        from simo.core.utils.validators import validate_svg

        f = io.BytesIO(b'<?xml version="1.0"?><html></html>')
        with self.assertRaises(ValidationError):
            validate_svg(f)

    def test_validate_slaves_rejects_direct_self_reference(self):
        from simo.core.utils.validators import validate_slaves

        class _Rel:
            def __init__(self, items):
                self._items = list(items)

            def all(self):
                return self

            def count(self):
                return len(self._items)

            def __iter__(self):
                return iter(self._items)

        class _Comp:
            def __init__(self, name, slaves=None):
                self.name = name
                self.slaves = _Rel(slaves or [])

            def __str__(self):
                return self.name

        comp = _Comp('main')
        with self.assertRaises(forms.ValidationError):
            validate_slaves([comp], comp)


class TestSerializationHelpers(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-serial', 'Serial')
        self.zone1 = Zone.objects.create(instance=self.inst, name='Z1', order=0)
        self.zone2 = Zone.objects.create(instance=self.inst, name='Z2', order=1)

        from simo.fleet.gateways import FleetGatewayHandler

        self.gw, _ = Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)
        self.colonel = Colonel.objects.create(
            instance=self.inst,
            uid='c-serial',
            type='sentinel',
            firmware_version='1.0',
            enabled=True,
        )
        self.component = Component.objects.create(
            name='C',
            zone=self.zone1,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={'colonel': self.colonel.id},
            meta={},
            value=None,
        )

    def test_serialize_and_deserialize_form_data_roundtrip(self):
        from simo.core.utils.serialization import deserialize_form_data, serialize_form_data

        payload = {
            'zone': self.zone1,
            'zones': [self.zone1, self.zone2],
            'n': 1,
            's': 'hello',
        }
        serialized = serialize_form_data(payload)
        self.assertEqual(serialized['zone']['model'], 'single')
        self.assertEqual(serialized['zones']['model'], 'many')

        restored = deserialize_form_data(serialized)
        self.assertEqual(restored['zone'].pk, self.zone1.pk)
        self.assertEqual([z.pk for z in restored['zones']], [self.zone1.pk, self.zone2.pk])
        self.assertEqual(restored['n'], 1)
        self.assertEqual(restored['s'], 'hello')

    def test_dirty_fields_to_current_values_prefers_relation_id(self):
        from simo.core.utils.model_helpers import dirty_fields_to_current_values

        current = dirty_fields_to_current_values(self.component, {'zone': True, 'name': True})
        self.assertEqual(current['zone'], self.zone1.id)
        self.assertEqual(current['name'], 'C')

    def test_dirty_fields_to_current_values_skips_many_to_many(self):
        from simo.core.utils.model_helpers import dirty_fields_to_current_values

        current = dirty_fields_to_current_values(self.component, {'slaves': True, 'name': True})
        self.assertNotIn('slaves', current)
        self.assertEqual(current['name'], 'C')


class TestLogFilePath(BaseSimoTestCase):
    def test_get_log_file_path_creates_file(self):
        from simo.core.utils.model_helpers import get_log_file_path

        inst = mk_instance('inst-log', 'Log')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(LOG_DIR=tmp):
                path = get_log_file_path(zone)
                self.assertTrue(os.path.exists(path))
                self.assertTrue(path.startswith(tmp))

        self.assertTrue(path.endswith('.log'))


class TestLoggers(SimpleTestCase):
    def test_get_component_logger_adds_handler_once(self):
        import logging

        from simo.core.loggers import get_component_logger

        component = mock.Mock()
        component.id = 123

        logger = logging.getLogger('Component Logger [123]')
        logger.handlers.clear()
        with (
            mock.patch('simo.core.loggers.get_log_file_path', return_value='/tmp/x.log'),
            mock.patch('simo.core.loggers.RotatingFileHandler') as handler,
        ):
            logger1 = get_component_logger(component)
            logger2 = get_component_logger(component)

        self.assertIs(logger1, logger2)
        self.assertEqual(handler.call_count, 1)
        logger.handlers.clear()
