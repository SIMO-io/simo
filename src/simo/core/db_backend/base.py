import random, time
from django.contrib.gis.db.backends.postgis.base import (
    DatabaseWrapper as PostGisPsycopg2DatabaseWrapper
)
from django.utils.asyncio import async_unsafe
from django.db.utils import InterfaceError
from django.conf import settings


class DatabaseWrapper(PostGisPsycopg2DatabaseWrapper):

    # connection already closed raised by default django postgresql db backend
    # which means that ensure_connection didn't ensured connection!
    # It happens when connection to the postgresql server is already lost,
    # but this backend handler knows nothing about it.
    # So we set connection to None immediately, therefore if there
    # is other thread trying to access the cursor
    # new connection will be established by ensure_connection() method.
    # We also wait for 0 - 10s, to not overwhelm anything in case
    # there are many multiple threads trying to access the same
    # db connection.


    def _cursor(self, name=None):
        self.ensure_connection()
        with self.wrap_database_errors:
            try:
                return self._prepare_cursor(self.create_cursor(name))
            except InterfaceError:

                self.connection = None
                time.sleep(random.randint(0, 100) / 10)
                return self._cursor(name)



