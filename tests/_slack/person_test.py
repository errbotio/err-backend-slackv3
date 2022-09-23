import json
import logging
import os
import sys
import unittest
from tempfile import mkdtemp

from errbot.backends.base import RoomDoesNotExistError
from mock import MagicMock

from _slack.person import *

log = logging.getLogger(__name__)


class SlackPersonTests(unittest.TestCase):

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

    USER_NOT_FOUND = json.loads(
        """
        {
            "ok": false,
            "error": "user_not_found"
        }
    """
    )

    CHANNEL_INFO_PUBLIC_OK = json.loads(
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

    CHANNEL_INFO_FAIL = json.loads(
        """
    {
        "ok": false,
        "error": "channel_not_found"
    }
    """
    )

    TEAM_INFO_OK = json.loads(
        """
        {
            "ok": true,
            "team": {
                "id": "T012AB3C4",
                "name": "My Team",
                "domain": "example",
                "email_domain": "example.com",
                "icon": {
                    "image_34": "https://...",
                    "image_44": "https://...",
                    "image_68": "https://...",
                    "image_88": "https://...",
                    "image_102": "https://...",
                    "image_132": "https://...",
                    "image_default": true
                },
                "enterprise_id": "E1234A12AB",
                "enterprise_name": "Umbrella Corporation"
            }
        }
        """
    )

    def setUp(self):
        self.webclient = MagicMock()
        self.webclient.users_info.return_value = SlackPersonTests.USER_INFO_OK
        self.webclient.conversations_info.return_value = (
            SlackPersonTests.CHANNEL_INFO_PUBLIC_OK
        )
        self.userid = "W012A3CDE"
        self.channelid = "C012AB3CD"
        self.p = SlackPerson(
            self.webclient, userid=self.userid, channelid=self.channelid
        )

    def test_wrong_userid(self):
        with self.assertRaises(Exception):
            SlackPerson(self.webclient, userid="invalid")

    def test_wrong_channelid(self):
        with self.assertRaises(Exception):
            SlackPerson(self.webclient, channelid="invalid")

    def test_username(self):
        self.assertEqual(self.p.userid, self.userid)
        self.assertEqual(self.p.username, "spengler")
        self.assertEqual(self.p.username, "spengler")
        self.webclient.users_info.assert_called_once_with(user=self.userid)

    def test_username_not_found(self):
        self.webclient.users_info.return_value = SlackPersonTests.USER_NOT_FOUND
        self.p = SlackPerson(self.webclient, userid="W012A3CDE")
        self.assertEqual(self.p.username, "")
        self.assertEqual(self.p.username, "")
        self.webclient.users_info.assert_called_with(user=self.userid)
        self.assertEqual(self.webclient.users_info.call_count, 2)

    def test_fullname(self):
        self.assertEqual(self.p.fullname, "Egon Spengler")
        self.assertEqual(self.p.fullname, "Egon Spengler")
        self.webclient.users_info.assert_called_once_with(user=self.userid)

    def test_fullname_not_found(self):
        self.webclient.users_info.return_value = SlackPersonTests.USER_NOT_FOUND
        self.p = SlackPerson(self.webclient, userid="W012A3CDE")
        self.assertEqual(self.p.fullname, "")
        self.assertEqual(self.p.fullname, "")
        self.webclient.users_info.assert_called_with(user=self.userid)
        self.assertEqual(self.webclient.users_info.call_count, 2)

    def test_email(self):
        self.assertEqual(self.p.email, "spengler@ghostbusters.example.com")
        self.assertEqual(self.p.email, "spengler@ghostbusters.example.com")
        self.webclient.users_info.assert_called_once_with(user=self.userid)

    def test_email_not_found(self):
        self.webclient.users_info.return_value = SlackPersonTests.USER_NOT_FOUND
        self.p = SlackPerson(self.webclient, userid="W012A3CDE")
        self.assertEqual(self.p.email, "")
        self.assertEqual(self.p.email, "")
        self.webclient.users_info.assert_called_with(user=self.userid)
        self.assertEqual(self.webclient.users_info.call_count, 2)

    def test_channelname(self):
        self.assertEqual(self.p.channelid, self.channelid)
        self.assertEqual(self.p.channelname, "general")
        self.assertEqual(self.p.channelname, "general")
        self.webclient.conversations_info.assert_called_once_with(channel="C012AB3CD")

    def test_channelname_channel_not_found(self):
        self.webclient.conversations_info.return_value = (
            SlackPersonTests.CHANNEL_INFO_FAIL
        )
        with self.assertRaises(RoomDoesNotExistError) as e:
            self.p = SlackPerson(self.webclient, channelid="C012AB3CD")
            self.p.channelname

    def test_domain(self):
        self.webclient = MagicMock()
        self.webclient.users_info.return_value = SlackPersonTests.USER_INFO_OK
        self.webclient.team_info.return_value = SlackPersonTests.TEAM_INFO_OK
        self.p = SlackPerson(self.webclient, userid="W012A3CDE")
        self.assertEqual(self.p.domain, "example")

    def test_aclattr(self):
        self.assertEqual(self.p.aclattr, "W012A3CDE")

    def test_person(self):
        self.assertEqual(self.p.person, "W012A3CDE")

    def test_to_string(self):
        self.assertEqual(str(self.p), "<@W012A3CDE>")

    def test_equal(self):
        self.another_p = SlackPerson(
            self.webclient, userid=self.userid, channelid=self.channelid
        )
        self.assertTrue(self.p == self.another_p)
        self.assertFalse(self.p == "this is not a person")

    def test_hash(self):
        self.assertEqual(hash(self.p), hash(self.p.userid))
