from dataclasses import dataclass

from src.protector import ProtectedContent


@dataclass
class LocalizationResult:
    source: str
    localized: str
    locale: str


class Localizer:
    """
    Localization layer.

    Content that must not be translated is replaced with
    placeholders before the provider is called and restored
    afterwards.
    """

    def __init__(
        self,
        provider,
        product_names: list[str] | None = None,
    ):
        self.provider = provider
        self.product_names = product_names or []

    def localize(
        self,
        text: str,
        locale: str,
    ) -> LocalizationResult:

        protector = ProtectedContent(
            product_names=self.product_names
        )

        protected = protector.protect(text)

        translated = self.provider.translate(
            protected,
            locale,
        )

        restored = protector.restore(
            translated
        )

        return LocalizationResult(
            source=text,
            localized=restored,
            locale=locale,
        )


class TestLocalizationProvider:
    """
    Deterministic provider used only for tests and local
    pipeline demonstrations.

    It does NOT perform real translation.
    """

    def translate(
        self,
        text: str,
        locale: str,
    ) -> str:
        return f"[{locale}] {text}"