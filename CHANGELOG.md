# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [0.2.0] Unreleased
### Added
### Changed
### Fixed
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
