Installation
========================================================================

Dependencies
------------------------------------------------------------------------

You need to install Slackv3 dependencies before using Errbot with Slack.  In the below example,
it is assumed slackv3 has been download to the /opt/errbot/backends directory and errbot has been
installed in a python virtual environment (adjust the command to your errbot's installation)::

    git clone https://github.com/errbotio/err-backend-slackv3.git
    source /opt/errbot/bin/activate
    /opt/errbot/bin/pip install .


Connection Methods
------------------------------------------------------------------------

Slack's OAuth and API architecture has evolved and caused some confusion.  No matter which OAuth bot token you're using or the API architecture in your environment, slackv3 will support it.

The backend will automatically detect which token and architecture you have and start listening for Slack events in the right way:

 - Legacy tokens (OAuthv1) with Real Time Messaging (RTM) API
 - Current token (OAuthv2) with Event API using the Event Subscriptions and Request URL.
 - Current token (Oauthv2) with Event API using the Socket-mode client.

Legacy tokens (OAuthv1) with Real Time Messaging (RTM) API
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When the following oauth scopes are detected, the RTM protocol will be used.  These scopes are automatically present when using a legacy token.

.. code::

    "apps"
    "bot"
    "bot:basic"
    "client"
    "files:write:user"
    "identify"
    "post"
    "read"

- Current token (OAuthv2) with Event API using the Event Subscriptions and Request URL.
- Current token (OAuthv2) with Event API using the Socket-mode client.

Backend Installation
------------------------------------------------------------------------

These instructions are for errbot running inside a Python virtual environment.  You will need to adapt these steps to your own errbot instance setup.
The virtual environment is created in `/opt/errbot/virtualenv` and errbot initialised in `/opt/errbot`.  The extra backend directory is in `/opt/errbot/backend`.

1. Create the errbot virtual environment

.. code::

    mkdir -p /opt/errbot/backend
    python3 -m venv /opt/errbot/virtualenv

2. Install and initialise errbot. `See here for details <https://errbot.readthedocs.io/en/latest/user_guide/setup.html>`_

.. code::

    source /opt/errbot/virtualenv/bin/activate
    pip install errbot
    cd /opt/errbot
    errbot --init

3. Configure the slackv3 backend and extra backend directory.  Located in `/opt/errbot/config.py`

.. code::

    BACKEND="SlackV3"
    BOT_EXTRA_BACKEND_DIR=/opt/errbot/backend

4. Clone `err-backend-slackv3` into the backend directory and install module dependencies.

.. code::

    cd /opt/errbot/backend
    git clone https://github.com/errbotio/err-backend-slackv3
    # to get a specific release use `--branch <release-tag>`, e.g. `--branch v0.1.0`
    git clone --depth 1 https://github.com/errbotio/err-backend-slackv3
    pip install .

5. Configure the slack bot token, signing secret (Events API with Request URLs) and/or app token (Events API with Socket-mode).  Located in `/opt/errbot/config.py`

.. code::

    BOT_IDENTITY = {
        'token': 'xoxb-...',
        'signing_secret': "<hexadecimal value>",
        'app_token': "xapp-..."
    }


Setting up Slack application
------------------------------------------------------------------------

Legacy token with RTM
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This was the original method for connecting a bot to Slack.  Create a bot token, configure errbot with it and start using Slack.
Pay attention when reading `real time messaging <https://github.com/slackapi/python-slack-sdk/blob/main/docs-src/real_time_messaging.rst>`_ explaining how to create a "classic slack application".  Slack does not allow Legacy bot tokens to use the Events API.

.. Note::
   Community members have shared the following steps to create a legacy token.
   It is documented here for convenience with no guarantee the steps will work, you will need to refer to official Slack documentation if they fail.
   Keep in mind Slacks intention is to deprecate the RTM protocol in favour of the Event protocol.

To create a classic app for Errbot.

1. Go to https://api.slack.com/apps?new_classic_app=1 and create a classic app
2. Go to OAuth & Permissions in the left pane
3. Add bot scope in the Scopes section
4. You'll see a warning saying "This scope is deprecated. Please update scopes to use granular permissions." but don't upgrade to the newer permission model
5. Go to App Home in the left pane
6. Click Add Legacy Bot User and set its name
7. Go to Install App in the left pane
8. Run the OAuth flow with your development workspace
9. Use Bot User OAuth Access Token for your RTM app


Current token with Events Request URLs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is by far the most complex method of having errbot communicate with Slack.  The architecture involves server to client communication over HTTP.  This means the Slack server must be able to reach errbot's `/slack/events` endpoint via the internet using a valid SSL connection.
How to set up such an architecture is outside the scope of this readme and is left as an exercise for the reader.  Read `slack events api document <https://github.com/slackapi/python-slack-events-api>`_ for details on how to configure the Slack app and request URL.

Current token with Events Socket-mode client
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Create a current bot token, enable socket mode.  Configure errbot to use the bot and app tokens and start using Slack.
Read `socket-mode <https://github.com/slackapi/python-slack-sdk/blob/main/docs-src/socket-mode/index.rst>`_ for instructions on setting up Socket-mode.

Ensure the bot is also subscribed to the following events:

- `file_created`
- `file_public`
- `message.channels`
- `message.groups`
- `message.im`

Bot manifest
------------------------------------------------------------------------

Slack allows configuration of bot oauth and other parameters through a manifest file.  An example below is provided to demonstrate what information can be supplied.

::

    display_information:
      name: Your Bot Name
      description: Description
      background_color: "#000000"
    features:
      bot_user:
        display_name: Your Bot Name
        always_online: true
    oauth_config:
      scopes:
        bot:
          - channels:history
          - channels:read
          - chat:write
          - groups:history
          - groups:read
          - groups:write
          - im:history
          - im:read
          - im:write
          - mpim:read
          - mpim:write
          - reactions:read
          - team:read
          - users:read
          - users:read.email
          - channels:manage
    settings:
      event_subscriptions:
        bot_events:
          - message.channels
          - message.groups
          - message.im
          - reaction_added
      interactivity:
        is_enabled: true
      org_deploy_enabled: false
      socket_mode_enabled: true
      token_rotation_enabled: false

It may also be necessary to enable _users being able to send message_ checkbox and create an app-level token with `connections:write` access.


Bot Admins
------------------------------------------------------------------------
Slack changed the way users are uniquely identified from display name ``@some_name`` to user id ``Uxxxxxx``. Errbot configuration will need to be updated before administrators can be correctly identified against the ACL sets.

The UserID is in plain text format. It can be found in the the Slack full profile page or using the ``!whoami`` command (``person`` field).

Because BOT_ADMINS is defined as plain text User IDs, they can not be used to send notifications. The mention format ``<@Uxxxxx>`` must be used in the BOT_ADMINS_NOTIFICATIONS configuration setting for errbot to initiate message to bot administrators.
