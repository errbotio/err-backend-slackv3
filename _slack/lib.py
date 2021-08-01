import re

USER_IS_BOT_HELPTEXT = (
    "Connected to Slack using a bot account, which cannot manage "
    "channels itself (you must invite the bot to channels instead, "
    "it will auto-accept) nor invite people.\n\n"
    "If you need this functionality, you will have to create a "
    "regular user account and connect Errbot using that account. "
    "For this, you will also need to generate a user token at "
    "https://api.slack.com/web."
)

# The Slack client automatically turns a channel name into a clickable
# link if you prefix it with a #. Other clients receive this link as a
# token matching this regex.
SLACK_CLIENT_CHANNEL_HYPERLINK = re.compile(r"^<#(?P<id>([CG])[0-9A-Z]+)>$")

COLORS = {
    "red": "#FF0000",
    "green": "#008000",
    "yellow": "#FFA500",
    "blue": "#0000FF",
    "white": "#FFFFFF",
    "cyan": "#00FFFF",
}


class SlackAPIResponseError(RuntimeError):
    """Slack API returned a non-OK response"""

    def __init__(self, *args, error="", **kwargs):
        """
        :param error:
            The 'error' key from the API response data
        """
        self.error = error
        super().__init__(*args, **kwargs)
