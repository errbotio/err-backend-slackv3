Legacy/Classic token migration
========================================================================

Slack annonced the `deprecation of legacy bot access <https://api.slack.com/changelog/2024-09-legacy-custom-bots-classic-apps-deprecation>`_  beginning 31st March 2025.  For people needing guidance to get their Errbot configuration migrated, here are is the procedure supplied by a community member.

When migrating from the legacy Slack RTM API to the Events API or Socket Mode, which Errbot's SlackV3 backend supports all three, the core problem is that the way the bot receives messages has fundamentally changed.

Understanding what's changing
------------------------------------------------------------------------

1. Legacy RTM vs. Modern Events Request URL/Socket Mode:
    - Legacy RTM: The bot established a persistent WebSocket connection and received all messages from channels it was a member of.  It would then filter these messages locally for the ``!`` prefix.
    - Modern Events API/Socket Mode: Slack now sends specific events to the bot (either via HTTP POST to an endpoint or over a WebSocket in Socket Mode).  The bot needs to explicitly subscribe to the events it cares about.  Simply being in a channel isn't enough to get all message events by default with some configurations.

#. Event Subscription is mandatory:
    After configuring the authentication tokens correctly, the Slack App must be subscribed to the necessary message events.  By default, new Slack apps only listen for direct mentions (@yourbot ...), subscribing to the necessary events allows Errbot to "see" the !status message.

#. Socket Mode:
    Socket Mode is the easier migration path as it doesn't require exposing a public HTTP endpoint, which is the required for Events Request URL.  It uses WebSockets, similar in concept to RTM but using the modern event structure.

Steps to Migrate
------------------------------------------------------------------------
1. Ensure the SlackV3 backend is configured
    - In ``config.py`` make sure the correct backend is used.
    ::

      BACKEND = 'SlackV3' # Or check errbot --list-backends for the exact name

    - Configure tokens, the Bot Token (``xoxb-...``).  If using Socket Mode, an App-Level Token is required (``xapp-...``).
    ::

      BOT_IDENTITY = {
          'token': 'xoxb-YOUR-BOT-TOKEN-HERE', # Bot User OAuth Token
          'signing_secret': 'your-signing-secret',
          'app_token': 'xapp-YOUR-APP-LEVEL-TOKEN-HERE', # Needed for Socket Mode
      }

2. Configure the Slack App (api.slack.com)
    - Go to the App's settings page on api.slack.com.
      a. Enable Socket Mode:
        - Navigate to "Settings" -> "Socket Mode".
        - Ensure it's toggled ON. Generate an App-Level Token if not already done (this is the ``xapp-...`` token used in ``config.py``).
      b. Add Required OAuth Scopes (Permissions):
        - Navigate to "Features" -> "OAuth & Permissions".
        - Scroll down to "Scopes".  Under "Bot Token Scopes", ensure at least the below scopes are selected:
            - ``chat:write``: To send messages.
            - ``app_mentions:read``: To receive ``@yourbot`` mentions (good practice).
            - ``channels:history``: To read messages from public channels the bot is in.
            - ``groups:history``: To read messages from private channels the bot is in.
            - ``im:history``: To read direct messages sent to the bot.
            - ``mpim:history``: To read messages in group direct messages the bot is in.
            - ``channels:read``, ``groups:read``, ``im:read``, ``mpim:read``: Often needed to get context about conversations.
            - ``users:read``: Often useful for looking up user info.
      c. Subscribe to Bot Events:
        - Navigate to "Features" -> "Event Subscriptions".
        - Ensure it's toggled ON (even if using Socket Mode, this is where you select which events Socket Mode will receive).
        - Expand "Subscribe to bot events".
        - Add the following events (at minimum):
            - ``app_mention``: To be notified when someone @mentions your bot.
            - ``message.channels``: To receive messages posted in public channels the bot is in.
            - ``message.groups``: To receive messages posted in private channels the bot is in.
            - ``message.im``: To receive direct messages sent to the bot.
            - ``message.mpim``: To receive messages in group direct messages the bot is in.
        - Crucially, without the ``message.*`` events, your bot will not see regular messages like ``!status`` unless they also ``@mention`` the bot.
      d. Reinstall App: After changing Scopes or Event Subscriptions, you must reinstall your app into your workspace. Go back to "Settings" -> "Install App" and click "Reinstall to Workspace" (or "Install to Workspace" if it's the first time after changes). Follow the prompts.

3. Ensure Bot is in the Channel: Double-check that your bot user has actually been invited to and joined the channel where you are typing the ``!status`` command.

4. Restart Errbot: After updating ``config.py`` and your Slack App settings (including reinstalling), restart your Errbot process.

5. Check Logs: Increase Errbot's log level in ``config.py`` (``BOT_LOG_LEVEL = logging.DEBUG``) and restart. Check the logs when you send a ``!status`` command. You should see evidence of the message event being received if the subscriptions are correct. If you see the message event but Errbot doesn't react, check your ``BOT_PREFIX`` setting in ``config.py``.

Checklist
------------------------------------------------------------------------

    - Use the correct Errbot backend (SlackV3 or similar) in config.py.
    - Provide both ``xoxb-`` (Bot Token) and ``xapp-`` (App-Level Token) in BOT_IDENTITY.
    - Enable Socket Mode in Slack App settings.
    - Add necessary OAuth Scopes (``chat:write``, ``channels:history``, ``groups:history``, ``im:history``, ``mpim:history``, etc.).
    - Subscribe to Bot Events (app_mention, message.channels, message.groups, message.im, message.mpim).
    - Reinstall the Slack App to apply scope/event changes.
    - Ensure the bot user is a member of the relevant channel(s).
    - Restart Errbot.
    - Check logs for errors or received message events.

Following these steps, particularly ensuring the correct Event Subscriptions (``message.*``) are active and the app is reinstalled, should get your Errbot responding to commands again.

Thanks to `grimesp <https://github.com/grimesp>`_ for supplying this migration guide.
