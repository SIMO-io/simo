# Generated by Django 4.2.10 on 2024-11-17 10:39
from tqdm import tqdm
from django.db import migrations


def forwards_func(apps, schema_editor):
    from simo.generic.scripting.helpers import haversine_distance
    UserDeviceReportLog = apps.get_model("users", "UserDeviceReportLog")

    logs = UserDeviceReportLog.objects.filter(
        instance__isnull=False
    ).select_related('instance')

    print("Calculate at_home on UserDeviceReportLog's!")

    bulk_update = []
    for log in tqdm(logs, total=logs.count()):
        log.at_home = False
        if not log.relay:
            log.at_home = True
        elif log.location:
            log.at_home = haversine_distance(
                log.instance.location, log.location
            ) < 250
        if log.at_home:
            bulk_update.append(log)
        if len(bulk_update) > 1000:
            UserDeviceReportLog.objects.bulk_update(bulk_update, ["at_home"])
            bulk_update = []
    UserDeviceReportLog.objects.bulk_update(bulk_update, ["at_home"])


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0038_userdevicereportlog_at_home_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards_func, reverse_func, elidable=True),
    ]