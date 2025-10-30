from django.contrib.gis.db.backends.postgis.base import (
    DatabaseWrapper as PostGisPsycopg2DatabaseWrapper
)
from django.db.utils import OperationalError, InterfaceError
from django.utils.asyncio import async_unsafe


class DatabaseWrapper(PostGisPsycopg2DatabaseWrapper):
    @async_unsafe
    def create_cursor(self, name=None):
        try:
            return super().create_cursor(name=name)
        except (InterfaceError, OperationalError):
            # Heal this very connection
            self.close()
            self.connect()
            return super().create_cursor(name=name)


