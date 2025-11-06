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
from simo.users.utils import introduce_user, get_current_user, get_device_user
from .utils.helpers import is_hex_color, classproperty
# from django.utils.functional import classproperty
from .gateways import BaseGatewayHandler
from .base_types import (
    BaseComponentType,
    NumericSensorType, MultiSensorType, BinarySensorType, ButtonType,
    DimmerType, DimmerPlusType, RGBWLightType, SwitchType,
    DoubleSwitchType, TripleSwitchType, QuadrupleSwitchType, QuintupleSwitchType,
    LockType, BlindsType, GateType
)
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


class ControllerMeta(ABCMeta):
    """Metaclass that normalizes class-level access to `base_type`.

    If a controller sets `base_type` to a BaseComponentType subclass,
    accessing `Controller.base_type` returns the slug string to preserve
    legacy comparisons. Assignment remains the class.
    """
    def __getattribute__(cls, name):
        val = super().__getattribute__(name)
        if name == 'base_type':
            if isinstance(val, str):
                return val
            if isinstance(val, type) and issubclass(val, BaseComponentType):
                return val.slug
        return val


class ControllerBase(ABC, metaclass=ControllerMeta):
    config_form = BaseComponentForm
    admin_widget_template = 'admin/controller_widgets/generic.html'
    default_config = {}
    default_meta = {}
    default_value_units = None
    discovery_msg = None
    manual_add = True # Can be added manually
    family = None
    masters_only = False # component can be created/modified by hub masters only
    info_template_path = None
    accepts_value = True

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
    def base_type(self):
        """Base type identifier. Accepts either a slug string (legacy)
        or a BaseComponentType subclass (preferred).
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
        # Normalize to slug whether base_type is a string or a BaseComponentType subclass
        bt = getattr(self.__class__, 'base_type', None)
        # ControllerMeta makes class attribute access return slug when
        # a BaseComponentType subclass is assigned to base_type.
        # So `bt` should already be a slug string in most cases.
        if isinstance(bt, str):
            slug = bt
        elif isinstance(bt, type) and issubclass(bt, BaseComponentType):
            slug = bt.slug
        else:
            slug = getattr(bt, 'slug', None)
        assert slug in ALL_BASE_TYPES, f"{slug} must be defined in BASE TYPES!"

    # --- Dynamic Config Hooks -------------------------------------------------
    def _get_dynamic_config_fields(self):
        """Return extra Django form fields to render on config forms.

        Forms that inherit from ConfigFieldsMixin will call this method on the
        controller during form initialization. Any fields returned here are
        added to the form but are NOT automatically persisted into
        `component.config` by the mixin. This allows controllers to expose
        driver- or gateway-specific settings alongside regular component fields.

        Expected return format:
        - dict[str, django.forms.Field]
          Mapping of field name to an instantiated Django form Field.

        Notes:
        - Keep this method fast and side-effect free; it may be called multiple
          times in admin.
        - Use unique, namespaced field names to avoid collisions.
        - If no dynamic fields are needed, return an empty dict (default).
        """
        return {}

    def _apply_dynamic_config(self, cleaned_data):
        """Handle persistence of dynamic fields added by this controller.

        After the form is saved, ConfigFieldsMixin will call this hook with the
        form's `cleaned_data`. Use it to:
        - Write dynamic field values into `component.config` under your own
          namespace, and/or
        - Send configuration updates to the underlying device via the gateway.

        Parameters:
        - cleaned_data (dict): The form's cleaned_data; read values for any
          keys you returned from `_get_dynamic_config_fields()`.

        Guidelines:
        - Be tolerant to missing keys (partial forms) and swallow exceptions if
          best-effort behavior is desired; the mixin ignores errors.
        - Avoid long blocking operations; if needed, consider background tasks.
        - This base implementation is a no-op.
        """
        return None

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
            cls, '_init_discovery'
        )

    @classmethod
    def info(cls, component=None):
        '''
        Override this to give users help on how to use this component type,
        after you do that, include any component instance specific information
        if you see it necessary.
        :return: Markdown component info on how to set it up and use it
        along with any other relative information,
         regarding this particular component instance
        '''
        if not cls.info_template_path:
            cls.info_template_path = f"{cls.__module__.split('.')[-2]}/" \
                                      f"controllers_info/{cls.__name__}.md"
        try:
            return render_to_string(
                cls.info_template_path, {
                    'component': component
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
        vals = []
        for val in v.split(','):
            val = val.strip()
            if val.lower() in ('none', 'null'):
                val = None
            elif val_type == bool:
                if val.lower() in ('0', 'false', 'off'):
                    val = False
                else:
                    val = True
            else:
                try:
                    val = val_type(val)
                except:
                    continue
            vals.append(val)
        return vals

    def send(self, value):
        """Send a value/command to the device via the gateway.

        Prefer controller-specific helpers (e.g., `turn_on()`, `open()`) when
        available. This performs validation, publishes to the gateway, and
        updates the component value when appropriate.
        """
        from .models import Component
        try:
            self.component.refresh_from_db()
        except Component.DoesNotExist:
            return


        # Bulk send if it is a switch or dimmer and has slaves
        if self.component.base_type in ('switch', 'dimmer') \
        and self.component.slaves.count():
            bulk_send_map = {self.component: value}
            for slave in self.component.slaves.all():
                bulk_send_map[slave] = value

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
        # Optional translation hook defined in component custom methods
        try:
            from django.template.loader import render_to_string as _r2s
            cm = getattr(self.component, 'custom_methods', '') or ''
            code = cm.strip() or _r2s('core/custom_methods.py')
            namespace = {}
            exec(code, namespace)
            val_translate = namespace.get('translate')
            if callable(val_translate):
                value = val_translate(value, BEFORE_SEND)
        except Exception:
            pass

        self._send_to_device(value)
        if value != self.component.value:
            self.component.value_previous = self.component.value
            self.component.value = value

    def set(self, value, actor=None, alive=None, error_msg=None):
        """Set the component value locally and record history.

        This is called by `send()` after the device confirms or when device
        reports a new value. Do not call from clients directly; prefer
        controller action methods or `send()`.

        Parameters:
        - value: JSON-serializable value after translation/validation for this type.
        - actor: Optional user that initiated the change.
        """
        from simo.users.models import InstanceUser
        try:
            from django.template.loader import render_to_string as _r2s
            cm = getattr(self.component, 'custom_methods', '') or ''
            code = cm.strip() or _r2s('core/custom_methods.py')
            namespace = {}
            exec(code, namespace)
            val_translate = namespace.get('translate')
            if callable(val_translate):
                value = val_translate(value, BEFORE_SET)
        except Exception:
            pass
        value = self._validate_val(value, BEFORE_SET)

        if not actor:
            actor = self._get_actor(value)
        if not actor:
            actor = get_current_user()

        self.component.refresh_from_db()
        if value != self.component.value and self.component.track_history:
            self.component.value_previous = self.component.value
            from .models import ComponentHistory
            ComponentHistory.objects.create(
                component=self.component, type='value', value=value,
                user=actor, alive=self.component.alive
            )
            from actstream import action
            action.send(
                actor, target=self.component, verb="value change",
                instance_id=self.component.zone.instance.id,
                action_type='comp_value', value=value
            )
            actor.last_action = timezone.now()
            actor.save()
        self.component.value = value
        self.component.change_init_by = None
        self.component.change_init_date = None
        self.component.change_init_to = None
        self.component.change_init_fingerprint = None
        if alive is not None:
            self.component.alive = alive
        if error_msg is not None:
            self.component.error_msg = error_msg
        self.component.change_actor = InstanceUser.objects.filter(
            instance=self.component.zone.instance,
            user=actor
        ).first()
        self.component.save()

    def _send_to_device(self, value):
        GatewayObjectCommand(
            self.component.gateway, self.component, set_val=value
        ).publish()

    def _receive_from_device(
        self, value, is_alive=True, battery_level=None, error_msg=None
    ):
        value = self._prepare_for_set(value)
        actor = self._get_actor(value)

        init_by_device = False
        if not actor:
            init_by_device = True
            actor = get_device_user()

        self.component.alive = is_alive
        if error_msg != None and not is_alive:
            self.component.error_msg = error_msg if error_msg.strip() else None
        else:
            self.component.error_msg = None
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
        """Best-effort wake-up: quickly toggle output to nudge the device.

        Some gateways/devices can recover from a brief toggle. This flips
        the state on subsequent calls to stimulate a response.
        """
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
        """Schedule a controller action at a specific UNIX timestamp.

        Parameters:
        - to_timestamp (float|int): Absolute UNIX epoch seconds in the future.
        - event (str|None): Optional controller method name to invoke when the
          timer elapses. Defaults to 'toggle' if not provided or invalid.

        Behavior:
        - Stores timer metadata in component.meta and persists it. The gateway or
          background tasks are expected to call the method when due.

        Raises:
        - ValidationError: if `to_timestamp` is not in the future.
        """
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
        """Pause a running timer.

        Stores the remaining time and clears the scheduled timestamp.

        Raises:
        - ValidationError: if no timer is currently scheduled.
        """
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
        """Resume a previously paused timer.

        Recomputes the target timestamp from the saved remaining time.

        Raises:
        - ValidationError: if the timer is not in a paused state.
        """
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
        """Stop and clear any active or paused timer for this component."""
        self.component.meta['timer_to'] = 0
        self.component.meta['timer_left'] = 0
        self.component.meta['timer_start'] = 0
        self.component.save(update_fields=['meta'])

    def timer_engaged(self):
        """Return True if there is an active or paused timer configured."""
        return any([
            self.component.meta.get('timer_to'),
            self.component.meta.get('timer_left'),
            self.component.meta.get('timer_start')
        ])

    def _on_timer_end(self):
        getattr(self, self.component.meta['timer_event'])()


class NumericSensor(ControllerBase):
    name = _("Numeric sensor")
    base_type = NumericSensorType
    config_form = NumericSensorForm
    default_value = 0
    accepts_value = False

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
    base_type = MultiSensorType
    app_widget = MultiSensorWidget
    config_form = MultiSensorConfigForm
    default_value = [
        ["Value 1", 20, "%"],
        ["Value 2", 50, "ᴼ C"],
        ["Value 3", False, ""]
    ]
    accepts_value = False

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


    def get_val(self, param):
        """Return value for a given label in a multi-sensor array.

        Parameters:
        - param (str): The label/name of the vector to read.
        Returns: The value part from [label, value, unit] or None.
        """
        for item in self.component.value:
            if item[0] == param:
                return item[1]


class BinarySensor(ControllerBase):
    name = _("Binary sensor")
    base_type = BinarySensorType
    app_widget = BinarySensorWidget
    admin_widget_template = 'admin/controller_widgets/binary_sensor.html'
    default_value = False
    accepts_value = False

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
    base_type = ButtonType
    app_widget = ButtonWidget
    admin_widget_template = 'admin/controller_widgets/button.html'
    default_value = 'up'

    def _validate_val(self, value, occasion=None):
        if value not in (
            'down', 'up', 'hold',
            'click', 'double-click', 'triple-click', 'quadruple-click', 'quintuple-click'
        ):
            raise ValidationError("Bad button value!")
        return value

    def send(self, value):
        """Simulate a button event.

        Parameters:
        - value (str): One of 'down', 'up', 'hold', 'click', 'double-click'.
        """
        return super().send(value)

    def is_down(self):
        """Return True while the button is pressed ('down' or 'hold')."""
        return self.component.value in ('down', 'hold')

    def is_held(self):
        """Return True if the button is currently in 'hold' state."""
        return self.component.value == 'hold'

    def get_bonded_gear(self):
        """Return components configured to be controlled by this button.

        Scans other components' config for controls referencing this button's id.
        Returns: list[Component]
        """
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
        """Best-effort wake-up: briefly toggle output to stimulate response."""
        if self._poke_toggle:
            self._poke_toggle = False
            self.turn_on()
        else:
            self._poke_toggle = True
            self.turn_off()


class Dimmer(ControllerBase, TimerMixin, OnOffPokerMixin):
    name = _("Dimmer")
    base_type = DimmerType
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
        """Turn output to the configured minimum level (usually 0%)."""
        self.send(self.component.config.get('min', 0.0))

    def turn_on(self):
        """Turn output on, restoring the last level when possible.

        If there is a previous level, restores it; otherwise uses configured
        maximum level.
        """
        self.component.refresh_from_db()
        if not self.component.value:
            if self.component.value_previous:
                self.send(self.component.value_previous)
            else:
                self.send(self.component.config.get('max', 90))

    def max_out(self):
        """Set output to the configured maximum level."""
        self.send(self.component.config.get('max', 90))

    def output_percent(self, value):
        """Set output by percentage (0–100).

        Parameters:
        - value (int|float): Percentage of configured [min, max] range.
        """
        min = self.component.config.get('min', 0)
        max = self.component.config.get('max', 100)
        delta = max - min
        self.send(min + delta * value / 100)

    def toggle(self):
        """Toggle output: turn off if non-zero, otherwise turn on."""
        self.component.refresh_from_db()
        if self.component.value:
            self.turn_off()
        else:
            self.turn_on()

    def fade_up(self):
        """Start increasing brightness smoothly (if supported by gateway)."""
        raise NotImplemented()

    def fade_down(self):
        """Start decreasing brightness smoothly (if supported by gateway)."""
        raise NotImplemented()

    def fade_stop(self):
        """Stop any ongoing fade operation (if supported by gateway)."""
        raise NotImplemented()

    def send(self, value):
        """Set dimmer level.

        Parameters:
        - value (int|float): absolute level within configured min/max, or
        - value (bool): True to restore previous/non-zero level, False for 0.
        """
        return super().send(value)


class DimmerPlus(ControllerBase, TimerMixin, OnOffPokerMixin):
    name = _("Dimmer Plus")
    base_type = DimmerPlusType
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
        """Turn both channels to their configured minimums."""
        self.send(
            {
                'main': self.component.config.get('main_min', 0.0),
                'secondary': self.component.config.get('secondary_min', 0.0),
            }

        )

    def turn_on(self):
        """Turn on: main at maximum, secondary to mid-range."""
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
        """Toggle on/off based on the 'main' channel state."""
        if self.component.value.get('main'):
            self.turn_off()
        else:
            self.turn_on()


    def fade_up(self):
        """Start increasing brightness smoothly (if supported by gateway)."""
        raise NotImplemented()

    def fade_down(self):
        """Start decreasing brightness smoothly (if supported by gateway)."""
        raise NotImplemented()

    def fade_stop(self):
        """Stop any ongoing fade operation (if supported by gateway)."""
        raise NotImplemented()

    def send(self, value):
        """Set Dimmer Plus channels.

        Parameters:
        - value (dict): {'main': number, 'secondary': number}, or
        - value (bool): True to restore previous, False to minimums.
        """
        return super().send(value)


class RGBWLight(ControllerBase, TimerMixin, OnOffPokerMixin):
    name = _("RGB(W) Light")
    base_type = RGBWLightType
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
        """Turn the light off (sets `is_on` to False and sends current value)."""
        self.component.refresh_from_db()
        self.component.value['is_on'] = False
        self.send(self.component.value)

    def turn_on(self):
        """Turn the light on (sets `is_on` to True and sends current value)."""
        self.component.refresh_from_db()
        self.component.value['is_on'] = True
        self.send(self.component.value)

    def toggle(self):
        """Toggle the light between on and off."""
        self.component.refresh_from_db()
        self.component.value['is_on'] = not self.component.value['is_on']
        self.send(self.component.value)


    def fade_up(self):
        raise NotImplemented()

    def fade_down(self):
        raise NotImplemented()

    def fade_stop(self):
        raise NotImplemented()

    def send(self, value):
        """Set RGB(W) light scenes and on/off.

        Parameters:
        - value (dict): {'scenes': ["#rrggbb[ww]"...], 'active': int 0-4,
                         'is_on': bool}
        """
        return super().send(value)


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

    def send(self, value):
        """Set one or multiple switch channels.

        Parameters:
        - value (bool) to set all channels, or
        - value (list[bool]) with a boolean per channel.
        """
        return super().send(value)


class Switch(MultiSwitchBase, TimerMixin, OnOffPokerMixin):
    name = _("Switch")
    base_type = SwitchType
    app_widget = SingleSwitchWidget
    config_form = SwitchForm
    admin_widget_template = 'admin/controller_widgets/switch.html'
    default_value = False

    def send(self, value):
        """Send value to device.
        If non boolean value is provided it is translated to a boolean one.

        Parameters:
        - value (bool): True = ON, False = OFF.
        """
        return super().send(value)

    def turn_on(self):
        """Turn the switch on (send True)."""
        if self.component.meta.get('pulse'):
            self.component.meta.pop('pulse')
            self.component.save()
        self.send(True)

    def turn_off(self):
        """Turn the switch off (send False)."""
        if self.component.meta.get('pulse'):
            self.component.meta.pop('pulse')
            self.component.save()
        self.send(False)

    def toggle(self):
        """Toggle the switch state based on current value."""
        if self.component.meta.get('pulse'):
            self.component.meta.pop('pulse')
            self.component.save()
        self.send(not self.component.value)

    def click(self):
        """Simulate a short press: turn on momentarily then off.

        This sends an on command and schedules an automatic off after ~1s.
        """
        if self.component.meta.get('pulse'):
            self.component.meta.pop('pulse')
            self.component.save()
        self.turn_on()
        from .tasks import component_action
        component_action.s(
            self.component.id, 'turn_off'
        ).apply_async(countdown=1)

    def pulse(self, frame_length_s, on_percentage):
        """Generate a PWM-like pulse train (only if gateway supports it).

        Parameters:
        - frame_length_s (float): Duration of a full on+off frame in seconds.
        - on_percentage (float|int): Duty cycle percentage (0–100) for on time.
        """
        self.component.meta['pulse'] = {
            'frame': frame_length_s, 'duty': on_percentage / 100
        }
        self.component.save()
        from simo.generic.gateways import GenericGatewayHandler
        from .models import Gateway
        generic_gateway = Gateway.objects.filter(
            type=GenericGatewayHandler.uid
        ).first()
        if generic_gateway:
            GatewayObjectCommand(
                generic_gateway, self.component,
                pulse=self.component.meta['pulse']
            ).publish()


class DoubleSwitch(MultiSwitchBase):
    name = _("Double Switch")
    base_type = DoubleSwitchType
    app_widget = DoubleSwitchWidget
    config_form = DoubleSwitchConfigForm
    default_value = [False, False]

    def _prepare_for_send(self, value):
        if isinstance(value, bool):
            return [value, value]
        return value


class TripleSwitch(MultiSwitchBase):
    name = _("Triple Switch")
    base_type = TripleSwitchType
    app_widget = TripleSwitchWidget
    config_form = TrippleSwitchConfigForm
    default_value = [False, False, False]

    def _prepare_for_send(self, value):
        if isinstance(value, bool):
            return [value, value, value]
        return value


class QuadrupleSwitch(MultiSwitchBase):
    name = _("Quadruple Switch")
    base_type = QuadrupleSwitchType
    app_widget = QuadrupleSwitchWidget
    config_form = QuadrupleSwitchConfigForm
    default_value = [False, False, False, False]

    def _prepare_for_send(self, value):
        if isinstance(value, bool):
            return [value, value, value, value]
        return value


class QuintupleSwitch(MultiSwitchBase):
    name = _("Quintuple Switch")
    base_type = QuintupleSwitchType
    app_widget = QuintupleSwitchWidget
    config_form = QuintupleSwitchConfigForm
    default_value = [False, False, False, False, False]

    def _prepare_for_send(self, value):
        if isinstance(value, bool):
            return [value, value, value, value, value]
        return value


class Lock(Switch):
    name = _("Lock")
    base_type = LockType
    app_widget = LockWidget
    admin_widget_template = 'admin/controller_widgets/lock.html'
    default_value = 'unlocked'

    UNLOCKED = 0
    LOCKED = 1
    LOCKING = 2
    UNLOCKING = 3
    FAULT = 4

    def lock(self):
        """Lock the device (equivalent to `turn_on()`)."""
        self.turn_on()

    def unlock(self):
        """Unlock the device (equivalent to `turn_off()`)."""
        self.turn_off()

    def send(self, value):
        """Lock/unlock.

        Parameters:
        - value (bool): True to lock; False to unlock.
        """
        return super().send(value)

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
    base_type = BlindsType
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
        """Open blinds fully.

        Sends {'target': 0} and preserves current angle if present.
        """
        send_val = {'target': 0}
        angle = self.component.value.get('angle')
        if angle is not None and 0 <= angle <= 180:
            send_val['angle'] = angle
        self.send(send_val)

    def close(self):
        """Close blinds fully.

        Sends {'target': open_duration_ms} and preserves current angle.
        """
        send_val = {'target': self.component.config['open_duration'] * 1000}
        angle = self.component.value.get('angle')
        if angle is not None and 0 <= angle <= 180:
            send_val['angle'] = angle
        self.send(send_val)

    def stop(self):
        """Stop blinds movement immediately.

        Sends {'target': -1} and preserves current angle.
        """
        send_val = {'target': -1}
        angle = self.component.value.get('angle')
        if angle is not None and 0 <= angle <= 180:
            send_val['angle'] = angle
        self.send(send_val)

    def send(self, value):
        """Control blinds position/angle.

        Parameters:
        - value (dict): {'target': milliseconds or -1 for stop,
                         'angle': optional 0-180}
        """
        return super().send(value)


class Gate(ControllerBase, TimerMixin):
    name = _("Gate")
    base_type = GateType
    app_widget = GateWidget
    admin_widget_template = 'admin/controller_widgets/gate.html'
    default_config = {
        'auto_open_distance': '150 m',
        'auto_open_for': [],
    }

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
        """Command the gate to open."""
        self.send('open')

    def close(self):
        """Command the gate to close."""
        self.send('close')

    def call(self):
        """Trigger the 'call' action (impulse) for gates in call-mode."""
        self.send('call')

    def send(self, value):
        """Control gate.

        Parameters:
        - value (str): 'open', 'close', or 'call' (depending on config).
        """
        return super().send(value)
