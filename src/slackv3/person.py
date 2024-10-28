import logging

from errbot.backends.base import Person, RoomDoesNotExistError
from slack_sdk.web import WebClient

log = logging.getLogger(__name__)


class SlackPerson(Person):
    """
    This class describes a person on Slack's network.
    Reference:
        https://api.slack.com/changelog/2016-08-11-user-id-format-changes
        https://api.slack.com/docs/conversations-api

        slack user:https://api.slack.com/methods/users.info
        slack channel: https://api.slack.com/methods/conversations.info

        Errbot Person composition
        {
            person: user.id,
            nick: user.profile.display_name
            fullname: user.profile.real_name
            client: conversation.channel.id
            email: user.profile.email (optional)
            domain: team.domain (used in archive url)
        }
    """

    def __init__(self, webclient: WebClient, userid=None, channelid=None):
        if userid is not None and userid[0] not in ("U", "W", "B"):
            raise Exception(
                f"This is not a Slack user or bot id: {userid} "
                "(should start with B, U or W)"
            )

        if channelid is not None and channelid[0] not in ("D", "C", "G"):
            raise Exception(
                f"This is not a valid Slack channelid: {channelid} "
                "(should start with D, C or G)"
            )

        self._userid = userid
        self._user_info = {}
        self._channelid = channelid
        self._channel_info = {}
        self._webclient = webclient

        if self._userid is not None:
            self._cache_user_info()
        if self._channelid is not None:
            self._cache_channel_info()

    @property
    def userid(self):
        """
        Slack ID is the only secure way to uniquely identify a user.
        """
        return self._userid

    @property
    def username(self):
        """
        Convert a Slack user ID to their display name.
        """
        return self._user_info.get("display_name", "")

    @property
    def fullname(self):
        """Convert a Slack user ID to their full name"""
        return self._user_info.get("real_name", "")

    @property
    def email(self):
        """Convert a Slack user ID to their user email"""
        return self._user_info.get("email", "")

    def _cache_user_info(self):
        """
        Cache all user info and return data.

        :rtype: dict[str, any]
        :return: the user info
        """
        if self._userid is None:
            raise ValueError("Unable to look up an undefined user id.")

        # Fix error while looking up shorter bot uid
        if len(self._userid) <= 3:
            return

        if self._userid[0] == "B":
            res = self._webclient.bots_info(bot=self._userid)
        else:
            res = self._webclient.users_info(user=self._userid)

        if res["ok"] is False:
            log.error(
                f"Cannot find user with ID {self._userid}. Slack Error: {res['error']}"
            )
        else:
            if "bot" in res:
                self._user_info["display_name"] = res["bot"].get("name", "")
            else:
                for attribute in ["real_name", "display_name", "email"]:
                    self._user_info[attribute] = res["user"]["profile"].get(
                        attribute, ""
                    )

                team = None
                # Normal users
                if res.get("user").get("team_id"):
                    team = res["user"]["team_id"]
                # Users in a ORG/grid setup do not have a team ID
                elif res.get("user", {}).get("enterprise_user"):
                    team = res["user"]["enterprise_user"].get("enterprise_id")
                else:
                    log.warning(
                        f"Failed to find team_id or enterprise_user details for userid {self._userid}."
                    )

                if team:
                    team_res = self._webclient.team_info(team=team)
                    if team_res["ok"]:
                        self._user_info["domain"] = team_res["team"]["domain"]
                    else:
                        log.warning(
                            f"Failed to fetch team information for userid {self._userid}. Slack error {team_res['ok']}"
                        )

    @property
    def channelid(self):
        return self._channelid

    @property
    def channelname(self):
        """
        Convert a Slack channel ID to its channel name
        """
        channel_name_key = "name"
        if self._channel_info.get("is_im") is True:
            channel_name_key = "user"

        return self._channel_info[channel_name_key]

    def _cache_channel_info(self, refresh=False):
        """
        Retrieve channel info from Slack if there isn't already a channel id cached.
        :refresh: Boolean to force fetching channel info even if it was already cached.
        """
        if self.channelid is None:
            raise ValueError("Unable to lookup an undefined channel id.")

        if self._channel_info.get("id") is None or refresh:
            res = self._webclient.conversations_info(channel=self.channelid)
            if res["ok"] is False:
                raise RoomDoesNotExistError(
                    f"No channel with ID {self._channelid} exists.  Slack error {res['error']}"
                )
            if res["channel"]["id"] != self._channelid:
                raise ValueError(
                    "Inconsistent data detected.  "
                    f"{res['channel']['id']} does not equal {self._channelid}"
                )
            for attribute in ["name", "user", "is_im", "is_mpim", "id"]:
                self._channel_info[attribute] = res["channel"].get(attribute)

    @property
    def domain(self):
        return self._user_info.get("domain", "")

    # Compatibility with the generic API.
    client = channelid
    nick = username

    # Override for ACLs
    @property
    def aclattr(self):
        # Note: Don't use str(self) here because that will return
        # an incorrect format from SlackMUCOccupant.
        # Only use user id as per slack's user-id-format-changes article.
        return f"{self._userid}"

    person = aclattr

    def __unicode__(self):
        return f"<@{self.aclattr}>"

    def __str__(self):
        return self.__unicode__()

    def __eq__(self, other):
        if not isinstance(other, SlackPerson):
            log.warning(f"tried to compare a SlackPerson with a {type(other)}")
            return False
        return other.userid == self.userid

    def __hash__(self):
        return self.userid.__hash__()
