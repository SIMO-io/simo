=================================
`SIMO.io <https://simo.io>`_ - Smart Home Supremacy
=================================


A fully featured `Python/Django <https://www.djangoproject.com/>`_ - based
smart home automation platform — built by professionals,
for professionals, designed specifically for high-quality
professional installations.

| Simplicity is the cornerstone of everything truly great — past, present, and future.
| If something is called smart, it must be both simple and comprehensive. Otherwise, it becomes a burden, not a solution.
|
| Simon
| Founder of SIMO.io


How do I start?
==========
This repository represents the SIMO.io main hub software that runs on every
SIMO.io hub.

For the full SIMO.io smart home experience a
`SIMO.io hub <https://simo.io/shop/simo-io-fleet/hub/>`_ is required. It
comes with this software preinstalled and configured, enabling true plug and
play.


Install / Upgrade on a SIMO hub
=============================
On an official SIMO hub, install and upgrades are handled via packaged
commands. SSH to your hub and run:

::

    simo-update         # one-off update to the latest release
    simo-auto-update    # check and update when appropriate

Both commands will safely migrate the database, collect static assets and
restart required services. You can always manually restart processes via
``supervisorctl`` (see below).


Core services (supervisor)
========================
The hub uses ``supervisord`` to run and supervise processes. Useful commands:

* ``supervisorctl status all`` – view health of all services
* ``supervisorctl restart all`` – restart everything
* ``supervisorctl restart simo-gateways`` – restart gateways only
* ``supervisorctl restart simo-gunicorn simo-daphne`` – restart HTTP stack

Main programs (managed by supervisor):

* ``simo-start`` – runs hub bootstrap tasks (on_http_start)
* ``simo-gunicorn`` – Django HTTP requests
* ``simo-daphne`` – WebSocket/ASGI endpoint (``/ws/``)
* ``simo-mcp`` – MCP server
* ``simo-gateways`` – gateways manager (spawns gateway handlers)
* ``simo-mqtt-control`` – internal MQTT control app
* ``simo-mqtt-fanout`` – internal MQTT fanout app
* ``simo-celery-beat``/``simo-celery-worker`` – background tasks

MQTT resilience
==============
This release hardens all MQTT clients to tolerate broker restarts at any time
(
for example when ``mosquitto`` is restarted during ``on_http_start``).

* All internal MQTT clients use asynchronous connect and background loops.
* Automatic reconnect with backoff is enabled; subscriptions are re-applied on
  reconnect.
* Hot loops were removed — if the broker is unavailable, CPU usage remains low
  and clients patiently reconnect.


System layout and logs
=====================
* Project directory: ``/etc/SIMO/hub`` (contains ``manage.py`` and settings)
* Virtual environment: ``/etc/SIMO/venv/simo-hub`` (``workon simo-hub``)
* Variable data: ``/etc/SIMO/_var`` (media, static, etc.)
* Logs: ``/var/log/simo``

Common logs to tail while debugging:

* ``/var/log/simo/gateways.log`` – gateways manager + handlers
* ``/var/log/simo/mqtt_control.log`` – MQTT control app
* ``/var/log/simo/mqtt_fanout.log`` – MQTT fanout app
* ``/var/log/simo/gunicorn.log`` – HTTP worker
* ``/var/log/simo/daphne.log`` – ASGI / WebSockets


Mobile App
==========
Once you have your hub running in your local network you will need SIMO.io mobile app,
which is available in `Apple App Store <https://apps.apple.com/us/app/id1578875225>`_ and `Google Play <https://play.google.com/store/apps/details?id=com.simo.simoCommander>`_.

Sign up for an account if you do not have one yet, tap "Add New"
and choose "Local". Fill few required details in and your SIMO.io smart home instance
will be created in a moment.

.. Note::

    Fun fact! - You can create more than one smart home instance on a single SIMO.io hub unit.

From there you can start connecting `The Game Changer <https://simo.io/shop/simo-io-fleet/the-game-changer/>`_
boards (Colonels) and configuring your smart home components.


Primary management interface (ideology)
-------------------------------------
The SIMO.io mobile app is the primary interface for day‑to‑day management of
your smart home. This includes pairing, excluding, naming and organizing
devices such as Z‑Wave nodes, creating automations, and managing scenes and
groups. The app orchestrates discovery flows and guides installers and owners
through safe, reliable device onboarding.

Z‑Wave management (via app)
--------------------------
- Use the SIMO.io app to add the Z‑Wave gateway (if not already present),
  include/exclude devices, and run interviews.
- Assign zones/categories, rename devices, and confirm capabilities directly
  in the app. Components appear in the Admin and API automatically.
- The Django Admin remains available for power users (advanced tweaks,
  diagnostics, and development), but is no longer the primary way to manage
  Z‑Wave nodes.


Django Admin
==========
All of your SIMO.io instances are available in your personal `Instances <https://simo.io/hubs/my-instances/>`_
page, where you can access full Django Admin interface to each of them,
from anywhere in the World!

Standard SIMO.io hub admin interface comes packed with various powerful features
and an easy and convenient way to extend your hub with all kinds of extras.

.. important::

   Django Admin is intended for professionals and power users. It is not the
   primary interface for adding/managing Z‑Wave nodes. Prefer the SIMO.io app
   for pairing/excluding devices and other day‑to‑day tasks.


Power User Paradise
===========

If you are someone who understands Linux, Python and Django framework, you are
more than welcome to dive in to the deepest depths of SIMO.io hub software. :)

Adding your public ssh key to your user account automatically transfers it to your hub
/root/.ssh/authorized_keys which allows you to ssh in to it remotely from anywhere!


Your hub's Django project dir is found in ``/etc/SIMO/hub``,
this is where you find infamous ``manage.py`` file, edit ``settings.py`` file
and add any additional Django apps that you might want to install or code on your own.

Calling ``workon simo-hub`` gets you up on a Python virtual environment that your hub is running.

Processes are managed by ``supervisord``, so you can do all kinds of things like:

 * ``supervisorctl status all`` - to see how healthy are SIMO.io hub processes
 * ``supervisorctl restart all`` - to restart SIMO.io hub processes
* ``supervisorctl stop simo-gunicorn`` - to stop SIMO.io gunicorn processes
* ``supervisorctl start simo-gunicorn`` - to start SIMO.io gunicorn processes

All of these processes are running as root user, because there is nothing more important
on your SIMO.io hub than it's main software. That's by design and thoughtful intention.

Logs are piped to ``/var/log`` directory.


Developer notes (non-hub installs)
===============================
Running outside the official hub is possible but not supported for production.
If you experiment locally, you will need:

* Python 3.12+
* PostgreSQL with PostGIS extension
* Redis server
* Mosquitto MQTT broker

Install the package and requirements:

::

    pip install simo

Create a database named ``SIMO`` and configure PostgreSQL accordingly. The
default settings expect local services (see ``simo/settings.py`` for details).
On the hub, migrations and static collection are handled by the update
commands; for local experiments you can run Django management commands via the
hub project in ``/etc/SIMO/hub`` once bootstrapped.


License
==========


© Copyright by SIMO LT, UAB. Lithuania.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see `<https://www.gnu.org/licenses/>`_.
