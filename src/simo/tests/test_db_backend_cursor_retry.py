from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase


class DbBackendCursorRetryTests(SimpleTestCase):
    def test_create_cursor_retries_once_on_operational_error(self):
        from simo.core.db_backend.base import DatabaseWrapper, DjangoOperationalError

        wrapper = DatabaseWrapper(settings.DATABASES['default'], alias='default')
        wrapper.close = mock.Mock()
        wrapper.connect = mock.Mock()

        sentinel = object()
        with mock.patch(
            'simo.core.db_backend.base.PostGisPsycopg2DatabaseWrapper.create_cursor',
            side_effect=[DjangoOperationalError('boom'), sentinel],
        ) as create_cursor:
            out = wrapper.create_cursor()

        self.assertIs(out, sentinel)
        self.assertEqual(create_cursor.call_count, 2)
        wrapper.close.assert_called_once()
        wrapper.connect.assert_called_once()

    def test_create_cursor_reraises_non_connectivity_errors(self):
        from simo.core.db_backend.base import DatabaseWrapper

        wrapper = DatabaseWrapper(settings.DATABASES['default'], alias='default')
        wrapper.close = mock.Mock()
        wrapper.connect = mock.Mock()

        with mock.patch(
            'simo.core.db_backend.base.PostGisPsycopg2DatabaseWrapper.create_cursor',
            side_effect=ValueError('nope'),
        ):
            with self.assertRaises(ValueError):
                wrapper.create_cursor()

        wrapper.close.assert_not_called()
        wrapper.connect.assert_not_called()

