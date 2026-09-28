import time
import logging
import signal
import threading
import multiprocessing
import sys
import json
from django.db import close_old_connections, connection as db_connection
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from simo.core.utils.logs import StreamToLogger

import paho.mqtt.client as mqtt
from simo.core.events import GatewayObjectCommand, get_event_obj
from simo.core.models import Gateway
from simo.core.loggers import get_gw_logger
from simo.core.utils.mqtt import connect_with_retry, install_reconnect_handler
from simo.core.utils.processes import install_parent_death_signal


class GatewayRunHandler(multiprocessing.Process):
    gateway = None
    logger = None
    exit_event = None

    def __init__(self, gateway_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gateway_id = gateway_id
        self.exit_event = multiprocessing.Event()
        self.logger = get_gw_logger(self.gateway_id)

    def run(self):
        # Signal handlers are inherited by forked children.  A gateway worker
        # must not inherit the manager's graceful-stop handler: it needs to
        # die if Supervisor stops the process group or its parent disappears.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        install_parent_death_signal('simo.gw-manager')

        db_connection.connect()
        try:
            self.gateway = Gateway.objects.get(id=self.gateway_id)
        except RuntimeError:
            # raises RuntimeError: generator raised StopIteration occasionally
            # because of unknown reason. Simply try again.
            self.gateway = Gateway.objects.get(id=self.gateway_id)

        self.logger = get_gw_logger(self.gateway_id)

        sys.stdout = StreamToLogger(self.logger, logging.INFO)
        sys.stderr = StreamToLogger(self.logger, logging.ERROR)
        self.gateway.status = 'running'
        self.gateway.save(update_fields=['status'])

        if not self.gateway.handler or not hasattr(self.gateway.handler, 'run'):
            self.gateway.status = 'finished'
            self.gateway.save(update_fields=['status'])
            return
        print("------START-------")
        try:
            self.gateway.handler.run(exit=self.exit_event)
        except:
            print("------ERROR------")
            self.gateway.status = 'error'
            self.gateway.save(update_fields=['status'])
            raise
        else:
            if self.exit_event.is_set():
                print("------STOPPED-----")
                self.gateway.status = 'stopped'
                self.gateway.save(update_fields=['status'])
            else:
                print("------FINISH-----")
                self.gateway.status = 'finished'
                self.gateway.save(update_fields=['status'])

        db_connection.close()
        return sys.exit(0)

    def stop(self):
        self.exit_event.set()


class GatewaysManager:
    '''
        WARNING! Make sure you do not run multiple instances of this manager!
        Only one manager per system is allowed, otherwise very bad things will happen!
    '''
    def __init__(self):
        self.running = False
        self.mqtt_client = None
        self.exit_event = None
        self.running_gateways = {}
        self._gateway_lock = threading.Lock()
        self._stopping_gateways = set()
        self._shutting_down = False
        self._mqtt_loop_started = False

    def terminate_this(self, signal, frame):
        print("---------------------- Gateways Manager  STOP ALL! ------------------------")
        self.exit_event.set()

    def start(self, exit_event=None):
        if exit_event is None:
            self.exit_event = multiprocessing.Event()
        else:
            self.exit_event = exit_event
        # We assume that this is the only one GatewaysManager instance
        # therefore if there are any gateways that are currently in running state
        # it's only because previous manager did not terminate nicely and
        # these running gateways are actually not running.
        for s in Gateway.objects.filter(status='running'):
            s.status = 'stopped'
            s.save()

        # Terminate subprocesses on close of this program
        if 'test' not in sys.argv:
            signal.signal(signal.SIGINT, self.terminate_this)
            signal.signal(signal.SIGTERM, self.terminate_this)

        print("-------------Gateways Manager START!------------------")

        try:
            for gateway in Gateway.objects.all():
                if hasattr(gateway, 'run'):
                    self.start_gateway(gateway)

            self.mqtt_client = mqtt.Client()
            self.mqtt_client.username_pw_set('root', settings.SECRET_KEY)
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_message = self.on_mqtt_message
            try:
                self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)
            except Exception:
                pass

            install_reconnect_handler(
                self.mqtt_client,
                logger=logging.getLogger('simo.gw-manager'),
                stop_event=self.exit_event,
                description='Gateways Manager MQTT',
            )
            if not connect_with_retry(
                self.mqtt_client,
                logger=logging.getLogger('simo.gw-manager'),
                stop_event=self.exit_event,
                description='Gateways Manager MQTT',
            ):
                return

            self.mqtt_client.loop_start()
            self._mqtt_loop_started = True
            while not self.exit_event.wait(1):
                pass
        finally:
            self.shutdown()
        return sys.exit()

    @staticmethod
    def _join_workers(workers, timeout):
        """Join a group of workers without letting the timeout grow per worker."""
        deadline = time.monotonic() + timeout
        for worker in workers:
            if worker.pid is None or not worker.is_alive():
                continue
            worker.join(max(0, deadline - time.monotonic()))

    @staticmethod
    def _live_workers(workers):
        return [worker for worker in workers if worker.pid is not None and worker.is_alive()]

    def _reap_workers(self, workers):
        """Stop, reap, then escalate until no manager child can escape."""
        for worker in workers:
            if worker.pid is not None:
                worker.exit_event.set()

        self._join_workers(workers, timeout=5)
        workers = self._live_workers(workers)
        for worker in workers:
            worker.terminate()

        self._join_workers(workers, timeout=3)
        workers = self._live_workers(workers)
        for worker in workers:
            worker.kill()

        # Do not let the manager exit normally while a child still exists.
        # Supervisor's group kill remains the final backstop for a kernel-
        # uninterruptible process.
        for worker in self._live_workers(workers):
            worker.join()

    def shutdown(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        if self.exit_event is not None:
            self.exit_event.set()

        with self._gateway_lock:
            workers = list(self.running_gateways.values())
        self._reap_workers(workers)
        gateway_ids = [worker.gateway_id for worker in workers]
        if gateway_ids:
            try:
                Gateway.objects.filter(
                    id__in=gateway_ids, status='running'
                ).update(status='stopped')
            except Exception:
                logging.getLogger('simo.gw-manager').exception(
                    'Could not persist stopped status for gateway workers.'
                )
        with self._gateway_lock:
            self.running_gateways.clear()
            self._stopping_gateways.clear()

        if self.mqtt_client:
            if self._mqtt_loop_started:
                try:
                    self.mqtt_client.loop_stop()
                except Exception:
                    logging.getLogger('simo.gw-manager').exception(
                        'Could not stop Gateways Manager MQTT loop.'
                    )
            try:
                self.mqtt_client.disconnect()
            except Exception:
                logging.getLogger('simo.gw-manager').exception(
                    'Could not disconnect Gateways Manager MQTT client.'
                )
        close_old_connections()
        print("-------------Gateways Manager STOPPED.------------------")

    def on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        mqtt_client.subscribe(f'{GatewayObjectCommand.TOPIC}/#')

    def on_mqtt_message(self, client, userdata, msg):
        payload = json.loads(msg.payload)
        gateway = get_event_obj(payload, Gateway)
        if not gateway:
            return
        if payload.get('set_val') == 'start':
            self.start_gateway(gateway)
        elif payload.get('set_val') == 'stop':
            self.stop_gateway(gateway)

    def start_gateway(self, gateway):
        if self._shutting_down:
            return
        with self._gateway_lock:
            if gateway.id in self.running_gateways:
                if self.running_gateways[gateway.id].is_alive():
                    return
                self.running_gateways[gateway.id].join()
                self.running_gateways.pop(gateway.id)
            print("START %s Gateway" % str(gateway))
            worker = GatewayRunHandler(gateway.id)
            self.running_gateways[gateway.id] = worker
            worker.start()

    def stop_gateway(self, gateway):
        with self._gateway_lock:
            worker = self.running_gateways.get(gateway.id)
            if not worker:
                return
            if worker.exitcode is not None:
                worker.join()
                self.running_gateways.pop(gateway.id, None)
                return
            if gateway.id in self._stopping_gateways:
                return
            self._stopping_gateways.add(gateway.id)

        worker.logger.log(
                logging.INFO, "-------STOP!------"
        )
        worker.exit_event.set()
        # This is intentionally non-daemon.  It is responsible for reaping a
        # stopped worker even if the manager itself is simultaneously exiting.
        threading.Thread(
            target=self._stop_and_reap_gateway,
            args=[gateway.id, worker],
            name='stop-gateway-%s' % gateway.id,
        ).start()

    def _stop_and_reap_gateway(self, gateway_id, worker):
        self._reap_workers([worker])
        try:
            gw = Gateway.objects.get(id=gateway_id)
            gw.status = 'stopped'
            gw.save(update_fields=['status'])
        except Exception:
            logging.getLogger('simo.gw-manager').exception(
                'Could not persist stopped status for gateway %s.', gateway_id
            )
        finally:
            with self._gateway_lock:
                if self.running_gateways.get(gateway_id) is worker:
                    self.running_gateways.pop(gateway_id, None)
                self._stopping_gateways.discard(gateway_id)


class Command(BaseCommand):
    def handle(self, *args, **options):
        GatewaysManager().start()
