from django import forms


class AdminReadonlyFieldWidget(forms.TextInput):

    def render(self, name, value, attrs=None, renderer=None):
        return '<p>%s<p> <span style="display: none">%s</span>' % (
            str(value), forms.TextInput().render(name, str(value))
        )


class EmptyFieldWidget(forms.TextInput):

    def render(self, name, value, attrs=None, renderer=None):
        return ''
