"""Web pages that Moodle courses link to, saved as text the notes pipeline can read."""

import re
from collections.abc import AsyncIterator
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx2

MAX_BYTES = 20 * 1024 * 1024
VIDEO_HOSTS = re.compile(r"(^|\.)(youtube\.com|youtu\.be|vimeo\.com)$")
SKIP = {"script", "style", "noscript", "svg", "nav", "template", "head", "button", "form"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCKS = {
    "p", "div", "section", "article", "main", "aside", "header", "footer", "ul", "ol", "li",
    "table", "tr", "br", "pre", "blockquote", "figure", "figcaption", "dl", "dt", "dd", "hr",
}  # fmt: skip


class PageTooLarge(Exception):
    pass


def is_video(url: str) -> bool:
    return bool(VIDEO_HOSTS.search(urlsplit(url).hostname or ""))


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0
        self.preformatted = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP:
            self.skipping += 1
        elif tag in HEADINGS:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in BLOCKS:
            self.parts.append("\n")
        if tag == "pre":
            self.preformatted += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in HEADINGS or tag in BLOCKS:
            self.parts.append("\n")
        if tag == "pre":
            self.preformatted = max(0, self.preformatted - 1)

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data if self.preformatted else re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    """Readable Markdown-like text: headings, list items and paragraphs, math as $...$."""
    parser = TextExtractor()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    text = re.sub(r"\\\((.+?)\\\)", r"$\1$", text, flags=re.S)
    text = re.sub(r"\\\[(.+?)\\\]", r"$$\1$$", text, flags=re.S)
    lines = (line.strip() for line in text.split("\n"))
    text = "\n".join(line for line in lines if not re.fullmatch(r"-|#+", line))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def fetch(web: httpx2.AsyncClient, url: str) -> tuple[str, bytes]:
    """The page's content type and body, refusing bodies over MAX_BYTES."""
    async with web.stream("GET", url) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > MAX_BYTES:
                raise PageTooLarge(url)
        return response.headers.get("content-type", ""), bytes(body)


async def get_web_client() -> AsyncIterator[httpx2.AsyncClient]:
    headers = {"user-agent": "kse-ai-notes-taker (course materials import)"}
    async with httpx2.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as web:
        yield web
