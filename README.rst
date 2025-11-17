=================================
`SIMO.io <https://simo.io>`_ - Smart Home Supremacy
=================================

.. image:: https://img.shields.io/badge/Published%20on-Django%20Packages-0c3c26
   :target: https://djangopackages.org/packages/p/simo/
   :alt: Published on Django Packages


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
This repository contains the SIMO.io Hub software — the same code that runs on
every SIMO.io hub. You have two ways to get started:

- Buy an OEM SIMO.io Hub (recommended):
  - Comes preinstalled and ready to go.
  - Includes 3 years of SIMO Cloud subscription.
  - Best total cost of ownership and zero setup hassle.
  - Shop: https://simo.io/shop/simo-io-fleet/hub/

- Self‑host on your own Ubuntu Server (fully supported):
  - Requirements: Ubuntu Server 24.04 LTS or newer, fresh install.
  - As root, run the installer which sets up all dependencies, database,
    services and the SIMO Hub application:

    ``sudo su root``

    ``wget https://simo.io/hubs/ubuntu-install -O - | python3``

  - Self‑hosted hubs receive a free 3‑month trial of SIMO Cloud.
  - After the trial, SIMO Cloud (remote access, mobile app outside LAN,
    AI scripts/automations) requires an $89/year subscription.
  - Local operation on your LAN continues regardless — only cloud features are
    disabled if you do not subscribe.


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


Django Admin
==========
All of your SIMO.io instances are available in your personal `Instances <https://simo.io/hubs/my-instances/>`_
page, where you can access full Django Admin interface to each of them,
from anywhere in the World!

Standard SIMO.io hub admin interface comes packed with powerful features and an
easy, convenient way to extend your hub with all kinds of extras.


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
 * ``supervisorctl stop simo-gunicorn`` - to stop SIMO.io simo-gunicorn processes
 * ``supervisorctl start simo-gunicorn`` - to start SIMO.io simo-gunicorn processes

All of these processes are running as root user, because there is nothing more important
on your SIMO.io hub than it's main software. That's by design and thoughtful intention.

Logs are piped to ``/var/log`` directory.


Notes about Cloud features and subscription
===========
- OEM hubs include a 3‑year SIMO Cloud subscription out of the box.
- Self‑hosted hubs start with a 3‑month free trial. After the trial, a
  subscription ($89/year) is required to keep remote access, the SIMO.io mobile
  app outside your LAN, AI scripts generation feature and Sentinel AI voice assistant enabled.
- If a subscription expires, your hub continues working locally on your network;
  only remote/cloud features are disabled until renewed.


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
