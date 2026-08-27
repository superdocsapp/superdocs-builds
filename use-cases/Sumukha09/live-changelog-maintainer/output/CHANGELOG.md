# Repo Changelog

## [1.6.0] - 2026-08-28

> *Multi-language support and safer previews*

### Added

- Full multi-language changelog generation
- No-spend preview mode that never calls SuperDocs
- Identity check that older releases stay byte-identical

### Changed

- House style is now enforced on every insert
- Export always produces Markdown + PDF by default

### Fixed

- Duplicate compare links no longer appear
- Section order is now consistent across all releases

### Removed

- Old experimental --force-rebuild flag

Thanks to @alice, @bob, @dave for contributing to this release.

[Compare v1.5.0...v1.6.0](https://github.com/org/repo/compare/v1.5.0...v1.6.0) | [Release Notes](https://github.com/org/repo/releases/tag/v1.6.0)

## [1.5.0] - 2026-08-27

> *Performance improvements and new CLI flags*

### Added

- New --dry-run flag for safe previews
- Support for custom house-style templates
- Automatic contributor detection from git

### Changed

- Faster surgical inserts (30% speed improvement)
- Default export now includes both Markdown and PDF

### Fixed

- Incorrect ordering when releases share the same date
- Missing blank line after the last section

### Breaking

- Removed support for the old v0 style format

### Removed

- Deprecated --legacy-export flag

Thanks to @alice, @bob, @carol for contributing to this release.

[Compare v1.4.0...v1.5.0](https://github.com/org/repo/compare/v1.4.0...v1.5.0) | [Release Notes](https://github.com/org/repo/releases/tag/v1.5.0)

## [1.4.0] - 2026-08-27

> *Better caching and Windows support*

### Added

- Native Windows binary
- Optional Redis cache backend

### Changed

- Default timeout increased to 30s

### Fixed

- Crash when config file is missing
- Incorrect version shown in --help

Thanks to @alice, @bob for contributing to this release.

[Compare v1.3.0...v1.4.0](https://github.com/org/repo/compare/v1.3.0...v1.4.0) | [Release Notes](https://github.com/org/repo/releases/tag/v1.4.0)

