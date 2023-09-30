Users Guide
========================================================================

.. Note::

    Slack provides advanced features above and beyond simple text messaging in the form of Slack Applications and Workflows.  These features cross into the domain of application development and use
    specialised events and data structures.  Support for these features is asked for by plugin developers, and for good reasons as their ChatOps requirements grow.  It is at this level of sophistication
    that errbot's framework reaches its limits because errbot's design goal is to be backend agnostic to ensure portability between all chat service providers.  For advanced use cases
    as mentioned early, it is strongly recommended to use `Slack's Bolt Application Framework <https://slack.dev/bolt-python/concepts>`_ to write complex application/workflows in Slack.  If you wish to
    continue using errbot with advanced features, check the developers section of the documentation which explains how to access the underlying Slack Python modules.

The Slack v3 backend provides some advanced formatting through direct access to the underlying python module functionality.  Below are examples of how to make use of Slack specific features.

Slack attachments and block
------------------------------------------------------------------------

It is possible to pass additional payload data along with the message.  When this extra information is present, the slack python module will process it.
The below example shows how to send attachments (deprecated) or blocks for advanced text message formatting.

.. code-block:: python

    from slack_sdk.models.blocks import SectionBlock, TextObject
    from errbot.backends.base import Message

    @botcmd
    def hello(self, msg, args):
        """Say hello to someone"""
        msg.body = "Using the sent message to shorten the code example"
        msg.extras['attachments'] = [{
            'color': '5F4B48',
            'fallback': 'Help text for: Bot plugin',
            'footer': 'For these commands: `help Bot`',
            'text': 'General commands to do with the ChatOps bot',
            'title': 'Bot'
        },{
            'color': 'FAF5F5',
            'fallback': 'Help text for: Example plugin',
            'footer': 'For these commands: `help Example`',
            'text': 'This is a very basic plugin to try out your new installation and get you started.\n Feel free to tweak me to experiment with Errbot.\n You can find me in your init directory in the subdirectory plugins.',
            'title': 'Example'
        }]

        self._bot.send_message(msg)


        # Example with the blocks SDK
        msg = Message()
        msg.extras['blocks'] = [
            SectionBlock(
                text=TextObject(
                    text="Welcome to Slack! :wave: We're so glad you're here. :blush:\n\n",
                    type="mrkdwn"
                )
            ).to_dict()
        ]
        self._bot.send_message(msg)


Bot online status indicator
------------------------------------------------------------------------

The online status indicator is an option in slack when you configure the bot and assign the oauth roles.

.. Note::
    The status indicator would be updated using the RTM protocol, but no longer updates with the Event protocol.
