from setuptools import find_packages, setup

REQUIREMENTS = [
    "slack-sdk>=3.12.0",
    "slackeventsapi>=3.0.0",
    "aiohttp",
    "markdown>=3.3.6",
]

setup(
    name="errbot-plugin-slackv3",
    version="0.2.0",
    description="Errbot SlackV3 backend plugin",
    author="Errbot",
    packages=find_packages(),
    include_package_data=True,
    install_requires=REQUIREMENTS,
    entry_points={
        "errbot.backend_plugins": [
            "slack = slackv3:SlackBackend",
        ]
    },
)
