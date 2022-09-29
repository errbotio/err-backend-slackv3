import copyreg
import json
import logging
import pprint
import re
import sys
import threading
from functools import lru_cache
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
    UserNotUniqueError,
)
from errbot.core import ErrBot
from errbot.core_plugins import flask_app
from errbot.utils import split_string_after

log = logging.getLogger(__name__)

try:
    from slack_sdk.errors import BotUserAccessError, SlackApiError
    from slack_sdk.rtm.v2 import RTMClient
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
    from slack_sdk.web import WebClient
    from slackeventsapi import SlackEventAdapter
except ImportError:
    log.exception("Could not start the SlackV3 backend")
    log.fatal(
        "You need to install python modules in order to use the Slack backend.\n"
        "You can do `pip install errbot-backend-slackv3` to install them."
    )
    sys.exit(1)

from slackv3._slack.lib import (
    COLORS,
    SLACK_CLIENT_CHANNEL_HYPERLINK,
    USER_IS_BOT_HELPTEXT,
    SlackAPIResponseError,
)
from slackv3._slack.markdown import slack_markdown_converter
from slackv3._slack.person import SlackPerson
from slackv3._slack.room import SlackBot, SlackRoom, SlackRoomBot, SlackRoomOccupant


class SlackBackend(ErrBot):
    def __init__(self, config):
        super().__init__(config)
        identity = config.BOT_IDENTITY
        self.token = identity.get("token", None)
        self.proxies = identity.get("proxies", None)

        if not self.token:
            log.fatal(
                'You need to set your token (found under "OAuth & Permissions" on Slack) in '
                "the BOT_IDENTITY setting in your configuration.  Without this token I "
                "cannot connect to Slack."
            )
            sys.exit(1)

        self.signing_secret = identity.get("signing_secret", None)
        self.app_token = identity.get("app_token", None)

        # Slack objects will be initialised in the serve_once method.
        self.auth = None
        self.slack_web = None
        self.slack_rtm = None
        self.slack_events = None
        self.slack_socket_mode = None
        self.bot_identifier = None

        compact = config.COMPACT_OUTPUT if hasattr(config, "COMPACT_OUTPUT") else False
        self.md = slack_markdown_converter(compact)
        self._register_identifiers_pickling()

    def set_message_size_limit(self, limit=4096, hard_limit=40000):
        """
        Slack supports upto 40000 characters per message, Errbot maintains 4096 by default.
        """
        super().set_message_size_limit(limit, hard_limit)

    def api_call(self, method, data=None, raise_errors=True):
        """
        Make an API call to the Slack API and return response data.

        This is a thin wrapper around `SlackClient.server.api_call`.

        :param method:
            The API method to invoke (see https://api.slack.com/methods/).
        :param raise_errors:
            Whether to raise :class:`~SlackAPIResponseError` if the API
            returns an error
        :param data:
            A dictionary with data to pass along in the API request.
        :returns:
            A dictionary containing the (JSON-decoded) API response
        :raises:
            :class:`~SlackAPIResponseError` if raise_errors is True and the
            API responds with `{"ok": false}`
        """
        if data is None:
            data = {}

        response = self.slack_web.api_call(method, **data)

        if raise_errors and not response["ok"]:
            raise SlackAPIResponseError(
                f"Slack API call to {method} failed: {response['error']}",
                error=response["error"],
            )
        return response

    @staticmethod
    def _unpickle_identifier(identifier_str):
        return SlackBackend.__build_identifier(identifier_str)

    @staticmethod
    def _pickle_identifier(identifier):
        return SlackBackend._unpickle_identifier, (str(identifier),)

    def _register_identifiers_pickling(self):
        """
        Register identifiers pickling.

        As Slack needs live objects in its identifiers, we need to override their pickling
        behavior. But for the unpickling to work we need to use bot.build_identifier, hence the bot
        parameter here. But then we also need bot for the unpickling so we save it here at module
        level.
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
                    f'Failed to look up Slack userid for alternate prefix "{prefix}": {str(e)}'
                )

        self.bot_alt_prefixes = tuple(
            x.lower() for x in self.bot_config.BOT_ALT_PREFIXES
        )
        log.debug(f"Converted bot_alt_prefixes: {self.bot_config.BOT_ALT_PREFIXES}")

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
            # slacksdk checks for duplicates only when passing a list of callbacks
            self.slack_events.on(t, self._generic_wrapper)

        self.connect_callback()

    def serve_once(self):
        self.slack_web = WebClient(token=self.token, proxy=self.proxies)

        log.info("Verifying authentication token")
        self.auth = self.slack_web.auth_test()
        log.debug(f"Auth response: {self.auth}")
        if not self.auth["ok"]:
            raise SlackAPIResponseError(
                error=f"Failed to authenticate with Slack.  Slack Error: {self.auth['error']}"
            )
        log.info("Token accepted")
        self.bot_identifier = SlackPerson(self.slack_web, self.auth["user_id"])
        log.debug(self.bot_identifier)

        # Inject bot identity to alternative prefixes
        self.update_alternate_prefixes()

        # detect legacy and classic bot based on auth_test response (https://api.slack.com/scopes)
        if set(
            [
                "apps",
                "bot",
                "bot:basic",
                "client",
                "files:write:user",
                "identify",
                "post",
                "read",
            ]
        ).issuperset(self.auth.headers["x-oauth-scopes"].split(",")):
            log.info("Using RTM API.")
            self.slack_rtm = RTMClient(
                token=self.token,
                proxy=self.proxies,
                auto_reconnect_enabled=True,
            )

            @self.slack_rtm.on("*")
            def _rtm_generic_event_handler(client: RTMClient, event: dict):
                """Calls the rtm event handler based on the event type"""
                log.debug("Received rtm event: {}".format(str(event)))
                event_type = event["type"]
                try:
                    event_handler = getattr(self, f"_rtm_handle_{event_type}")
                    return event_handler(client, event)
                except AttributeError as e:
                    log.debug(f"RTM event type {event_type} not supported.")

            log.info("Connecting to Slack RTM API")
            self.slack_rtm.connect()
        else:
            # If the Application token is set, run in socket mode otherwise use Request URL.
            if self.app_token:
                log.info("Using Events API - Socket mode client.")
                self.slack_socket_mode = SocketModeClient(
                    app_token=self.app_token,
                    web_client=self.slack_web,
                    on_message_listeners=[self._sm_handle_hello],
                )
                self.slack_socket_mode.message_listeners.append(self._sm_handle_hello)
                self.slack_socket_mode.socket_mode_request_listeners.append(
                    self._sm_generic_event_handler
                )
                # TODO: The socket_mode listener will need to gracefully handle disconnections.
                self.slack_socket_mode.connect()
            else:
                log.info("Using Events API - HTTP listener for request URLs.")
                if not self.signing_secret:
                    log.fatal(
                        "The BOT_IDENTITY doesn't contain the signing_secret.  Errbot can not "
                        "receive events without this value.  Check the installation "
                        "documentation for guidance and review the bot's configuration settings."
                    )
                    sys.exit(1)
                self.slack_events = SlackEventAdapter(
                    self.signing_secret, "/slack/events", flask_app
                )
                self._setup_event_callbacks()

        try:
            log.debug("Initialised, waiting for events.")
            # Block here to remain in serve_once().
            threading.Event().wait()
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
        try:
            event = event_data["event"]
            event_type = event["type"]

            try:
                event_handler = getattr(self, f"_handle_{event_type}")
                return event_handler(self.slack_web, event)
            except AttributeError:
                log.debug(f"Event type {event_type} not supported.")
        except KeyError:
            log.debug("Ignoring unsupported Slack event!")

    def _sm_generic_event_handler(
        self, client: SocketModeClient, req: SocketModeRequest
    ):
        log.debug(
            f"Event type: {req.type}\n"
            f"Envelope ID: {req.envelope_id}\n"
            f"Accept Response Payload: {req.accepts_response_payload}\n"
            f"Retry Attempt: {req.retry_attempt}\n"
            f"Retry Reason: {req.retry_reason}\n"
        )
        # Acknowledge the request
        client.send_socket_mode_response(
            SocketModeResponse(envelope_id=req.envelope_id)
        )
        # Dispatch event to the Event API generic event handler.
        self._generic_wrapper(req.payload)

    def _sm_handle_hello(self, *args):
        # Workaround socket-mode client calling handler twice with different signatures.
        if len(args) == 3:
            sm_client, event, raw_event = args
            log.debug(f"message listeners : {sm_client.message_listeners}")
            if event["type"] == "hello":
                self.connect_callback()
                self.callback_presence(
                    Presence(identifier=self.bot_identifier, status=ONLINE)
                )
                # Stop calling hello handler for future events.
                sm_client.message_listeners.remove(self._sm_handle_hello)
                log.info("Unregistered 'hello' handler from socket-mode client")

    def _rtm_handle_hello(self, client: RTMClient, event: dict):
        """Event handler for the 'hello' event"""
        self.slack_web = client.web_client
        self.connect_callback()
        self.callback_presence(Presence(identifier=self.bot_identifier, status=ONLINE))

    def _rtm_handle_goodbye(self, client: RTMClient, event: dict):
        """Handle Slack server's intention to close the connection"""
        log.info("Received 'goodbye' from slack server.")
        log.debug("Disconnect from Slack RTM API")
        self.slack_rtm.disconnect()
        self.disconnect_callback()
        log.debug("Connect to Slack RTM API")
        self.slack_rtm.connect()

    def _rtm_handle_message(self, client: RTMClient, event: dict):
        self._handle_message(client.web_client, event)

    def _rtm_handle_open(self, client: RTMClient, event: dict):
        """Register the bot identity when the RTM connection is established."""
        self.bot_identifier = SlackPerson(client.web_client, event["self"]["id"])

    def _rtm_handle_presence_change(self, client: RTMClient, event: dict):
        """Event handler for the 'presence_change' event"""
        idd = SlackPerson(client.web_client, event["user"])
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

    def _rtm_handle_reaction_added(self, client: RTMClient, event: dict):
        self._handle_reaction_added(client.web_client, event)

    def _rtm_handle_reaction_removed(self, client: RTMClient, event: dict):
        self._handle_reaction_removed(client.web_client, event)

    def _handle_reaction_added(self, webclient: WebClient, event):
        """Event handler for the 'reaction_added' event"""
        self._handle_reaction_event(event, REACTION_ADDED)

    def _handle_reaction_removed(self, webclient: WebClient, event):
        """Event handler for the 'reaction_removed' event"""
        self._handle_reaction_event(event, REACTION_REMOVED)

    def _handle_reaction_event(self, event, action):
        """Event handler for the 'reaction_added' and 'reaction_removed' events"""
        log.debug("Reaction: {} {}".format(event["type"], event["reaction"]))
        user = SlackPerson(self.slack_web, event["user"])

        item_user = event.get("item_user")
        if item_user:
            item_user = SlackPerson(self.slack_web, item_user)

        reaction = Reaction(
            reactor=user,
            reacted_to_owner=item_user,
            action=action,
            timestamp=event["event_ts"],
            reaction_name=event["reaction"],
            reacted_to=event["item"],
        )

        self.callback_reaction(reaction)

    def _handle_message(self, webclient: WebClient, event):
        """Event handler for the 'message' event"""
        channel = event["channel"]
        if channel[0] not in "CGD":
            log.warning(f"Unknown message type! Unable to handle {channel}")
            return

        subtype = event.get("subtype", None)

        if subtype in ("message_deleted", "channel_topic", "message_replied"):
            log.debug(f"Message of type {subtype}, ignoring this event")
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
                "by Slack auto-expanding a link."
            )
            return

        if "message" in event:
            text = event["message"].get("text", "")
            user = event["message"].get("user", event.get("bot_id"))
        else:
            text = event.get("text", "")
            user = event.get("user", event.get("bot_id"))

        text, mentioned = self.process_mentions(text)
        text = self.sanitize_uris(text)

        log.debug(f"Saw an event: {pprint.pformat(event)}")
        log.debug(f"Escaped IDs event text: {text}")

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
                msg.to = SlackPerson(webclient, user, channel)
            else:
                if user == self.bot_identifier.userid:
                    msg.frm = self.bot_identifier
                    msg.to = self.bot_identifier
                else:
                    msg.frm = SlackPerson(webclient, user, channel)
                    msg.to = msg.frm
            msg.extras["url"] = (
                f"https://{msg.frm.domain}.slack.com/archives/"
                f'{event["channel"]}/p{self._ts_for_message(msg).replace(".", "")}'
            )
        else:
            if subtype == "bot_message":
                msg.frm = SlackRoomBot(
                    webclient,
                    bot_id=event.get("bot_id"),
                    bot_username=event.get("username", ""),
                    channelid=channel,
                    bot=self,
                )
                msg.to = SlackRoom(webclient=webclient, channelid=channel, bot=self)
            else:
                if user == self.bot_identifier.userid:
                    msg.frm = self.bot_identifier
                    msg.to = self.bot_identifier
                else:
                    msg.to = SlackRoom(webclient=webclient, channelid=channel, bot=self)
                    msg.frm = SlackRoomOccupant(webclient, user, channel, self)

        self.callback_message(msg)

        if mentioned:
            self.callback_mention(msg, mentioned)

    def _rtm_handle_member_joined_channel(self, client: RTMClient, event: dict):
        self._handle_member_joined_channel(client.web_client, event)

    def _handle_member_joined_channel(self, webclient: WebClient, event):
        """Event handler for the 'member_joined_channel' event"""
        user = SlackPerson(webclient, event["user"])
        if user == self.bot_identifier:
            self.callback_room_joined(
                SlackRoom(webclient=webclient, channelid=event["channel"], bot=self)
            )

    def userid_to_username(self, id_: str):
        """Convert a Slack user ID to their user name"""
        return SlackPerson(self.slack_web, userid=id_).username

    def username_to_userid(self, name: str):
        """
        Convert a Slack user name to their user ID

        Raises:
            UserNotFoundError when no matches are found.
            UserNotUniqueError when multiple names are found.
        Returns:
            User_id if and only if a single username is matched.
        """
        username = name.lstrip("@")
        if username == self.auth["user"]:
            return self.bot_identifier.userid
        user_ids = []
        cursor = None
        while cursor != "":
            res = self.slack_web.users_list(cursor=cursor, limit=1000)
            if res["ok"] is False:
                log.exception(f"Unable to list users.  Slack error: {res['error']}")
            for user in res["members"]:
                if user["name"] == username:
                    user_ids.append(user["id"])
            else:
                cursor = res["response_metadata"].get("next_cursor", "")
        if len(user_ids) == 0:
            raise UserDoesNotExistError(f"Cannot find user '{username}'.")
        if len(user_ids) > 1:
            raise UserNotUniqueError(
                f"'{username}' isn't unique: {len(user_ids)} matches found."
            )
        return user_ids[0]

    @lru_cache(1024)
    def channelid_to_channelname(self, id_: str):
        """Convert a Slack channel ID to its channel name"""
        log.debug(f"get channel name from {id_}")
        room = SlackRoom(self.slack_web, channelid=id_, bot=self)
        return room.channelname

    @lru_cache(1024)
    def channelname_to_channelid(self, name: str):
        """Convert a Slack channel name to its channel ID"""
        log.debug(f"get channel id from {name}")
        return SlackRoom(self.slack_web, name=name, bot=self).id

    def channels(
        self,
        exclude_archived=True,
        joined_only=False,
        types="public_channel,private_channel",
    ):
        """
        Get all channels and groups and return information about them.

        :param exclude_archived:
            Exclude archived channels/groups
        :param joined_only:
            Filter out channels the bot hasn't joined
        :param types:
            Channel / Group types to search
        :returns:
            Lists all channels in a Slack team.
            References:
                - https://slack.com/api/conversations.list
        """
        response = self.slack_web.conversations_list(
            exclude_archived=exclude_archived, types=types
        )

        channels = [
            channel
            for channel in response["channels"]
            if channel["is_member"] or not joined_only
        ]

        return channels

    @lru_cache(1024)
    def get_im_channel(self, id_):
        """Open a direct message channel to a user"""
        try:
            response = self.slack_web.conversations_open(users=id_)
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
                to_channel_id = self.get_im_channel(msg.to.userid)
        return to_humanreadable, to_channel_id

    def send_message(self, msg) -> Message:
        super().send_message(msg)

        if msg.parent is not None:
            # we are asked to reply to a specific thread.
            try:
                msg.extras["thread_ts"] = self._ts_for_message(msg.parent)
            except KeyError:
                # Cannot reply to thread without a timestamp from the parent.
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
                    to_channel_id = self.get_im_channel(msg.to.userid)
                else:
                    to_channel_id = msg.to.channelid

            msgtype = "direct" if msg.is_direct else "channel"
            log.debug(
                f"Sending {msgtype} message to {to_humanreadable} ({to_channel_id})."
            )
            body = self.md.convert(msg.body)
            log.debug(f"Message size: {len(body)}.")

            parts = self.prepare_message_body(body, self.message_size_limit)
            current_ts_length = len(msg.extras.get("ts", ""))

            timestamps = []
            for index, part in enumerate(parts):
                data = {
                    "channel": to_channel_id,
                    "text": part,
                    "unfurl_media": "true",
                    "link_names": "1",
                    "as_user": "true",
                }

                if index == len(parts) - 1:
                    # Only add attachments/blocks if it's the last message, to avoid duplication
                    if "attachments" in msg.extras:
                        # If attachments are provided, and it's the last part of the mssage
                        data["attachments"] = json.dumps(msg.extras["attachments"])

                    if "blocks" in msg.extras:
                        # If blocksare provided, and it's the last part of the mssage
                        data["blocks"] = json.dumps(msg.extras["blocks"])

                # Keep the thread_ts to answer to the same thread.
                if "thread_ts" in msg.extras:
                    data["thread_ts"] = msg.extras["thread_ts"]

                if "ts" in msg.extras and current_ts_length > index:
                    # If a timestamp exists for the current chunk, update it - otherwise, send it as new
                    data["ts"] = msg.extras["ts"][index]
                    result = self.slack_web.chat_update(**data)

                elif msg.extras.get("ephemeral"):
                    data["user"] = msg.to.userid
                    # undo divert / room to private
                    if isinstance(msg.to, RoomOccupant):
                        data["channel"] = msg.to.channelid
                    result = self.slack_web.chat_postEphemeral(**data)
                else:
                    result = self.slack_web.chat_postMessage(**data)

                if "ts" in result:
                    timestamps.append(result["ts"])

            if "ts" in msg.extras and current_ts_length > len(parts):
                # If we have more timestamps than msg parts, delete the remaining timestamps
                for timestamp in msg.extras["ts"][len(parts) - current_ts_length - 1]:
                    data = {
                        "channel": to_channel_id,
                        "ts": timestamp,
                        "unfurl_media": "true",
                        "link_names": "1",
                        "as_user": "true",
                    }
                    self.slack_web.chat_delete(**data)

            msg.extras["ts"] = timestamps
        except Exception:
            log.exception(
                f"An exception occurred while trying to send the following message "
                f"to {to_humanreadable}: {msg.body}."
            )

        return msg

    def update_message(self, msg) -> Message:
        if "ts" not in msg.extras or len(msg.extras["ts"]) <= 0:
            # If a timestamp wasn't provided, log an error and return the original message
            log.error(f'No timestamp provided to update message "{msg.body}"')
            return msg
        return self.send_message(msg)

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
            if resp.get("ok"):
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
            f"Requesting upload of {name} to {user.channelname} "
            f"(size hint: {size}, stream type: {stream_type})."
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

            if card.parent is not None:
                # we are asked to reply to a specific thread.
                try:
                    data["thread_ts"] = self._ts_for_message(card.parent)
                except KeyError:
                    # Cannot reply to thread without a timestamp from the parent.
                    log.exception(
                        "The provided parent message is not a Slack message "
                        "or does not contain a Slack timestamp."
                    )
            try:
                log.debug(f"Sending data:\n{data}")
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

        Reference: https://api.slack.com/changelog/2017-09-the-one-about-usernames

        Supports strings with the following formats::

            <#C12345>
            <#C12345|channel>
            <@U12345>
            <@U12345|user>  ** deprecated for removal.
            @user           ** deprecated for removal.
            #channel/user
            #channel

        Returns the tuple (username, userid, channelname, channelid).
        Some elements may come back as None.
        """
        exception_message = (
            "Unparseable slack identifier, should be of the format `<#C12345>`, `<@U12345>`, "
            "`#channel/user` or `#channel`. (Got `%s`)"
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
                "Unparseable Slack ID, should start with U, B, C, G, D or W (got `%s`)"
            )
            if text[1] not in ("@", "#"):
                raise ValueError(
                    f"Expected '@' or '#' Slack ID prefix but got '{text[1]}'."
                )
            text = text[2:-1]
            if text == "":
                raise ValueError(exception_message % "")
            if text[0] in ("U", "B", "W"):
                if "|" in text:
                    raise ValueError("Slack ID can not contain '|'.")
                userid = text
            elif text[0] in ("C", "G", "D"):
                if "|" in text:
                    channelid, channelname = text.split("|")
                else:
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
        log.debug(f"Building an identifier from {txtrep}.")
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
            if userid == self.bot_identifier.userid:
                return self.bot_identifier
            return SlackPerson(self.slack_web, userid, self.get_im_channel(userid))
        if channelid is not None:
            return SlackRoom(webclient=self.slack_web, channelid=channelid, bot=self)

        raise Exception(
            "You found a bug.  I expected at least one of userid, channelid, username "
            "or channelname to be resolved but none of them were. This shouldn't "
            "happen so, please file a bug."
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
                data={
                    "json": {
                        "channel": to_channel_id,
                        "timestamp": ts,
                        "name": reaction,
                    }
                },
            )
        except SlackAPIResponseError as e:
            if e.error == "invalid_name":
                raise ValueError(e.error, "No such emoji", reaction)
            elif e.error in ("no_reaction", "already_reacted"):
                # This is common if a message was edited after you reacted to it, and you reacted
                # to it again.  Chances are you don't care about this. If you do, call
                # api_call() directly.
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
            self.slack_rtm.close()
        super().shutdown()

    @property
    def mode(self):
        return "slackv3"

    def query_room(self, room):
        """Room can either be a name or a channelid"""
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

        Returns a plain text representation of the URI.
        :returns:
            string
        """
        text = re.sub(r"<([^#][^|>]+)\|([^|>]+)>", r"\2", text)
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
                log.debug(f"Someone mentioned user {identifier}")
                mentioned.append(identifier)
                text = text.replace(word, f"{identifier}")
            elif isinstance(identifier, SlackRoom):
                log.debug(f"Someone mentioned channel {identifier}")
                mentioned.append(identifier)
                text = text.replace(word, f"{identifier}")

        return text, mentioned
