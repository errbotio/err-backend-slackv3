import logging
import sys

from errbot.backends.base import (
    Room,
    RoomDoesNotExistError,
    RoomError,
    UserDoesNotExistError,
)

from _slack.lib import USER_IS_BOT_HELPTEXT

try:
    from slack_sdk.errors import SlackApiError
except ImportError:
    log.exception("Could not start the SlackSDK backend")
    log.fatal(
        "You need to install python modules in order to use the Slack backend.\n"
        "You can do `pip install errbot[slack-sdk]` to install them."
    )
    sys.exit(1)

log = logging.getLogger(__name__)


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
        log.debug("Resolving channel '{self.name}' by iterating all channels")
        channel_id = None
        cursor = None
        while channel_id is None and cursor != "":
            res = self.slack_web.conversations_list(cursor=cursor, limit=1000)

            if res["ok"] is True:
                for channel in res["channels"]:
                    if channel["name"] == self.name:
                        channel_id = channel["id"]
                        break
                else:
                    cursor = res["response_metadata"].get("next_cursor", "")
            else:
                log.exception(f"Unable to list channels.  Slack error {res['error']}")

        if channelid is None:
            raise RoomDoesNotExistError(f"Cannot find channel {self.name}.")
        log.debug(f"Channel '{self.name}' resolved to channel id '{channel_id}'")
        return channel_id

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
