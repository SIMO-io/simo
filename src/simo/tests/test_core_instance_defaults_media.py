from simo.core.models import Instance, Category

from .base import BaseSimoTestCase


class TestInstanceDefaultsMedia(BaseSimoTestCase):
    def test_default_category_images_are_instance_scoped(self):
        inst = Instance.objects.create(uid='inst-defaults', name='Inst', slug='inst')

        images = list(
            Category.objects.filter(instance=inst)
            .exclude(header_image='')
            .values_list('header_image', flat=True)
        )
        self.assertTrue(images)
        for rel in images:
            self.assertTrue(rel.startswith(f"instances/{inst.uid}/categories/"))

