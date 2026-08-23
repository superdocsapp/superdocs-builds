from dataclasses import dataclass
from bs4 import BeautifulSoup, Tag


@dataclass
class ImageReference:
    index: int
    src: str
    alt: str
    caption: str | None


@dataclass
class Article:
    html: str
    images: list[ImageReference]


class ArticleParser:
    """
    Parses a help article while preserving its HTML structure.
    """

    def parse(self, html: str) -> Article:
        soup = BeautifulSoup(html, "html.parser")

        images = []

        for index, image in enumerate(soup.find_all("img")):
            parent = image.parent

            caption = None

            if parent and parent.name == "figure":
                caption_tag = parent.find("figcaption")

                if caption_tag:
                    caption = caption_tag.get_text(
                        " ",
                        strip=True,
                    )

            images.append(
                ImageReference(
                    index=index,
                    src=image.get("src", ""),
                    alt=image.get("alt", ""),
                    caption=caption,
                )
            )

        return Article(
            html=str(soup),
            images=images,
        )

    def replace_image(
        self,
        html: str,
        image_index: int,
        new_src: str,
    ) -> str:
        soup = BeautifulSoup(html, "html.parser")

        images = soup.find_all("img")

        if image_index < 0 or image_index >= len(images):
            raise IndexError(
                f"Image index {image_index} is out of range."
            )

        images[image_index]["src"] = new_src

        return str(soup)