import sys
import unittest
import logging
import os
import json

from tempfile import mkdtemp
from mock import MagicMock

from _slack.person import *
from errbot.backends.base import RoomDoesNotExistError


log = logging.getLogger(__name__)


class SlackPersonTests(unittest.TestCase):

    USER_INFO_OK = json.loads("""
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
    """)

    USER_INFO_FAIL = json.loads("""
        {
            "ok": false,
            "error": "user_not_found"
        }
    """)

    def setUp(self):
        self.webClient = MagicMock()
        self.webClient.users_info.return_value = SlackPersonTests.USER_INFO_OK
        self.userid = "W012A3CDE"
        self.channelid = "Ctest_channel_id"
        self.p = SlackPerson(
            self.webClient, userid=self.userid, channelid=self.channelid
        )

    def test_wrong_userid(self):
        with self.assertRaises(Exception):
            SlackPerson(self.webClient, userid="invalid")

    def test_wrong_channelid(self):
        with self.assertRaises(Exception):
            SlackPerson(self.webClient, channelid="invalid")

    def test_username(self):
        self.assertEqual(self.p.userid, self.userid)
        self.assertEqual(self.p.username, "spengler")
        self.assertEqual(self.p.username, "spengler")
        self.webClient.users_info.assert_called_once_with(user=self.userid)

    def test_username_not_found(self):
        self.webClient.users_info.return_value = {"user": None}
        self.assertEqual(self.p.username, "")
        self.assertEqual(self.p.username, "")
        self.webClient.users_info.assert_called_with(user=self.userid)
        self.assertEqual(self.webClient.users_info.call_count, 2)

    def test_fullname(self):
        self.assertEqual(self.p.fullname, "Egon Spengler")
        self.assertEqual(self.p.fullname, "Egon Spengler")
        self.webClient.users_info.assert_called_once_with(user=self.userid)

    def test_fullname_not_found(self):
        self.webClient.users_info.return_value = {"user": None}
        self.assertEqual(self.p.fullname, "")
        self.assertEqual(self.p.fullname, "")
        self.webClient.users_info.assert_called_with(user=self.userid)
        self.assertEqual(self.webClient.users_info.call_count, 2)

    def test_email(self):
        self.assertEqual(self.p.email, "spengler@ghostbusters.example.com")
        self.assertEqual(self.p.email, "spengler@ghostbusters.example.com")
        self.webClient.users_info.assert_called_once_with(user=self.userid)

    def test_email_not_found(self):
        self.webClient.users_info.return_value = {"user": None}
        self.assertEqual(self.p.email, "")
        self.assertEqual(self.p.email, "")
        self.webClient.users_info.assert_called_with(user=self.userid)
        self.assertEqual(self.webClient.users_info.call_count, 2)

    def test_channelname(self):
        self.assertEqual(self.p.channelid, self.channelid)
        self.webClient.conversations_list.return_value = {
            "channels": [{"id": self.channelid, "name": "test_channel"}]
        }
        self.assertEqual(self.p.channelname, "test_channel")
        self.assertEqual(self.p.channelname, "test_channel")
        self.webClient.conversations_list.assert_called_once_with()
        self.p._channelid = None
        self.assertIsNone(self.p.channelname)

    def test_channelname_channel_not_found(self):
        self.webClient.conversations_list.return_value = {
            "channels": [{"id": "random", "name": "random_channel"}]
        }
        with self.assertRaises(RoomDoesNotExistError) as e:
            self.p.channelname

    def test_channelname_channel_empty_channel_list(self):
        self.webClient.conversations_list.return_value = {"channels": []}
        with self.assertRaises(RoomDoesNotExistError) as e:
            self.p.channelname

    def test_domain(self):
        with self.assertRaises(NotImplementedError) as e:
            self.p.domain

    def test_aclattr(self):
        self.p._username = "aclusername"
        self.assertEqual(self.p.aclattr, "@aclusername")

    def test_person(self):
        self.p._username = "personusername"
        self.assertEqual(self.p.person, "@personusername")

    def test_to_string(self):
        self.assertEqual(str(self.p), "@test_username")

    def test_equal(self):
        self.another_p = SlackPerson(
            self.webClient, userid=self.userid, channelid=self.channelid
        )
        self.assertTrue(self.p == self.another_p)
        self.assertFalse(self.p == "this is not a person")

    def test_hash(self):
        self.assertEqual(hash(self.p), hash(self.p.userid))
