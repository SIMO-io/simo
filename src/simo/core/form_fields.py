import copy
from django import forms
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

    def __init__(self, url, forward=None, *args, **kwargs):
        self.url = url
        self.forward = []
        if forward:
            self.forward = [fw.to_dict() for fw in forward]

        widget = Select2Multiple(
            url=url, forward=forward, attrs={'data-html': True}
        )
        widget.choices = kwargs.pop('choices', None)

        super().__init__(widget, *args, **kwargs)


class Select2ModelMultipleChoiceField(
    Select2MultipleMixin, forms.ModelMultipleChoiceField
):
    pass


class Select2ListMultipleChoiceField(
    Select2MultipleMixin, forms.MultipleChoiceField
):
    pass