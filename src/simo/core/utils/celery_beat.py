from celery.beat import PersistentScheduler


class SafePersistentScheduler(PersistentScheduler):
    """
    PersistentScheduler that auto-recovers from a corrupted celerybeat-schedule
    file instead of dying with 'cannot add item to database'.
    """

    def setup_schedule(self):
        try:
            return super().setup_schedule()
        except Exception as exc:
            # This removes the bad schedule file(s) and reopens a fresh store.
            self._store = self._destroy_open_corrupted_schedule(exc)
            # Try again with a clean store.
            return super().setup_schedule()
