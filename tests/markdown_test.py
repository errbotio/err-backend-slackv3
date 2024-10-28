import logging
import unittest

from slackv3.markdown import slack_markdown_converter

log = logging.getLogger(__name__)


class SlackMarkdownTests(unittest.TestCase):
    def testSlackMarkdownConverter(self):
        md = slack_markdown_converter()
        markdown = md.convert("**hello** [link](http://to.site/path)")
        self.assertEqual(markdown, "*hello* <http://to.site/path|link>")
