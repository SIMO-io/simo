from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from simo.multimedia.models import Sound
from simo.users.models import User

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class MultimediaSoundTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.user = mk_user('su@example.com', 'SU')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.user, self.inst, role, is_active=True)
        self.user = User.objects.get(pk=self.user.pk)

    def test_sounds_api_list_is_instance_scoped(self):
        Sound.objects.create(
            instance=self.inst,
            name='S1',
            duration=1,
            file=SimpleUploadedFile('s1.mp3', b'123', content_type='audio/mpeg'),
        )
        other_inst = mk_instance('inst-b', 'B')
        Sound.objects.create(
            instance=other_inst,
            name='S2',
            duration=1,
            file=SimpleUploadedFile('s2.mp3', b'456', content_type='audio/mpeg'),
        )

        api = APIClient()
        api.force_authenticate(user=self.user)
        resp = api.get(f'/api/{self.inst.slug}/multimedia/sounds/')
        self.assertEqual(resp.status_code, 200)
        names = [row['name'] for row in resp.json().get('results', [])]
        self.assertEqual(names, ['S1'])

    def test_sound_stream_serves_file_and_supports_ranges(self):
        sound = Sound.objects.create(
            instance=self.inst,
            name='S1',
            duration=1,
            file=SimpleUploadedFile('s1.mp3', b'abcdef', content_type='audio/mpeg'),
        )

        client = Client()
        resp = client.get(f'/multimedia/sound-{sound.id}-stream/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get('Accept-Ranges'), 'bytes')

        resp = client.get(f'/multimedia/sound-{sound.id}-stream/', HTTP_RANGE='bytes=0-1')
        self.assertEqual(resp.status_code, 206)
        self.assertIn('Content-Range', resp.headers)

