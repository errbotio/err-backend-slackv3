import copyreg
import json
import logging
import pprint
import re
import sys
from functools import lru_cache
from time import sleep
from typing import BinaryIO

from errbot.backends.base import (
    AWAY,
    ONLINE,
    REACTION_ADDED,
    REACTION_REMOVED,
    Card,
    Identifier,
    Message,
    Presence,
    Reaction,
    Room,
    RoomDoesNotExistError,
    RoomError,
    RoomOccupant,
    Stream,
    UserDoesNotExistError,
)
from errbot.core import ErrBot
from errbot.core_plugins import flask_app
from errbot.utils import split_string_after

try:
    from slack_sdk.errors import BotUserAccessError, SlackApiError
    from slack_sdk.oauth import AuthorizeUrlGenerator
    from slack_sdk.rtm import RTMClient
    from slack_sdk.web import WebClient
    from slack_sdk.webhook import WebhookClient
    from slackeventsapi import SlackEventAdapter

except ImportError:
    log.exception("Could not start the SlackSDK backend")
    log.fatal(
        "You need to install python modules in order to use the Slack backend.\n"
        "You can do `pip install errbot[slack-sdk]` to install them."
    )
    sys.exit(1)

from ._slack.markdown import slack_markdown_converter
from ._slack.person import SlackPerson

log = logging.getLogger(__name__)


# The Slack client automatically turns a channel name into a clickable
# link if you prefix it with a #. Other clients receive this link as a
# token matching this regex.
SLACK_CLIENT_CHANNEL_HYPERLINK = re.compile(r"^<#(?P<id>([CG])[0-9A-Z]+)>$")

USER_IS_BOT_HELPTEXT = (
    "Connected to Slack using a bot account, which cannot manage "
    "channels itself (you must invite the bot to channels instead, "
    "it will auto-accept) nor invite people.\n\n"
    "If you need this functionality, you will have to create a "
    "regular user account and connect Errbot using that account. "
    "For this, you will also need to generate a user token at "
    "https://api.slack.com/web."
)

COLORS = {
    "red": "#FF0000",
    "green": "#008000",
    "yellow": "#FFA500",
    "blue": "#0000FF",
    "white": "#FFFFFF",
    "cyan": "#00FFFF",
}  # Slack doesn't know its colors


class SlackAPIResponseError(RuntimeError):
    """Slack API returned a non-OK response"""

    def __init__(self, *args, error="", **kwargs):
        """
        :param error:
            The 'error' key from the API response data
        """
        self.error = error
        super().__init__(*args, **kwargs)


class SlackRoomOccupant(RoomOccupant, SlackPerson):
    """
    This class represents a person inside a MUC.
    """

    def __init__(self, webclient: WebClient, userid, channelid, bot):
        super().__init__(webclient, userid, channelid)
        self._room = SlackRoom(webclient=webclient, channelid=channelid, bot=bot)

    @property
    def room(self):
        return self._room

    def __unicode__(self):
        return f"#{self._room.name}/{self.username}"

    def __str__(self):
        return self.__unicode__()

    def __eq__(self, other):
        if not isinstance(other, SlackRoomOccupant):
            log.warning(
                "tried to compare a SlackRoomOccupant with a SlackPerson %s vs %s",
                self,
                other,
            )
            return False
        return other.room.id == self.room.id and other.userid == self.userid


class SlackBot(SlackPerson):
    """
    This class describes a bot on Slack's network.
    """

    def __init__(self, webclient: WebClient, bot_id, bot_username):
        self._bot_id = bot_id
        self._bot_username = bot_username
        super().__init__(webclient, userid=bot_id)

    @property
    def username(self):
        return self._bot_username

    # Beware of gotcha. Without this, nick would point to username of SlackPerson.
    nick = username

    @property
    def aclattr(self):
        # Make ACLs match against integration ID rather than human-readable
        # nicknames to avoid webhooks impersonating other people.
        return f"<{self._bot_id}>"

    @property
    def fullname(self):
        return None


class SlackRoomBot(RoomOccupant, SlackBot):
    """
    This class represents a bot inside a MUC.
    """

    def __init__(self, sc, bot_id, bot_username, channelid, bot):
        super().__init__(sc, bot_id, bot_username)
        self._room = SlackRoom(webclient=sc, channelid=channelid, bot=bot)

    @property
    def room(self):
        return self._room

    def __unicode__(self):
        return f"#{self._room.name}/{self.username}"

    def __str__(self):
        return self.__unicode__()

    def __eq__(self, other):
        if not isinstance(other, SlackRoomOccupant):
            log.warning(
                "tried to compare a SlackRoomBotOccupant with a SlackPerson %s vs %s",
                self,
                other,
            )
            return False
        return other.room.id == self.room.id and other.userid == self.userid


class SlackBackend(ErrBot):
    def __init__(self, config):
        super().__init__(config)
        identity = config.BOT_IDENTITY
        self.token = identity.get("token", None)
        self.proxies = identity.get("proxies", None)

        if not self.token:
            log.fatal(
                'You need to set your token (found under "Bot Integration" on Slack) in '
                "the BOT_IDENTITY setting in your configuration. Without this token I "
                "cannot connect to Slack."
            )
            sys.exit(1)

        self.signing_secret = identity.get("signing_secret", None)

        # Slack objects will be initialised in the serve_forever method.
        self.slack_web = None
        self.slack_rtm = None
        self.slack_events = None
        self.bot_identifier = None

        compact = config.COMPACT_OUTPUT if hasattr(config, "COMPACT_OUTPUT") else False
        self.md = slack_markdown_converter(compact)
        self._register_identifiers_pickling()

    def set_message_size_limit(self, limit=4096, hard_limit=40000):
        """
        Slack supports upto 40000 characters per message, Errbot maintains 4096 by default.
        """
        super().set_message_size_limit(limit, hard_limit)

    @staticmethod
    def _unpickle_identifier(identifier_str):
        return SlackBackend.__build_identifier(identifier_str)

    @staticmethod
    def _pickle_identifier(identifier):
        return SlackBackend._unpickle_identifier, (str(identifier),)

    def _register_identifiers_pickling(self):
        """
        Register identifiers pickling.

        As Slack needs live objects in its identifiers, we need to override their pickling behavior.
        But for the unpickling to work we need to use bot.build_identifier, hence the bot parameter here.
        But then we also need bot for the unpickling so we save it here at module level.
        """
        SlackBackend.__build_identifier = self.build_identifier
        for cls in (SlackPerson, SlackRoomOccupant, SlackRoom):
            copyreg.pickle(
                cls, SlackBackend._pickle_identifier, SlackBackend._unpickle_identifier
            )

    def update_alternate_prefixes(self):
        """Converts BOT_ALT_PREFIXES to use the slack ID instead of name

        Slack only acknowledges direct callouts `@username` in chat if referred
        by using the ID of that user.
        """
        # convert BOT_ALT_PREFIXES to a list
        try:
            bot_prefixes = self.bot_config.BOT_ALT_PREFIXES.split(",")
        except AttributeError:
            bot_prefixes = list(self.bot_config.BOT_ALT_PREFIXES)

        converted_prefixes = []
        for prefix in bot_prefixes:
            try:
                converted_prefixes.append(f"<@{self.username_to_userid(prefix)}>")
            except Exception as e:
                log.error(
                    'Failed to look up Slack userid for alternate prefix "%s": %s',
                    prefix,
                    e,
                )

        self.bot_alt_prefixes = tuple(
            x.lower() for x in self.bot_config.BOT_ALT_PREFIXES
        )
        log.debug("Converted bot_alt_prefixes: %s", self.bot_config.BOT_ALT_PREFIXES)

    def _setup_rtm_callbacks(self):
        rtm_events = [
            "accounts_changed",
            "bot_added",
            "bot_changed",
            "channel_archive",
            "channel_created",
            "channel_deleted",
            "channel_history_changed",
            "channel_joined",
            "channel_left",
            "channel_marked",
            "channel_rename",
            "channel_unarchive",
            "commands_changed",
            "dnd_updated",
            "dnd_updated_user",
            "email_domain_changed",
            "emoji_changed",
            "external_org_migration_finished",
            "external_org_migration_started",
            "file_change",
            "file_comment_added",
            "file_comment_deleted",
            "file_comment_edited",
            "file_created",
            "file_deleted",
            "file_public",
            "file_shared",
            "file_unshared",
            "goodbye",
            "group_archive",
            "group_close",
            "group_deleted",
            "group_history_changed",
            "group_joined",
            "group_left",
            "group_marked",
            "group_open",
            "group_rename",
            "group_unarchive",
            "hello",
            "im_close",
            "im_created",
            "im_history_changed",
            "im_marked",
            "im_open",
            "manual_presence_change",
            "member_joined_channel",
            "member_left_channel",
            "message",
            "pin_added",
            "pin_removed",
            "pref_change",
            "presence_change",
            "presence_query",
            "presence_sub",
            "reaction_added",
            "reaction_removed",
            "reconnect_url",
            "star_added",
            "star_removed",
            "subteam_created",
            "subteam_members_changed",
            "subteam_self_added",
            "subteam_self_removed",
            "subteam_updated",
            "team_domain_change",
            "team_join",
            "team_migration_started",
            "team_plan_change",
            "team_pref_change",
            "team_profile_change",
            "team_profile_delete",
            "team_profile_reorder",
            "team_rename",
            "user_change",
            "user_typing",
        ]
        for event_type in rtm_events:
            try:
                event_handler = getattr(self, f"_rtm_handle_{event_type}")
                self.slack_rtm.on(event=event_type, callback=event_handler)
            except AttributeError:
                pass

    def _setup_event_callbacks(self):
        # List of events obtained from https://api.slack.com/events
        slack_event_types = [
            "app_home_opened",
            "app_mention",
            "app_rate_limited",
            "app_requested",
            "app_uninstalled",
            "call_rejected",
            "channel_archive",
            "channel_created",
            "channel_deleted",
            "channel_history_changed",
            "channel_left",
            "channel_rename",
            "channel_shared",
            "channel_unarchive",
            "channel_unshared",
            "dnd_updated",
            "dnd_updated_user",
            "email_domain_changed",
            "emoji_changed",
            "file_change",
            "file_comment_added",
            "file_comment_deleted",
            "file_comment_edited",
            "file_created",
            "file_deleted",
            "file_public",
            "file_shared",
            "file_unshared",
            "grid_migration_finished",
            "grid_migration_started",
            "group_archive",
            "group_close",
            "group_deleted",
            "group_history_changed",
            "group_left",
            "group_open",
            "group_rename",
            "group_unarchive",
            "im_close",
            "im_created",
            "im_history_changed",
            "im_open",
            "hello",
            "invite_requested",
            "link_shared",
            "member_joined_channel",
            "member_left_channel",
            "message",
            "message.app_home",
            "message.channels",
            "message.groups",
            "message.im",
            "message.mpim",
            "pin_added",
            "pin_removed",
            "reaction_added",
            "reaction_removed",
            "resources_added",
            "resources_removed",
            "scope_denied",
            "scope_granted",
            "star_added",
            "star_removed",
            "subteam_created",
            "subteam_members_changed",
            "subteam_self_added",
            "subteam_self_removed",
            "subteam_updated",
            "team_domain_change",
            "team_join",
            "team_rename",
            "tokens_revoked",
            "url_verification",
            "user_change",
            "user_resource_denied",
            "user_resource_granted",
            "user_resource_removed",
            "workflow_step_execute",
        ]
        for t in slack_event_types:
            self.slack_events.on(t, self._generic_wrapper)

        self.connect_callback()

    def serve_once(self):
        self.slack_web = WebClient(token=self.token, proxy=self.proxies)

        log.info("Verifying authentication token")
        self.auth = self.slack_web.auth_test()
        log.debug(f"Auth response: {self.auth}")
        if not self.auth["ok"]:
            raise SlackAPIResponseError(
                error=f"Couldn't authenticate with Slack. Server said: {self.auth['error']}"
            )
        log.info("Token accepted")
        self.bot_identifier = SlackPerson(self.slack_web, self.auth["user_id"])
        log.debug(self.bot_identifier)

        # Inject bot identity to alternative prefixes
        self.update_alternate_prefixes()

        # detect api type based on auth_test response
        is_rtm_api = "bot:basic" in self.auth.headers["x-oauth-scopes"]

        if is_rtm_api:
            log.info("Using RTM API")
            self.slack_rtm = RTMClient(
                token=self.token, proxy=self.proxies, auto_reconnect=False
            )

            @RTMClient.run_on(event="open")
            def get_bot_identity(**payload):
                self.bot_identifier = SlackPerson(
                    payload["web_client"], payload["data"]["self"]["id"]
                )
                # only hook up the message callback once we have our identity set.
                self._setup_rtm_callbacks()

        else:
            if not self.signing_secret:
                log.fatal(
                    'You need to set your signing_secret (found under "Bot Integration" on Slack)'
                    " in the BOT_IDENTITY setting in your configuration. Without this secret I "
                    "cannot receive events from Slack."
                )
                sys.exit(1)
            log.info("Using Events API")
            self.slack_events = SlackEventAdapter(
                self.signing_secret, "/slack/events", flask_app
            )
            self._setup_event_callbacks()

        try:
            if is_rtm_api:
                log.info("Connecting to Slack RTM API")
                self.slack_rtm.connect()
                log.info("************** UNBLOCKED **************")
            else:
                log.debug("Initialized, waiting for events")
                while True:
                    sleep(1)
        except KeyboardInterrupt:
            log.info("Interrupt received, shutting down..")
            return True
        except Exception:
            log.exception("Error reading from RTM stream:")
        finally:
            log.debug("Triggering disconnect callback")
            self.disconnect_callback()

    def _generic_wrapper(self, event_data):
        """Calls the event handler based on the event type"""
        log.debug("Received event: {}".format(str(event_data)))
        event = event_data["event"]
        event_type = event["type"]

        try:
            event_handler = getattr(self, f"_handle_{event_type}")
            return event_handler(self.slack_web, event)
        except AttributeError:
            log.info(f"Event type {event_type} not supported")

    def _rtm_handle_hello(self, **payload):
        """Event handler for the 'hello' event"""
        self.slack_web = payload["web_client"]
        self.connect_callback()
        self.callback_presence(Presence(identifier=self.bot_identifier, status=ONLINE))

    def _rtm_handle_goodbye(self, **payload):
        """Handle Slack server's intention to close the connection"""
        log.info("Received 'goodbye' from slack server.")
        self.slack_rtm.stop()

    def _rtm_handle_reaction_added(self, **payload):
        self._handle_reaction_added(payload["web_client"], payload["data"])

    def _handle_reaction_added(self, webclient: WebClient, event):
        """Event handler for the 'reaction_added' event"""
        emoji = event["reaction"]
        log.debug("Added reaction: {}".format(emoji))

    def _rtm_handle_reaction_removed(self, **payload):
        self._handle_reaction_removed(payload["web_client"], payload["data"])

    def _handle_reaction_removed(self, webclient: WebClient, event):
        """Event handler for the 'reaction_removed' event"""
        emoji = event["reaction"]
        log.debug("Removed reaction: {}".format(emoji))

    def _rtm_handle_presence_change(self, **payload):
        """Event handler for the 'presence_change' event"""
        event = payload["data"]
        idd = SlackPerson(payload["web_client"], event["user"])
        presence = event["presence"]
        # According to https://api.slack.com/docs/presence, presence can
        # only be one of 'active' and 'away'
        if presence == "active":
            status = ONLINE
        elif presence == "away":
            status = AWAY
        else:
            log.error(
                f"It appears the Slack API changed, I received an unknown presence type {presence}."
            )
            status = ONLINE
        self.callback_presence(Presence(identifier=idd, status=status))

    def _rtm_handle_message(self, **payload):
        self._handle_message(payload["web_client"], payload["data"])

    def _handle_message(self, webclient: WebClient, event):
        """Event handler for the 'message' event"""
        channel = event["channel"]
        if channel[0] not in "CGD":
            log.warning("Unknown message type! Unable to handle %s", channel)
            return

        subtype = event.get("subtype", None)

        if subtype in ("message_deleted", "channel_topic", "message_replied"):
            log.debug("Message of type %s, ignoring this event", subtype)
            return

        if subtype == "message_changed" and "attachments" in event["message"]:
            # If you paste a link into Slack, it does a call-out to grab details
            # from it so it can display this in the chatroom. These show up as
            # message_changed events with an 'attachments' key in the embedded
            # message. We should completely ignore these events otherwise we
            # could end up processing bot commands twice (user issues a command
            # containing a link, it gets processed, then Slack triggers the
            # message_changed event and we end up processing it again as a new
            # message. This is not what we want).
            log.debug(
                "Ignoring message_changed event with attachments, likely caused "
                "by Slack auto-expanding a link"
            )
            return
        text = event["text"]

        text, mentioned = self.process_mentions(text)

        text = self.sanitize_uris(text)

        log.debug("Saw an event: %s", pprint.pformat(event))
        log.debug("Escaped IDs event text: %s", text)

        msg = Message(
            text,
            extras={
                "attachments": event.get("attachments"),
                "slack_event": event,
            },
        )

        if channel.startswith("D"):
            if subtype == "bot_message":
                msg.frm = SlackBot(
                    webclient,
                    bot_id=event.get("bot_id"),
                    bot_username=event.get("username", ""),
                )
            else:
                msg.frm = SlackPerson(webclient, event["user"], event["channel"])
            msg.to = SlackPerson(
                webclient, self.bot_identifier.userid, event["channel"]
            )
            channel_link_name = event["channel"]
        else:
            if subtype == "bot_message":
                msg.frm = SlackRoomBot(
                    webclient,
                    bot_id=event.get("bot_id"),
                    bot_username=event.get("username", ""),
                    channelid=event["channel"],
                    bot=self,
                )
            else:
                msg.frm = SlackRoomOccupant(
                    webclient, event["user"], event["channel"], bot=self
                )
            msg.to = SlackRoom(
                webclient=webclient, channelid=event["channel"], bot=self
            )
            channel_link_name = msg.to.name

        # TODO: port to slack_sdk
        # msg.extras['url'] = f'https://{self.slack_web.server.domain}.slack.com/archives/' \
        #                     f'{channel_link_name}/p{self._ts_for_message(msg).replace(".", "")}'

        self.callback_message(msg)

        if mentioned:
            self.callback_mention(msg, mentioned)

    def _rtm_handle_member_joined_channel(self, **payload):
        self._handle_member_joined_channel(payload["web_client"], payload["data"])

    def _handle_member_joined_channel(self, webclient: WebClient, event):
        """Event handler for the 'member_joined_channel' event"""
        user = SlackPerson(webclient, event["user"])
        if user == self.bot_identifier:
            self.callback_room_joined(
                SlackRoom(webclient=webclient, channelid=event["channel"], bot=self)
            )

    def userid_to_username(self, id_: str):
        """Convert a Slack user ID to their user name"""
        user = self.slack_web.users_info(user=id_)["user"]
        if user is None:
            raise UserDoesNotExistError(f"Cannot find user with ID {id_}.")
        return user["name"]

    def username_to_userid(self, name: str):
        """Convert a Slack user name to their user ID"""
        name = name.lstrip("@")
        user = [
            user
            for user in self.slack_web.users_list()["members"]
            if user["name"] == name
        ]
        if user == []:
            raise UserDoesNotExistError(f"Cannot find user {name}.")
        if len(user) > 1:
            log.error(
                "Failed to uniquely identify '{}'.  Errbot found the following users: {}".format(
                    name, " ".join(["{}={}".format(u["name"], u["id"]) for u in user])
                )
            )
            raise UserNotUniqueError(f"Failed to uniquely identify {name}.")
        return user[0]["id"]

    def channelid_to_channelname(self, id_: str):
        """Convert a Slack channel ID to its channel name"""
        channel = self.slack_web.conversations_info(channel=id_)["channel"]
        if channel is None:
            raise RoomDoesNotExistError(f"No channel with ID {id_} exists.")
        return channel["name"]

    def channelname_to_channelid(self, name: str):
        """Convert a Slack channel name to its channel ID"""
        name = name.lstrip("#")
        channel = [
            channel
            for channel in self.slack_web.conversations_list()["channels"]
            if channel["name"] == name
        ]
        if not channel:
            raise RoomDoesNotExistError(f"No channel named {name} exists")
        return channel[0]["id"]

    def channels(self, exclude_archived=True, joined_only=False):
        """
        Get all channels and groups and return information about them.

        :param exclude_archived:
            Exclude archived channels/groups
        :param joined_only:
            Filter out channels the bot hasn't joined
        :returns:
            Lists all channels in a Slack team and conversations the calling user may access.
            References:
                - https://slack.com/api/conversations.list
                - https://slack.com/api/users.conversations
        """
        response = self.slack_web.conversations_list(exclude_archived=exclude_archived)
        channels = [
            channel
            for channel in response["channels"]
            if channel["is_member"] or not joined_only
        ]

        response = self.slack_web.users_conversations(exclude_archived=exclude_archived)
        # No need to filter for 'is_member' in this next call (it doesn't
        # (even exist) because leaving a group means you have to get invited
        # back again by somebody else.
        groups = [group for group in response["groups"]]

        return channels + groups

    @lru_cache(1024)
    def get_im_channel(self, id_):
        """Open a direct message channel to a user"""
        try:
            response = self.slack_web.conversations_open(user=id_)
            return response["channel"]["id"]
        except SlackAPIResponseError as e:
            if e.error == "cannot_dm_bot":
                log.info("Tried to DM a bot.")
                return None
            else:
                raise e

    def _prepare_message(self, msg):  # or card
        """
        Translates the common part of messaging for Slack.
        :param msg: the message you want to extract the Slack concept from.
        :return: a tuple to user human readable, the channel id
        """
        if msg.is_group:
            to_channel_id = msg.to.id
            to_humanreadable = (
                msg.to.name
                if msg.to.name
                else self.channelid_to_channelname(to_channel_id)
            )
        else:
            to_humanreadable = msg.to.username
            to_channel_id = msg.to.channelid
            if to_channel_id.startswith("C"):
                log.debug(
                    "This is a divert to private message, sending it directly to the user."
                )
                to_channel_id = self.get_im_channel(
                    self.username_to_userid(msg.to.username)
                )
        return to_humanreadable, to_channel_id

    def send_message(self, msg):
        super().send_message(msg)

        if msg.parent is not None:
            # we are asked to reply to a specify thread.
            try:
                msg.extras["thread_ts"] = self._ts_for_message(msg.parent)
            except KeyError:
                # Gives to the user a more interesting explanation if we cannot find a ts from the parent.
                log.exception(
                    "The provided parent message is not a Slack message "
                    "or does not contain a Slack timestamp."
                )

        to_humanreadable = "<unknown>"
        try:
            if msg.is_group:
                to_channel_id = msg.to.id
                to_humanreadable = (
                    msg.to.name
                    if msg.to.name
                    else self.channelid_to_channelname(to_channel_id)
                )
            else:
                to_humanreadable = msg.to.username
                if isinstance(
                    msg.to, RoomOccupant
                ):  # private to a room occupant -> this is a divert to private !
                    log.debug(
                        "This is a divert to private message, sending it directly to the user."
                    )
                    to_channel_id = self.get_im_channel(
                        self.username_to_userid(msg.to.username)
                    )
                else:
                    to_channel_id = msg.to.channelid

            msgtype = "direct" if msg.is_direct else "channel"
            log.debug(
                "Sending %s message to %s (%s).",
                msgtype,
                to_humanreadable,
                to_channel_id,
            )
            body = self.md.convert(msg.body)
            log.debug("Message size: %d.", len(body))

            parts = self.prepare_message_body(body, self.message_size_limit)

            timestamps = []
            for part in parts:
                data = {
                    "channel": to_channel_id,
                    "text": part,
                    "unfurl_media": "true",
                    "link_names": "1",
                    "as_user": "true",
                }

                # Keep the thread_ts to answer to the same thread.
                if "thread_ts" in msg.extras:
                    data["thread_ts"] = msg.extras["thread_ts"]

                result = self.slack_web.chat_postMessage(**data)
                timestamps.append(result["ts"])

            msg.extras["ts"] = timestamps
        except Exception:
            log.exception(
                f"An exception occurred while trying to send the following message "
                f"to {to_humanreadable}: {msg.body}."
            )

    def _slack_upload(self, stream: Stream) -> None:
        """
        Performs an upload defined in a stream
        :param stream: Stream object
        :return: None
        """
        try:
            stream.accept()
            resp = self.slack_web.files_upload(
                channels=stream.identifier.channelid, filename=stream.name, file=stream
            )
            if "ok" in resp and resp["ok"]:
                stream.success()
            else:
                stream.error()
        except Exception:
            log.exception(
                f"Upload of {stream.name} to {stream.identifier.channelname} failed."
            )

    def send_stream_request(
        self,
        user: Identifier,
        fsource: BinaryIO,
        name: str = None,
        size: int = None,
        stream_type: str = None,
    ) -> Stream:
        """
        Starts a file transfer. For Slack, the size and stream_type are unsupported

        :param user: is the identifier of the person you want to send it to.
        :param fsource: is a file object you want to send.
        :param name: is an optional filename for it.
        :param size: not supported in Slack backend
        :param stream_type: not supported in Slack backend

        :return Stream: object on which you can monitor the progress of it.
        """
        stream = Stream(user, fsource, name, size, stream_type)
        log.debug(
            "Requesting upload of %s to %s (size hint: %d, stream type: %s).",
            name,
            user.channelname,
            size,
            stream_type,
        )
        self.thread_pool.apply_async(self._slack_upload, (stream,))
        return stream

    def send_card(self, card: Card):
        if isinstance(card.to, RoomOccupant):
            card.to = card.to.room
        to_humanreadable, to_channel_id = self._prepare_message(card)
        attachment = {}
        if card.summary:
            attachment["pretext"] = card.summary
        if card.title:
            attachment["title"] = card.title
        if card.link:
            attachment["title_link"] = card.link
        if card.image:
            attachment["image_url"] = card.image
        if card.thumbnail:
            attachment["thumb_url"] = card.thumbnail

        if card.color:
            attachment["color"] = (
                COLORS[card.color] if card.color in COLORS else card.color
            )

        if card.fields:
            attachment["fields"] = [
                {"title": key, "value": value, "short": True}
                for key, value in card.fields
            ]

        parts = self.prepare_message_body(card.body, self.message_size_limit)
        part_count = len(parts)
        footer = attachment.get("footer", "")
        for i in range(part_count):
            if part_count > 1:
                attachment["footer"] = f"{footer} [{i + 1}/{part_count}]"
            attachment["text"] = parts[i]
            data = {
                "channel": to_channel_id,
                "attachments": json.dumps([attachment]),
                "link_names": "1",
                "as_user": "true",
            }
            try:
                log.debug("Sending data:\n%s", data)
                self.slack_web.chat_postMessage(**data)
            except Exception:
                log.exception(
                    f"An exception occurred while trying to send a card to {to_humanreadable}.[{card}]"
                )

    def __hash__(self):
        return 0  # this is a singleton anyway

    def change_presence(self, status: str = ONLINE, message: str = "") -> None:
        self.slack_web.users_setPresence(
            presence="auto" if status == ONLINE else "away"
        )

    @staticmethod
    def prepare_message_body(body, size_limit):
        """
        Returns the parts of a message chunked and ready for sending.

        This is a staticmethod for easier testing.

        Args:
            body (str)
            size_limit (int): chunk the body into sizes capped at this maximum

        Returns:
            [str]

        """
        fixed_format = body.startswith("```")  # hack to fix the formatting
        parts = list(split_string_after(body, size_limit))

        if len(parts) == 1:
            # If we've got an open fixed block, close it out
            if parts[0].count("```") % 2 != 0:
                parts[0] += "\n```\n"
        else:
            for i, part in enumerate(parts):
                starts_with_code = part.startswith("```")

                # If we're continuing a fixed block from the last part
                if fixed_format and not starts_with_code:
                    parts[i] = "```\n" + part

                # If we've got an open fixed block, close it out
                if part.count("```") % 2 != 0:
                    parts[i] += "\n```\n"

        return parts

    @staticmethod
    def extract_identifiers_from_string(text):
        """
        Parse a string for Slack user/channel IDs.

        Supports strings with the following formats::

            <#C12345>
            <@U12345>
            <@U12345|user>
            @user
            #channel/user
            #channel

        Returns the tuple (username, userid, channelname, channelid).
        Some elements may come back as None.
        """
        exception_message = (
            "Unparseable slack identifier, should be of the format `<#C12345>`, `<@U12345>`, "
            "`<@U12345|user>`, `@user`, `#channel/user` or `#channel`. (Got `%s`)"
        )
        text = text.strip()

        if text == "":
            raise ValueError(exception_message % "")

        channelname = None
        username = None
        channelid = None
        userid = None

        if text[0] == "<" and text[-1] == ">":
            exception_message = (
                "Unparseable slack ID, should start with U, B, C, G, D or W (got `%s`)"
            )
            text = text[2:-1]
            if text == "":
                raise ValueError(exception_message % "")
            if text[0] in ("U", "B", "W"):
                if "|" in text:
                    userid, username = text.split("|")
                else:
                    userid = text
            elif text[0] in ("C", "G", "D"):
                channelid = text
            else:
                raise ValueError(exception_message % text)
        elif text[0] == "@":
            username = text[1:]
        elif text[0] == "#":
            plainrep = text[1:]
            if "/" in text:
                channelname, username = plainrep.split("/", 1)
            else:
                channelname = plainrep
        else:
            raise ValueError(exception_message % text)

        return username, userid, channelname, channelid

    def build_identifier(self, txtrep):
        """
        Build a :class:`SlackIdentifier` from the given string txtrep.

        Supports strings with the formats accepted by
        :func:`~extract_identifiers_from_string`.
        """
        log.debug("building an identifier from %s.", txtrep)
        username, userid, channelname, channelid = self.extract_identifiers_from_string(
            txtrep
        )

        if userid is None and username is not None:
            userid = self.username_to_userid(username)
        if channelid is None and channelname is not None:
            channelid = self.channelname_to_channelid(channelname)
        if userid is not None and channelid is not None:
            return SlackRoomOccupant(self.slack_web, userid, channelid, bot=self)
        if userid is not None:
            return SlackPerson(self.slack_web, userid, self.get_im_channel(userid))
        if channelid is not None:
            return SlackRoom(webclient=self.slack_web, channelid=channelid, bot=self)

        raise Exception(
            "You found a bug. I expected at least one of userid, channelid, username or channelname "
            "to be resolved but none of them were. This shouldn't happen so, please file a bug."
        )

    def is_from_self(self, msg: Message) -> bool:
        return self.bot_identifier.userid == msg.frm.userid

    def build_reply(self, msg, text=None, private=False, threaded=False):
        response = self.build_message(text)

        if "thread_ts" in msg.extras["slack_event"]:
            # If we reply to a threaded message, keep it in the thread.
            response.extras["thread_ts"] = msg.extras["slack_event"]["thread_ts"]
        elif threaded:
            # otherwise check if we should start a new thread
            response.parent = msg

        response.frm = self.bot_identifier
        if private:
            response.to = msg.frm
        else:
            response.to = msg.frm.room if isinstance(msg.frm, RoomOccupant) else msg.frm
        return response

    def add_reaction(self, msg: Message, reaction: str) -> None:
        """
        Add the specified reaction to the Message if you haven't already.
        :param msg: A Message.
        :param reaction: A str giving an emoji, without colons before and after.
        :raises: ValueError if the emoji doesn't exist.
        """
        return self._react("reactions.add", msg, reaction)

    def remove_reaction(self, msg: Message, reaction: str) -> None:
        """
        Remove the specified reaction from the Message if it is currently there.
        :param msg: A Message.
        :param reaction: A str giving an emoji, without colons before and after.
        :raises: ValueError if the emoji doesn't exist.
        """
        return self._react("reactions.remove", msg, reaction)

    def _react(self, method: str, msg: Message, reaction: str) -> None:
        try:
            # this logic is from send_message
            if msg.is_group:
                to_channel_id = msg.to.id
            else:
                to_channel_id = msg.to.channelid

            ts = self._ts_for_message(msg)

            self.api_call(
                method,
                data={"channel": to_channel_id, "timestamp": ts, "name": reaction},
            )
        except SlackAPIResponseError as e:
            if e.error == "invalid_name":
                raise ValueError(e.error, "No such emoji", reaction)
            elif e.error in ("no_reaction", "already_reacted"):
                # This is common if a message was edited after you reacted to it, and you reacted to it again.
                # Chances are you don't care about this. If you do, call api_call() directly.
                pass
            else:
                raise SlackAPIResponseError(error=e.error)

    def _ts_for_message(self, msg):
        try:
            return msg.extras["slack_event"]["message"]["ts"]
        except KeyError:
            return msg.extras["slack_event"]["ts"]

    def shutdown(self):
        if self.slack_rtm:
            self.slack_rtm.stop()
        super().shutdown()

    @property
    def mode(self):
        return "slackv3"

    def query_room(self, room):
        """ Room can either be a name or a channelid """
        if room.startswith("C") or room.startswith("G"):
            return SlackRoom(webclient=self.slack_web, channelid=room, bot=self)

        m = SLACK_CLIENT_CHANNEL_HYPERLINK.match(room)
        if m is not None:
            return SlackRoom(
                webclient=self.slack_web, channelid=m.groupdict()["id"], bot=self
            )

        return SlackRoom(webclient=self.slack_web, name=room, bot=self)

    def rooms(self):
        """
        Return a list of rooms the bot is currently in.

        :returns:
            A list of :class:`~SlackRoom` instances.
        """
        channels = self.channels(joined_only=True, exclude_archived=True)
        return [
            SlackRoom(webclient=self.slack_web, channelid=channel["id"], bot=self)
            for channel in channels
        ]

    def prefix_groupchat_reply(self, message, identifier):
        super().prefix_groupchat_reply(message, identifier)
        message.body = f"@{identifier.nick}: {message.body}"

    @staticmethod
    def sanitize_uris(text):
        """
        Sanitizes URI's present within a slack message. e.g.
        <mailto:example@example.org|example@example.org>,
        <http://example.org|example.org>
        <http://example.org>

        :returns:
            string
        """
        text = re.sub(r"<([^|>]+)\|([^|>]+)>", r"\2", text)
        text = re.sub(r"<(http([^>]+))>", r"\1", text)

        return text

    def process_mentions(self, text):
        """
        Process mentions in a given string
        :returns:
            A formatted string of the original message
            and a list of any :class:`~SlackPerson` or
            :class:`~SlackRoom` instances.
        """
        mentioned = []

        m = re.findall("<[@#][^>]*>*", text)

        for word in m:
            try:
                identifier = self.build_identifier(word)
            except Exception as e:
                log.debug(
                    f"Tried to build an identifier from '{word}' "
                    f"but got exception: {e}"
                )
                continue

            # We track mentions of persons and rooms.
            if isinstance(identifier, SlackPerson):
                log.debug(f'Someone mentioned user {identifier}')
                mentioned.append(identifier)
                text = text.replace(word, f'@{identifier.userid}')
            elif isinstance(identifier, SlackRoom):
                log.debug(f'Someone mentioned channel {identifier}')
                mentioned.append(identifier)
                text = text.replace(word, f'#{identifier.channelid}')

        return text, mentioned


class SlackRoom(Room):
    def __init__(self, webclient=None, name=None, channelid=None, bot=None):
        if channelid is not None and name is not None:
            raise ValueError("channelid and name are mutually exclusive")

        if name is not None:
            if name.startswith("#"):
                self._name = name[1:]
            else:
                self._name = name
        else:
            self._name = bot.channelid_to_channelname(channelid)

        self._id = channelid
        self._bot = bot
        self.slack_web = webclient

    def __str__(self):
        return f"#{self.name}"

    @property
    def channelname(self):
        return self._name

    @property
    def _channel(self):
        """
        The channel object exposed by SlackClient
        """
        _id = None
        # Cursors
        cursor = ""
        while cursor is not None:
            conversations_list = self.slack_web.conversations_list(cursor=cursor)
            cursor = None
            for channel in conversations_list["channels"]:
                if channel["name"] == self.name:
                    _id = channel["id"]
                    break
            else:
                if conversations_list["response_metadata"]["next_cursor"] is not None:
                    cursor = conversations_list["response_metadata"]["next_cursor"]
                else:
                    raise RoomDoesNotExistError(
                        f"{str(self)} does not exist (or is a private group you don't have access to)"
                    )
        return _id

    @property
    def _channel_info(self):
        """
        Channel info as returned by the Slack API.

        See also:
          * https://api.slack.com/methods/channels.list
          * https://api.slack.com/methods/groups.list
        """
        return self._bot.slack_web.conversations_info(channel=self.id)["channel"]

    @property
    def private(self):
        """Return True if the room is a private group"""
        return self._channel_info["is_private"]

    @property
    def id(self):
        """Return the ID of this room"""
        if self._id is None:
            self._id = self._channel
        return self._id

    @property
    def name(self):
        """Return the name of this room"""
        return self._name

    def join(self, username=None, password=None):
        log.info("Joining channel '{}'".format(self.name))
        join_failure = True
        try:
            self._bot.slack_web.conversations_join(channel=self.id)
            join_failure = False
        except SlackApiError as e:
            log.error(f"Unable to join '{self.name}'. Slack API Error {str(e)}")
        except BotUserAccessError as e:
            log.error(f"OAuthv1 bot token not allowed to join channels. '{self.name}'.")

        if join_failure:
            raise RoomError(f"Unable to join channel. {USER_IS_BOT_HELPTEXT}")

    def leave(self, reason=None):
        try:
            log.info("Leaving conversation %s (%s)", self, self.id)
            self._bot.slack_web.conversations_leave(channel=self.id)
        except SlackAPIResponseError as e:
            if e.error == "user_is_bot":
                raise RoomError(f"Unable to leave channel. {USER_IS_BOT_HELPTEXT}")
            else:
                raise RoomError(e)
        self._id = None

    def create(self, private=False):
        try:
            if private:
                log.info("Creating private conversation %s.", self)
                self._bot.slack_web.conversations_create(
                    name=self.name, is_private=True
                )
            else:
                log.info("Creating conversation %s.", self)
                self._bot.slack_web.conversations_create(name=self.name)
        except SlackAPIResponseError as e:
            if e.error == "user_is_bot":
                raise RoomError(f"Unable to create channel. {USER_IS_BOT_HELPTEXT}")
            else:
                raise RoomError(e)

    def destroy(self):
        try:
            log.info("Archiving conversation %s (%s)", self, self.id)
            self._bot.slack_web.conversations_archive(self.id)
        except SlackAPIResponseError as e:
            if e.error == "user_is_bot":
                raise RoomError(f"Unable to archive channel. {USER_IS_BOT_HELPTEXT}")
            else:
                raise RoomError(e)
        self._id = None

    @property
    def exists(self):
        channels = self._bot.channels(joined_only=False, exclude_archived=False)
        return len([c for c in channels if c["name"] == self.name]) > 0

    @property
    def joined(self):
        channels = self._bot.channels(joined_only=True)
        return len([c for c in channels if c["name"] == self.name]) > 0

    @property
    def topic(self):
        if self._channel_info["topic"]["value"] == "":
            return None
        else:
            return self._channel_info["topic"]["value"]

    @topic.setter
    def topic(self, topic):
        if self.private:
            log.info("Setting topic of %s (%s) to %s.", self, self.id, topic)
            self._bot.api_call(
                "groups.setTopic", data={"channel": self.id, "topic": topic}
            )
        else:
            log.info("Setting topic of %s (%s) to %s.", self, self.id, topic)
            self._bot.api_call(
                "channels.setTopic", data={"channel": self.id, "topic": topic}
            )

    @property
    def purpose(self):
        if self._channel_info["purpose"]["value"] == "":
            return None
        else:
            return self._channel_info["purpose"]["value"]

    @purpose.setter
    def purpose(self, purpose):
        if self.private:
            log.info("Setting purpose of %s (%s) to %s.", self, self.id, purpose)
            self._bot.api_call(
                "groups.setPurpose", data={"channel": self.id, "purpose": purpose}
            )
        else:
            log.info("Setting purpose of %s (%s) to %s.", str(self), self.id, purpose)
            self._bot.api_call(
                "channels.setPurpose", data={"channel": self.id, "purpose": purpose}
            )

    @property
    def occupants(self):
        members = self._channel_info["members"]
        return [
            SlackRoomOccupant(self.slack_web, m, self.id, self._bot) for m in members
        ]

    def invite(self, *args):
        users = {
            user["name"]: user["id"]
            for user in self._bot.api_call("users.list")["members"]
        }
        for user in args:
            if user not in users:
                raise UserDoesNotExistError(f'User "{user}" not found.')
            log.info("Inviting %s into %s (%s)", user, self, self.id)
            method = "groups.invite" if self.private else "channels.invite"
            response = self._bot.api_call(
                method,
                data={"channel": self.id, "user": users[user]},
                raise_errors=False,
            )

            if not response["ok"]:
                if response["error"] == "user_is_bot":
                    raise RoomError(f"Unable to invite people. {USER_IS_BOT_HELPTEXT}")
                elif response["error"] != "already_in_channel":
                    raise SlackAPIResponseError(
                        error=f'Slack API call to {method} failed: {response["error"]}.'
                    )

    def __eq__(self, other):
        if not isinstance(other, SlackRoom):
            return False
        return self.id == other.id
