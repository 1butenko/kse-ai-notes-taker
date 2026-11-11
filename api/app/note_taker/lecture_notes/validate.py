"""What the agent may write in a lecture note: an allowlist checked before every render.

The note's body is model-written Quarto Markdown and is rendered on the server, then shown in a
sandboxed iframe. Nothing in it may run on the server, read files, or reach outside the page:

- no metadata (the server writes the front matter), no shortcodes, no raw blocks or attributes;
- cells only `{mermaid}`, `{dot}` and `{ojs}`, with allowlisted options; other code is shown in
  a plain fence (```python);
- div, span and heading attributes from an allowlist; tiny inline HTML only;
- images only the note's own SVG assets, which are parsed and checked element by element;
- links only http(s), mailto and in-page anchors;
- OJS cells without network, storage or frame access (the sandbox and CSP contain the rest).

Each problem comes back with its line, so the agent can fix it and render again.
"""

import html
import re
from dataclasses import dataclass
from urllib.parse import unquote
from xml.etree import ElementTree

MAX_BODY_BYTES = 300_000
MAX_ASSET_BYTES = 200_000
MAX_DIAGRAMS = 20
MAX_OJS_CELLS = 6
ASSET_NAME = re.compile(r"^assets/[a-z0-9][a-z0-9-]{0,60}\.svg$")

CELLS = {"mermaid", "dot", "ojs"}
CELL_OPTIONS = {
    "label",
    "fig-cap",
    "fig-alt",
    "fig-width",
    "fig-height",
    "fig-align",
    "echo",
    "code-fold",
    "code-summary",
    "panel",
}
OPTION_PREFIXES = ("#|", "%%|", "//|")

CLASSES = {
    "callout-note",
    "callout-tip",
    "callout-important",
    "callout-warning",
    "callout-caution",
    "panel-tabset",
    "panel-sidebar",
    "panel-fill",
    "panel-center",
    "panel-input",
    "columns",
    "column",
    "column-margin",
    "column-body",
    "column-body-outset",
    "column-page",
    "column-page-inset",
    "column-screen-inset",
    "aside",
    "border",
    "unnumbered",
    "unlisted",
    "smaller",
    "lightbox",
    "nostretch",
    "mark",
    "underline",
    "smallcaps",
}
ID_PREFIXES = (
    "sec-",
    "fig-",
    "tbl-",
    "eq-",
    "thm-",
    "lem-",
    "cor-",
    "prp-",
    "def-",
    "exm-",
    "exr-",
    "cnj-",
    "rem-",
)
ATTRIBUTES = {
    "title",
    "collapse",
    "icon",
    "appearance",
    "width",
    "height",
    "fig-align",
    "fig-alt",
    "layout-ncol",
    "layout-nrow",
    "layout-valign",
    "tbl-colwidths",
    "group",
}
INLINE_HTML = {"kbd", "sub", "sup", "br", "details", "summary"}

SVG_ELEMENTS = {
    "svg",
    "g",
    "defs",
    "title",
    "desc",
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "text",
    "tspan",
    "marker",
    "linearGradient",
    "radialGradient",
    "stop",
    "clipPath",
    "mask",
    "pattern",
    "use",
    "symbol",
    "style",
}

OJS_FORBIDDEN = re.compile(
    r"\b(?:FileAttachment|fetch|XMLHttpRequest|WebSocket|EventSource|importScripts|eval|"
    r"Function|postMessage|localStorage|sessionStorage|indexedDB|navigator|cookie|"
    r"opener|parent|top|frames|Worker|SharedWorker|require)\b|\bimport\s*\(|"
    r"\bimport\b[^;\n]*\bfrom\s*['\"]|document\.(?:write|domain|location)|window\.location|"
    r"\blocation\s*\.|\bhttps?://",
)
MERMAID_FORBIDDEN = re.compile(r"^\s*(?:click\b|%%\{)", re.M)
DOT_FORBIDDEN = re.compile(r"\b(?:image|imagepath|shapefile|fontpath|fontnames)\s*=", re.I)
MATH_FORBIDDEN = re.compile(r"\\(?:input|include|href|url|require|unicode|class|cssId|style)\b")
BAD_SCHEME = re.compile(r"(?:javascript|vbscript|data|file|blob):", re.I)


@dataclass(frozen=True)
class Issue:
    line: int  # 1-based; 0 for the whole document or an asset
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}" if self.line else self.message


def parse_attributes(text: str) -> list[tuple[str, str]] | None:
    """Pandoc attribute tokens: ('class', x), ('id', x) or (key, value). None if not attributes."""
    tokens = re.findall(r"""\.[\w-]+|#[\w:.-]+|[\w-]+=(?:"[^"]*"|'[^']*'|[^\s"']+)|\S+""", text)
    found: list[tuple[str, str]] = []
    for token in tokens:
        if token.startswith("."):
            found.append(("class", token[1:]))
        elif token.startswith("#"):
            found.append(("id", token[1:]))
        elif "=" in token:
            key, _, value = token.partition("=")
            found.append((key, value.strip("\"'")))
        else:
            return None
    return found


def attribute_issues(line: int, attrs: list[tuple[str, str]]) -> list[Issue]:
    issues = []
    for kind, value in attrs:
        if kind == "class":
            if value not in CLASSES:
                issues.append(Issue(line, f"class .{value} is not allowed"))
        elif kind == "id":
            if not value.startswith(ID_PREFIXES) or not re.fullmatch(r"[\w-]+", value):
                issues.append(
                    Issue(line, f"id #{value} must start with one of {', '.join(ID_PREFIXES)}")
                )
        elif kind not in ATTRIBUTES:
            issues.append(Issue(line, f"attribute {kind}= is not allowed"))
        elif BAD_SCHEME.search(re.sub(r"\s+", "", unquote(html.unescape(value)))):
            issues.append(Issue(line, f"attribute {kind}= has an unsafe value"))
    return issues


def strip_inline(text: str) -> str:
    """Prose without inline code and math, which may hold braces and angle brackets."""
    text = re.sub(r"(`+)(.+?)\1", " ", text)
    return re.sub(r"\$\$.+?\$\$|\$[^$\n]+?\$", " ", text)


def cell_issues(kind: str, start: int, lines: list[str]) -> list[Issue]:
    issues = []
    code = []
    for offset, raw in enumerate(lines, start=start + 1):
        stripped = raw.strip()
        if stripped.startswith(OPTION_PREFIXES):
            option = stripped.split("|", 1)[1].strip()
            key, _, value = option.partition(":")
            key, value = key.strip(), value.strip().strip("\"'")
            if key not in CELL_OPTIONS:
                issues.append(Issue(offset, f"cell option {key!r} is not allowed"))
            elif key == "label" and not re.fullmatch(r"fig-[\w-]+", value):
                issues.append(Issue(offset, "a cell label must look like fig-name"))
            continue
        code.append(raw)
    body = "\n".join(code)
    pattern = {"ojs": OJS_FORBIDDEN, "mermaid": MERMAID_FORBIDDEN, "dot": DOT_FORBIDDEN}[kind]
    if match := pattern.search(body):
        what = match.group(0).strip()
        issues.append(
            Issue(start, f"{{{kind}}} cell uses {what!r}, which is not allowed (see the skill)")
        )
    return issues


def validate_body(body: str, assets: dict[str, bytes] | None = None) -> list[Issue]:
    """Problems in a note's body (the .qmd without front matter) and its SVG assets."""
    assets = assets or {}
    issues: list[Issue] = []
    if len(body.encode()) > MAX_BODY_BYTES:
        issues.append(Issue(0, f"the note is over {MAX_BODY_BYTES // 1000} KB; shorten it"))

    # Reference-style link definitions ([x]: target) are checked like inline links.
    for number, target in (
        (n, m[1])
        for n, line in enumerate(body.splitlines(), start=1)
        if (m := re.match(r"^\s{0,3}\[(?!\^)[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", line))
    ):
        if not re.match(r"(?:https?://|mailto:|#)", target):
            issues.append(Issue(number, f"link {target!r}: only http(s), mailto and # links"))

    lines = body.splitlines()
    fence: str | None = None
    cell: str | None = None
    cell_start = 0
    cell_lines: list[str] = []
    in_math = False
    diagrams = ojs = 0
    for number, line in enumerate(lines, start=1):
        match = re.match(r"^\s*(`{3,}|~{3,})\s*(.*?)\s*$", line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2]:
                if cell:
                    issues += cell_issues(cell, cell_start, cell_lines)
                fence, cell, cell_lines = None, None, []
            elif cell:
                cell_lines.append(line)
            continue
        if match:
            fence, info = match[1], match[2]
            braced = re.fullmatch(r"\{\s*([\w-]+)\s*\}", info)
            if braced and braced[1] in CELLS:
                cell, cell_start = braced[1], number
                if cell == "ojs":
                    ojs += 1
                else:
                    diagrams += 1
            elif info.startswith("{") or not re.fullmatch(r"[\w+.#-]*", info):
                issues.append(
                    Issue(
                        number,
                        "only {mermaid}, {dot} and {ojs} cells are allowed; show other code in a "
                        "plain fence such as ```python",
                    )
                )
            continue
        if in_math or "$$" in line.replace("\\$", ""):
            # Display math may span lines; braces in it ({t=1}) are TeX, not attributes.
            visible, in_math = outside_math(line, in_math)
            if MATH_FORBIDDEN.search(line):
                issues.append(Issue(number, "this TeX command is not allowed"))
            issues += line_issues(number, visible, assets) if visible.strip() else []
            continue
        issues += line_issues(number, line, assets)
    if fence:
        issues.append(Issue(len(lines), "a code fence is never closed"))
    if diagrams > MAX_DIAGRAMS:
        issues.append(Issue(0, f"at most {MAX_DIAGRAMS} diagrams per note"))
    if ojs > MAX_OJS_CELLS:
        issues.append(Issue(0, f"at most {MAX_OJS_CELLS} {{ojs}} cells per note"))

    for name, data in assets.items():
        issues += [Issue(0, f"{name}: {problem}") for problem in svg_issues(name, data)]
    return issues


def outside_math(line: str, in_math: bool) -> tuple[str, bool]:
    """The parts of a line outside display math (`$$ ... $$`), and whether math continues on the
    next line."""
    parts = line.replace("\\$", "  ").split("$$")
    visible = []
    for index, part in enumerate(parts):
        if not in_math:
            visible.append(part)
        if index < len(parts) - 1:
            in_math = not in_math
    return " ".join(visible), in_math


def line_issues(number: int, line: str, assets: dict[str, bytes]) -> list[Issue]:
    issues = []
    if re.fullmatch(r"\s*(?:---|\.\.\.)\s*", line):
        return [Issue(number, "metadata blocks are not allowed; use *** for a horizontal rule")]
    if re.search(r"\{\{\s*[<%]", line):
        issues.append(Issue(number, "shortcodes ({{< >}}) are not allowed"))
    if re.search(r"\{\s*=", line):
        issues.append(Issue(number, "raw blocks and attributes ({=html}) are not allowed"))
    if MATH_FORBIDDEN.search(line):
        issues.append(Issue(number, "this TeX command is not allowed"))

    prose = strip_inline(line)
    div = re.match(r"^\s*:{3,}\s*(.*?)\s*:*\s*$", prose)
    if div and div[1]:
        inner = div[1][1:-1] if div[1].startswith("{") and div[1].endswith("}") else div[1]
        attrs = parse_attributes(
            inner if inner.startswith(("{", ".", "#")) or "=" in inner else "." + inner
        )
        if attrs is None:
            issues.append(Issue(number, f"cannot read the div attributes {div[1]!r}"))
        else:
            issues += attribute_issues(number, attrs)
        return issues

    # Attribute blocks after headings, spans, images and table captions: {#sec-x}, {.aside}.
    for block in re.findall(r"\{([^{}]*)\}", prose):
        attrs = parse_attributes(block)
        if attrs and (
            block.strip().startswith((".", "#")) or any(k not in ("class", "id") for k, _ in attrs)
        ):
            issues += attribute_issues(number, attrs)

    for path in re.findall(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)", prose):
        if not ASSET_NAME.fullmatch(path):
            issues.append(Issue(number, f"image {path!r}: use your own assets/<name>.svg files"))
        elif path not in assets:
            issues.append(Issue(number, f"image {path!r} does not exist in /notes/assets/"))
    without_images = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", prose)
    for target in re.findall(r"\]\(\s*<?([^)\s>]+)", without_images):
        if not re.match(r"(?:https?://|mailto:|#)", target):
            issues.append(Issue(number, f"link {target!r}: only http(s), mailto and # links"))

    without_autolinks = re.sub(r"<(?:https?|mailto):[^>\s]+>", " ", prose)
    for tag, attrs in re.findall(r"</?([A-Za-z][\w-]*)([^>]*)>", without_autolinks):
        if tag.lower() not in INLINE_HTML or attrs.strip(" /"):
            issues.append(Issue(number, f"HTML <{tag}> is not allowed; use Markdown"))
    if re.search(r"<[!?]", without_autolinks):
        issues.append(Issue(number, "HTML comments and declarations are not allowed"))
    return issues


def local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def svg_issues(name: str, data: bytes) -> list[str]:
    if not ASSET_NAME.fullmatch(name):
        return ["asset names must look like assets/<lowercase-name>.svg"]
    if len(data) > MAX_ASSET_BYTES:
        return [f"over {MAX_ASSET_BYTES // 1000} KB"]
    text = data.decode("utf-8", errors="replace")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I):
        return ["DOCTYPE and ENTITY declarations are not allowed"]
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        return [f"not valid XML: {error}"]
    if local_name(root.tag) != "svg":
        return ["the root element must be <svg>"]
    problems = []
    for element in root.iter():
        tag = local_name(element.tag)
        if tag not in SVG_ELEMENTS:
            problems.append(f"<{tag}> is not allowed")
            continue
        for key, value in element.attrib.items():
            attr = local_name(key)
            flat = re.sub(r"\s+", "", unquote(html.unescape(value)))
            if attr.lower().startswith("on"):
                problems.append(f"<{tag} {attr}> event handlers are not allowed")
            elif attr == "href" and not value.startswith("#"):
                problems.append(f"<{tag} href> may only point inside the SVG (#id)")
            elif BAD_SCHEME.search(flat) or re.search(r"url\((?!['\"]?#)", flat, re.I):
                problems.append(f"<{tag} {attr}> has an external or active value")
        if tag == "style" and element.text:
            css = re.sub(r"\s+", "", element.text)
            if (
                "@import" in css
                or re.search(r"url\((?!['\"]?#)", css, re.I)
                or "expression(" in css
            ):
                problems.append("<style> may not import or load anything")
    return problems
