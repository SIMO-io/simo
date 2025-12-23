from unittest import mock

from django.conf import settings

from simo.users.auth_backends import SSOBackend
from simo.users.models import User, InstanceInvitation, InstanceUser

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role


class SSOBackendTests(BaseSimoTestCase):
    def test_system_user_emails_are_rejected(self):
        backend = SSOBackend()
        for email in settings.SYSTEM_USERS:
            self.assertIsNone(
                backend.authenticate(None, user_data={'email': email, 'name': 'X'})
            )

    def test_first_real_user_is_created_as_master(self):
        backend = SSOBackend()
        user = backend.authenticate(None, user_data={'email': 'first@example.com', 'name': 'First'})
        self.assertIsNotNone(user)
        user.refresh_from_db()
        self.assertTrue(user.is_master)

    def test_invitation_token_creates_user_and_assigns_role(self):
        inst = mk_instance('inst-a', 'A')
        role = mk_role(inst, is_default=True)
        inv = InstanceInvitation.objects.create(instance=inst, role=role, to_email='x@example.com')

        backend = SSOBackend()
        user = backend.authenticate(
            None,
            user_data={
                'email': 'invited@example.com',
                'name': 'Invited',
                'invitation_token': inv.token,
            },
        )
        self.assertIsNotNone(user)
        inv.refresh_from_db()
        self.assertEqual(inv.taken_by_id, user.id)
        self.assertTrue(InstanceUser.objects.filter(user=user, instance=inst, role=role).exists())

    def test_inactive_user_is_rejected(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        # No active roles => not active.
        backend = SSOBackend()
        self.assertIsNone(backend.authenticate(None, user_data={'email': user.email, 'name': 'U'}))

    def test_avatar_download_attempts_to_save(self):
        user = User.objects.create(email='u@example.com', name='U', is_master=True)
        backend = SSOBackend()

        fake_resp = mock.Mock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.iter_content.return_value = [b'123']

        with mock.patch('simo.users.auth_backends.requests.get', autospec=True, return_value=fake_resp), \
                mock.patch('django.db.models.fields.files.FieldFile.save', autospec=True) as save_avatar:
            res = backend.authenticate(
                None,
                user_data={
                    'email': user.email,
                    'name': 'U',
                    'avatar_url': 'https://example.com/a.jpg',
                },
            )
        self.assertIsNotNone(res)
        self.assertTrue(save_avatar.called)
