# errbot-backend-slackv3

[![Documentation Status](https://readthedocs.org/projects/err-backend-slackv3/badge/?version=latest)](https://err-backend-slackv3.readthedocs.io/en/latest/?badge=latest)

Slack Events and Real Time Messaging backend for Errbot.

## Quick Start

It is recommended to install errbot into a Python virtual environment.  The steps are as follows:
_Note: The examples assume the virtual environment is created as `/opt/errbot` but you can adapt this path to your needs._

1. Create and activate the virtual environment.

```
python3 -m venv /opt/errbot
. /opt/errbot/bin/activate
```

2. Install errbot and slackv3.
```
pip install errbot[slack]
```

3. Initialise errbot.
```
errbot --init
```

4. Edit `config.py` to configure the backend with the correct Slack credentials. (See the official documentation of details on how to configure the backend for RTM vs Events)
```
BACKEND = 'SlackV3'
BOT_IDENTITY = {
    'token': 'xoxb-000000000000-000000000000-xxxxxxxxxxxxxxxxxxxxxxxx',
    #'signing_secret': "xxxxxx",
    #'app_token': "xxxxx"
}
```

5. Start errbot
```
errbot -c config.py
```

## Documentation

See the [slackv3 documentation](https://err-backend-slackv3.readthedocs.io/en/latest/) for:
 - Installation
 - Configuration
 - User guide
 - Developer guide

## Support

If you need help for an `errbot-backend-slackv3` problem, open an issue at [github repository](https://github.com/errbotio/err-backend-slackv3)
