from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScreenshotResolution:
    source: str
    locale: str
    resolved: str | None
    missing: bool


class ScreenshotResolver:
    """
    Resolves article screenshots to locale-specific assets.

    A missing locale screenshot is never silently replaced
    with the source-language screenshot.
    """

    def __init__(self, screenshot_root: str | Path):
        self.root = Path(screenshot_root)

    def resolve(
        self,
        source_path: str,
        locale: str,
    ) -> ScreenshotResolution:

        source = Path(source_path)

        candidate = (
            self.root
            / locale
            / source.name
        )

        if candidate.exists():
            return ScreenshotResolution(
                source=source_path,
                locale=locale,
                resolved=candidate.as_posix(),
                missing=False,
            )

        return ScreenshotResolution(
            source=source_path,
            locale=locale,
            resolved=None,
            missing=True,
        )