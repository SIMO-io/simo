from unittest import mock

from django.test import Client

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class CoreAdminActionViewsTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.master = mk_user('m@example.com', 'M', is_master=True)
        # Master users become active via roles; give one role.
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.master, self.inst, role, is_active=True)
        from simo.users.models import User

        self.master = User.objects.get(pk=self.master.pk)

    def test_upgrade_requires_master_and_calls_task(self):
        client = Client()
        client.force_login(self.master)
        with mock.patch('simo.core.views.update_task.delay', autospec=True) as delay:
            resp = client.post('/core/upgrade/', follow=False)
        self.assertEqual(resp.status_code, 302)
        delay.assert_called_once()

    def test_restart_requires_master_and_calls_task(self):
        client = Client()
        client.force_login(self.master)
        with mock.patch('simo.core.views.supervisor_restart.delay', autospec=True) as delay:
            resp = client.post('/core/restart/', follow=False)
        self.assertEqual(resp.status_code, 302)
        delay.assert_called_once()

    def test_reboot_requires_master_and_calls_task(self):
        client = Client()
        client.force_login(self.master)
        with mock.patch('simo.core.views.hardware_reboot.delay', autospec=True) as delay:
            resp = client.post('/core/reboot/', follow=False)
        self.assertEqual(resp.status_code, 302)
        delay.assert_called_once()


class CoreDeleteInstanceViewTests(BaseSimoTestCase):
    def test_delete_instance_forbidden_for_non_master(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)
        from simo.users.models import User

        user = User.objects.get(pk=user.pk)

        client = Client()
        client.force_login(user)
        resp = client.post('/core/delete-instance/', data={'uid': inst.uid})
        self.assertEqual(resp.status_code, 403)

    def test_delete_instance_deletes_by_uid_for_master(self):
        inst = mk_instance('inst-a', 'A')
        master = mk_user('m@example.com', 'M', is_master=True)
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(master, inst, role, is_active=True)
        from simo.users.models import User
        from simo.core.models import Instance

        master = User.objects.get(pk=master.pk)

        client = Client()
        client.force_login(master)
        resp = client.post('/core/delete-instance/', data={'uid': inst.uid})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Instance.objects.filter(uid=inst.uid).exists())

