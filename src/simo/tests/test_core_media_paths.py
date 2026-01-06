from django.test import SimpleTestCase

from simo.core.media_paths import (
    INSTANCE_FILEFIELD_MAX_LENGTH,
    instance_categories_upload_to,
    instance_private_files_upload_to,
)


class _Obj:
    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            setattr(self, key, val)


class TestMediaPaths(SimpleTestCase):
    def test_instance_categories_upload_to_is_bounded(self):
        inst = _Obj(uid='u' * 50)
        cat = _Obj(pk=123, instance=inst)

        long_filename = ('a' * 400) + '.jpg'
        rel = instance_categories_upload_to(cat, long_filename)

        self.assertLessEqual(len(rel), INSTANCE_FILEFIELD_MAX_LENGTH)
        self.assertTrue(rel.startswith(f"instances/{inst.uid}/categories/"))
        self.assertTrue(rel.endswith('.jpg'))

    def test_instance_private_files_upload_to_is_bounded(self):
        inst = _Obj(uid='u' * 50)
        zone = _Obj(instance=inst)
        component = _Obj(pk=999, zone=zone)
        pf = _Obj(pk=555, component=component)

        long_filename = ('b' * 400) + '.pdf'
        rel = instance_private_files_upload_to(pf, long_filename)

        self.assertLessEqual(len(rel), INSTANCE_FILEFIELD_MAX_LENGTH)
        self.assertTrue(rel.startswith(f"instances/{inst.uid}/private_files/"))
        self.assertTrue(rel.endswith('.pdf'))

