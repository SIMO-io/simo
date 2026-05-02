import csv
import math
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from simo.core.models import Component


SAMPLE_PERIOD_SEC = 30
CSV_COLUMNS = ('timestamp', 't_real', 't_aht', 't_tmp', 'tmp1', 'tmp2', 'hum')


def _parse_local_datetime(value, local_tz):
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(
            "Use datetime format like '2026-04-29 12:00'."
        ) from exc

    if timezone.is_naive(parsed):
        parsed = parsed.replace(tzinfo=local_tz)
    else:
        parsed = parsed.astimezone(local_tz)
    return parsed.astimezone(datetime_timezone.utc)


def _history_value_as_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        data = {}
        for item in value:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            data[item[0]] = item[1]
        return data
    return {}


def _as_float(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, (int, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _extract_sentinel_sample(value):
    data = _history_value_as_dict(value)
    t_aht = _as_float(data.get('out', data.get('outside')))
    t_tmp = _as_float(data.get('core'))
    if t_aht is None or t_tmp is None:
        return None
    return {
        't_aht': t_aht,
        't_tmp': t_tmp,
        'tmp1': _as_float(data.get('tmp1')),
        'tmp2': _as_float(data.get('tmp2')),
        'hum': _as_float(data.get('hum', data.get('humidity'))),
    }


def _extract_real_temperature(value):
    direct = _as_float(value)
    if direct is not None:
        return direct

    data = _history_value_as_dict(value)
    for key in ('temperature', 'temp', 'value'):
        direct = _as_float(data.get(key))
        if direct is not None:
            return direct
    return None


def _load_points(component, dt_from, dt_to, extractor):
    points = []
    previous = (
        component.history
        .filter(type='value', alive=True, date__lt=dt_from)
        .order_by('-date')
        .first()
    )
    if previous:
        sample = extractor(previous.value)
        if sample is not None:
            points.append((previous.date, sample))

    for item in (
        component.history
        .filter(type='value', alive=True, date__gte=dt_from, date__lte=dt_to)
        .order_by('date')
    ):
        sample = extractor(item.value)
        if sample is not None:
            points.append((item.date, sample))
    return points


def _format_float(value):
    if value is None:
        return ''
    return ('%.6f' % value).rstrip('0').rstrip('.')


class Command(BaseCommand):
    help = "Output Sentinel temperature calibration CSV using another component as t_real."

    def add_arguments(self, parser):
        parser.add_argument(
            '--th', type=int, required=True,
            help='Sentinel temperature/humidity component ID',
        )
        parser.add_argument(
            '--t_real', type=int, required=True,
            help='Reference numeric temperature component ID',
        )
        parser.add_argument(
            '--from', dest='date_from', required=True,
            help="Local start datetime, e.g. '2026-04-29 12:00'",
        )
        parser.add_argument(
            '--to', dest='date_to', required=True,
            help="Local end datetime, e.g. '2026-04-29 18:00'",
        )

    def handle(self, *args, **options):
        try:
            th = Component.objects.select_related('zone__instance').get(
                id=options['th']
            )
        except Component.DoesNotExist as exc:
            raise CommandError('Sentinel component does not exist.') from exc
        try:
            t_real = Component.objects.select_related('zone__instance').get(
                id=options['t_real']
            )
        except Component.DoesNotExist as exc:
            raise CommandError('Reference temperature component does not exist.') from exc

        instance = th.zone.instance
        if t_real.zone.instance_id != instance.id:
            raise CommandError('--th and --t_real must belong to the same instance.')

        local_tz = ZoneInfo(instance.timezone)
        timezone.activate(local_tz)
        dt_from = _parse_local_datetime(options['date_from'], local_tz)
        dt_to = _parse_local_datetime(options['date_to'], local_tz)
        if dt_from >= dt_to:
            raise CommandError('--from must be before --to.')

        th_points = _load_points(th, dt_from, dt_to, _extract_sentinel_sample)
        real_points = _load_points(t_real, dt_from, dt_to, _extract_real_temperature)
        if not th_points:
            raise CommandError(
                'No Sentinel temperature/humidity history found in the requested window.'
            )
        if not real_points:
            raise CommandError(
                'No reference temperature history found in the requested window.'
            )

        start = dt_from
        if th_points[0][0] > start:
            start = th_points[0][0]
        if real_points[0][0] > start:
            start = real_points[0][0]
        if start > dt_to:
            raise CommandError('No overlapping history found in the requested window.')

        writer = csv.writer(self.stdout)
        writer.writerow(CSV_COLUMNS)

        th_idx = 0
        real_idx = 0
        cur = start
        step = timedelta(seconds=SAMPLE_PERIOD_SEC)
        while cur <= dt_to:
            while (
                th_idx + 1 < len(th_points)
                and th_points[th_idx + 1][0] <= cur
            ):
                th_idx += 1
            while (
                real_idx + 1 < len(real_points)
                and real_points[real_idx + 1][0] <= cur
            ):
                real_idx += 1

            th_sample = th_points[th_idx][1]
            row = {
                'timestamp': timezone.localtime(
                    cur, local_tz
                ).strftime('%Y-%m-%dT%H:%M:%S'),
                't_real': _format_float(real_points[real_idx][1]),
                't_aht': _format_float(th_sample['t_aht']),
                't_tmp': _format_float(th_sample['t_tmp']),
                'tmp1': _format_float(th_sample['tmp1']),
                'tmp2': _format_float(th_sample['tmp2']),
                'hum': _format_float(th_sample['hum']),
            }
            writer.writerow([row[column] for column in CSV_COLUMNS])
            cur += step
