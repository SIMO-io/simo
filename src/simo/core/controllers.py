import sys
import time
import datetime
import statistics
import threading
from decimal import Decimal as D
from abc import ABC, ABCMeta, abstractmethod
from django.utils.functional import cached_property
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from simo.users.middleware import introduce, get_current_user
from simo.users.utils import get_device_user
from .utils.helpers import is_hex_color, classproperty
# from django.utils.functional import classproperty
from .gateways import BaseGatewayHandler
from .app_widgets import *
from .forms import (
    BaseComponentForm, NumericSensorForm,
    MultiSensorConfigForm,
    SwitchForm, DoubleSwitchConfigForm,
    TrippleSwitchConfigForm, QuadrupleSwitchConfigForm,
    QuintupleSwitchConfigForm, DimmerConfigForm, DimmerPlusConfigForm,
    RGBWConfigForm
)
from .events import GatewayObjectCommand

BEFORE_SEND = 'before-send'
BEFORE_SET = 'before-set'


class ControllerBase(ABC):
    config_form = BaseComponentForm
    admin_widget_template = 'admin/controller_widgets/generic.html'
    default_config = {}
    default_meta = {}
    default_value_units = None
    discovery_msg = None
    manual_add = True # Can be added manually
    family = None
    masters_only = False # component can be created/modified by hub masters only

    @property
    @abstractmethod
    def name(self) -> str:
        """
        :return: name of this controller
        """

    @property
    @abstractmethod
    def gateway_class(self):
        """
        :return: Gateway class
        """

    @property
    @abstractmethod
    def base_type(self) -> str:
        """
        :return" base type name
        """

    @property
    @abstractmethod
    def app_widget(self):
        """
        :return: app widget class of this type
        """

    @property
    @abstractmethod
    def default_value(self):
        """
        :return: Default value of this base component type
        """

    @property
    def info_template_path(self) -> str:
        return f"{self.__class__.__module__.split('.')[-2]}/" \
               f"controllers_info/{self.__class__.__name__}.md"

    @abstractmethod
    def _validate_val(self, value, occasion=None):
        """
        raise ValidationError if value is not appropriate for this type
        """

    def __init__(self, component):
        from .utils.type_constants import ALL_BASE_TYPES
        from .models import Component
        assert isinstance(component, Component), \
            "Must be an instance of Component model"
        self.component = component
        assert issubclass(self.gateway_class, BaseGatewayHandler)
        assert issubclass(self.config_form, BaseComponentForm)
        assert issubclass(self.app_widget, BaseAppWidget)
        assert self.base_type in ALL_BASE_TYPES, \
            f"{self.base_type} must be defined in BASE_TYPES!"

    @classproperty
    @classmethod
    def uid(cls):
        return ".".join([cls.__module__, cls.__name__])

    @classproperty
    @classmethod
    def add_form(cls):
        """
        Override this if something different is needed for add form.
        """
        return cls.config_form

    @classproperty
    @classmethod
    def is_discoverable(cls):
        return hasattr(
            cls, 'init_discovery'
        ) and hasattr(
            cls, '_process_discovery'
        )

    def info(self):
        '''
        Override this to give users help on how to use this component type,
        after you do that, include any component instance specific information
        if you see it necessary.
        :return: Markdown component info on how to set it up and use it
        along with any other relative information,
         regarding this particular component instance
        '''
        try:
            return render_to_string(
                self.info_template_path, {
                    'component': self.component if hasattr(self, 'component') else None
                }
            )
        except:
            return

    def _aggregate_values(self, values):
        if type(values[0]) in (float, int):
            return [statistics.mean(values)]
        else:
            return [statistics.mode(values)]


    def _get_value_history(self, period):
        from .models import ComponentHistory
        entries = []
        qs = ComponentHistory.objects.filter(
            component=self.component, type='value'
        ).order_by('date')
        if period == 'day':
            last_val = None
            first_item = qs.filter(
                date__lte=timezone.now() - datetime.timedelta(hours=24)
            ).last()
            if first_item:
                last_val = first_item.value
            for i in range(24, 0, -1):
                h = timezone.now() - datetime.timedelta(hours=i)
                changes = qs.filter(
                    date__gt=h,
                    date__lt=h + datetime.timedelta(hours=1),
                )
                if not changes:
                    entries.append(self._aggregate_values([last_val]))
                    continue
                values = []
                current_change = 0
                for i in range(60):
                    if changes[current_change].date < h + datetime.timedelta(minutes=i):
                        last_val = changes[current_change].value
                        current_change += 1
                    values.append(last_val)
                entries.append(self._aggregate_values(values))
            return entries
        elif period == 'week':
            return entries
        elif period == 'month':
            return entries
        elif period == 'year':
            return entries
        return entries

    def _get_value_history_chart_metadata(self):
        return [
            {'label': _("Value"), 'style': 'line'}
        ]

    def _get_actor(self, to_value):
        if self.component.change_init_fingerprint and self.component.change_init_fingerprint.user:
            return self.component.change_init_fingerprint.user
        if self.component.change_init_by:
            if self.component.change_init_date < timezone.now() - datetime.timedelta(seconds=30):
                self.component.change_init_by = None
                self.component.change_init_date = None
                self.component.change_init_to = None
                self.component.save(
                    update_fields=['change_init_by', 'change_init_date',
                                   'change_init_to', 'alive']
                )
                return None
            else:
                return self.component.change_init_by

    def _string_to_vals(self, v):
        '''
        Convert a string containing list of values to approporiate list of component values
        :param v:
        :return:
        '''
        val_type = type(self.default_value)
        v = str(v).strip('(').strip('[').rstrip(')').rstrip(']')
        return [val_type(val.strip()) for val in v.split(',')]

    def send(self, value):
        self.component.refresh_from_db()

        # Bulk send if it is a switch or dimmer and has slaves
        if self.component.base_type in ('switch', 'dimmer') \
        and self.component.slaves.count():
            bulk_send_map = {self.component: value}
            for slave in self.component.slaves.all():
                bulk_send_map[slave] = value
            from .models import Component
            Component.objects.bulk_send(bulk_send_map)
            return

        # Regular send
        value = self._validate_val(value, BEFORE_SEND)

        self.component.change_init_by = get_current_user()
        self.component.change_init_date = timezone.now()
        self.component.save(
            update_fields=['change_init_by', 'change_init_date']
        )
        value = self._prepare_for_send(value)
        GatewayObjectCommand(
            self.component.gateway, self.component, set_val=value
        ).publish()
        if value != self.component.value:
            self.component.value_previous = self.component.value
            self.component.value = value

    def set(self, value, actor=None):
        value = self._validate_val(value, BEFORE_SET)

        if not actor:
            actor = self._get_actor(value)
        if not actor:
            actor = get_current_user()

        # Introducing user to this thread for changes that might happen to other components
        # in relation to the change of this component
        introduce(actor)

        self.component.refresh_from_db()
        if value != self.component.value:
            self.component.value_previous = self.component.value
        self.component.value = value

        self.component.change_init_by = None
        self.component.change_init_date = None
        self.component.change_init_to = None
        self.component.change_init_fingerprint = None
        self.component.save()

    def _receive_from_device(
        self, value, is_alive=True, battery_level=None, error_msg=None
    ):
        value = self._prepare_for_set(value)
        actor = self._get_actor(value)

        init_by_device = False
        if not actor:
            init_by_device = True
            actor = get_device_user()

        # Introducing user to this thread for changes that might happen to other components
        # in relation to the change of this component
        introduce(actor)
        self.component.alive = is_alive
        if error_msg != None:
            self.component.error_msg = error_msg if error_msg.strip() else None
        if battery_level:
            self.component.battery_level = battery_level
        self.component.save(update_fields=['alive', 'battery_level', 'error_msg'])
        self.set(value, actor)

        if init_by_device and self.component.slaves.count():
            slaves_qs = self.component.slaves.all()
            # slaves are being controlled by colonels internally
            if self.component.controller_uid.startswith('simo.fleet.') \
            and self.component.config.get('colonel'):
                slaves_qs = slaves_qs.exclude(
                    config__colonel=self.component.config['colonel']
                )
            bulk_send_map = {s: value for s in slaves_qs}
            from .models import Component
            Component.objects.bulk_send(bulk_send_map)

    def _history_display(self, values):
        assert type(values) in (list, tuple)

        if type(self.component.value) in (int, float):
            return [
                {'name': self.component.name, 'type': 'numeric',
                 'val': sum(values)/len(values) if values else None}
            ]
        elif type(self.component.value) == bool:
            if self.component.icon:
                icon = self.component.icon.slug
            else:
                icon = 'circle-dot'

            return [
                {'name': self.component.name, 'type': 'icon',
                 'val': icon if any(values) else None}
            ]

    def poke(self):
        '''Use this when component is dead to try and wake it up'''
        pass

    def _prepare_for_send(self, value):
        return value

    def _prepare_for_set(self, value):
        return value




class TimerMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert hasattr(self, 'toggle'), \
            "Controller must have toggle method defined to support timer mixin."

    def set_timer(self, to_timestamp, event=None):
        if to_timestamp > time.time():
            self.component.refresh_from_db()
            self.component.meta['timer_to'] = to_timestamp
            self.component.meta['timer_left'] = 0
            self.component.meta['timer_start'] = time.time()
            if event and hasattr(self.component, event):
                self.component.meta['timer_event'] = event
            else:
                self.component.meta['timer_event'] = 'toggle'
            self.component.save(update_fields=['meta'])
        else:
            raise ValidationError(
                "You must provide future timestamp. Got '%s' instead."
                % str(to_timestamp)
            )

    def pause_timer(self):
        if self.component.meta.get('timer_to', 0) > time.time():
            time_left = self.component.meta['timer_to'] - time.time()
            self.component.meta['timer_left'] = time_left
            self.component.meta['timer_to'] = 0
            self.component.save(update_fields=['meta'])
        else:
            raise ValidationError(
                "Timer is not set yet, so you can't pause it."
            )

    def resume_timer(self):
        if self.component.meta.get('timer_left', 0):
            self.component.meta['timer_to'] = \
                time.time() + self.component.meta['timer_left']
            self.component.meta['timer_left'] = 0
            self.component.save(update_fields=['meta'])
        else:
            raise ValidationError(
                "Timer is not in a paused state, so you can't resume it."
            )

    def stop_timer(self):
        self.component.meta['timer_to'] = 0
        self.component.meta['timer_left'] = 0
        self.component.meta['timer_start'] = 0
        self.component.save(update_fields=['meta'])

    def timer_engaged(self):
        return any([
            self.component.meta.get('timer_to'),
            self.component.meta.get('timer_left'),
            self.component.meta.get('timer_start')
        ])

    def _on_timer_end(self):
        getattr(self, self.component.meta['timer_event'])()


class NumericSensor(ControllerBase):
    name = _("Numeric sensor")
    base_type = 'numeric-sensor'
    config_form = NumericSensorForm
    default_value = 0

    def _validate_val(self, value, occasion=None):
        if type(value) not in (int, float, D):
            raise ValidationError(
                "Numeric sensor must have numeric value. "
                "type - %s; val - %s supplied instead." % (
                    str(type(value)), str(value)
                )
            )
        return value

    @property
    def app_widget(self):
        if self.component.config.get('widget') == 'numeric-sensor-graph':
            return NumericSensorGraphWidget
        else:
            return NumericSensorWidget


class MultiSensor(ControllerBase):
    name = _("Multi sensor")
    base_type = 'multi-sensor'
    app_widget = MultiSensorWidget
    config_form = MultiSensorConfigForm
    default_value = [
        ["Value 1", 20, "%"],
        ["Value 2", 50, "ᴼ C"],
        ["Value 3", False, ""]
    ]

    def _validate_val(self, value, occasion=None):
        if len(value) != len(self.default_value):
            raise ValidationError("Must have %d values not %d" % (
                len(self.default_value), len(value)
            ))
        for i, val in enumerate(value):
            if len(val) != 3:
                raise ValidationError(
                    "Must have 3 data items, not %d on value no: %d" % (
                    len(val), i
                ))
        return value

    def _history_display(self, values):
        assert type(values) in (list, tuple)

        vectors = []
        for i in range(len(self.component.value)):

            vals = [v[i][1] for v in values]

            if type(self.component.value[i][1]) in (int, float):
                vectors.append(
                    {'name': self.component.value[i][0], 'type': 'numeric',
                     'val': sum(vals)/len(vals) if vals else None}
                )
            elif type(self.component.value[i][1]) == bool:
                icon = 'circle-dot'

                return [
                    {'name': self.component.value[i][0], 'type': 'icon',
                     'val': icon if any(vals) else None}
                ]

        return vectors


class BinarySensor(ControllerBase):
    name = _("Binary sensor")
    base_type = 'binary-sensor'
    app_widget = BinarySensorWidget
    admin_widget_template = 'admin/controller_widgets/binary_sensor.html'
    default_value = False

    def _validate_val(self, value, occasion=None):
        if not isinstance(value, bool):
            raise ValidationError(
                "Binary sensor, must have boolean value. "
                "type - %s; val - %s supplied instead." % (
                    str(type(value)), str(value)
                )
            )
        return value


class Button(ControllerBase):
    name = _("Button")
    base_type = 'button'
    app_widget = ButtonWidget
    admin_widget_template = 'admin/controller_widgets/button.html'
    default_value = 'up'

    def _validate_val(self, value, occasion=None):
        if value not in ('down', 'up', 'hold', 'click', 'double-click'):
            raise ValidationError("Bad button value!")
        return value

    def is_down(self):
        return self.component.value in ('down', 'hold')

    def is_held(self):
        return self.component.value == 'hold'

    @cached_property
    def bonded_gear(self):
        from simo.core.models import Component
        gear = []
        for comp in Component.objects.filter(config__has_key='controls'):
            for ctrl in comp.config['controls']:
                if ctrl.get('button') == self.component.id:
                    gear.append(comp)
                    break
        return gear


class OnOffPokerMixin:
    _poke_toggle = False

    def poke(self):
        if self._poke_toggle:
            self._poke_toggle = False
            self.turn_on()
        else:
            self._poke_toggle = True
            self.turn_off()


class Dimmer(ControllerBase, TimerMixin, OnOffPokerMixin):
    name = _("Dimmer")
    base_type = 'dimmer'
    app_widget = KnobWidget
    config_form = DimmerConfigForm
    admin_widget_template = 'admin/controller_widgets/knob.html'
    default_config = {'min': 0.0, 'max': 100.0, 'inverse': False}
    default_value = 0
    default_value_units = '%'

    def _receive_from_device(self, value, *args, **kwargs):
        if isinstance(value, bool):
            if value:
                value = self.component.config.get('max', 100.0)
            else:
                value = self.component.config.get('min', 0)
        return super()._receive_from_device(value, *args, **kwargs)

    def _prepare_for_send(self, value):
        if isinstance(value, bool):
            if value:
                self.component.refresh_from_db()
                if self.component.value:
                    return self.component.value
                else:
                    if self.component.value_previous:
                        return self.component.value_previous
                    return self.component.config.get('max', 100.0)
            else:
                return 0
        return value

    def _validate_val(self, value, occasion=None):
        if value > self.component.config.get('max', 100.0):
            raise ValidationError("Value to big.")
        elif value < self.component.config.get('min', 0.0):
            raise ValidationError("Value to small.")
        return value

    def turn_off(self):
        self.send(self.component.config.get('min', 0.0))

    def turn_on(self):
        self.component.refresh_from_db()
        if not self.component.value:
            if self.component.value_previous:
                self.send(self.component.value_previous)
            else:
                self.send(self.component.config.get('max', 90))

    def toggle(self):
        self.component.refresh_from_db()
        if self.component.value:
            self.turn_off()
        else:
            self.turn_on()


class DimmerPlus(ControllerBase, TimerMixin, OnOffPokerMixin):
    name = _("Dimmer Plus")
    base_type = 'dimmer-plus'
    app_widget = KnobPlusWidget
    config_form = DimmerPlusConfigForm
    default_config = {
        'main_min': 0.0,
        'main_max': 1.0,
        'secondary_min': 0.0,
        'secondary_max': 1.0
    }
    default_value = {'main': 0.0, 'secondary': 0.0}

    def _validate_val(self, value, occasion=None):
        if not isinstance(value, dict) or (
            'main' not in value and 'secondary' not in value
        ):
            raise ValidationError(
                "Dictionary of {'main': number, 'secondary': number} expected. "
                "got %s (%s) instead" % (str(value), type(value))
            )

        if 'main' in value:
            if value['main'] > self.component.config.get('main_max', 1.0):
                raise ValidationError("Main value is to big.")
            if value['main'] < self.component.config.get('main_min', 0.0):
                raise ValidationError("Main value is to small.")

        if 'secondary' in value:
            if value['secondary'] > self.component.config.get('secondary_max', 1.0):
                raise ValidationError("Secondary value is to big.")
            if value['secondary'] < self.component.config.get('secondary_min', 0.0):
                raise ValidationError("Secondary value to small.")

        if 'main' not in value:
            self.component.refresh_from_db()
            try:
                value['main'] = self.component.value.get('main')
            except:
                value['main'] = self.component.config.get('main_min', 0.0)
        if 'secondary' not in value:
            self.component.refresh_from_db()
            try:
                value['secondary'] = self.component.value.get('secondary')
            except:
                middle = (self.component.config.get('secondary_max', 1.0) -
                          self.component.config.get('secondary_min', 1.0)) / 2
                value['secondary'] = middle

        return value

    def turn_off(self):
        self.send(
            {
                'main': self.component.config.get('main_min', 0.0),
                'secondary': self.component.config.get('secondary_min', 0.0),
            }

        )

    def turn_on(self):
        self.component.refresh_from_db()
        if not self.component.value:
            if self.component.value_previous:
                self.send(self.component.value_previous)
            else:
                middle = (self.component.config.get('secondary_max', 1.0) -
                         self.component.config.get('secondary_min', 1.0)) / 2
                self.send({
                    'main': self.component.config.get('main_max', 1.0),
                    'secondary': middle,
                })

    def toggle(self):
        if self.component.value.get('main'):
            self.turn_off()
        else:
            self.turn_on()


class RGBWLight(ControllerBase, TimerMixin, OnOffPokerMixin):
    name = _("RGB(W) Light")
    base_type = 'rgbw-light'
    app_widget = RGBWidget
    config_form = RGBWConfigForm
    admin_widget_template = 'admin/controller_widgets/rgb.html'
    default_config = {'has_white': False}

    @property
    def default_value(self):

        if self.component.config.get('has_white'):
            return {
                'scenes': [
                    '#ff000000', '#4b97f300', '#ebff0000', '#00ff1400',
                    '#d600ff00'
                ], 'active': 0, 'is_on': False
            }
        else:
            return {
                'scenes': [
                    '#ff0000', '#4b97f3', '#ebff00', '#00ff14', '#d600ff'
                ], 'active': 0, 'is_on': False
            }

    def _validate_val(self, value, occasion=None):
        assert 0 <= value['active'] <= 4
        assert isinstance(value['is_on'], bool)
        if 'scenes' not in value:
            value['scenes'] = self.component.value['scenes']
        for color in value['scenes']:
            if not is_hex_color(color):
                raise ValidationError("Bad color value!")
            if self.component.config.get('has_white'):
                if len(color) != 9:
                    raise ValidationError("Bad color value!")
            else:
                if len(color) != 7:
                    raise ValidationError("Bad color value!")

        return value

    def turn_off(self):
        self.component.refresh_from_db()
        self.component.value['is_on'] = False
        self.send(self.component.value)

    def turn_on(self):
        self.component.refresh_from_db()
        self.component.value['is_on'] = True
        self.send(self.component.value)

    def toggle(self):
        self.component.refresh_from_db()
        self.component.value['is_on'] = not self.component.value['is_on']
        self.send(self.component.value)


class MultiSwitchBase(ControllerBase):

    def _validate_val(self, value, occasion=None):
        number_of_values = 1
        if isinstance(self.default_value, list) \
        or isinstance(self.default_value, tuple):
            number_of_values = len(self.default_value)
        if not(0 < number_of_values < 16):
            raise ValidationError("Wrong number of values")
        if number_of_values == 1:
            if isinstance(value, int):
                value = bool(value)
            elif not isinstance(value, bool):
                raise ValidationError("Must be a boolean value")
        else:
            if not isinstance(value, list):
                raise ValidationError("Must be a list of values")
            if len(value) != number_of_values:
                raise ValidationError(
                    "Must have %d values" % number_of_values
                )
            for i, v in enumerate(value):
                if not isinstance(v, bool):
                    raise ValidationError(
                        'Boolean values expected, but got %s in position %d' % (
                        str(type(v)), i
                    ))
        return value


class Switch(MultiSwitchBase, TimerMixin, OnOffPokerMixin):
    name = _("Switch")
    base_type = 'switch'
    app_widget = SingleSwitchWidget
    config_form = SwitchForm
    admin_widget_template = 'admin/controller_widgets/switch.html'
    default_value = False

    def turn_on(self):
        self.send(True)

    def turn_off(self):
        self.send(False)

    def toggle(self):
        self.send(not self.component.value)

    def click(self):
        '''
        Gateway specific implementation is very welcome of this!
        '''
        self.turn_on()
        time.sleep(0.5)
        self.turn_off()


class DoubleSwitch(MultiSwitchBase):
    name = _("Double Switch")
    base_type = 'switch-double'
    app_widget = DoubleSwitchWidget
    config_form = DoubleSwitchConfigForm
    default_value = [False, False]

    def _prepare_for_send(self, value):
        if isinstance(value, bool):
            return [value, value]
        return value


class TripleSwitch(MultiSwitchBase):
    name = _("Triple Switch")
    base_type = 'switch-triple'
    app_widget = TripleSwitchWidget
    config_form = TrippleSwitchConfigForm
    default_value = [False, False, False]

    def _prepare_for_send(self, value):
        if isinstance(value, bool):
            return [value, value, value]
        return value


class QuadrupleSwitch(MultiSwitchBase):
    name = _("Quadruple Switch")
    base_type = 'switch-quadruple'
    app_widget = QuadrupleSwitchWidget
    config_form = QuadrupleSwitchConfigForm
    default_value = [False, False, False, False]

    def _prepare_for_send(self, value):
        if isinstance(value, bool):
            return [value, value, value, value]
        return value


class QuintupleSwitch(MultiSwitchBase):
    name = _("Quintuple Switch")
    base_type = 'switch-quintuple'
    app_widget = QuintupleSwitchWidget
    config_form = QuintupleSwitchConfigForm
    default_value = [False, False, False, False, False]

    def _prepare_for_send(self, value):
        if isinstance(value, bool):
            return [value, value, value, value, value]
        return value


class Lock(Switch):
    name = _("Lock")
    base_type = 'lock'
    app_widget = LockWidget
    admin_widget_template = 'admin/controller_widgets/lock.html'
    default_value = 'unlocked'

    UNLOCKED = 0
    LOCKED = 1
    LOCKING = 2
    UNLOCKING = 3
    FAULT = 4

    def lock(self):
        self.turn_on()

    def unlock(self):
        self.turn_off()

    def _receive_from_device(
        self, value, *args, **kwargs
    ):
        if type(value) == bool:
            if value:
                value = 'locked'
            else:
                value = 'unlocked'
        if type(value) == int:
            values_map = {
                self.UNLOCKED: 'unlocked',
                self.LOCKED: 'locked',
                self.LOCKING: 'locking',
                self.UNLOCKING: 'unlocking',
                self.FAULT: 'fault'
            }
            value = values_map.get(value, 'fault')
        return super()._receive_from_device(
            value, *args, **kwargs
        )

    def _validate_val(self, value, occasion=None):
        if occasion == BEFORE_SEND:
            if type(value) != bool:
                raise ValidationError("Boolean required to lock/unlock.")
        else:
            available_values = (
                'locked', 'unlocked', 'locking', 'unlocking',
                'operating', 'fault'
            )
            if value not in available_values:
                raise ValidationError(
                    f"Received value ({value}) that is not "
                    f"one of available values [{available_values}] for lock."
                )
        return value

    def set(self, value, actor=None):
        super().set(value, actor=actor)
        if actor and value in ('locking', 'unlocking'):
            self.component.change_init_by = actor
            self.component.change_init_date = timezone.now()
            self.component.save(
                update_fields=['change_init_by', 'change_init_date']
            )


class Blinds(ControllerBase, TimerMixin):
    name = _("Blind")
    base_type = 'blinds'
    admin_widget_template = 'admin/controller_widgets/blinds.html'
    default_config = {}

    @property
    def app_widget(self):
        if self.component.config.get('control_mode') == 'slide':
            return SlidesWidget
        else:
            return BlindsWidget

    @property
    def default_value(self):
        # target and current positions in milliseconds, angle in degrees (0 - 180)
        return {'target': 0, 'position': 0, 'angle': 0}

    def _validate_val(self, value, occasion=None):

        if occasion == BEFORE_SEND:
            if isinstance(value, int) or isinstance(value, float):
                # legacy support
                value = {'target': int(value)}
            if 'target' not in value:
                raise ValidationError("Target value is required!")
            target = value.get('target')
            if type(target) not in (float, int):
                raise ValidationError(
                    "Bad target position for blinds to go."
                )
            if target > self.component.config.get('open_duration') * 1000:
                raise ValidationError(
                    "Target value lower than %d expected, "
                    "%d received instead" % (
                        self.component.config['open_duration'] * 1000,
                        target
                    )
                )
            if 'angle' in value:
                try:
                    angle = int(value['angle'])
                except:
                    raise ValidationError(
                        "Integer between 0 - 180 is required for blinds angle."
                    )
                if angle < 0 or angle > 180:
                    raise ValidationError(
                        "Integer between 0 - 180 is required for blinds angle."
                    )
            else:
                value['angle'] = self.component.value.get('angle', 0)

        elif occasion == BEFORE_SET:
            if not isinstance(value, dict):
                raise ValidationError("Dictionary is expected")
            for key, val in value.items():
                if key not in ('target', 'position', 'angle'):
                    raise ValidationError(
                        "'target', 'position' or 'angle' parameters are expected."
                    )
                if key == 'position':
                    if val < 0:
                        raise ValidationError(
                            "Positive integer expected for blind position"
                        )
                    if val > self.component.config.get('open_duration') * 1000:
                        raise ValidationError(
                            "Positive value is to big. Must be lower than %d, "
                            "but you have provided %d" % (
                                self.component.config.get('open_duration') * 1000, val
                            )
                        )

            self.component.refresh_from_db()
            if 'target' not in value:
                value['target'] = self.component.value.get('target')
            if 'position' not in value:
                value['position'] = self.component.value.get('position')
            if 'angle' not in value:
                value['angle'] = self.component.value.get('angle')

        return value

    def open(self):
        send_val = {'target': 0}
        angle = self.component.value.get('angle')
        if angle is not None and 0 <= angle <= 180:
            send_val['angle'] = angle
        self.send(send_val)

    def close(self):
        send_val = {'target': self.component.config['open_duration'] * 1000}
        angle = self.component.value.get('angle')
        if angle is not None and 0 <= angle <= 180:
            send_val['angle'] = angle
        self.send(send_val)

    def stop(self):
        send_val = {'target': -1}
        angle = self.component.value.get('angle')
        if angle is not None and 0 <= angle <= 180:
            send_val['angle'] = angle
        self.send(send_val)


class Gate(ControllerBase, TimerMixin):
    name = _("Gate")
    base_type = 'gate'
    app_widget = GateWidget
    admin_widget_template = 'admin/controller_widgets/gate.html'
    default_config = {}

    @property
    def default_value(self):
        return 'closed'

    def _validate_val(self, value, occasion=None):
        if occasion == BEFORE_SEND:
            if self.component.config.get('action_method') == 'click':
                if value != 'call':
                    raise ValidationError(
                        'Gate component understands only one command: '
                        '"call". You have provided: "%s"' % (str(value))
                    )
            else:
                if value not in ('call', 'open', 'close'):
                    raise ValidationError(
                        'This gate component understands only 3 commands: '
                        '"open", "close" and "call". You have provided: "%s"' %
                        (str(value))
                    )
        elif occasion == BEFORE_SET and value not in (
            'closed', 'open', 'open_moving', 'closed_moving'
        ):
            raise ValidationError(
                'Gate component can only be in 4 states:  '
                '"closed", "closed", "open_moving", "closed_moving". '
                'You have provided: "%s"' % (str(value))
            )
        return value

    def open(self):
        self.send('open')

    def close(self):
        self.send('close')

    def call(self):
        self.send('call')