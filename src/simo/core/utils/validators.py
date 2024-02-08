import xml.etree.cElementTree as et
from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError


def validate_svg(f):
    # Find "start" word in file and get "tag" from there
    f.seek(0)
    tag = None
    try:
        for event, el in et.iterparse(f, ('start',)):
            tag = el.tag
            break
    except et.ParseError:
        pass

    # Check that this "tag" is correct
    if tag != '{http://www.w3.org/2000/svg}svg':
        raise ValidationError(_('Uploaded file is not an image or SVG file.'))

    # Do not forget to "reset" file
    f.seek(0)

    return f


def validate_flr(f):
    return f
    # if not f.endswith('.flr'):
    #     raise ValidationError("Only .flr files accepted")
    # return f


def validate_slaves(slaves, component, master_component=None):
    for slave in slaves:
        if slave == component:
            raise forms.ValidationError(_(f"{component} is already a slave of {slave}"))
        if slave == master_component:
            raise forms.ValidationError(_(f"{master_component} is already a slave of {slave}"))
        subslaves = slave.slaves.all()
        if subslaves.count():
            validate_slaves(subslaves, slave, master_component=None)
    return slaves