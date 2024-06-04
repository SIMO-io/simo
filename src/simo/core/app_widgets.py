from django.utils.translation import gettext_lazy as _


class BaseAppWidget:
    uid = None
    name = None
    size = None


    def __init__(self, component):
        self.component = component
        assert self.uid, "App widget needs to have uid"
        assert self.name, "App widget needs to have a name"
        assert isinstance(self.size, list), "App widget needs to have a size"
        assert 0 < self.size[0] < 5, "Widget width must be between 1 and 4"
        assert 0 < self.size[1] < 5, "Widget height must be between 1 and 4"



class BinarySensorWidget(BaseAppWidget):
    uid = 'binary-sensor'
    name = _("Binary sensor")
    size = [2, 1]


class ButtonWidget(BaseAppWidget):
    uid = 'button'
    name = _("Button")
    size = [2, 1]


class NumericSensorWidget(BaseAppWidget):
    uid = 'numeric-sensor'
    name = _("Numeric sensor")
    size = [2, 1]


class NumericSensorGraphWidget(BaseAppWidget):
    uid = 'numeric-sensor-graph'
    name = _("Numeric sensor")
    size = [4, 1]


class MultiSensorWidget(BaseAppWidget):
    uid = 'multi-sensor'
    name = _("Multi sensor")
    size = [2, 2]


class KnobWidget(BaseAppWidget):
    uid = 'knob'
    name = _("Knob")
    size = [2, 1]


class KnobPlusWidget(BaseAppWidget):
    uid = 'knob-plus'
    name = _("Knob Plus")
    size = [2, 1]


class RGBWidget(BaseAppWidget):
    uid = 'rgb-light'
    name = _('RGB light')
    size = [2, 1]


class SingleSwitchWidget(BaseAppWidget):
    uid = 'switch-single'
    name = _("Single Switch")
    size = [2, 1]


class DoubleSwitchWidget(BaseAppWidget):
    uid = 'switch-double'
    name = _("Double Switch")
    size = [2, 1]


class TripleSwitchWidget(BaseAppWidget):
    uid = 'switch-triple'
    name = _("Triple Switch")
    size = [4, 1]


class QuadrupleSwitchWidget(BaseAppWidget):
    uid = 'switch-quadruple'
    name = _("Quadruple Switch")
    size = [4, 1]


class QuintupleSwitchWidget(BaseAppWidget):
    uid = 'switch-quintuple'
    name = _("Quintuple Switch")
    size = [4, 1]


class LockWidget(BaseAppWidget):
    uid = 'lock'
    name = _("Lock")
    size = [2, 2]

