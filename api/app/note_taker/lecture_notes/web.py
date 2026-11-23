"""The motivation scout's web tools: search, a page's images, and checking an image.

The note's opening hook may cite facts from the web and show real images. Images are hot-linked:
the page's `<img>` points at the original URL, nothing is copied to our storage (a removed image
shows as broken, which is accepted for now). `check_image` fetches each image once on the server
so the agent cannot invent a URL, and records it; `render_notes` refuses `https://` images that
were not checked in this run.

Every request made here is to a URL the model chose, so `safe_get` allows only `https://` to hosts
whose addresses are all public, checks again on every redirect, and caps size and time.

`web_search` calls OpenRouter's chat API with its `web` plugin (Exa-backed) on a small model and
returns the answer with the pages it cited (`url_citation` annotations; LangChain's OpenRouter
model drops those, so it is called directly).
"""

import base64
import io
import ipaddress
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx
from langchain_core.tools import BaseTool, tool

from app.note_taker.lecture_notes.tools import RenderState, RunCancelled
from app.note_taker.progress import Progress

TIMEOUT = 15.0
MAX_REDIRECTS = 4
MAX_PAGE_BYTES = 2_000_000
MAX_IMAGE_BYTES = 10_000_000
MAX_PAGE_IMAGES = 12
IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}
USER_AGENT = "KSE-Note-Agent/1.0 (lecture notes; image check)"

Resolve = Callable[[str], list[str]]
Search = Callable[[str], dict[str, Any]]
Describe = Callable[[bytes], str | None]


class WebError(Exception):
    """A URL the tools refuse or could not read; the message goes back to the agent."""


def resolve_host(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]


def check_url(url: str, resolve: Resolve) -> None:
    """Refuse anything but https:// to a host whose every address is public."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise WebError(f"only https:// URLs: {url[:200]}")
    if parts.username or parts.password or (parts.port not in (None, 443)):
        raise WebError(f"no credentials or ports in URLs: {url[:200]}")
    try:
        addresses = resolve(parts.hostname)
    except OSError as error:
        raise WebError(f"cannot resolve {parts.hostname}: {error}") from error
    if not addresses:
        raise WebError(f"cannot resolve {parts.hostname}")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global:
            raise WebError(f"{parts.hostname} is not a public host")


def safe_get(
    client: httpx.Client, url: str, resolve: Resolve, max_bytes: int
) -> tuple[str, str, bytes]:
    """(final URL, content type, body) of a GET, following redirects by hand so that every hop
    is checked. A body over `max_bytes` is refused."""
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url, resolve)
        with client.stream(
            "GET", url, headers={"User-Agent": USER_AGENT}, follow_redirects=False
        ) as response:
            if response.is_redirect:
                location = response.headers.get("location", "")
                url = urljoin(url, location)
                continue
            if response.status_code != 200:
                raise WebError(f"{url[:200]} answered HTTP {response.status_code}")
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise WebError(f"{url[:200]} is over {max_bytes // 1_000_000} MB")
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise WebError(f"{url[:200]} is over {max_bytes // 1_000_000} MB")
                chunks.append(chunk)
            return url, response.headers.get("content-type", ""), b"".join(chunks)
    raise WebError(f"too many redirects from {url[:200]}")


class PageImages(HTMLParser):
    """The title and image candidates of an HTML page: og/twitter images, then <img> tags."""

    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.title = ""
        self.in_title = False
        self.found: list[dict[str, str]] = []

    def add(self, src: str, alt: str = "", size: str = "") -> None:
        url = urljoin(self.base, src.strip())
        if url.startswith("https://") and all(f["url"] != url for f in self.found):
            self.found.append({"url": url, "alt": alt.strip()[:200], "size": size})

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "title":
            self.in_title = True
        elif tag == "meta" and (a.get("property") or a.get("name")) in (
            "og:image",
            "og:image:url",
            "twitter:image",
        ):
            self.add(a.get("content", ""), "page preview image")
        elif tag == "img":
            src = a.get("src") or a.get("data-src") or ""
            if src and not src.startswith("data:"):
                size = f"{a['width']}x{a['height']}" if a.get("width") and a.get("height") else ""
                self.add(src, a.get("alt", ""), size)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data


def markdown_url(url: str) -> str:
    """A URL safe inside Markdown's `(...)`: parentheses and spaces escaped."""
    return quote(url, safe=":/?#[]@!$&'*+,;=%~-._")


def openrouter_search(client: httpx.Client, *, base_url: str, api_key: str, model: str) -> Search:
    def search(query: str) -> dict[str, Any]:
        response = client.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "plugins": [{"id": "web", "max_results": 5}],
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Search the web and answer briefly and factually, with dates, names "
                            "and numbers where they matter. Cite your sources.\n\n" + query
                        ),
                    }
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        sources = []
        for note in message.get("annotations") or []:
            cited = note.get("url_citation") or {}
            if cited.get("url") and all(s["url"] != cited["url"] for s in sources):
                sources.append(
                    {
                        "url": cited["url"],
                        "title": cited.get("title", ""),
                        "snippet": (cited.get("content") or "")[:400],
                    }
                )
        return {"answer": message.get("content") or "", "sources": sources}

    return search


def openrouter_describe(
    client: httpx.Client, *, base_url: str, api_key: str, model: str
) -> Describe:
    """One sentence on what an image shows, from a vision model, so the agent (which cannot see
    it) knows it picked the right picture."""

    def describe(preview_jpeg: bytes) -> str | None:
        data = base64.b64encode(preview_jpeg).decode()
        response = client.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Describe in one plain sentence what this image shows. "
                                "Mention any visible text.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{data}"},
                            },
                        ],
                    }
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        return (response.json()["choices"][0]["message"].get("content") or "").strip()[:400]

    return describe


@dataclass
class WebLimits:
    searches: int = 6
    images: int = 4


@dataclass
class WebUse:
    searches: int = 0
    pages: int = 0
    images: int = 0
    log: list[str] = field(default_factory=list)


@dataclass
class WebAccess:
    """How the scout reaches the web; tests pass fakes."""

    search: Search | None
    describe: Describe | None = None
    client: httpx.Client | None = None
    resolve: Resolve = resolve_host
    limits: WebLimits = field(default_factory=WebLimits)


def openrouter_access(
    *,
    base_url: str,
    api_key: str,
    search_model: str,
    vision_model: str | None,
    limits: WebLimits,
) -> WebAccess:
    client = httpx.Client(timeout=TIMEOUT)
    options = {"base_url": base_url, "api_key": api_key}
    return WebAccess(
        search=openrouter_search(client, model=search_model, **options),
        describe=openrouter_describe(client, model=vision_model, **options)
        if vision_model
        else None,
        client=client,
        limits=limits,
    )


def make_web_tools(
    state: RenderState,
    access: WebAccess,
    *,
    progress: Progress | None = None,
    cancelled: threading.Event | None = None,
) -> list[BaseTool]:
    """`web_search`, `page_images` and `check_image`. Checked images go to `state.web_images`,
    which `render_notes` uses to refuse unchecked ones."""
    from PIL import Image

    search, describe, resolve, limits = (
        access.search,
        access.describe,
        access.resolve,
        access.limits,
    )
    client = access.client or httpx.Client(timeout=TIMEOUT)
    progress = progress or Progress()
    use = WebUse()

    def stop_if_cancelled() -> None:
        if cancelled is not None and cancelled.is_set():
            raise RunCancelled

    @tool
    def web_search(query: str) -> str:
        """Search the web. Use it to check facts for the hook (dates, names, numbers, real cases)
        and to find pages with good images. Returns a short answer and the pages it cites.
        Limited per run: make each query count."""
        stop_if_cancelled()
        if search is None:
            return "Web search is off for this run. Work from the readings and your knowledge."
        if use.searches >= limits.searches:
            return f"Search limit reached ({limits.searches}). Use what you found."
        use.searches += 1
        with progress.action(f"Searching the web: {query[:80]}") as action:
            try:
                found = search(query)
            except Exception as error:  # the network or OpenRouter; the agent may go on
                action.status, action.detail = "failed", str(error)[:200]
                return f"Search failed: {error}"[:500]
            action.detail = f"{len(found['sources'])} source(s)"
        lines = [found["answer"].strip()[:3000], "", "Sources:"]
        lines += [
            f"- {s['title'] or s['url']}: {s['url']}\n  {s['snippet']}" for s in found["sources"]
        ] or ["- (none cited)"]
        return "\n".join(lines)

    @tool
    def page_images(url: str) -> str:
        """List the images on a web page (its preview image first, then <img> tags with their
        alt text), to pick one for check_image. `url` is the page, not an image."""
        stop_if_cancelled()
        if use.pages >= limits.searches * 2:
            return "Page limit reached. Pick from the images you have."
        use.pages += 1
        try:
            final, kind, body = safe_get(client, url, resolve, MAX_PAGE_BYTES)
        except (WebError, httpx.HTTPError) as error:
            return f"Cannot read the page: {error}"[:500]
        if "html" not in kind:
            return f"Not an HTML page ({kind or 'unknown type'})."
        parser = PageImages(final)
        parser.feed(body.decode("utf-8", errors="replace"))
        found = parser.found[:MAX_PAGE_IMAGES]
        if not found:
            return f"No images found on {final}."
        lines = [f"Page: {parser.title.strip()[:200] or final}", f"URL: {final}", "Images:"]
        lines += [
            f"- {f['url']}" + (f" ({f['size']})" if f["size"] else "") + f" alt: {f['alt']!r}"
            for f in found
        ]
        return "\n".join(lines)

    @tool
    def check_image(image_url: str, source_page: str, source_title: str) -> str:
        """Check an image on the web before showing it in the note, and get the Markdown to use.

        `image_url` is the image file (https), `source_page` the page it comes from (its
        credit link), `source_title` that page's name. The image is shown from its own URL (not
        copied); its caption must keep the source link. Returns what the image shows and the
        Markdown, or why it cannot be used."""
        stop_if_cancelled()
        if image_url in state.web_images:
            return "Already checked:\n" + state.web_images[image_url]["markdown"]
        if use.images >= limits.images:
            return f"Image limit reached ({limits.images}). Use the images you have."
        try:
            check_url(source_page, resolve)
        except WebError as error:
            return f"Bad source page: {error}"
        with progress.action("Checking an image from the web") as action:
            try:
                final, _, data = safe_get(client, image_url, resolve, MAX_IMAGE_BYTES)
                with Image.open(io.BytesIO(data)) as image:
                    image_format = image.format or ""
                    width, height = image.size
                    frames = getattr(image, "n_frames", 1)
                    if image_format not in IMAGE_FORMATS:
                        raise WebError(f"not a JPEG, PNG, GIF or WebP image ({image_format})")
                    if width < 200 or height < 120:
                        raise WebError(f"too small to show ({width}x{height})")
                    preview = image.convert("RGB")
                    preview.thumbnail((512, 512))
                    buffer = io.BytesIO()
                    preview.save(buffer, "JPEG", quality=80)
            except (WebError, httpx.HTTPError, OSError, Image.DecompressionBombError) as error:
                action.status, action.detail = "failed", str(error)[:200]
                return f"Cannot use this image: {error}"[:500]
            use.images += 1
            shows = None
            if describe is not None:
                try:
                    shows = describe(buffer.getvalue())
                except Exception:  # the description is a help, never a reason to fail
                    shows = None
            title = " ".join(source_title.replace("[", "(").replace("]", ")").split())[:120]
            title = title or urlsplit(source_page).hostname or "source"
            markdown = (
                f"![<what it shows and why it matters>. Source: [{title}]"
                f"({markdown_url(source_page)})]({markdown_url(final)})"
            )
            # Both spellings count as checked: the one the agent sent and the one to write.
            record = {
                "url": final,
                "source_page": source_page,
                "title": title,
                "width": width,
                "height": height,
                "format": image_format,
                "markdown": markdown,
            }
            for url in {image_url, final, markdown_url(final)}:
                state.web_images[url] = record
            action.detail = f"{image_format} {width}x{height}"
        animated = f", animated ({frames} frames)" if frames > 1 else ""
        return "\n".join(
            [
                f"OK: {image_format} {width}x{height}{animated}.",
                f"It shows: {shows}" if shows else "No description available; trust the alt text.",
                "Use this Markdown on a line of its own (write the caption; keep the Source "
                "link). In the hook leave it unnumbered; elsewhere add {#fig-name} after it.",
                markdown,
            ]
        )

    return [web_search, page_images, check_image]
