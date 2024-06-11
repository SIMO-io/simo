from django import forms
from django.shortcuts import render, redirect
from django.contrib.admin.helpers import Fieldset
from django.db import models, router
from django.utils.text import capfirst
from django.urls import NoReverseMatch, reverse
from django.contrib.admin.utils import NestedObjects, quote
from django.utils.html import format_html


class AdminFormActionForm(forms.Form):

    def __init__(self, modeladmin, request, queryset, *args, **kwargs):
        self.modeladmin = modeladmin
        self.request = request
        self.queryset = queryset
        super().__init__(*args, **kwargs)


class FormAction:

    def __init__(self, form, apply_func, title):
        self.form_cls = form
        self.apply_func = apply_func
        self.short_description = title
        self.__name__ = title

    def __call__(self, modeladmin, request, queryset):

        form = self.form_cls(modeladmin, request, queryset)

        select_across = request.POST.get('select_across')
        selected_items = request.POST.getlist('_selected_action')

        if 'Submit' in request.POST:
            form = self.form_cls(modeladmin, request, queryset, request.POST)
            form.request = request
            form.request = queryset
            form.modeladmin = modeladmin

            if form.is_valid():
                if type(self.apply_func) == str:
                    getattr(modeladmin, self.apply_func)(
                        request, queryset, form
                    )
                else:
                    self.apply_func(
                        request, queryset, form
                    )
                return

        context = {
            **modeladmin.admin_site.each_context(request),
            "title": "Batch update items",
            "opts": modeladmin.model._meta,
            'action_title': self.__name__,
            'select_across': select_across,
            'selected_items': selected_items,
            'objects': queryset,
            'fieldset': Fieldset(form, fields=form.fields.keys())
        }
        return render(request, 'admin/action_intermediate_form.html', context)


class EasyObjectsDeleteMixin:

    def get_deleted_objects(self, objs, request):
        return [], [], [], []