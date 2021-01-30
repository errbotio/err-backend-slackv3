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
        self._channelid = channelid
        self._channelname = None
        self._webclient = webclient
        self._profile = None

    @property
    def userid(self):
        return self._userid

    @property
    def username(self):
        """Convert a Slack user ID to their user name"""
        if self._profile:
            return (self._profile['display_name_normalized'] or
                    self._profile['real_name_normalized'])
        return self._get_user_info('username')

    @property
    def fullname(self):
        """Convert a Slack user ID to their full name"""
        if self._profile:
            return self._profile['real_name']
        return self._get_user_info('fullname')

    @property
    def email(self):
        """Convert a Slack user ID to their user email"""
        if self._profile:
            return self._profile.get('email', None)
        return self._get_user_info('email')

    def _get_user_info(self, retdata):
        """Cache all user info and return data"""
        user = self._webclient.users_info(user=self._userid)["user"]

        if user is None:
            log.error(f"Cannot find user with ID {self._userid}")
            return f"<{self._userid}>"

        self._profile = user['profile']
        return getattr(self, retdata)

    @property
    def channelid(self):
        return self._channelid

    @property
    def channelname(self):
        """Convert a Slack channel ID to its channel name"""
        if self._channelid is None:
            return None

        if self._channelname:
            return self._channelname

        channel = [
            channel
            for channel in self._webclient.conversations_list()["channels"]
            if channel["id"] == self._channelid
        ]

        if not channel:
            raise RoomDoesNotExistError(
                f"No channel with ID {self._channelid} exists."
            )

        self._channelname = channel[0]["name"]
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
        return f"@{self.userid}"

    person = aclattr

    def __unicode__(self):
        return f"@{self.username}"

    def __str__(self):
        return self.__unicode__()

    def __eq__(self, other):
        if not isinstance(other, SlackPerson):
            log.warning(f"tried to compare a SlackPerson with a {type(other)}")
            return False
        return other.userid == self.userid

    def __hash__(self):
        return self.userid.__hash__()
