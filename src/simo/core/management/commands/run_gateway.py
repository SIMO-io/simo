import multiprocessing
from django.core.management.base import BaseCommand
from simo.core.models import Gateway


class Command(BaseCommand):


    def add_arguments(self, parser):
        parser.add_argument(
            'gateway_id', nargs=1, type=int,
            help="Gateway ID"
        )

    def handle(self, *args, **options):
        gateway = Gateway.objects.get(pk=options['gateway_id'][0])
        if not hasattr(gateway, 'run'):
            return
        exit_event = multiprocessing.Event()
        try:
            gateway.run(exit_event)
        except KeyboardInterrupt:
            exit_event.set()

        print("\nBYE!")

