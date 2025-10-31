from django.contrib.gis.db.backends.postgis.base import (
    DatabaseWrapper as PostGisPsycopg2DatabaseWrapper
)
"""Custom PostGIS database wrapper with light self-healing.

We retry cursor creation on transient driver-level errors. Previously we
were catching Django's wrapper exceptions (django.db.utils.InterfaceError/
OperationalError). However, those are only raised by the outer
`wrap_database_errors` context. Inside `create_cursor()` the driver
(`psycopg2`) raises its own exceptions, so our except block never ran and
connections weren't healed.

By catching psycopg2 errors here (in addition to Django's), we ensure
we can close() and reconnect() this connection when `self.connection`
is already closed or becomes unusable, avoiding busy error loops in
MQTT threads and periodic tasks.
"""

from django.db.utils import OperationalError as DjangoOperationalError, InterfaceError as DjangoInterfaceError
try:
    # Catch driver-level errors where they originate.
    from psycopg2 import OperationalError as PsycopgOperationalError, InterfaceError as PsycopgInterfaceError
except Exception:  # pragma: no cover - very defensive
    PsycopgOperationalError = PsycopgInterfaceError = Exception
from django.utils.asyncio import async_unsafe
import time
import random


class DatabaseWrapper(PostGisPsycopg2DatabaseWrapper):
    @async_unsafe
    def create_cursor(self, name=None):
        """Create a DB cursor with a single, simple heal-once path.

        - Fast path: return cursor immediately.
        - On error: if it's a connectivity issue (known exceptions or
          connection.closed set), close + backoff + reconnect, then retry once.
        - Otherwise: re-raise the original exception.
        """
        try:
            return super().create_cursor(name=name)
        except Exception as e:
            # Determine if this is a connectivity problem
            is_connectivity_err = isinstance(
                e,
                (
                    DjangoInterfaceError,
                    DjangoOperationalError,
                    PsycopgInterfaceError,
                    PsycopgOperationalError,
                ),
            )
            if not is_connectivity_err:
                try:
                    conn = getattr(self, 'connection', None)
                    is_connectivity_err = bool(getattr(conn, 'closed', 0))
                except Exception:
                    is_connectivity_err = False

            if not is_connectivity_err:
                # Not a connection issue; bubble up unchanged
                raise

            # Heal this very connection and retry once
            try:
                self.close()
            finally:
                try:
                    time.sleep(0.05 + random.random() * 0.15)  # 50–200 ms
                except Exception:
                    pass
                self.connect()
            return super().create_cursor(name=name)
