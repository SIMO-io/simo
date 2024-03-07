import time
import threading
import subprocess
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.shortcuts import get_object_or_404, render, redirect
from django.http import FileResponse, HttpResponse, Http404
from django.contrib.gis.geos import Point
from django.contrib import messages
from simo.users.models import User
from simo.conf import dynamic_settings
from .models import Instance
from .tasks import update as update_task, supervisor_restart
from .forms import (
    HubConfigForm, CoordinatesForm, TermsAndConditionsForm
)
from .middleware import introduce_instance


def get_timestamp(request):
    return HttpResponse(time.time())


@login_required
def setup_wizard(request):

    step = request.session.get('setup_wizard_step', 1)

    if request.method == 'POST' and 'back' in request.POST and step > 1:
        request.session['setup_wizard_step'] = step - 1
        return redirect(request.path)

    if step == 1:
        cover_img = dynamic_settings['core__cover_image']
        if cover_img:
            cover_img.field.storage = cover_img.storage
        initial = {
            'name': dynamic_settings['core__hub_name'],
            'uid': dynamic_settings['core__hub_uid'],
            'time_zone': dynamic_settings['core__time_zone'],
            'units_of_measure': dynamic_settings['core__units_of_measure'],
            'cover_image': cover_img
        }
        form = HubConfigForm(initial=initial, user=request.user)
        if request.method == 'POST':
            form = HubConfigForm(
                request.POST, request.FILES, initial=initial, user=request.user
            )
            if form.is_valid():
                dynamic_settings['core__hub_name'] = form.cleaned_data['name']
                dynamic_settings['core__hub_uid'] = form.cleaned_data['uid']
                dynamic_settings['core__time_zone'] = form.cleaned_data[
                    'time_zone'
                ]
                dynamic_settings['core__units_of_measure'] = form.cleaned_data[
                    'units_of_measure'
                ]
                if not dynamic_settings['core__location_coordinates'] \
                and request.POST.get('location-guess'):
                    dynamic_settings['core__location_coordinates'] = \
                        request.POST['location-guess']
                if form.cleaned_data['cover_image']:
                    dynamic_settings['core__cover_image'] = \
                        form.cleaned_data['cover_image']
                    dynamic_settings['core__cover_image_synced'] = False
                request.session['setup_wizard_step'] = 2
                return redirect(request.path)
    elif step == 2:
        initial = {
            'location': dynamic_settings['core__location_coordinates'],
            'share_location': dynamic_settings['core__share_location']
        }
        form = CoordinatesForm(initial=initial)
        if request.method == 'POST':
            form = CoordinatesForm(request.POST, initial=initial)
            if form.is_valid():
                dynamic_settings['core__location_coordinates'] = \
                    form.cleaned_data['location']
                dynamic_settings['core__share_location'] = \
                    form.cleaned_data['share_location']
                request.session['setup_wizard_step'] = 3
                return redirect(request.path)
    else:
        form = TermsAndConditionsForm()
        if request.method == 'POST':
            form = TermsAndConditionsForm(request.POST)
            if form.is_valid() and form.cleaned_data['accept']:
                request.session.pop('setup_wizard_step')
                messages.success(
                    request, "Congratulations! "
                             "Your Hub is now configured and restarting in the background. "
                             "Will be fully ready in 30 seconds."
                )
                threading.Thread(target=supervisor_restart).start()
                return redirect(reverse('admin:index'))

    return render(request, 'setup_wizard/form.html', {'form': form, 'step': step})


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