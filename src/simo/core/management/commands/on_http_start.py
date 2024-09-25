from django.core.management.base import BaseCommand

class Command(BaseCommand):


    def handle(self, *args, **options):
        from simo.management.on_http_start import *