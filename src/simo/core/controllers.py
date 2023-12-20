import time
import datetime
import statistics
import threading
from decimal import Decimal as D
from abc import ABC, ABCMeta, abstractmethod
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from simo.users.middleware import introduce, get_current_user
from simo.users.utils import get_device_user
from .utils.helpers import is_hex_color, classproperty
from .gateways import BaseGatewayHandler
from .app_widgets import *
from .forms import (
    BaseComponentForm, NumericSensorForm,
    MultiSensorConfigForm, DoubleSwitchConfigForm,
    TrippleSwitchConfigForm, QuadrupleSwitchConfigForm,
    QuintupleSwitchConfigForm, DimmerConfigForm, DimmerPlusConfigForm,
    RGBWConfigForm
)
from .events import ObjectCommand, ObjectManagementEvent

BEFORE_SEND = 'before-send'
BEFORE_SET = 'before-set'


class ControllerBase(ABC):
    config_form = BaseComponentForm
    admin_widget_template = 'admin/controller_widgets/generic.html'
    default_config = {}
    default_meta = {}

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
            "base_type must be defined in BASE_TYPES"

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
        if self.component.change_init_by:
            if self.component.change_init_date < timezone.now() - datetime.timedelta(seconds=5):
                self.component.change_init_by = None
                self.component.change_init_date = None
                self.component.change_init_to = None
                self.component.save(
                    update_fields=['change_init_by', 'change_init_date',
                                   'change_init_to', 'alive']
                )
                return None
            if self.component.change_init_to == to_value:
                return self.component.change_init_by

    def set(self, value, actor=None):
        from .models import ComponentHistory
        if not actor:
            actor = self._get_actor(value)
        if not actor:
            actor = get_current_user()
        # Introducing user to this thread for changes that might happen to other components
        # in relation to the change of this component
        introduce(actor)

        value = self.component.translate_before_set(value)
        value = self._validate_val(value, BEFORE_SET)
        self.component.refresh_from_db()
        old_arm_status = self.component.arm_status
        if value != self.component.value:
            self.component.value_previous = self.component.value
        self.component.value = value
        self.component.change_init_by = None
        self.component.change_init_date = None
        self.component.change_init_to = None
        self.component.save()

    def _send_to_device(self, value):
        ObjectCommand(self.component, **{'set_val': value}).publish()

    def _receive_from_device(self, value, is_alive=True):
        value = self._prepare_for_set(value)
        actor = self._get_actor(value)
        if not actor:
            actor = get_device_user()
        # Introducing user to this thread for changes that might happen to other components
        # in relation to the change of this component
        introduce(actor)
        self.component.alive = is_alive
        self.component.save(update_fields=['alive'])
        self.set(value, actor)

    def _prepare_for_send(self, value):
        return value

    def _prepare_for_set(self, value):
        return value

    def _val_to_success(self, value):
        """
        Override this if component receives different value
        on successful execution.

        For example script component only accepts 'start' and 'stop' values,
        but once that is in effect component value changes to
        'running', 'stopped', 'finished' or 'error'
        """
        return value

    def send(self, value):
        self.component.refresh_from_db()
        value = self.component.translate_before_send(value)
        value = self._validate_val(value, BEFORE_SEND)
        value = self._prepare_for_send(value)
        success_value = self._val_to_success(value)
        if success_value == self.component.value:
            return
        self.component.change_init_by = get_current_user()
        self.component.change_init_date = timezone.now()
        self.component.change_init_to = success_value
        self.component.save(
            update_fields=['change_init_by', 'change_init_date', 'change_init_to']
        )
        self._send_to_device(value)
        if success_value != self.component.value:
            self.component.value_previous = self.component.value
            self.component.value = success_value

    def history_display(self, values):
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

    def history_display(self, values):
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


class Dimmer(ControllerBase, TimerMixin):
    name = _("Dimmer")
    base_type = 'dimmer'
    app_widget = KnobWidget
    config_form = DimmerConfigForm
    admin_widget_template = 'admin/controller_widgets/knob.html'
    default_config = {'min': 0.0, 'max': 100.0, 'inverse': False}
    default_value = 0

    def _validate_val(self, value, occasion=None):
        if value > self.component.config.get('max', 1.0):
            raise ValidationError("Value to big.")
        elif value < self.component.config.get('min', 0.0):
            raise ValidationError("Value to small.")
        return value

    def turn_off(self):
        self.send(self.component.config.get('min', 0.0))

    def turn_on(self):
        if not self.component.value:
            if self.component.value_previous:
                self.send(self.component.value_previous)
            else:
                self.send(self.component.config.get('max', 1.0))

    def toggle(self):
        if self.component.value:
            self.turn_off()
        else:
            self.turn_on()


class DimmerPlus(ControllerBase, TimerMixin):
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
        if self.component.value:
            self.turn_off()
        else:
            self.turn_on()


class RGBWLight(ControllerBase, TimerMixin):
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
            if not isinstance(value, bool):
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


class Switch(MultiSwitchBase, TimerMixin):
    name = _("Switch")
    base_type = 'switch'
    app_widget = SingleSwitchWidget
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
        def toggle_back():
            time.sleep(0.5)
            self.turn_off()
        threading.Thread(target=toggle_back).start()

    def _prepare_for_send(self, value):
        if self.component.config.get('inverse'):
            return not value
        return value

    def _prepare_for_set(self, value):
        if self.component.config.get('inverse'):
            return not value
        return value


class DoubleSwitch(MultiSwitchBase):
    name = _("Double Switch")
    base_type = 'switch-double'
    app_widget = DoubleSwitchWidget
    config_form = DoubleSwitchConfigForm
    default_value = [False, False]


class TripleSwitch(MultiSwitchBase):
    name = _("Triple Switch")
    base_type = 'switch-triple'
    app_widget = TripleSwitchWidget
    config_form = TrippleSwitchConfigForm
    default_value = [False, False, False]


class QuadrupleSwitch(MultiSwitchBase):
    name = _("Quadruple Switch")
    base_type = 'switch-quadruple'
    app_widget = QuadrupleSwitchWidget
    config_form = QuadrupleSwitchConfigForm
    default_value = [False, False, False, False]


class QuintupleSwitch(MultiSwitchBase):
    name = _("Quintuple Switch")
    base_type = 'switch-quintuple'
    app_widget = QuintupleSwitchWidget
    config_form = QuintupleSwitchConfigForm
    default_value = [False, False, False, False, False]


class Lock(Switch):
    name = _("Lock")
    base_type = 'lock'

    def lock(self):
        self.turn_on()

    def unlock(self):
        self.turn_off()
