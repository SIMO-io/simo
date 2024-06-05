import json
from django import forms
from django.db import models
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from .helpers import get_random_string


def set_field_html_name_and_id(cls, new_name, new_attrs):
    """
    This creates wrapper around the normal widget rendering,
    allowing for a custom field name (new_name).
    """
    old_render = cls.widget.render
    def _widget_render_wrapper(name, value, attrs=None, renderer=None):
        if not attrs:
            attrs = {}
        attrs.update(new_attrs)
        return old_render(new_name, value, attrs, renderer)

    cls.widget.render = _widget_render_wrapper


class FormsetWidget(forms.Widget):
    formset_cls = None
    formset = None
    use_cached = False

    class Media:
        css = {
            'all': ['adminsortable2/css/sortable.css']
        }
        js = (
            'admin/js/inlines.js',
            'adminsortable2/js/adminsortable2.js',
        )

    def render(self, name, value, attrs=None, renderer=None):
        prefix = name

        if not self.use_cached and isinstance(value, list):
            self.formset = self.formset_cls(initial=value, prefix=name)

        if not self.formset:
            if isinstance(value, list):
                self.formset = self.formset_cls(initial=value, prefix=name)
            else:
                self.formset = self.formset_cls(value, prefix=name)

        if self.formset.management_form.initial:
            total_org_forms = self.formset.management_form.initial.get(
                'INITIAL_FORMS', 9999
            )
        else:
            total_org_forms = int(self.formset.management_form.data.get(
                '%s-INITIAL_FORMS' % prefix, 9999
            ))

        inline_formset_data = {
            "name": "#%s" % prefix,
            "options": {
                "prefix": prefix,
                "addText": "Add another",
                "deleteText": "Remove"
            }
        }

        empty_form = self.formset_cls(initial=[{}])[0]
        empty_form.data = {}
        empty_form.initial = {}
        for name, field in empty_form.fields.items():
            attrs = {'id': 'id_%s-__prefix__-%s' % (prefix, name)}
            if name == "ORDER":
                field.initial = 9999
                field.widget = forms.HiddenInput(attrs={"class": '_reorder_'})
            set_field_html_name_and_id(
                field, '%s-__prefix__-%s' % (prefix, name), attrs
            )

        for form in self.formset:
            form.fields['ORDER'].widget = forms.HiddenInput(
                attrs={"class": '_reorder_'}
            )

        cell_count = len(list(self.formset.form.declared_fields.keys())) + 1
        if self.formset.can_order:
            cell_count += 1
        if self.formset.can_delete:
            cell_count += 1

        return mark_safe(
            render_to_string(
                'admin/formset_widget.html', {
                    'formset': self.formset,
                    'inline_formset_data': json.dumps(inline_formset_data),
                    'cell_count': cell_count,
                    'empty_form': empty_form,
                    'total_org_forms': total_org_forms
                }
            )
        )

    def value_from_datadict(self, data, files, name):
        formset_data = {}
        for key, val in data.items():
            if key.startswith(name + '-'):
                formset_data[key] = val

        return formset_data


class FormsetField(forms.Field):
    widget = FormsetWidget
    formset_cls = None

    def __init__(self, formset_cls, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefix = get_random_string(5)
        self.formset_cls = formset_cls
        self.widget.formset_cls = formset_cls
        self.widget.prefix = self.prefix

    def clean(self, formset_data):

        try:
            first_key = list(formset_data.keys())[0]
        except:
            return

        prefix = first_key[:first_key.find('-')]

        self.widget.formset = self.formset_cls(formset_data, prefix=prefix)

        if not self.widget.formset.is_valid():
            self.widget.use_cached = True
            raise forms.ValidationError("")

        cleaned_value = []
        for i in range(int(formset_data.get('%s-TOTAL_FORMS' % prefix))):
            if formset_data.get('%s-%d-DELETE' % (prefix, i)) == 'on':
                continue
            form_data = {}

            for field_name, field in self.formset_cls().form.declared_fields.items():
                form_data[field_name] = formset_data.get(
                    '%s-%d-%s' % (prefix, i, field_name)
                )

            f_data = {}
            for key, val in form_data.items():
                f_data[f"{self.formset_cls.form.prefix}-{key}"] = val
            form = self.formset_cls.form(f_data)
            if form.is_valid():
                form_data = form.cleaned_data

            for field_name, field in self.formset_cls().form.declared_fields.items():

                if isinstance(field, forms.models.ModelChoiceField):
                    if isinstance(form_data[field_name], models.Model):
                        form_data[field_name] = form_data[field_name].pk
                    else:
                        form_data[field_name] = int(form_data[field_name])
                elif isinstance(field, forms.models.ModelMultipleChoiceField):
                    form_data[field_name] = [
                        obj.pk for obj in form_data[field_name]
                    ]
                elif isinstance(field, forms.fields.BooleanField):
                    form_data[field_name] = form_data[field_name] == 'on'
                elif isinstance(field, forms.fields.IntegerField):
                    try:
                        form_data[field_name] = int(form_data[field_name])
                    except:
                        form_data[field_name] = None

            if self.widget.formset.can_order:
                form_data['order'] = int(formset_data.get(
                    '%s-%d-ORDER' % (prefix, i), 0
                ))


            cleaned_value.append(form_data)



        if self.widget.formset.can_order:
            cleaned_value = sorted(cleaned_value, key=lambda d: d['order'])
            for i in range(len(cleaned_value)):
                cleaned_value[i].pop('order')

        return cleaned_value


