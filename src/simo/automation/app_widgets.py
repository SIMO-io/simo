from django.utils.translation import gettext_lazy as _
from simo.core.app_widgets import BaseAppWidget


class ScriptWidget(BaseAppWidget):
    uid = 'script'
    name = _("Script")
    size = [2, 1]