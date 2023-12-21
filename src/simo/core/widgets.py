from django import forms
from django.conf import settings
from django.templatetags.static import static
from django.utils.safestring import mark_safe
from location_field.widgets import LocationWidget as OrgLocationWidget


class LocationWidget(OrgLocationWidget):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        zoom = kwargs.get('zoom', None)
        if zoom:
            self.options['map.zoom'] = zoom

    @property
    def media(self):
        return forms.Media({
            'js': [
                static('location_field') + '/js/form.js',
            ],
        })


class SVGFileWidget(forms.ClearableFileInput):
    template_name = 'admin/svg_file_widget.html'



class PythonCode(forms.Textarea):

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs=extra_attrs)
        attrs.setdefault('class', 'python-code')
        return attrs

    @property
    def media(self):

        return forms.Media(
            js=(
               'third_party/codemirror/lib/codemirror.js',
               'third_party/codemirror/mode/python/python.js',
               'admin/js/codemirror-init.js',
               ),
            css={
                'screen': (
                    'third_party/codemirror/lib/codemirror.css',
                    'third_party/codemirror/theme/lucario.css'
                ),
            },
        )


class LogOutputWidget(forms.TextInput):

    def __init__(self, log_socket_url=None, *args, **kwargs):
        self.log_socket_url = log_socket_url
        super().__init__(*args, **kwargs)

    @property
    def media(self):
        extra = '' if settings.DEBUG else '.min'
        return forms.Media(
            js=(
                # 'admin/js/vendor/jquery/jquery%s.js' % extra,
                # 'admin/js/jquery.init.js',
                'admin/js/log_output_widget.js',
            ),
            css={'all': ['ansi_styles.css']}
        )

    def render(self, name, value, attrs=None, renderer=None):
        socket_url = self.log_socket_url
        if not socket_url:
            socket_url = ''
        return mark_safe(
            '<div class="code-log" data-ws_url="%s">'
            '<div class="log-container">'
            '<div class="scroller"></div></div>'
            '<p style="margin-left: 170px; margin-top: 10px;">'
            '<button style="padding: 5px 20px" class="button button-secondary">'
            '<i class="fas fa-trash-alt"></i> Clear</button><p>'
            '</div>' %
            socket_url
        )


class AdminImageWidget(forms.widgets.ClearableFileInput):
    template_name = "admin/clearable_easy_thumbnails_widget.html"


class ImageWidget(forms.widgets.ClearableFileInput):
    template_name = "setup_wizard/clearable_easy_thumbnails_widget.html"

