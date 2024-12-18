import copy
import json
import six
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django import forms
from django.conf import settings
from dal import autocomplete


class LazyChoicesMixin:

    _choices = ()

    @property
    def choices(self):
        if callable(self._choices):
            return self._choices()
        return self._choices

    @choices.setter
    def choices(self, value):
        self._choices = value

    def __deepcopy__(self, memo):
        obj = copy.copy(self)
        obj.attrs = self.attrs.copy()
        if not callable(self._choices):
            obj._choices = copy.copy(self._choices)
        memo[id(self)] = obj
        return obj

    def optgroups(self, name, value, attrs=None):
        if len(value) == 2:
            for (val, display) in self.choices:
                if val == value[0]:
                    self.choices = [(val, display)]
                    break
        return super().optgroups(name, value, attrs)


class ListSelect2(LazyChoicesMixin, autocomplete.ListSelect2):
    pass


class Select2Multiple(LazyChoicesMixin, autocomplete.Select2Multiple):
    pass


class Select2ListMixin:

    def __init__(self, url, forward=None, *args, **kwargs):
        self.url = url
        self.forward = []
        if forward:
            self.forward = [fw.to_dict() for fw in forward]

        widget = ListSelect2(
            url=url, forward=forward, attrs={'data-html': True},

        )
        widget.choices = kwargs.get('choices', None)

        super().__init__(widget=widget, *args, **kwargs)

class Select2ModelChoiceField(Select2ListMixin, forms.ModelChoiceField):
    pass


class Select2ListChoiceField(Select2ListMixin, forms.ChoiceField):
    pass


class Select2MultipleMixin:

    def __init__(self, url=None, forward=None, *args, **kwargs):
        self.url = url
        self.forward = []
        if forward:
            self.forward = [fw.to_dict() for fw in forward]

        widget = Select2Multiple(
            url=url, forward=forward, attrs={'data-html': True}
        )
        widget.choices = kwargs.pop('choices', [])

        super().__init__(widget=widget, *args, **kwargs)


class Select2ModelMultipleChoiceField(
    Select2MultipleMixin, forms.ModelMultipleChoiceField
):
    pass


class Select2ListMultipleChoiceField(
    Select2MultipleMixin, forms.MultipleChoiceField
):
    pass


class LocationWidget(forms.widgets.TextInput):
    def __init__(self, **kwargs):
        attrs = kwargs.pop('attrs', None)

        self.options = dict(settings.LOCATION_FIELD)
        self.options['map.zoom'] = kwargs.get('zoom')
        self.options['field_options'] = {
            'based_fields': kwargs.pop('based_fields')
        }

        super(LocationWidget, self).__init__(attrs)

    def render(self, name, value, attrs=None, renderer=None):
        if value is not None:
            try:
                if isinstance(value, six.string_types):
                    lat, lng = value.split(',')
                else:
                    lng = value.x
                    lat = value.y

                value = '%s,%s' % (
                    float(lat),
                    float(lng),
                )
            except ValueError:
                value = ''
        else:
            value = ''

        if '-' not in name:
            prefix = ''
        else:
            prefix = name[:name.rindex('-') + 1]

        self.options['field_options']['prefix'] = prefix

        attrs = attrs or {}
        attrs['data-location-field-options'] = json.dumps(self.options)

        # Django added renderer parameter in 1.11, made it mandatory in 2.1
        kwargs = {}
        if renderer is not None:
            kwargs['renderer'] = renderer
        text_input = super(LocationWidget, self).render(name, value, attrs=attrs, **kwargs)

        return render_to_string('location_field/map_widget.html', {
            'field_name': name,
            'field_input': mark_safe(text_input)
        })

    @property
    def media(self):
        return forms.Media(**settings.LOCATION_FIELD['resources.media'])



class PlainLocationField(forms.fields.CharField):

    zoom = 13

    def __init__(self, based_fields=None, zoom=None, suffix='', *args, **kwargs):
        self.zoom = zoom
        if not based_fields:
            based_fields = []
        if not self.zoom:
            self.zoom = settings.LOCATION_FIELD['map.zoom']
        self.widget = LocationWidget(based_fields=based_fields, zoom=self.zoom,
                                     suffix=suffix, **kwargs)

        dwargs = {
            'required': True,
            'label': None,
            'initial': None,
            'help_text': None,
            'error_messages': None,
            'show_hidden_initial': False,
        }

        for attr in dwargs:
            if attr in kwargs:
                dwargs[attr] = kwargs[attr]

        super(PlainLocationField, self).__init__(*args, **dwargs)



class SoundField(forms.fields.FileField):
    pass



class PasswordField(forms.fields.CharField):

    def __init__(self, *args, **kwargs):
        super().__init__(widget=forms.PasswordInput, *args, **kwargs)
