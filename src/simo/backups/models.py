import uuid
from django.db import models


class Backup(models.Model):
    datetime = models.DateTimeField(db_index=True)
    mac = models.CharField(max_length=100, db_index=True)
    filepath = models.CharField(max_length=200)

    class Meta:
        unique_together = 'datetime', 'mac'

    @property
    def device(self):
        if self.mac == str(hex(uuid.getnode())):
            return "This machine"
        return self.mac


class BackupLog(models.Model):
    datetime = models.DateTimeField(db_index=True, auto_now_add=True)
    level = models.CharField(default='info', choices=(
        ('info', "INFO"), ('warning', "WARNING"), ('error', "ERROR")
    ))
    msg = models.TextField()