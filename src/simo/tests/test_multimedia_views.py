from types import SimpleNamespace
from unittest import mock

from django.test import Client, RequestFactory, override_settings
from django.http import Http404
from django.core.files.uploadedfile import SimpleUploadedFile

from simo.multimedia.models import Sound

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class SoundAutocompleteTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.user = mk_user('u@example.com', 'U')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.user, self.inst, role, is_active=True)
        self.rf = RequestFactory()

    def test_autocomplete_requires_authentication(self):
        from simo.multimedia.views import SoundAutocomplete

        req = self.rf.get('/multimedia/autocomplete-sound/?q=x')
        req.user = SimpleNamespace(is_authenticated=False)
        view = SoundAutocomplete()
        view.request = req
        view.q = 'x'

        with self.assertRaises(Http404):
            view.get_queryset()

    @override_settings(IS_VIRTUAL=True)
    def test_autocomplete_returns_empty_for_virtual_hubs(self):
        from simo.multimedia.views import SoundAutocomplete

        Sound.objects.create(
            instance=self.inst,
            name='S1',
            duration=1,
            file=SimpleUploadedFile('s1.mp3', b'123', content_type='audio/mpeg'),
        )

        req = self.rf.get('/multimedia/autocomplete-sound/?q=s')
        req.user = self.user
        view = SoundAutocomplete()
        view.request = req
        view.q = 's'

        qs = view.get_queryset()
        self.assertEqual(qs.count(), 0)

    def test_autocomplete_filters_by_value_ids(self):
        from simo.multimedia.views import SoundAutocomplete

        s1 = Sound.objects.create(
            instance=self.inst,
            name='S1',
            duration=1,
            file=SimpleUploadedFile('s1.mp3', b'123', content_type='audio/mpeg'),
        )
        s2 = Sound.objects.create(
            instance=self.inst,
            name='S2',
            duration=1,
            file=SimpleUploadedFile('s2.mp3', b'456', content_type='audio/mpeg'),
        )
        other_inst = mk_instance('inst-b', 'B')
        Sound.objects.create(
            instance=other_inst,
            name='S3',
            duration=1,
            file=SimpleUploadedFile('s3.mp3', b'789', content_type='audio/mpeg'),
        )

        req = self.rf.get(f'/multimedia/autocomplete-sound/?value={s1.id},{s2.id}')
        req.user = self.user
        view = SoundAutocomplete()
        view.request = req
        view.q = ''

        with mock.patch('simo.multimedia.views.get_current_instance', autospec=True, return_value=self.inst):
            qs = view.get_queryset()
        self.assertEqual(list(qs.order_by('id').values_list('id', flat=True)), [s1.id, s2.id])

    def test_autocomplete_returns_empty_when_instance_is_missing(self):
        from simo.multimedia.views import SoundAutocomplete

        req = self.rf.get('/multimedia/autocomplete-sound/?q=x')
        req.user = self.user
        view = SoundAutocomplete()
        view.request = req
        view.q = 'x'

        with mock.patch('simo.multimedia.views.get_current_instance', autospec=True, return_value=None):
            qs = view.get_queryset()
        self.assertEqual(qs.count(), 0)

    def test_autocomplete_search_uses_search_queryset(self):
        from simo.multimedia.views import SoundAutocomplete

        Sound.objects.create(
            instance=self.inst,
            name='Beep',
            duration=1,
            file=SimpleUploadedFile('s1.mp3', b'123', content_type='audio/mpeg'),
        )

        req = self.rf.get('/multimedia/autocomplete-sound/?q=bee')
        req.user = self.user
        view = SoundAutocomplete()
        view.request = req
        view.q = 'bee'

        with (
            mock.patch('simo.multimedia.views.get_current_instance', autospec=True, return_value=self.inst),
            mock.patch('simo.multimedia.views.search_queryset', autospec=True) as search,
        ):
            search.side_effect = lambda qs, q, fields: qs.filter(name__icontains=q)
            qs = view.get_queryset()

        search.assert_called_once()
        self.assertEqual(qs.count(), 1)

    def test_autocomplete_without_value_or_query_returns_all_instance_sounds(self):
        from simo.multimedia.views import SoundAutocomplete

        s1 = Sound.objects.create(
            instance=self.inst,
            name='S1',
            duration=1,
            file=SimpleUploadedFile('s1.mp3', b'123', content_type='audio/mpeg'),
        )
        Sound.objects.create(
            instance=mk_instance('inst-b', 'B'),
            name='S2',
            duration=1,
            file=SimpleUploadedFile('s2.mp3', b'456', content_type='audio/mpeg'),
        )

        req = self.rf.get('/multimedia/autocomplete-sound/')
        req.user = self.user
        view = SoundAutocomplete()
        view.request = req
        view.q = ''

        with (
            mock.patch('simo.multimedia.views.get_current_instance', autospec=True, return_value=self.inst),
            mock.patch('simo.multimedia.views.search_queryset', autospec=True) as search,
        ):
            qs = view.get_queryset()

        search.assert_not_called()
        self.assertEqual(list(qs.values_list('id', flat=True)), [s1.id])


class SoundStreamTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')

    @override_settings(IS_VIRTUAL=True)
    def test_stream_returns_404_for_virtual_hubs(self):
        sound = Sound.objects.create(
            instance=self.inst,
            name='S1',
            duration=1,
            file=SimpleUploadedFile('s1.mp3', b'abcdef', content_type='audio/mpeg'),
        )

        client = Client()
        resp = client.get(f'/multimedia/sound-{sound.id}-stream/')
        self.assertEqual(resp.status_code, 404)

    def test_stream_open_ended_range_clamps_to_file_size(self):
        sound = Sound.objects.create(
            instance=self.inst,
            name='S1',
            duration=1,
            file=SimpleUploadedFile('s1.mp3', b'abcdef', content_type='audio/mpeg'),
        )

        client = Client()
        with mock.patch('builtins.print'):
            resp = client.get(f'/multimedia/sound-{sound.id}-stream/', HTTP_RANGE='bytes=2-')

        self.assertEqual(resp.status_code, 206)
        self.assertEqual(resp.headers.get('Content-Range'), 'bytes 2-5/6')

    def test_stream_range_limited_to_8mb_chunks(self):
        size = 9 * 1024 * 1024
        data = b'a' * size
        sound = Sound.objects.create(
            instance=self.inst,
            name='S1',
            duration=1,
            file=SimpleUploadedFile('s1.mp3', data, content_type='audio/mpeg'),
        )

        client = Client()
        with mock.patch('builtins.print'):
            resp = client.get(f'/multimedia/sound-{sound.id}-stream/', HTTP_RANGE='bytes=0-')

        self.assertEqual(resp.status_code, 206)
        # The stream caps each response to 8 MiB.
        self.assertEqual(resp.headers.get('Content-Range'), f'bytes 0-{8 * 1024 * 1024}/{size}')

    def test_stream_without_range_is_200_and_sets_accept_ranges(self):
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

    def test_file_iterator_reads_offsets_and_lengths(self):
        from simo.multimedia.views import file_iterator

        sound = Sound.objects.create(
            instance=self.inst,
            name='S1',
            duration=1,
            file=SimpleUploadedFile('s1.mp3', b'abcdef', content_type='audio/mpeg'),
        )

        out = b''.join(file_iterator(sound.file.path, chunk_size=2, offset=1, length=3))
        self.assertEqual(out, b'bcd')

        out = b''.join(file_iterator(sound.file.path, chunk_size=2, offset=4, length=None))
        self.assertEqual(out, b'ef')
