# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [0.3.0] Unreleased
### Added
### Changed
### Fixed

## [0.2.1] 2022-10-02
### Added
 - Send cards to threads, when requested. #76 (@TheJokersThief)
 - Ability to update slack messages. #75 (@TheJokersThief)
 - Allow supplying raw attachments/blocks for messages. #83 (@TheJokersThief)

### Changed
 - refactored repository for setting it up as a pypi package. #82, #89 (@sijis)

### Fixed
 - Ensure ephemeral messages return a ts attribute. #81 (@TheJokersThief)

## [0.2.0] 2022-09-22
### Added
 -  Ability to update slack messages. #75 (@TheJokersThief)
 -  Send cards to threads, when asked. #76 + #79 (@TheJokersThief + @duhow)
### Changed
### Fixed
 - Unable to add add/remove reactions. #66 (@pdkhai)
 - Exception being raised on unsupported Slack events like modal and other Slack GUI events. #72 (@nzlosh)
 - Getting topic for non-existent channel. #73 (@sijis)
 - Bot id lookup for Bot accounts and Slack bot messages #74 (@jcfrt)

### Removed

## [0.1.1] 2021-12-09
### Added
  - Documentation for configuring BOT_ADMIN and BOT_ADMIN_NOTIFICATION.
### Changed
### Fixed
  - Channel mentions caused messages to be silently dropped. #57 (@nzlosh)
### Removed

## [0.1.0] 2021-11-25
### Added
  - changelog file.
  - Github actions for unit tests, codestyle, lint.
  - unit tests.
  - Python 3.10 to unit tets
  - handler for reaction add/remove events.

### Changed
  - Person field returns unique identifier instead of @ usernames which aren't guaranteed to be unique.
    See https://github.com/errbotio/err-backend-slackv3/issues/33 for details.
  - Markdown dependency to pull from github commit that includes slack mention fix.
    See https://github.com/Python-Markdown/markdown/pull/1165 for details.

### Removed
  - Python 3.6 from unit tests.
