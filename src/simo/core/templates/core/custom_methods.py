def translate(value, occasion):
    """
        Adjust this to make value translations before value is
        set on to a component and before it is sent to a device 
        from your SIMO.io smart home instance.
    """
    if occasion == 'before-set':
        return value
    else:  # 'before-send'
        return value


def is_in_alarm(self):
    return bool(self.value)

