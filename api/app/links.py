"""Web pages that Moodle courses link to or hold (url, page and book modules), saved as Markdown
the notes pipeline can read."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urljoin, urlsplit

import httpx2
from bs4 import BeautifulSoup, NavigableString
from markdownify import MarkdownConverter

MAX_BYTES = 20 * 1024 * 1024
VIDEO_HOSTS = re.compile(r"(^|\.)(youtube\.com|youtu\.be|vimeo\.com)$")
# Page chrome and code that carries no reading text.
DROP = ["script", "style", "noscript", "svg", "nav", "template", "head", "button", "form", "iframe"]
DROP_SELECTORS = [".slide-menu-button", ".quarto-title-meta", ".sourceCode .code-copy-button"]
# MathJax delimiters: \( inline \) and \[ display \].
MATH = re.compile(r"\\\((.+?)\\\)|\\\[(.+?)\\\]", re.S)
TOKEN = "MDMATH{}X"


class PageTooLarge(Exception):
    pass


def is_video(url: str) -> bool:
    return bool(VIDEO_HOSTS.search(urlsplit(url).hostname or ""))


def _content_root(soup: BeautifulSoup):
    """The page's content: reveal.js slides, the main or article element, else the body."""
    return (
        soup.select_one(".reveal .slides")
        or soup.find("main")
        or soup.find("article")
        or soup.body
        or soup
    )


def _collapse_whitespace(root) -> None:
    """Runs of whitespace read as one space, as a browser shows them; code keeps its own."""
    for text in list(root.find_all(string=re.compile(r"\s\s|\n"))):
        if not text.find_parent(["pre", "code"]):
            text.replace_with(NavigableString(re.sub(r"\s+", " ", str(text))))


def _hide_math(root, formulas: list[str]) -> None:
    """Swap LaTeX for tokens, so Markdown escaping does not touch it, and keep it as $...$."""
    for text in list(root.find_all(string=MATH)):
        if text.find_parent(["pre", "code"]):
            continue

        def token(match: re.Match) -> str:
            inline, display = match.group(1), match.group(2)
            if inline is not None:
                formulas.append(f"${inline.strip()}$")
            else:
                formulas.append(f"\n\n$$\n{display.strip()}\n$$\n\n")
            return TOKEN.format(len(formulas) - 1)

        text.replace_with(NavigableString(MATH.sub(token, str(text))))


def _base(url: str) -> str:
    """The URL relative links resolve against. A last segment without an extension is a folder:
    sites like Quarto Pub serve `/deck` but keep its images under `/deck/`."""
    parts = urlsplit(url)
    last = parts.path.rsplit("/", 1)[-1]
    if last and "." not in last:
        return parts._replace(path=parts.path + "/").geturl()
    return url


def _absolute_links(root, base_url: str) -> None:
    base_url = _base(base_url)
    for image in root.find_all("img"):
        # reveal.js loads images lazily from data-src.
        src = image.get("src") or image.get("data-src")
        if not src or src.startswith("data:"):
            image.decompose()
            continue
        image["src"] = urljoin(base_url, src)
    for link in root.find_all("a", href=True):
        if link["href"].startswith("#"):
            link.unwrap()
        else:
            link["href"] = urljoin(base_url, link["href"])


def html_to_markdown(html: str, base_url: str = "") -> str:
    """The page's content as Markdown: headings, lists, tables, code, links and images (made
    absolute against `base_url`), and math as $...$ and $$...$$."""
    soup = BeautifulSoup(html, "html.parser")
    # Comments, CDATA and the doctype: the steps below rewrite only plain text.
    for node in soup.find_all(string=lambda s: type(s) is not NavigableString):
        node.extract()
    for tag in soup(DROP):
        tag.decompose()
    for selector in DROP_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()
    root = _content_root(soup)
    formulas: list[str] = []
    _hide_math(root, formulas)
    _collapse_whitespace(root)
    _absolute_links(root, base_url)

    text = MarkdownConverter(heading_style="ATX", bullets="-", escape_misc=False).convert_soup(root)
    text = re.sub(r"MDMATH(\d+)X", lambda m: formulas[int(m.group(1))], text)
    lines = (line.rstrip() for line in text.split("\n"))
    # Empty headings and bullets, as slides without a title leave them.
    text = "\n".join(line for line in lines if not re.fullmatch(r"\s*(-|#+)", line))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def reading_markdown(title: str, source: str, body: str) -> str:
    """A saved reading: the title, where it came from, then the page's Markdown."""
    return f"# {title}\n\nSource: {source}\n\n{body}\n"


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
