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
    running = False
    mqtt_client = None
    exit_event = None
    running_gateways = {}

    def terminate_this(self, signal, frame):
        print("---------------------- Gateways Manager  STOP ALL! ------------------------")
        self.exit_event.set()

    def start(self, exit_event=None):
        if not exit_event:
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
            # SIGTERM can not be used here as it's being caught by this
            # when main process sends SIGTERM signal to any child process.
            # signal.signal(signal.SIGTERM, self.terminate_this)

        print("-------------Gateways Manager START!------------------")

        for gateway in Gateway.objects.all():
            if hasattr(gateway, 'run'):
                self.start_gateway(gateway)

        self.mqtt_client = mqtt.Client()
        self.mqtt_client.username_pw_set('root', settings.SECRET_KEY)
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message
        self.mqtt_client.connect(
            host=settings.MQTT_HOST, port=settings.MQTT_PORT
        )

        while not self.exit_event.is_set():
            self.mqtt_client.loop()

        ids_to_stop = [id for id in self.running_gateways.keys()]
        for id in ids_to_stop:
            self.stop_gateway(Gateway(id=id))
        while self.running_gateways.keys():
            time.sleep(0.3)
        close_old_connections()
        print("-------------Gateways Manager STOPPED.------------------")
        return sys.exit()

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
        if gateway.id in self.running_gateways:
            if self.running_gateways[gateway.id].is_alive():
                return
            # self.running_gateways[gateway.id].join()
        print("START %s Gateway" % str(gateway))
        self.running_gateways[gateway.id] = GatewayRunHandler(gateway.id)
        self.running_gateways[gateway.id].start()

    def stop_gateway(self, gateway):
        if gateway.id not in self.running_gateways:
            return
        if self.running_gateways[gateway.id].exitcode is None:
            self.running_gateways[gateway.id].logger.log(
                logging.INFO, "-------STOP!------"
            )
            self.running_gateways[gateway.id].exit_event.set()
            threading.Thread(
                target=self.bury, args=[gateway.id], daemon=True
            ).start()
        else:
            self.running_gateways.pop(gateway.id)

    def bury(self, gateway_id):
        wait_seconds = 5
        while wait_seconds >= 0:
            if not self.running_gateways[gateway_id].is_alive():
                self.running_gateways.pop(gateway_id)
                return
            time.sleep(1)
            wait_seconds -= 1

        logger = get_gw_logger(gateway_id)
        logger.log(logging.ERROR, "------KILLED-----")
        self.running_gateways[gateway_id].kill()
        gw = Gateway.objects.get(id=gateway_id)
        gw.status = 'stopped'
        gw.save()
        self.running_gateways.pop(gateway_id)


class Command(BaseCommand):
    def handle(self, *args, **options):
        GatewaysManager().start()
