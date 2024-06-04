"""
  This is where apps define custom component base types.
"""

from django.utils.translation import gettext_lazy as _

BASE_TYPES = {
    'numeric-sensor': _("Numeric sensor"),
    'multi-sensor': _("Multi sensor"),
    'binary-sensor': _("Binary sensor"),
    'button': _("Button"),
    'dimmer': _("Dimmer"),
    'dimmer-plus': _("Dimmer Plus"),
    'rgbw-light': _('RGB(W) light'),
    'switch': _("Switch"),
    'switch-double': _("Switch Double"),
    'switch-triple': _("Switch Triple"),
    'switch-quadruple': _("Switch Quadruple"),
    'switch-quintuple': _("Switch Quintuple"),
    'lock': _("Lock"),
}
