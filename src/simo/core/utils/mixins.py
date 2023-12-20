from django.urls import reverse_lazy


class SimoAdminMixin(object):

    def get_admin_url(self):
        return reverse_lazy('admin:%s_%s_change' %
                       (self._meta.app_label,  self._meta.model_name),
                       args=[self.pk])