# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [1.0.0] Unreleased
### Added
  - Added changelog file.
  - Added Github actions for unit tests, codestyle, lint.
  - Added Python 3.10 to unit tets
  - Added unit tests.
  - Added handler for reaction add/remove.

### Changed
  - Person field returns unique identifier instead of @ usernames which aren't guaranteed to be unique.
    See https://github.com/errbotio/err-backend-slackv3/issues/33 for details.
  - Markdown dependency to pull from github commit that includes slack mention fix.
    See https://github.com/Python-Markdown/markdown/pull/1165 for details.

### Removed
  - Python 3.6 from unit tests.
