from django.core.exceptions import ValidationError




class BaseConfigValue:
    default = None

    def __init__(self, default):
        super().__init__()
        self.default = self.validate(default)

    def validate(self, val):
        raise ValidationError("This is not valid value!")


class BooleanConfigValue(BaseConfigValue):

    def validate(self, val):
        if not isinstance(val, bool):
            raise ValidationError(
                'Boolean value required, but you are trying to pass: "%s"'
                % str(val)
            )
        return val


class StringConfigValue(BaseConfigValue):

    def validate(self, val):
        if not isinstance(val, str):
            raise ValidationError('String value required, got "%s" instead' % str(val))
        return val


class ThermostatModeConfigValue(StringConfigValue):

    def validate(self, val):
        super().validate(val)
        if val not in ('auto', 'heater', 'cooler'):
            raise ValidationError("Must be one of [auto, heater, cooler]")
        return val


class ChoicesConfigValue(StringConfigValue):

    def __init__(self, default, choices_list):
        self.choices_list = choices_list
        super().__init__(default)

    def validate(self, val):
        super().validate(val)
        if val not in self.choices_list:
            raise ValidationError("Must be one of %s" % str(self.choices_list))
        return val


class IntegerConfigValue(BaseConfigValue):

    def validate(self, val):
        if not isinstance(val, int):
            raise ValidationError(
                'Integer value required, but you are trying to pass: "%s"'
                % str(val)
            )
        return val


class FloatConfigValue(BaseConfigValue):

    def validate(self, val):
        if type(val) not in (float, int):
            raise ValidationError(
                'Float value required, but you are trying to pass: "%s"'
                % str(val)
            )
        return val


class TimeConfigValue(BaseConfigValue):

    def validate(self, val, min=None, max=None):
        for item in val:
            try:
                hour = int(item.split(':')[0])
                assert 0 <= hour < 24
                minute = int(item.split(':')[1])
                assert 0 <= minute < 59
            except:
                raise ValidationError('Bad time value')
        return val


class TimeTempConfigValue(BaseConfigValue):

    def validate(self, val, min=None, max=None):
        for item in val:
            if len(item) != 2:
                raise ValidationError(
                    "Must be a list or tuple of time and target temperature!"
                )
            try:
                hour = int(item[0].split(':')[0])
                assert 0 <= hour < 24
                minute = int(item[0].split(':')[1])
                assert 0 <= minute < 59
            except:
                raise ValidationError('Bad time value')

            try:
                target_temp = float(item[1])
            except:
                raise ValidationError('Bad target temperature value')

            if min and target_temp < min:
                raise ValidationError(
                    'Target temp "%s" is to low' % str(target_temp)
                )

            if max and target_temp > max:
                raise ValidationError(
                    'Target temp "%s" is to high' % str(target_temp)
                )

        return val


def config_to_dict(obj):
    if isinstance(obj, dict):
        for key, val in obj.items():
            obj[key] = config_to_dict(val)
    elif isinstance(obj, (list, tuple)):
        obj = [config_to_dict(item) for item in obj]
    elif isinstance(obj, BaseConfigValue):
        obj = obj.default
    return obj


def validate_new_conf(new_conf, old_conf, default):

    if isinstance(default, BaseConfigValue):
        # print(new_conf, old_conf)
        if isinstance(new_conf, BaseConfigValue):
            if isinstance(old_conf, BaseConfigValue):
                return default.default
            else:
                return old_conf
        else:
            return default.validate(new_conf)

    if isinstance(default, dict):
        conf = {}
        for key, val in default.items():
            conf[key] = validate_new_conf(
                new_conf.get(key, val), old_conf.get(key, val), val
            )
        return conf

    elif isinstance(default, (list, tuple)):
        conf = []
        for i, item in enumerate(default):
            try:
                new = new_conf[i]
            except:
                new = item
            try:
                old = old_conf[i]
            except:
                old = item
            conf.append(
                validate_new_conf(new, old, item)
            )
        return conf

    return new_conf


class ConfigException(Exception):

    def __init__(self, data):
        self.data = data



def has_errors(errors_obj):
    if isinstance(errors_obj, dict):
        for key, val in errors_obj.items():
            if type(val) in (list, dict):
                if has_errors(val):
                    return True
            else:
                return True
        return False
    elif isinstance(errors_obj, list):
        for val in errors_obj:
            if type(val) in (list, dict):
                if has_errors(val):
                    return True
            else:
                return True
        return False
    else:
        return True
