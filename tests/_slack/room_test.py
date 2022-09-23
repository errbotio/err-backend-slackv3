import logging
import sys
import unittest
from tempfile import mkdtemp

import pytest
from mock import MagicMock

from _slack.room import *

log = logging.getLogger(__name__)


class SlackRoomTests(unittest.TestCase):
    def test_create_room_without_arguments(self):
        with pytest.raises(ValueError) as excinfo:
            SlackRoom()
        assert "A name or channelid is required to create a Room." in str(excinfo.value)
