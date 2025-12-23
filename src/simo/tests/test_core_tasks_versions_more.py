from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase


def _version_no(v: str) -> int:
    major, minor, patch = v.split('.')
    return int(major) * 1000000 + int(minor) * 1000 + int(patch)


class TestMaybeUpdateToLatestVersionSorting(SimpleTestCase):
    pass


def _mk_case(versions):
    from simo.core.tasks import maybe_update_to_latest

    expected = max(versions, key=_version_no)

    def _test(self):
        ds = {'core__latest_version_available': '', 'core__auto_update': False}

        resp = mock.Mock(status_code=200)
        resp.json.return_value = {'releases': {v: {} for v in versions}}

        inst_qs = mock.Mock()
        inst_qs.count.return_value = 0

        with (
            mock.patch('simo.core.tasks.requests.get', return_value=resp),
            mock.patch('simo.conf.dynamic_settings', ds),
            mock.patch(
                'simo.core.tasks.pkg_resources.get_distribution',
                return_value=mock.Mock(version='0.0.0'),
            ),
            mock.patch('simo.core.models.Instance.objects.all', return_value=inst_qs),
            mock.patch('simo.core.tasks.update.s', return_value='sig'),
            mock.patch('builtins.print'),
        ):
            out = maybe_update_to_latest()

        self.assertEqual(ds['core__latest_version_available'], expected)
        self.assertEqual(out, 'sig')

    return _test


_CASES = []
for i in range(0, 220):
    # Deterministic but varied version sets.
    v1 = f"0.{i // 10}.{i % 10}"
    v2 = f"1.{(i * 3) % 50}.{(i * 7) % 50}"
    v3 = f"2.{(i * 5) % 20}.{(i * 11) % 100}"
    v4 = f"3.{i % 4}.{(i * 13) % 30}"
    v5 = f"1.{(i * 17) % 50}.{(i * 19) % 50}"
    _CASES.append([v1, v2, v3, v4, v5])

for idx, versions in enumerate(_CASES):
    setattr(
        TestMaybeUpdateToLatestVersionSorting,
        f'test_case_{idx}',
        _mk_case(versions),
    )

