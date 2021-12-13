# err-backend-slackv3

Slack Events and Real Time Messaging backend for Errbot

## Purpose

This backend has been developed to support both the Slack Events and Real Time Messaging APIs using the latest SDK from Slack.

The backend has been made available outside the core errbot project to allow development and user feedback to happen on independent release cycles.

## Connection Methods

Slack has been making changes to their OAuth and API architecture that can seem quite confusing.
No matter which OAuth bot token you're using or the API architecture in your environment, `slackv3` has got you covered.

The backend will automatically detect which token and architecture you have and start listening for Slack events in the right way:

- Legacy tokens (OAuthv1) with Real Time Messaging (RTM) API
- Current token (OAuthv2) with Event API using the Event Subscriptions and Request URL.
- Current token (Oauthv2) with Event API using the Socket-mode client.

## Backend Installation

These instructions are for errbot running inside a Python virtual environment.  You will need to adapt these steps to your own errbot instance setup.
The virtual environment is created in `/opt/errbot/virtualenv` and errbot initialised in `/opt/errbot`.  The extra backend directory is in `/opt/erbot/backend`.

1. Create the errbot virtual environment

    ```bash
    mkdir -p /opt/errbot/backend
    virtualenv --python=python3 /opt/errbot/virtualenv
    ```

2. Install and initialise errbot. [See here for details](https://errbot.readthedocs.io/en/latest/user_guide/setup.html)

    ```bash
    source /opt/errbot/virtualenv/bin/activate
    pip install errbot
    cd /opt/errbot
    errbot --init
    ```

3. Configure the slackv3 backend and extra backend directory.  Located in `/opt/errbot/config.py`

    ```python
    BACKEND="SlackV3"
    BOT_EXTRA_BACKEND_DIR="/opt/errbot/backend"
    ```

4. Clone `err-backend-slackv3` into the backend directory and install module dependencies.

    ```bash
    cd /opt/errbot/backend
    git clone https://github.com/errbotio/err-backend-slackv3
    # to get a specific release use `--branch <release-tag>`, e.g. `--branch v0.1.0`
    git clone --depth 1 https://github.com/errbotio/err-backend-slackv3
    pip install -r /opt/errbot/backend/err-backend-slackv3/requirements.txt
    ```

5. Configure the slack bot token, signing secret (Events API with Request URLs) and/or app token (Events API with Socket-mode).  Located in `/opt/errbot/config.py`

    ```python
    BOT_IDENTITY = {
        'token': 'xoxb-...',
        'signing_secret': "<hexadecimal value>",
        'app_token': "xapp-..."
    }
    ```

## Setting up Slack application

### Legacy token with RTM

This was the original method for connecting a bot to Slack.  Create a bot token, configure errbot with it and start using Slack.
Pay attention when reading [this document](https://github.com/slackapi/python-slack-sdk/blob/main/docs-src/real_time_messaging.rst) explaining how to create a "classic slack application".  Slack does not allow Legacy bot tokens to use the Events API.

### Current token with Events Request URLs

This is by far the most complex method of having errbot communicate with Slack.  The architecture involves server to client communication over HTTP.  This means the Slack server must be able to reach errbot's `/slack/events` endpoint via the internet using a valid SSL connection.
How to set up such an architecture is outside the scope of this readme and is left as an exercise for the reader.  Read [this document](https://github.com/slackapi/python-slack-events-api) for details on how to configure the Slack app and request URL.

### Current token with Events Socket-mode client

Create a current bot token, enable socket mode.  Configure errbot to use the bot and app tokens and start using Slack.
Read [this document](https://github.com/slackapi/python-slack-sdk/blob/main/docs-src/socket-mode/index.rst) for instructions on setting up Socket-mode.

Ensure the bot is also subscribed to the following events:

- `file_created`
- `file_public`
- `message.channels`
- `message.groups`
- `message.im`

Moving from older slack backends

### Bot Admins
Slack changed the way users are uniquely identified from display name `@some_name` to user id `Uxxxxxx`.
Errbot configuration will need to be updated before administrators can be correctly identified aginst
the ACL sets.

The UserID is in plain text format.  It can be found in the the Slack full profile page or using the `!whoami` command (`person` field).

Because BOT_ADMINS is defined as plain text User IDs, they can not be used to send notifications.  The mention format
`<@Uxxxxx>` must be used in the BOT_ADMINS_NOTIFICATIONS configuration setting for errbot to initiate message to bot administrators.
