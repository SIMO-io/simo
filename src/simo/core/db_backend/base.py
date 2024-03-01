import random, time
from django.contrib.gis.db.backends.postgis.base import (
    DatabaseWrapper as PostGisPsycopg2DatabaseWrapper
)
from django.db import close_old_connections, connection as db_connection
from django.utils.asyncio import async_unsafe
from django.db.utils import InterfaceError
from django.conf import settings


class DatabaseWrapper(PostGisPsycopg2DatabaseWrapper):

    @async_unsafe
    def create_cursor(self, name=None):
        if not self.is_usable():
            close_old_connections()
            db_connection.connect()
        return super().create_cursor(name=name)



