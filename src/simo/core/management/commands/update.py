from django.core.management.base import BaseCommand
from simo.core.tasks import update


class Command(BaseCommand):

    def handle(self, *args, **options):
        update()
