import logging
import os
import sys
import json
import unittest
from tempfile import mkdtemp

from mock import MagicMock

from errbot.bootstrap import bot_config_defaults

log = logging.getLogger(__name__)

try:
    import slackv3 as slack

    class TestSlackBackend(slack.SlackBackend):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.test_msgs = []
            self.bot_identifier = MagicMock()
            self.bot_identifier.userid.return_value = "ULxxzzz00"

        def callback_message(self, msg):
            self.test_msgs.append(msg)

        # ~ def find_user(self, user):
            # ~ m = MagicMock()
            # ~ m.name = user
            # ~ return m


except SystemExit:
    log.exception("Can't import backends.slack for testing")


USER_INFO_OK = json.loads(
"""
    {
        "ok": true,
        "user": {
            "id": "W012A3CDE",
            "team_id": "T012AB3C4",
            "name": "spengler",
            "deleted": false,
            "color": "9f69e7",
            "real_name": "Egon Spengler",
            "tz": "America/Los_Angeles",
            "tz_label": "Pacific Daylight Time",
            "tz_offset": -25200,
            "profile": {
                "avatar_hash": "ge3b51ca72de",
                "status_text": "Print is dead",
                "status_emoji": ":books:",
                "real_name": "Egon Spengler",
                "display_name": "spengler",
                "real_name_normalized": "Egon Spengler",
                "display_name_normalized": "spengler",
                "email": "spengler@ghostbusters.example.com",
                "image_original": "https://.../avatar/e3b51ca72dee4ef87916ae2b9240df50.jpg",
                "image_24": "https://.../avatar/e3b51ca72dee4ef87916ae2b9240df50.jpg",
                "image_32": "https://.../avatar/e3b51ca72dee4ef87916ae2b9240df50.jpg",
                "image_48": "https://.../avatar/e3b51ca72dee4ef87916ae2b9240df50.jpg",
                "image_72": "https://.../avatar/e3b51ca72dee4ef87916ae2b9240df50.jpg",
                "image_192": "https://.../avatar/e3b51ca72dee4ef87916ae2b9240df50.jpg",
                "image_512": "https://.../avatar/e3b51ca72dee4ef87916ae2b9240df50.jpg",
                "team": "T012AB3C4"
            },
            "is_admin": true,
            "is_owner": false,
            "is_primary_owner": false,
            "is_restricted": false,
            "is_ultra_restricted": false,
            "is_bot": false,
            "updated": 1502138686,
            "is_app_user": false,
            "has_2fa": false
        }
    }
"""
)

CONVERSATION_INFO_PUBLIC_OK = json.loads(
"""
    {
        "ok": true,
        "channel": {
            "id": "C012AB3CD",
            "name": "general",
            "is_channel": true,
            "is_group": false,
            "is_im": false,
            "created": 1449252889,
            "creator": "W012A3BCD",
            "is_archived": false,
            "is_general": true,
            "unlinked": 0,
            "name_normalized": "general",
            "is_read_only": false,
            "is_shared": false,
            "parent_conversation": null,
            "is_ext_shared": false,
            "is_org_shared": false,
            "pending_shared": [],
            "is_pending_ext_shared": false,
            "is_member": true,
            "is_private": false,
            "is_mpim": false,
            "last_read": "1502126650.228446",
            "topic": {
                "value": "For public discussion of generalities",
                "creator": "W012A3BCD",
                "last_set": 1449709364
            },
            "purpose": {
                "value": "This part of the workspace is for fun. Make fun here.",
                "creator": "W012A3BCD",
                "last_set": 1449709364
            },
            "previous_names": [
                "specifics",
                "abstractions",
                "etc"
            ],
            "locale": "en-US"
        }
    }
"""
)

CHANNEL_INFO_DIRECT_1TO1_OK = json.loads(
"""
{
    "ok": true,
    "channel": {
        "id": "C012AB3CD",
        "created": 1507235627,
        "is_im": true,
        "is_org_shared": false,
        "user": "U27FFLNF4",
        "last_read": "1513718191.000038",
        "latest": {
            "type": "message",
            "user": "U5R3PALPN",
            "text": "Psssst!",
            "ts": "1513718191.000038"
        },
        "unread_count": 0,
        "unread_count_display": 0,
        "is_open": true,
        "locale": "en-US",
        "priority": 0.043016851216706
    }
}
"""
)

CONVERSATION_OPEN_OK = json.loads(
"""
{
    "ok": true,
    "channel": {
        "id": "C012AB3CD"
    }
}
"""
)

class SlackTests(unittest.TestCase):
    def setUp(self):
        # make up a config.
        tempdir = mkdtemp()
        # reset the config every time
        sys.modules.pop("errbot.config-template", None)
        __import__("errbot.config-template")
        config = sys.modules["errbot.config-template"]
        bot_config_defaults(config)
        config.BOT_DATA_DIR = tempdir
        config.BOT_LOG_FILE = os.path.join(tempdir, "log.txt")
        config.BOT_EXTRA_PLUGIN_DIR = []
        config.BOT_LOG_LEVEL = logging.DEBUG
        config.BOT_IDENTITY = {"username": "err@localhost", "token": "___"}
        config.BOT_ASYNC = False
        config.BOT_PREFIX = "!"
        config.CHATROOM_FN = "blah"

        self.slack = TestSlackBackend(config)

    def testBotMessageWithAttachments(self):
        attachment = {
            "title": "sometitle",
            "id": 1,
            "fallback": " *Host:* host-01",
            "color": "daa038",
            "fields": [{"title": "Metric", "value": "1", "short": True}],
            "title_link": "https://xx.com",
        }
        bot_id = "B04HMXXXX"
        bot_msg = {
            "channel": "C0XXXXY6P",
            "icons": {"emoji": ":warning:", "image_64": "https://xx.com/26a0.png"},
            "ts": "1444416645.000641",
            "type": "message",
            "text": "",
            "bot_id": bot_id,
            "username": "riemann",
            "subtype": "bot_message",
            "attachments": [attachment],
        }
        mocked_webclient = MagicMock()
        mocked_webclient.conversations_info.return_value = CONVERSATION_INFO_PUBLIC_OK

        self.slack._handle_message(mocked_webclient, bot_msg)
        msg = self.slack.test_msgs.pop()

        self.assertEqual(msg.extras["attachments"], [attachment])

    def testSlackEventObjectAddedToExtras(self):
        bot_id = "B04HMXXXX"
        bot_msg = {
            "channel": "C0XXXXY6P",
            "icons": {"emoji": ":warning:", "image_64": "https://xx.com/26a0.png"},
            "ts": "1444416645.000641",
            "type": "message",
            "text": "",
            "bot_id": bot_id,
            "username": "riemann",
            "subtype": "bot_message",
        }

        self.slack._handle_message(MagicMock(), bot_msg)
        msg = self.slack.test_msgs.pop()

        self.assertEqual(msg.extras["slack_event"], bot_msg)

    def testPrepareMessageBody(self):
        test_body = """
        hey, this is some code:
            ```
            foobar
            ```
        """
        parts = self.slack.prepare_message_body(test_body, 10000)
        assert parts == [test_body]

        test_body = """this block is unclosed: ``` foobar """
        parts = self.slack.prepare_message_body(test_body, 10000)
        assert parts == [test_body + "\n```\n"]

        test_body = """``` foobar """
        parts = self.slack.prepare_message_body(test_body, 10000)
        assert parts == [test_body + "\n```\n"]

        test_body = """closed ``` foobar ``` not closed ```"""
        # ---------------------------------^ 21st char
        parts = self.slack.prepare_message_body(test_body, 21)
        assert len(parts) == 2
        assert parts[0].count("```") == 2
        assert parts[0].endswith("```")
        assert parts[1].count("```") == 2
        assert parts[1].endswith("```\n")

    def test_extract_identifiers(self):
        extract_from = self.slack.extract_identifiers_from_string

        self.assertEqual(extract_from("<@U12345>"), (None, "U12345", None, None))

        self.assertEqual(
            extract_from("<@U12345|UName>"), ("UName", "U12345", None, None)
        )

        self.assertEqual(extract_from("<@B12345>"), (None, "B12345", None, None))

        self.assertEqual(extract_from("<#C12345>"), (None, None, None, "C12345"))

        self.assertEqual(extract_from("<#G12345>"), (None, None, None, "G12345"))

        self.assertEqual(extract_from("<#D12345>"), (None, None, None, "D12345"))

        self.assertEqual(extract_from("@person"), ("person", None, None, None))

        self.assertEqual(
            extract_from("#general/someuser"), ("someuser", None, "general", None)
        )

        self.assertEqual(extract_from("#general"), (None, None, "general", None))

        with self.assertRaises(ValueError):
            extract_from("")

        with self.assertRaises(ValueError):
            extract_from("general")

        with self.assertRaises(ValueError):
            extract_from("<>")

        with self.assertRaises(ValueError):
            extract_from("<C12345>")

        with self.assertRaises(ValueError):
            extract_from("<@I12345>")

    def test_build_identifier(self):
        self.slack.slack_web = MagicMock()
        self.slack.slack_web.conversations_info.return_value = CONVERSATION_INFO_PUBLIC_OK
        self.slack.slack_web.users_info.return_value = USER_INFO_OK
        self.slack.slack_web.conversations_open.return_value = CONVERSATION_OPEN_OK
        build_from = self.slack.build_identifier

        def check_person(person, expected_uid, expected_cid):
            return person.userid == expected_uid and person.channelid == expected_cid

        assert build_from("<#C0XXXXY6P>").name == "general"
        assert check_person(build_from("<@U12345>"), "U12345", "Cfoo")
        assert check_person(build_from("@user"), "Utest", "Cfoo")
        assert build_from("#channel").name == "meh"

        self.assertEqual(
            build_from("#channel/user"),
            slack.SlackRoomOccupant(None, "Utest", "Cfoo", self.slack),
        )

    def test_uri_sanitization(self):
        sanitize = self.slack.sanitize_uris

        self.assertEqual(
            sanitize("The email is <mailto:test@example.org|test@example.org>."),
            "The email is test@example.org.",
        )

        self.assertEqual(
            sanitize(
                "Pretty URL Testing: <http://example.org|example.org> with " "more text"
            ),
            "Pretty URL Testing: example.org with more text",
        )

        self.assertEqual(sanitize("URL <http://example.org>"), "URL http://example.org")

        self.assertEqual(
            sanitize("Normal &lt;text&gt; that shouldn't be affected"),
            "Normal &lt;text&gt; that shouldn't be affected",
        )

        self.assertEqual(
            sanitize(
                "Multiple uris <mailto:test@example.org|test@example.org>, "
                "<mailto:other@example.org|other@example.org> and "
                "<http://www.example.org>, <https://example.com> and "
                "<http://subdomain.example.org|subdomain.example.org>."
            ),
            "Multiple uris test@example.org, other@example.org and "
            "http://www.example.org, https://example.com and subdomain.example.org.",
        )

    def test_slack_markdown_link_preprocessor(self):
        convert = self.slack.md.convert
        self.assertEqual(
            "This is <http://example.com/|a link>.",
            convert("This is [a link](http://example.com/)."),
        )
        self.assertEqual(
            "This is <https://example.com/|a link> and <mailto:me@comp.org|an email address>.",
            convert(
                "This is [a link](https://example.com/) and [an email address](mailto:me@comp.org)."
            ),
        )
        self.assertEqual(
            "This is <http://example.com/|a link> and a manual URL: https://example.com/.",
            convert(
                "This is [a link](http://example.com/) and a manual URL: https://example.com/."
            ),
        )
        self.assertEqual(
            "<http://example.com/|This is a link>",
            convert("[This is a link](http://example.com/)"),
        )
        self.assertEqual(
            "This is http://example.com/image.png.",
            convert("This is ![an image](http://example.com/image.png)."),
        )
        self.assertEqual(
            "This is [some text] then <http://example.com|a link>",
            convert("This is [some text] then [a link](http://example.com)"),
        )

    def test_mention_processing(self):
        self.slack.webclient.server.users.find = MagicMock(
            side_effect=self.slack.find_user
        )

        mentions = self.slack.process_mentions

        self.assertEqual(
            mentions("<@U1><@U2><@U3>"),
            (
                "@U1@U2@U3",
                [
                    self.slack.build_identifier("<@U1>"),
                    self.slack.build_identifier("<@U2>"),
                    self.slack.build_identifier("<@U3>"),
                ],
            ),
        )

        self.assertEqual(
            mentions("Is <@U12345>: here?"),
            ("Is @U12345: here?", [self.slack.build_identifier("<@U12345>")]),
        )

        self.assertEqual(
            mentions("<@U12345> told me about @a and <@U56789> told me about @b"),
            (
                "@U12345 told me about @a and @U56789 told me about @b",
                [
                    self.slack.build_identifier("<@U12345>"),
                    self.slack.build_identifier("<@U56789>"),
                ],
            ),
        )

        self.assertEqual(
            mentions("!these!<@UABCDE>!mentions! will !still!<@UFGHIJ>!work!"),
            (
                "!these!@UABCDE!mentions! will !still!@UFGHIJ!work!",
                [
                    self.slack.build_identifier("<@UABCDE>"),
                    self.slack.build_identifier("<@UFGHIJ>"),
                ],
            ),
        )
