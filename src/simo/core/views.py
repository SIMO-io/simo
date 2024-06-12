import time
import threading
import subprocess
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.shortcuts import redirect
from django.http import HttpResponse, Http404
from django.contrib import messages
from .models import Instance
from .tasks import update as update_task, supervisor_restart
from .middleware import introduce_instance


def get_timestamp(request):
    return HttpResponse(time.time())

@login_required
def update(request):
    if not request.user.is_superuser:
        raise Http404()
    messages.warning(request, "Hub update initiated. ")
    threading.Thread(target=update_task).start()
    if request.META.get('HTTP_REFERER'):
        return redirect(request.META.get('HTTP_REFERER'))
    return redirect(reverse('admin:index'))


@login_required
def restart(request):
    if not request.user.is_superuser:
        raise Http404()
    messages.warning(
        request, "Hub restart initiated. "
                 "Your hub will be out of operation for next few seconds."
    )
    threading.Thread(target=supervisor_restart).start()
    if request.META.get('HTTP_REFERER'):
        return redirect(request.META.get('HTTP_REFERER'))
    return redirect(reverse('admin:index'))



@login_required
def reboot(request):
    if not request.user.is_superuser:
        raise Http404()
    messages.error(
        request,
        "Hub reboot initiated. Hub will be out of reach for a minute or two."
    )

    def hardware_reboot():
        time.sleep(2)
        print("Reboot system")
        subprocess.run(['reboot'])

    threading.Thread(target=hardware_reboot).start()
    if request.META.get('HTTP_REFERER'):
        return redirect(request.META.get('HTTP_REFERER'))
    return redirect(reverse('admin:index'))


@login_required
def set_instance(request, instance_slug):
    instance = Instance.objects.filter(slug=instance_slug).first()
    if instance:
        introduce_instance(instance, request)
        
    if request.META.get('HTTP_REFERER'):
        return redirect(request.META.get('HTTP_REFERER'))
    return redirect(reverse('admin:index'))