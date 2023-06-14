import logging
import sys

from errbot.backends.base import (
    Room,
    RoomDoesNotExistError,
    RoomError,
    RoomOccupant,
    UserDoesNotExistError,
)

from .lib import USER_IS_BOT_HELPTEXT, SlackAPIResponseError
from .person import SlackPerson

log = logging.getLogger(__name__)

try:
    from slack_sdk.errors import BotUserAccessError, SlackApiError
    from slack_sdk.web import WebClient
except ImportError:
    log.exception("Could not start the SlackSDK backend")
    log.fatal(
        "You need to install python modules in order to use the Slack backend.\n"
        "You can do `pip install errbot-backend-slackv3` to install them."
    )
    sys.exit(1)


class SlackRoom(Room):
    def __init__(self, webclient=None, name=None, channelid=None, bot=None):
        if channelid is not None and name is not None:
            raise ValueError("channelid and name are mutually exclusive")
        if channelid is None and name is None:
            raise ValueError("A name or channelid is required to create a Room.")

        self._bot = bot
        self._webclient = webclient
        self._cache = None

        if name is not None:
            if name.startswith("#"):
                self._name = name[1:]
            else:
                self._name = name

            # channelid = self._channelname_to_id(name)
            try:
                channelid = self._channelname_to_id(name)
            except RoomDoesNotExistError:
                pass

        if channelid:
            self._cache_channel_info(channelid)

    def __str__(self):
        return f"<#{self.id}|{self.name}>"

    @property
    def channelname(self):
        return self._cache["name"]

    def _channelname_to_id(self, name):
        """
        Resolve channel name to channel id.
        """
        log.debug(f"Resolving channel '{name}' by iterating all channels")
        channel_id = None
        cursor = None
        while channel_id is None and cursor != "":
            res = self._webclient.conversations_list(
                cursor=cursor,
                limit=1000,
                types="public_channel,private_channel,mpim,im",
            )

            if res["ok"] is True:
                for channel in res["channels"]:
                    if "name" in channel and channel["name"] == name:
                        channel_id = channel["id"]
                        break
                else:
                    cursor = res["response_metadata"].get("next_cursor", "")
            else:
                log.exception(f"Unable to list channels.  Slack error {res['error']}")

        if channel_id is None:
            raise RoomDoesNotExistError(f"Cannot find channel {name}.")
        log.debug(f"Channel '{name}' resolved to channel id '{channel_id}'")
        return channel_id

    def _cache_channel_info(self, channelid):
        """
        Channel info as returned by the Slack API.
        Reference:
            https://api.slack.com/methods/conversations.info
        """
        res = self._webclient.conversations_info(channel=channelid)
        if res["ok"] is True:
            channel = res["channel"]
            self._cache = {
                "id": channel["id"],
                "name": channel["name"],
                "topic": channel["topic"]["value"],
                "purpose": channel["purpose"]["value"],
                "is_private": channel.get("is_private", None),
                "is_im": channel.get("is_im", None),
                "is_mpim": channel.get("is_mpim", None),
            }
        else:
            log.exception(
                f"Failed to fetch information for channel id {channelid}."
                f"  Slack error {res['error']}"
            )

    @property
    def private(self):
        """Return True if the room is a private group"""
        return self._cache["is_private"]

    @property
    def id(self):
        """Return the ID of this room"""
        return self._cache["id"]

    aclattr = id

    @property
    def channelid(self):
        """Return the Slack representation of the channel in the form <#CHANNELID|CHANNELNAME>"""
        return f"<#{self.id}|{self.name}>"

    @property
    def name(self):
        """Return the name of this room"""
        return self._cache["name"]

    def join(self, username=None, password=None):
        log.info(f"Joining channel '{self.name}'")
        join_failure = True
        try:
            self._webclient.conversations_join(channel=self.id)
            join_failure = False
        except SlackApiError as e:
            log.error(f"Unable to join '{self.name}'. Slack API Error {str(e)}")
        except BotUserAccessError:
            log.error(f"OAuthv1 bot token not allowed to join channels. '{self.name}'.")

        if join_failure:
            raise RoomError(f"Unable to join channel. {USER_IS_BOT_HELPTEXT}")

    def leave(self, reason=None):
        try:
            log.info(f"Leaving conversation {self} ({self.id})")
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
                log.info(f"Creating private conversation {self}.")
                self._bot.slack_web.conversations_create(
                    name=self.name, is_private=True
                )
            else:
                log.info(f"Creating conversation {self}.")
                self._bot.slack_web.conversations_create(name=self.name)
        except SlackAPIResponseError as e:
            if e.error == "user_is_bot":
                raise RoomError(f"Unable to create channel. {USER_IS_BOT_HELPTEXT}")
            else:
                raise RoomError(e)

    def destroy(self):
        try:
            log.info(f"Archiving conversation {self} ({self.id})")
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
        """
        Return topic string or None when it's an empty string.
        """
        topic = None
        if self._cache:
            topic = self._cache.get("topic")
        return topic

    @topic.setter
    def topic(self, topic):
        log.info(f"Setting topic of {self} ({self.id}) to {topic}.")
        res = self._webclient.conversations_setTopic(channel=self.id, topic=topic)
        if res["ok"] is True:
            self._cache["topic"] = topic
        else:
            log.error(f"Unable to set topic.  Slack error {res['error']}")

    @property
    def purpose(self):
        return self._cache["purpose"] or None

    @purpose.setter
    def purpose(self, purpose):
        log.info(f"Setting purpose of {self} ({self.id}) to {purpose}.")
        res = self._webclient.conversations_setPurpose(channel=self.id, purpose=purpose)
        if res["ok"] is True:
            self._cache["purpose"] = purpose
        else:
            log.error(f"Unable to set purpose.  Slack error {res['error']}")

    @property
    def occupants(self):
        occupants = []
        cursor = None
        while cursor != "":
            res = self._webclient.conversations_members(
                channel=self.id,
                cursor=cursor,
                limit=1000,
            )
            if res["ok"] is True:
                for member in res["members"]:
                    occupants.append(
                        SlackRoomOccupant(self._webclient, member, self.id, self._bot)
                    )
                cursor = res["response_metadata"]["next_cursor"]
            else:
                log.exception(
                    f"Unable to fetch members in conversation {self.id}."
                    f"  Slack error {res['error']}"
                )
        return occupants

    def invite(self, *args):
        users = {
            user["name"]: user["id"]
            for user in self._webclient.api_call("users.list")["members"]
        }

        for user in args:
            if user not in users:
                raise UserDoesNotExistError(f'User "{user}" not found.')
            log.info("Inviting %s into %s (%s)", user, self, self.id)
            method = "conversations.invite"
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

    def __init__(self, webclient, bot_id, bot_username, channelid, bot):
        super().__init__(webclient, bot_id, bot_username)
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
                "tried to compare a SlackRoomBotOccupant with a SlackPerson %s vs %s",
                self,
                other,
            )
            return False
        return other.room.id == self.room.id and other.userid == self.userid
