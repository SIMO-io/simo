=================================
`SIMO.io <https://simo.io>`_ - Smart Home Supremacy
=================================

Fully fledged `Python/Django <https://www.djangoproject.com/>`_ based smart home automation platform built by professionals
for professionals to be used in professional installations!

| Simplicity is the main building block of everything great that was or will be ever created!
| If something claimed to be smart, it must be simple yet comprehensive, otherwise it becomes tedious.

| Simanas Venčkauskas
| Founder of SIMO.io


How do I start?
==========
This repository represents SIMO.io main hub software that is
responsible for every SIMO.io hub out there.

For full SIMO.io smart home experience purchasing of
`SIMO.io hub <https://simo.io/shop/simo-io-fleet/hub/>`_ is required.
It comes with this software already preinstalled and various SIMO.io network
features enabled, which allows for Plug and Play use of a system.


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

Standard SIMO.io hub admin interface comes packed with various powerful features
and an easy and convenient way to extend your hub with all kinds of extras.


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