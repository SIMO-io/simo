from django import forms
from dal import autocomplete


class ListSelect2Widget(autocomplete.ListSelect2):

    def filter_choices_to_render(self, selected_choices):
        if selected_choices:
            self.choices = [(selected_choices[0], selected_choices[0]),]


class AutocompleteSelect2(forms.TypedChoiceField):

    def __init__(self, url, *args, **kwargs):
        self.autocomplete_url = url
        super().__init__(
            widget=ListSelect2Widget(
                url=url, attrs={'data-html': True}
            ),
            *args, **kwargs
        )

    def valid_value(self, value):
        return True
