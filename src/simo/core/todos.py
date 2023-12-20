from django.urls import reverse_lazy
from simo.conf import dynamic_settings


# def set_main_climate_sensor():
#     if not dynamic_settings['core__indoor_climate_sensor']:
#         section, name = dynamic_settings.parse_lookup('core__indoor_climate_sensor')
#         db_pref = dynamic_settings.get_db_pref(section, name)
#         link = reverse_lazy(
#             'admin:%s_%s_change' % (db_pref._meta.app_label, db_pref._meta.model_name),
#             args=[db_pref.pk]
#         )
#         return [{
#             'icon': 'fas fa-thermometer-half',
#             'label': 'Set your main indoor temperature sensor!',
#             'link': link
#         }]
