import threading
import time
import json
import paho.mqtt.client as mqtt
from django.conf import settings
from django.db import close_old_connections
from abc import ABC, abstractmethod
from simo.core.utils.helpers import classproperty
from simo.core.events import GatewayObjectCommand, get_event_obj
from simo.core.loggers import get_gw_logger




class BaseGatewayHandler(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """
        :return: name of this gateway decriptor
        """

    @property
    @abstractmethod
    def config_form(self):
        """
        :return: Config form of this gateway class
        """

    @classproperty
    @classmethod
    def uid(cls):
        return ".".join([cls.__module__, cls.__name__])

    def __init__(self, gateway_instance):
        self.gateway_instance = gateway_instance
        super().__init__()
        assert self.name, "Gateway needs a name"
        assert self.config_form, "Gateway needs config_form"



class BaseObjectCommandsGatewayHandler(BaseGatewayHandler):
    periodic_tasks = ()

    exit = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.username_pw_set('root', settings.SECRET_KEY)
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message


    def run(self, exit):
        self.exit = exit
        self.logger = get_gw_logger(self.gateway_instance.id)

        for task, period in self.periodic_tasks:
            threading.Thread(
                target=self._run_periodic_task, args=(self.exit, task, period), daemon=True
            ).start()

        self.mqtt_client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)
        self.mqtt_client.loop_start()

        while not self.exit.is_set():
            time.sleep(1)

        self.mqtt_client.loop_stop()

    def _run_periodic_task(self, exit, task, period):
        while not exit.is_set():
            try:
                #print(f"Run periodic task {task}!")
                getattr(self, task)()
            except Exception as e:
                self.logger.error(e, exc_info=True)
            time.sleep(period)

    def _on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        print("MQTT Connected!")
        self.mqtt_client = mqtt_client
        command = GatewayObjectCommand(self.gateway_instance)
        self.mqtt_client.subscribe(command.get_topic())

    def _on_mqtt_message(self, client, userdata, msg):
        from simo.core.models import Component
        payload = json.loads(msg.payload)
        if 'set_val' in payload:
            component = get_event_obj(payload, Component)
            if not component:
                return
            print(f"Perform Value ({str(payload['set_val'])}) Send to {component}")
            try:
                self.perform_value_send(component, payload['set_val'])
            except Exception as e:
                self.logger.error(e, exc_info=True)

        if 'bulk_send' in payload:
            self.perform_bulk_send(payload['bulk_send'])

    def perform_value_send(self, component, value):
        raise NotImplemented()

    def perform_bulk_send(self, data):
        from simo.core.models import Component
        for comp_id, val in data.items():
            component = Component.objects.filter(
                pk=comp_id, gateway=self.gateway_instance
            ).first()
            if not component:
                continue
            try:
                self.perform_value_send(component, val)
            except Exception as e:
                self.logger.error(e, exc_info=True)


