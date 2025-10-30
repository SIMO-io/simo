from django.core.management.base import BaseCommand
import os
import pwd
import grp
import sys
import subprocess
import importlib
import traceback
from django.apps import apps
from crontab import CronTab
from django.conf import settings
from django.template.loader import render_to_string
from django.db import transaction


def prepare_mosquitto():
    if os.geteuid() != 0:
        return

    from simo.users.models import User

    users_file = '/etc/mosquitto/mosquitto_users'
    if not os.path.exists(users_file):
        with open(users_file, 'w') as f:
            f.write('')

        uid = pwd.getpwnam("mosquitto").pw_uid
        gid = grp.getgrnam("mosquitto").gr_gid
        os.chown(users_file, uid, gid)
        os.chmod(users_file, 0o640)

        acls_file = '/etc/mosquitto/acls.conf'
        with open(acls_file, 'w') as f:
            f.write('')

        uid = pwd.getpwnam("mosquitto").pw_uid
        gid = grp.getgrnam("mosquitto").gr_gid
        os.chown(acls_file, uid, gid)
        os.chmod(acls_file, 0o640)

    ps = subprocess.Popen(
        ['mosquitto_passwd /etc/mosquitto/mosquitto_users root'],
        shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    ps.communicate(f"{settings.SECRET_KEY}\n{settings.SECRET_KEY}".encode())

    for user in User.objects.all():
        user.update_mqtt_secret(reload=False)

    from simo.users.utils import update_mqtt_acls

    update_mqtt_acls()

    if not os.path.exists('/etc/mosquitto/conf.d/simo.conf'):
        with open('/etc/mosquitto/conf.d/simo.conf', 'w') as f:
            f.write(render_to_string('conf/mosquitto.conf'))

    subprocess.run(
        ['service', 'mosquitto', 'restart'], stdout=subprocess.PIPE
    )


def update_auto_update():

    if os.geteuid() != 0:
        print("You are not a root user!")
        return

    executable_path = f'{os.path.dirname(sys.executable)}/simo-auto-update'
    cron = CronTab(user='root')
    for item in cron:
        if executable_path in str(item):
            return

    job = cron.new(command=executable_path)
    job.hour.every(1)
    job.enable()
    cron.write()


class Command(BaseCommand):

    def handle(self, *args, **options):
        prepare_mosquitto()
        from simo.core.tasks import maybe_update_to_latest
        maybe_update_to_latest.delay()
        update_auto_update()
        # Auto-create Gateway rows for handlers that opted in
        try:
            from simo.core.models import Gateway
            from simo.core.utils.type_constants import GATEWAYS_MAP
            created_any = False
            for uid, handler_cls in GATEWAYS_MAP.items():
                if getattr(handler_cls, 'auto_create', False):
                    # Build default config from handler's config_form
                    config_defaults = {}
                    try:
                        form_cls = getattr(handler_cls, 'config_form', None)
                        if form_cls is not None:
                            tmp_instance = Gateway(type=uid)
                            form = form_cls(instance=tmp_instance)
                            for fname, field in getattr(form, 'fields', {}).items():
                                if fname in ('log',):
                                    continue
                                init = getattr(field, 'initial', None)
                                if init is None:
                                    continue
                                # Normalize potential Model/QuerySet values to pks
                                try:
                                    import json as _json
                                    def _norm(v):
                                        try:
                                            return _json.loads(_json.dumps(v))
                                        except Exception:
                                            pass
                                        # Model instance
                                        if hasattr(v, 'pk'):
                                            return v.pk
                                        # QuerySet or iterable of models
                                        try:
                                            from django.db.models.query import QuerySet as _QS
                                            if isinstance(v, _QS):
                                                return [obj.pk for obj in v]
                                        except Exception:
                                            pass
                                        if isinstance(v, (list, tuple, set)):
                                            return [_norm(x) for x in v]
                                        return v
                                    config_defaults[fname] = _norm(init)
                                except Exception:
                                    # Best-effort; skip if cannot serialize
                                    continue
                    except Exception:
                        # If we cannot introspect defaults, fall back to empty config
                        pass

                    obj, created = Gateway.objects.get_or_create(
                        type=uid, defaults={'config': config_defaults}
                    )
                    if created:
                        created_any = True
                        print(f"Auto-created gateway: {handler_cls.name} ({uid})")
                        try:
                            obj.start()
                        except Exception:
                            print(traceback.format_exc(), file=sys.stderr)
            if created_any:
                pass
        except Exception:
            # Do not fail startup on gateway auto-create issues
            print(traceback.format_exc(), file=sys.stderr)
        for name, app in apps.app_configs.items():
            if name in (
                'auth', 'admin', 'contenttypes', 'sessions', 'messages',
                'staticfiles'
            ):
                continue
            try:
                importlib.import_module('%s.on_start' % app.name)
            except ModuleNotFoundError:
                continue
            except:
                print(traceback.format_exc(), file=sys.stderr)
