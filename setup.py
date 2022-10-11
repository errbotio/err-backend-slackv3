import pathlib

from setuptools import find_packages, setup


def read(name, encoding="ascii"):
    filename = pathlib.Path(__file__).absolute().parent / name
    return open(filename, "r", encoding=encoding).read()


REQUIREMENTS = [
    "slack-sdk>=3.12.0",
    "slackeventsapi>=3.0.0",
    "aiohttp",
    "markdown>=3.3.6",
]

setup(
    name="errbot-backend-slackv3",
    version="0.2.1",
    description="Errbot SlackV3 backend plugin",
    author="Errbot",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    package_data={"slackv3": ["*.plug"]},
    include_package_data=True,
    install_requires=REQUIREMENTS,
    long_description_content_type="text/markdown",
    long_description=read("README.md"),
    entry_points={
        "errbot.backend_plugins": [
            "slack = slackv3:SlackBackend",
        ]
    },
)
