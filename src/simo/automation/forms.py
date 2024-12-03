import time
from django import forms
from django.forms import formset_factory
from django.utils.translation import gettext_lazy as _
from django.urls.base import get_script_prefix
from django.contrib.contenttypes.models import ContentType
from simo.core.forms import BaseComponentForm
from simo.core.models import Component
from simo.core.controllers import BEFORE_SET
from simo.core.widgets import PythonCode, LogOutputWidget
from dal import forward
from simo.core.utils.formsets import FormsetField
from simo.core.form_fields import (
    Select2ModelChoiceField,
    Select2ModelMultipleChoiceField
)


class ScriptConfigForm(BaseComponentForm):
    autostart = forms.BooleanField(
        initial=True, required=False,
        help_text="Start automatically on system boot."
    )
    keep_alive = forms.BooleanField(
        initial=True, required=False,
        help_text="Restart the script if it fails. "
    )
    assistant_request = forms.CharField(
        label="Request for AI assistant", required=False, max_length=1000,
        widget=forms.Textarea(
            attrs={'placeholder':
                    "Close the blind and turn on the main light "
                    "in my living room when it get's dark."
            }
        ),
        help_text="Clearly describe in your own words what kind of automation "
                  "you want to happen with this scenario script. <br>"
                  "The more defined, exact and clear is your description the more "
                  "accurate automation script SIMO.io AI assistanw will generate.<br>"
                  "Use component, zone and category id's for best accuracy. <br>"
                  "SIMO.io AI will re-generate your automation code and update it's description in Notes field "                  
                  "every time this field is changed and it might take up to 60s to do it. <br>"
                  "Actual script code can only be edited via SIMO.io Admin.",
    )
    code = forms.CharField(widget=PythonCode, required=False)
    log = forms.CharField(
        widget=forms.HiddenInput, required=False
    )

    app_exclude_fields = ('alarm_category', 'code', 'log')

    _ai_resp = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.basic_fields.extend(['autostart', 'keep_alive'])
        if self.instance.pk:
            prefix = get_script_prefix()
            if prefix == '/':
                prefix = ''
            if 'log' in self.fields:
                self.fields['log'].widget = LogOutputWidget(
                    prefix + '/ws/log/%d/%d/' % (
                        ContentType.objects.get_for_model(Component).id,
                        self.instance.id
                    )
                )

    @classmethod
    def get_admin_fieldsets(cls, request, obj=None):
        base_fields = (
            'id', 'gateway', 'base_type', 'name', 'icon', 'zone', 'category',
            'show_in_app', 'autostart', 'keep_alive',
            'assistant_request', 'notes', 'code', 'control', 'log'
        )

        fieldsets = [
            (_("Base settings"), {'fields': base_fields}),
            (_("History"), {
                'fields': ('history',),
                'classes': ('collapse',),
            }),
        ]
        return fieldsets


    def clean(self):
        if self.cleaned_data.get('assistant_request'):
            if self.instance.pk:
                org = Component.objects.get(pk=self.instance.pk)
                call_assistant = org.config.get('assistant_request') \
                                 != self.cleaned_data['assistant_request']
            else:
                call_assistant = True
            call_assistant = False
            if call_assistant:
                resp = self.instance.ai_assistant(
                    self.cleaned_data['assistant_request'],
                )
                if resp['status'] == 'success':
                    self._ai_resp = resp
                elif resp['status'] == 'error':
                    self.add_error('assistant_request', resp['result'])

        return self.cleaned_data

    def save(self, commit=True):
        if commit and self._ai_resp:
            self.instance.config['code'] = self._ai_resp['result']
            self.instance.notes = self._ai_resp['description']
            if 'code' in self.cleaned_data:
                self.cleaned_data['code'] = self._ai_resp['result']
            if 'notes' in self.cleaned_data:
                self.cleaned_data['notes'] = self._ai_resp['description']
        return super().save(commit)


class ConditionForm(forms.Form):
    component = Select2ModelChoiceField(
        queryset=Component.objects.all(),
        url='autocomplete-component',
    )
    op = forms.ChoiceField(
        initial="==", choices=(
            ('==', "is equal to"),
            ('>', "is greather than"), ('>=', "Is greather or equal to"),
            ('<', "is lower than"), ('<=', "is lower or equal to"),
            ('in', "is one of")
        )
    )
    value = forms.CharField()
    prefix = 'breach_events'

    def clean(self):
        if not self.cleaned_data.get('component'):
            return self.cleaned_data
        if not self.cleaned_data.get('op'):
            return self.cleaned_data
        component = self.cleaned_data.get('component')

        if self.cleaned_data['op'] == 'in':
            self.cleaned_data['value'] = self.cleaned_data['value']\
                .strip('(').strip('[').rstrip(')').rstrip(']').strip()
            values = self.cleaned_data['value'].split(',')
        else:
            values = [self.cleaned_data['value']]

        final_values = []
        controller_val_type = type(component.controller.default_value)
        for val in values:
            val = val.strip()
            if controller_val_type == bool:
                if val.lower() in ('0', 'false', 'none', 'null', 'off'):
                    final_val = False
                else:
                    final_val = True
            else:
                try:
                    final_val = controller_val_type(val)
                except:
                    self.add_error(
                        'value', f"{val} bad value type for selected component."
                    )
                    continue
            try:
                component.controller._validate_val(final_val, BEFORE_SET)
            except Exception as e:
                self.add_error(
                    'value', f"{val} is not compatible with selected component."
                )
                continue

            if final_val == True:
                final_val = 'ON'
            elif final_val == False:
                final_val = 'OFF'

            final_values.append(final_val)

        if self.cleaned_data['op'] == 'in':
            self.cleaned_data['value'] = ', '.join(str(v) for v in final_values)
        elif final_values:
            self.cleaned_data['value'] = final_values[0]

        return self.cleaned_data


class LightTurnOnForm(forms.Form):
    light = Select2ModelChoiceField(
        queryset=Component.objects.filter(
            base_type__in=('switch', 'dimmer', 'rgbw-light', 'rgb-light')
        ),
        required=True,
        url='autocomplete-component',
        forward=(
            forward.Const(['switch', 'dimmer', 'rgbw-light', 'rgb-light'],
                          'base_type'),
        )
    )
    on_value = forms.IntegerField(
        min_value=0, initial=100,
        help_text="Value applicable for dimmers. "
                  "Switches will receive turn on command."
    )
    off_value = forms.TypedChoiceField(
        coerce=int, initial=1, choices=(
            (0, "0"), (1, "Original value before turning the light on.")
        )
    )


class PresenceLightingConfigForm(BaseComponentForm):
    presence_sensors = Select2ModelMultipleChoiceField(
        queryset=Component.objects.filter(
            base_type__in=('binary-sensor', 'switch')
        ),
        required=True,
        url='autocomplete-component',
        forward=(forward.Const(['binary-sensor', 'switch'], 'base_type'),)
    )
    act_on = forms.TypedChoiceField(
        coerce=int, initial=0, choices=(
            (0, "At least one sensor detects presence"),
            (1, "All sensors detect presence"),
        )
    )
    hold_time = forms.TypedChoiceField(
        initial=3, coerce=int, required=False, choices=(
            (0, '----'),
            (1, "10 s"), (2, "20 s"), (3, "30 s"), (4, "40 s"), (5, "50 s"),
            (6, "1 min"), (9, "1.5 min"), (12, "2 min"), (18, "3 min"),
            (30, "5 min"), (60, "10 min"), (120, "20 min"), (180, "30 min"),
            (3600, "1 h")
        ),
        help_text="Hold off time after last presence detector is deactivated."
    )
    conditions = FormsetField(
        formset_factory(
            ConditionForm, can_delete=True, can_order=True, extra=0
        ), label='Additional conditions'
    )

    lights = FormsetField(
        formset_factory(
            LightTurnOnForm, can_delete=True, can_order=True, extra=0
        ), label='Lights'
    )


    autostart = forms.BooleanField(
        initial=True, required=False,
        help_text="Start automatically on system boot."
    )
    keep_alive = forms.BooleanField(
        initial=True, required=False,
        help_text="Restart the script if it fails. "
    )
    log = forms.CharField(
        widget=forms.HiddenInput, required=False
    )

    app_exclude_fields = ('alarm_category', 'code', 'log')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.basic_fields.extend(
            ['lights', 'on_value', 'off_value', 'presence_sensors',
             'act_on', 'hold_time', 'conditions', 'autostart', 'keep_alive']
        )
        if self.instance.pk and 'log' in self.fields:
            prefix = get_script_prefix()
            if prefix == '/':
                prefix = ''
            self.fields['log'].widget = LogOutputWidget(
                prefix + '/ws/log/%d/%d/' % (
                    ContentType.objects.get_for_model(Component).id,
                    self.instance.id
                )
            )