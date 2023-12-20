import threading
import traceback
import time
import pytz
from django.utils import timezone
import paho.mqtt.client as mqtt
from django.conf import settings
from abc import ABC, abstractmethod
from simo.core.utils.helpers import classproperty
from simo.core.events import ObjectCommand, get_comp_set_val
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

    def run(self, exit):
        self.exit = exit
        self.logger = get_gw_logger(self.gateway_instance.id)

        for task, period in self.periodic_tasks:
            threading.Thread(
                target=self._run_periodic_task, args=(task, period), daemon=True
            ).start()

        mqtt_client = mqtt.Client()

        mqtt_client.on_connect = self._on_mqtt_connect
        mqtt_client.on_message = self._on_mqtt_message
        mqtt_client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)
        mqtt_client.loop_start()

        while not self.exit.is_set():
            time.sleep(1)

        mqtt_client.loop_stop()

    def _run_periodic_task(self, task, period):
        while not self.exit.is_set():
            try:
                print(f"Run periodic task {task}!")
                getattr(self, task)()
            except Exception as e:
                self.logger.error(e, exc_info=True)
            time.sleep(period)

    def _on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        print("MQTT Connected!")
        mqtt_client.subscribe(ObjectCommand.TOPIC)

    def _on_mqtt_message(self, client, userdata, msg):
        component, set_val = get_comp_set_val(msg, self.gateway_instance)
        if not component:
            return
        print("Perform Value Send!")
        self.perform_value_send(component, set_val)

    def perform_value_send(self, component, value):
        raise NotImplemented()

