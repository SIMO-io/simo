from __future__ import annotations

import datetime
from unittest import mock

import requests
from django.conf import settings
from django.db.models.fields.files import FieldFile
from django.utils import timezone

from simo.users.models import InstanceUser

from .base import BaseSimoTestCase, mk_instance, mk_instance_user, mk_role, mk_user


class TestSyncWithRemote(BaseSimoTestCase):
    def test_sync_with_remote_posts_instance_scoped_users(self):
        from simo.core.tasks import sync_with_remote

        ds = {
            'core__hub_uid': 'hub-uid',
            'core__hub_secret': 'hub-secret',
            'core__remote_conn_version': 1,
        }

        inst_a = mk_instance('inst-a', 'A')
        inst_b = mk_instance('inst-b', 'B')
        role_a = mk_role(inst_a, is_owner=True)
        role_b = mk_role(inst_b, is_owner=True)

        user_a = mk_user('a@example.com', 'A')
        user_b = mk_user('b@example.com', 'B')
        mk_instance_user(user_a, inst_a, role_a, is_active=True)
        mk_instance_user(user_b, inst_b, role_b, is_active=True)

        master = mk_user('master@example.com', 'M', is_master=True)

        resp = mock.Mock(status_code=500)
        with (
            mock.patch('simo.core.tasks.dynamic_settings', ds),
            mock.patch('simo.core.tasks.get_self_ip', return_value='1.2.3.4'),
            mock.patch('simo.core.tasks.uuid.getnode', return_value=0x1234),
            mock.patch('simo.core.tasks.pkg_resources.get_distribution', return_value=mock.Mock(version='9.9.9')),
            mock.patch('simo.core.tasks.requests.post', return_value=resp) as post,
            mock.patch('builtins.print'),
        ):
            sync_with_remote()

        sent = post.call_args.kwargs['json']
        self.assertEqual(sent['hub_uid'], 'hub-uid')
        self.assertEqual(sent['hub_secret'], 'hub-secret')
        self.assertEqual(sent['simo_version'], '9.9.9')
        self.assertEqual(sent['local_http'], 'https://1.2.3.4')

        inst_payload = {i['uid']: i for i in sent['instances']}
        self.assertEqual(set(inst_payload.keys()), {inst_a.uid, inst_b.uid})

        users_a = {u['email'] for u in inst_payload[inst_a.uid]['users']}
        users_b = {u['email'] for u in inst_payload[inst_b.uid]['users']}
        self.assertIn('a@example.com', users_a)
        self.assertIn('b@example.com', users_b)
        self.assertNotIn('b@example.com', users_a)
        self.assertNotIn('a@example.com', users_b)

        # Hub masters are included on every instance.
        self.assertIn('master@example.com', users_a)
        self.assertIn('master@example.com', users_b)

    def test_sync_with_remote_updates_dynamic_settings_and_calls_save_config(self):
        from simo.core.tasks import sync_with_remote

        ds = {
            'core__hub_uid': 'hub-uid',
            'core__hub_secret': 'hub-secret',
            'core__remote_conn_version': 1,
            'core__remote_http': '',
            'core__paid_until': 0,
        }

        r_json = {
            'hub_uid': 'new-uid',
            'hub_remote_http': 'https://remote',
            'new_secret': 'new-secret',
            'paid_until': '123',
            'remote_conn_version': 2,
            'instances': [],
        }
        resp = mock.Mock(status_code=200)
        resp.json.return_value = r_json

        with (
            mock.patch('simo.core.tasks.dynamic_settings', ds),
            mock.patch('simo.core.tasks.get_self_ip', return_value='1.2.3.4'),
            mock.patch('simo.core.tasks.uuid.getnode', return_value=0x1234),
            mock.patch('simo.core.tasks.pkg_resources.get_distribution', return_value=mock.Mock(version='9.9.9')),
            mock.patch('simo.core.tasks.requests.post', return_value=resp),
            mock.patch('simo.core.tasks.save_config', autospec=True) as save_config,
            mock.patch('builtins.print'),
        ):
            sync_with_remote()

        save_config.assert_called_once_with(r_json)
        self.assertEqual(ds['core__hub_uid'], 'new-uid')
        self.assertEqual(ds['core__remote_http'], 'https://remote')
        self.assertEqual(ds['core__hub_secret'], 'new-secret')
        self.assertEqual(ds['core__paid_until'], 123)
        self.assertEqual(ds['core__remote_conn_version'], 2)

    def test_sync_with_remote_creates_users_for_instance_without_users(self):
        from simo.core.tasks import sync_with_remote

        ds = {
            'core__hub_uid': 'hub-uid',
            'core__hub_secret': 'hub-secret',
            'core__remote_conn_version': 1,
        }

        inst = mk_instance('inst-a', 'A')
        role_owner = mk_role(inst, is_owner=True)
        role_superuser = mk_role(inst, is_superuser=True)

        r_json = {
            'remote_conn_version': 1,
            'instances': [
                {
                    'uid': inst.uid,
                    'name': 'Updated',
                    'slug': inst.slug,
                    'units_of_measure': inst.units_of_measure,
                    'timezone': inst.timezone,
                    'users': {
                        'su@example.com': {
                            'name': 'SU',
                            'is_superuser': True,
                        },
                        # Any extra users should be ignored; they must come via invitations.
                        'owner@example.com': {'name': 'O', 'is_owner': True},
                    },
                }
            ],
        }
        resp = mock.Mock(status_code=200)
        resp.json.return_value = r_json

        with (
            mock.patch('simo.core.tasks.dynamic_settings', ds),
            mock.patch('simo.core.tasks.get_self_ip', return_value='1.2.3.4'),
            mock.patch('simo.core.tasks.uuid.getnode', return_value=0x1234),
            mock.patch('simo.core.tasks.pkg_resources.get_distribution', return_value=mock.Mock(version='9.9.9')),
            mock.patch('simo.core.tasks.requests.post', return_value=resp),
            mock.patch('builtins.print'),
        ):
            sync_with_remote()

        inst.refresh_from_db()
        self.assertEqual(inst.name, 'Updated')

        self.assertTrue(
            InstanceUser.objects.filter(
                user__email='su@example.com',
                role=role_superuser,
                is_active=True,
            ).exists()
        )
        self.assertFalse(
            InstanceUser.objects.filter(user__email='owner@example.com').exists()
        )

        from simo.users.models import User

        su = User.objects.get(email='su@example.com')
        self.assertTrue(su.is_master)
        self.assertFalse(User.objects.filter(email='owner@example.com').exists())

    def test_sync_with_remote_bootstrap_ignores_system_users(self):
        from simo.core.tasks import sync_with_remote

        ds = {
            'core__hub_uid': 'hub-uid',
            'core__hub_secret': 'hub-secret',
            'core__remote_conn_version': 1,
        }

        # System users must not block bootstrap.
        mk_user(settings.SYSTEM_USERS[0], 'Internal')

        inst = mk_instance('inst-a', 'A')
        role_owner = mk_role(inst, is_owner=True)

        resp = mock.Mock(status_code=200)
        resp.json.return_value = {
            'remote_conn_version': 1,
            'instances': [
                {
                    'uid': inst.uid,
                    'name': inst.name,
                    'slug': inst.slug,
                    'units_of_measure': inst.units_of_measure,
                    'timezone': inst.timezone,
                    'users': {
                        'first@example.com': {'name': 'First', 'is_owner': True},
                    },
                }
            ],
        }

        with (
            mock.patch('simo.core.tasks.dynamic_settings', ds),
            mock.patch('simo.core.tasks.get_self_ip', return_value='1.2.3.4'),
            mock.patch('simo.core.tasks.requests.post', return_value=resp),
            mock.patch('builtins.print'),
        ):
            sync_with_remote()

        from simo.users.models import User

        self.assertTrue(User.objects.filter(email='first@example.com', is_master=True).exists())
        self.assertTrue(
            InstanceUser.objects.filter(
                user__email='first@example.com',
                role=role_owner,
                is_active=True,
            ).exists()
        )

    def test_sync_with_remote_updates_user_name_and_avatar(self):
        from simo.core.tasks import sync_with_remote

        ds = {
            'core__hub_uid': 'hub-uid',
            'core__hub_secret': 'hub-secret',
            'core__remote_conn_version': 1,
        }

        inst = mk_instance('inst-a', 'A')
        role = mk_role(inst, is_owner=True)
        existing = mk_user('u@example.com', 'Old')
        # Ensure instance has at least one InstanceUser so sync does not auto-create.
        mk_instance_user(existing, inst, role, is_active=True)

        avatar_url = 'https://example.com/avatar.png'
        r_json = {
            'remote_conn_version': 1,
            'instances': [
                {
                    'uid': inst.uid,
                    'name': inst.name,
                    'slug': inst.slug,
                    'units_of_measure': inst.units_of_measure,
                    'timezone': inst.timezone,
                    'users': {
                        existing.email: {
                            'name': 'New Name',
                            'avatar_url': avatar_url,
                        }
                    },
                }
            ],
        }
        resp = mock.Mock(status_code=200)
        resp.json.return_value = r_json

        avatar_resp = mock.Mock()
        avatar_resp.raise_for_status.return_value = None
        avatar_resp.iter_content.return_value = [b'hello']

        fixed_now = timezone.make_aware(datetime.datetime(2025, 1, 1, 0, 0, 0))
        with (
            mock.patch('simo.core.tasks.dynamic_settings', ds),
            mock.patch('simo.core.tasks.get_self_ip', return_value='1.2.3.4'),
            mock.patch('simo.core.tasks.uuid.getnode', return_value=0x1234),
            mock.patch('simo.core.tasks.pkg_resources.get_distribution', return_value=mock.Mock(version='9.9.9')),
            mock.patch('simo.core.tasks.requests.post', return_value=resp),
            mock.patch('simo.core.tasks.requests.get', return_value=avatar_resp),
            mock.patch.object(FieldFile, 'save', autospec=True) as ff_save,
            mock.patch('simo.core.tasks.timezone.now', return_value=fixed_now),
            mock.patch('builtins.print'),
        ):
            sync_with_remote()

        existing.refresh_from_db()
        self.assertEqual(existing.name, 'New Name')
        self.assertEqual(existing.avatar_url, avatar_url)
        self.assertEqual(existing.avatar_last_change, fixed_now)
        ff_save.assert_called()

    def test_sync_with_remote_ignores_request_timeout(self):
        from simo.core.tasks import sync_with_remote

        ds = {
            'core__hub_uid': 'hub-uid',
            'core__hub_secret': 'hub-secret',
            'core__remote_conn_version': 1,
        }

        with (
            mock.patch('simo.core.tasks.dynamic_settings', ds),
            mock.patch('simo.core.tasks.get_self_ip', return_value='1.2.3.4'),
            mock.patch('simo.core.tasks.requests.post', side_effect=requests.Timeout),
            mock.patch('builtins.print'),
        ):
            sync_with_remote()

        self.assertEqual(ds['core__hub_uid'], 'hub-uid')

    def test_sync_with_remote_ignores_bad_json(self):
        from simo.core.tasks import sync_with_remote

        ds = {
            'core__hub_uid': 'hub-uid',
            'core__hub_secret': 'hub-secret',
            'core__remote_conn_version': 1,
        }

        resp = mock.Mock(status_code=200)
        resp.json.side_effect = ValueError('bad json')

        with (
            mock.patch('simo.core.tasks.dynamic_settings', ds),
            mock.patch('simo.core.tasks.get_self_ip', return_value='1.2.3.4'),
            mock.patch('simo.core.tasks.requests.post', return_value=resp),
            mock.patch('builtins.print'),
        ):
            sync_with_remote()

        self.assertEqual(ds['core__hub_uid'], 'hub-uid')

    def test_sync_with_remote_ignores_malformed_user_payload(self):
        from simo.core.tasks import sync_with_remote

        ds = {
            'core__hub_uid': 'hub-uid',
            'core__hub_secret': 'hub-secret',
            'core__remote_conn_version': 1,
        }

        inst = mk_instance('inst-a', 'A')
        mk_role(inst, is_owner=True)

        resp = mock.Mock(status_code=200)
        resp.json.return_value = {
            'remote_conn_version': 1,
            'instances': [
                {
                    'uid': inst.uid,
                    'name': inst.name,
                    'slug': inst.slug,
                    'units_of_measure': inst.units_of_measure,
                    'timezone': inst.timezone,
                    'users': {
                        'u@example.com': {
                            # Missing 'name' should not crash.
                            'avatar_url': 'https://example.com/avatar.png'
                        }
                    },
                }
            ],
        }

        with (
            mock.patch('simo.core.tasks.dynamic_settings', ds),
            mock.patch('simo.core.tasks.get_self_ip', return_value='1.2.3.4'),
            mock.patch('simo.core.tasks.requests.post', return_value=resp),
            mock.patch('builtins.print'),
        ):
            sync_with_remote()
