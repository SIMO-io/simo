import sys
import math
import traceback
import subprocess
import datetime
import numpy as np
from django.core.cache import cache
from django.utils import timezone
from django.template.loader import render_to_string


def get_system_user():
    from .models import User
    system, new = User.objects.get_or_create(
        email='system@simo.io', defaults={
            'name': "System"
        }
    )
    return system


def get_device_user():
    from .models import User
    device, new = User.objects.get_or_create(
        email='device@simo.io', defaults={
            'name': "Device"
        }
    )
    return device


def rebuild_authorized_keys():
    from .models import User
    try:
        with open('/root/.ssh/authorized_keys', 'w') as keys_file:
            for user in User.objects.filter(
                ssh_key__isnull=False, is_master=True
            ):
                has_roles = user.instance_roles.filter(
                    instance__is_active=True
                ).first()
                has_active_roles = user.instance_roles.filter(
                    instance__is_active=True, is_active=True
                ).first()
                # if master user has active roles on some instances
                # but no longer has a single active role on an instance
                # he is most probably has been disabled by the property owner
                # therefore he should no longer be able to ssh in to this hub!
                if has_roles and not has_active_roles:
                    continue
                keys_file.write(user.ssh_key + '\n')
    except:
        print(traceback.format_exc(), file=sys.stderr)
        pass


def update_mqtt_acls():
    from .models import User
    users = User.objects.all()
    with open('/etc/mosquitto/acls.conf', 'w') as f:
        f.write(
            render_to_string('conf/mosquitto_acls.conf', {'users': users})
        )
    subprocess.run(
        ['service', 'mosquitto', 'reload'], stdout=subprocess.PIPE
    )


class KalmanFilter:
    def __init__(self, process_variance, measurement_variance, x=None, P=None):
        self.x = x if x is not None else np.array([[0], [0], [0], [0]])  # State
        self.P = P if P is not None else np.eye(4)  # State covariance
        self.process_variance = process_variance
        self.measurement_variance = measurement_variance

    def predict(self, delta_t):
        F = np.array([
            [1, 0, delta_t, 0],
            [0, 1, 0, delta_t],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ])
        Q = self.process_variance * np.array([
            [delta_t ** 4 / 4, 0, delta_t ** 3 / 2, 0],
            [0, delta_t ** 4 / 4, 0, delta_t ** 3 / 2],
            [delta_t ** 3 / 2, 0, delta_t ** 2, 0],
            [0, delta_t ** 3 / 2, 0, delta_t ** 2]
        ])
        self.x = np.dot(F, self.x)
        self.P = np.dot(np.dot(F, self.P), F.T) + Q

    def update(self, z):
        H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0]
        ])
        R = self.measurement_variance * np.eye(2)
        y = z - np.dot(H, self.x)  # Innovation
        S = np.dot(H, np.dot(self.P, H.T)) + R  # Innovation covariance
        K = np.dot(np.dot(self.P, H.T), np.linalg.inv(S))  # Kalman Gain
        self.x = self.x + np.dot(K, y)
        I = np.eye(self.P.shape[0])
        self.P = np.dot(I - np.dot(K, H), self.P)

    def get_state(self):
        return self.x[:2].flatten()  # Latitude and Longitude


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points on the Earth."""
    R = 6371e3  # Earth's radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c  # Distance in meters


def get_smoothed_location(user_device, new_location):
    try:
        new_lat, new_lon = map(float, new_location.split(','))
    except ValueError:
        raise ValueError("Invalid new location format. Expected 'lat,lon'.")

    cache_key = f"kalman_state_{user_device.id}"
    cached_data = cache.get(cache_key)

    if cached_data:
        kf = KalmanFilter(
            process_variance=1,
            measurement_variance=10,
            x=np.array(cached_data['x']),
            P=np.array(cached_data['P'])
        )
        last_processed_time = cached_data['last_processed_time']
        last_location = cached_data['last_location']
    else:
        kf = KalmanFilter(process_variance=1, measurement_variance=10)
        last_processed_time = None
        last_location = None

    last_log = None
    logs_query = user_device.report_logs.filter(
        location__isnull=False,
        datetime__gt=last_processed_time or timezone.now() - datetime.timedelta(minutes=20)
    ).order_by('datetime')

    for log in logs_query:
        try:
            lat, lon = map(float, log.location.split(','))
        except ValueError:
            continue  # Skip invalid data

        if last_log and log.location == last_log.location:
            continue  # Skip duplicate locations

        if last_log:
            delta_t = (log.datetime - last_log.datetime).total_seconds()
            kf.predict(max(delta_t, 0))  # Prevent negative delta_t

        kf.update(np.array([[lat], [lon]]))
        last_log = log

    if last_log:
        delta_t = (timezone.now() - last_log.datetime).total_seconds()
        kf.predict(max(delta_t, 0))

    kf.update(np.array([[new_lat], [new_lon]]))

    # Compute speed if the previous location exists
    average_speed = 0
    if last_location:
        last_lat, last_lon = last_location
        distance = haversine_distance(last_lat, last_lon, new_lat, new_lon)
        time_diff = (timezone.now() - last_processed_time).total_seconds() if last_processed_time else None
        if time_diff and time_diff > 0:
            average_speed = distance / time_diff  # Speed in meters per second

    # Cache the updated filter state and last processed log time
    cache.set(cache_key, {
        'x': kf.x.tolist(),
        'P': kf.P.tolist(),
        'last_processed_time': timezone.now(),
        'last_location': (new_lat, new_lon)
    }, timeout=3600)  # Cache for 1 hour

    smoothed_location = ','.join(f"{coord:.6f}" for coord in kf.get_state())
    return smoothed_location, average_speed