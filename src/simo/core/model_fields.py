from django.db import models


class LowercaseEmailField(models.EmailField):
    """Email field that normalizes values to lowercase for storage and lookups."""

    def normalize_email_value(self, value):
        if value is None:
            return value
        value = super().to_python(value)
        if isinstance(value, str):
            value = value.strip().lower()
        return value

    def to_python(self, value):
        return self.normalize_email_value(value)

    def get_prep_value(self, value):
        return super().get_prep_value(self.normalize_email_value(value))

    def pre_save(self, model_instance, add):
        value = getattr(model_instance, self.attname)
        value = self.normalize_email_value(value)
        setattr(model_instance, self.attname, value)
        return value
