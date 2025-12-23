from __future__ import annotations

import io
import json

from django.test import SimpleTestCase
from rest_framework import serializers

# Import the bundled drf_braces test-suite so it gets executed by
# `django test simo.tests` (the upstream modules live outside simo.tests).
from simo.core.drf_braces.tests.fields.test_custom import (  # noqa: F401
    TestNonValidatingChoiceField,
    TestPositiveIntegerField,
    TestRoundedDecimalField,
    TestUTCDateTimeField,
    TestUnvalidatedField,
)
from simo.core.drf_braces.tests.fields.test_fields import TestFields  # noqa: F401
from simo.core.drf_braces.tests.fields.test_mixins import (  # noqa: F401
    TestAllowBlankFieldMixin,
    TestEmptyStringFieldMixin,
    TestValueAsTextFieldMixin,
)
from simo.core.drf_braces.tests.fields.test_modified import (  # noqa: F401
    TestBooleanField,
    TestDateTimeField,
    TestDecimalField,
)
from simo.core.drf_braces.tests.forms.test_fields import TestISO8601DateTimeField  # noqa: F401
from simo.core.drf_braces.tests.forms.test_serializer_form import (  # noqa: F401
    TestSerializerForm,
    TestSerializerFormBase,
    TestSerializerFormMeta,
    TestSerializerFormOptions,
    TestUtils as TestSerializerFormUtils,
)
from simo.core.drf_braces.tests.serializers.test_enforce_validation_serializer import (  # noqa: F401
    TestEnforceValidationFieldMixin,
    TestUtils as TestEnforceValidationUtils,
)
from simo.core.drf_braces.tests.serializers.test_form_serializer import (  # noqa: F401
    TestFormSerializer,
    TestFormSerializerBase,
    TestFormSerializerFieldMixin,
    TestFormSerializerMeta,
    TestFormSerializerOptions,
    TestLazyLoadingValidationsMixin,
    TestUtils as TestFormSerializerUtils,
)
from simo.core.drf_braces.tests.serializers.test_swapping import (  # noqa: F401
    TestSwappingSerializerMixin,
)
from simo.core.drf_braces.tests.test_mixins import (  # noqa: F401
    TestMapDataViewMixin,
    TestMultipleSerializersViewMixin,
    TestStrippingJSONViewMixin,
)
from simo.core.drf_braces.tests.test_parsers import (  # noqa: F401
    TestSortedJSONParser,
    TestStrippingJSONParser,
)
from simo.core.drf_braces.tests.test_renderers import TestDoubleAsStrJsonEncoder  # noqa: F401
from simo.core.drf_braces.tests.test_utils import TestUtils as TestDrfBracesUtils  # noqa: F401


class TestDrfBracesExtra(SimpleTestCase):
    def test_sorted_json_parser_preserves_order(self):
        from simo.core.drf_braces.parsers import SortedJSONParser

        payload = json.dumps({'b': 2, 'a': 1}).encode('utf-8')
        parsed = SortedJSONParser().parse(io.BytesIO(payload))
        self.assertEqual(list(parsed.keys()), ['b', 'a'])

    def test_stripping_json_parser_keeps_original_when_root_missing(self):
        from simo.core.drf_braces.parsers import StrippingJSONParser

        payload = json.dumps({'x': 1}).encode('utf-8')
        parsed = StrippingJSONParser().parse(
            io.BytesIO(payload),
            parser_context={'parse_root': 'missing', 'encoding': 'utf-8'},
        )
        self.assertEqual(parsed, {'x': 1})

    def test_double_as_str_renderer_media_type(self):
        from simo.core.drf_braces.renderers import DoubleAsStrJsonRenderer

        self.assertIn('double=str', DoubleAsStrJsonRenderer.media_type)

    def test_multiple_serializers_view_mixin_uses_kwarg_serializer_class(self):
        from simo.core.drf_braces.mixins import MultipleSerializersViewMixin

        class _View(MultipleSerializersViewMixin):
            def get_serializer_class(self):
                raise AssertionError('should not be used')

            def get_serializer_context(self):
                return {'ctx': 1}

        class _S(serializers.Serializer):
            a = serializers.IntegerField()

        view = _View()
        ser = view.get_serializer(serializer_class=_S, data={'a': 1})
        self.assertTrue(ser.is_valid())
        self.assertEqual(ser.context['ctx'], 1)

