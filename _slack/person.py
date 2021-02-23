import logging

from slack_sdk.web import WebClient

from errbot.backends.base import Person, RoomDoesNotExistError

log = logging.getLogger(__name__)


class SlackPerson(Person):
    """
    This class describes a person on Slack's network.
    """
    def __init__(self, webclient: WebClient, userid=None, channelid=None):
        if userid is not None and userid[0] not in ("U", "B", "W"):
            raise Exception(
                f"This is not a Slack user or bot id: {userid} "
                "(should start with U, B or W)"
            )

        if channelid is not None and channelid[0] not in ("D", "C", "G"):
            raise Exception(
                f"This is not a valid Slack channelid: {channelid} "
                "(should start with D, C or G)"
            )

        self._userid = userid
        self._user_info = {}
        self._channelid = channelid
        self._channelname = None
        self._webclient = webclient

        if self._userid is not None:
            self._cache_user_info()

    @property
    def userid(self):
        return self._userid

    @property
    def info(self):
        """
        Return the user info, but load it if we didn't do it yet.

        :rtype: dict[str, any]
        :return: the user info
        """
        if not self._info:
            self._info = self._get_user_info()
        return self._info

    @property
    def username(self):
        """
        Convert a Slack user ID to their display name.
        """
        return self._user_info.get("profile", {}).get("display_name", "")

    @property
    def fullname(self):
        """Convert a Slack user ID to their full name"""
        return self._user_info.get("profile", {}).get("real_name", "")

    @property
    def email(self):
        """Convert a Slack user ID to their user email"""
        return self._user_info.get("profile", {}).get("email", "")

    def _cache_user_info(self):
        """
        Cache all user info and return data.

        :rtype: dict[str, any]
        :return: the user info
        """
        res = self._webclient.users_info(user=self._userid)

        if res["ok"] is False:
            log.error(f"Cannot find user with ID {self._userid}. Slack Error: {res['error']}")
            self._user_info = {}
        else:
            self._user_info = res["user"]

    @property
    def channelid(self):
        return self._channelid

    @property
    def channelname(self):
        """Convert a Slack channel ID to its channel name"""
        if self.channelid is None:
            return None

        if self._channelname:
            return self._channelname

        res = self._webclient.conversations_info(channel=self.channelid)

        if res['ok'] is False:
            raise RoomDoesNotExistError(
                f"No channel with ID {self._channelid} exists.  Slack error {res['error']}"
            )
        channel = res['channel']

        if channel['is_im']:
            self._channelname = channel["user"]
        else:
            self._channelname = channel["name"]
        return self._channelname

    @property
    def domain(self):
        raise NotImplementedError

    # Compatibility with the generic API.
    client = channelid
    nick = username

    # Override for ACLs
    @property
    def aclattr(self):
        # Note: Don't use str(self) here because that will return
        # an incorrect format from SlackMUCOccupant.
        # Only use user id as per https://api.slack.com/changelog/2017-09-the-one-about-usernames
        return f"{self._userid}"

    person = aclattr

    def __unicode__(self):
        return f"@<{self._userid}>"

    def __str__(self):
        return self.__unicode__()

    def __eq__(self, other):
        if not isinstance(other, SlackPerson):
            log.warning(f"tried to compare a SlackPerson with a {type(other)}")
            return False
        return other.userid == self.userid

    def __hash__(self):
        return self.userid.__hash__()
