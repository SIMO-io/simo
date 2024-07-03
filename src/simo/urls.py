import importlib
import inspect
import sys
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from django.views.generic import RedirectView
from django.core.files.storage import FileSystemStorage
from django.apps import apps
from django.contrib.auth.views import LogoutView
from rest_framework import routers
from rest_framework.viewsets import GenericViewSet
from django.contrib.admin import site as admin_site
from simo.users.views import protected_static
from simo.core.views import hub_info



rest_router = routers.DefaultRouter()
registered_classes = []
for name, app in apps.app_configs.items():
    try:
        apis = importlib.import_module('%s.api' % app.name)
    except ModuleNotFoundError as e:
        continue
    for cls_name, cls in apis.__dict__.items():
        cls_id = '%s.%s' % (app.name, cls_name)
        if inspect.isclass(cls) and issubclass(cls, GenericViewSet) \
        and getattr(cls, 'url', None) and getattr(cls, 'basename', None):
            rest_router.register(
                cls.url, cls, basename=cls.basename
            )
            registered_classes.append(cls_id)

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='admin:index')),
    path('login/', include('simo.users.sso_urls')),


    path('admin/login/',
         RedirectView.as_view(
             pattern_name='login', query_string=True
         )
    ),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('admin/', admin_site.urls),
    path('api-hub-info/', hub_info),
    path('api/<instance_slug>/', include(rest_router.urls)),

]

for name, app in apps.app_configs.items():
    if name in (
        'auth', 'admin', 'contenttypes', 'sessions', 'messages',
        'staticfiles'
    ):
        continue
    try:
        urls = importlib.import_module('%s.auto_urls' % app.name)
    except ModuleNotFoundError:
        continue

    for var_name, item in urls.__dict__.items():
        if isinstance(item, list) and var_name == 'urlpatterns':
            urlpatterns.append(
                path('%s/' % name, include('%s.auto_urls' % app.name))
            )

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL, document_root=settings.MEDIA_ROOT
    )
else:
    urlpatterns += [
        protected_static(settings.MEDIA_URL),
        protected_static(settings.STATIC_URL),
    ]
