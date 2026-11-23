"""Text that a line, curve, shape edge or other label runs through, in a hand-made SVG figure.

Models place labels by eye and put them on top of their own curves and axes, which reads badly
(the letters are cut by the lines). This estimates each `<text>`'s box from its font size and
character count and checks it against every drawn segment, including where animated elements
move to, so `render_notes` can send the agent back to move the label.

It is an estimate, not a renderer: a label's width is taken as `WIDTH_EM` of the font size per
character, and the box is shrunk by `SLACK` so a line that only grazes a label passes. A label
with a halo (`stroke` and `paint-order="stroke"`) may sit on lines; a shape's inside may hold
labels (a box with its name in it), only its edges count. Rotated text is skipped.
"""

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from xml.etree import ElementTree

WIDTH_EM = 0.55  # average advance of Helvetica/Arial for mixed text, per font-size
ASCENT_EM = 0.72
DESCENT_EM = 0.2
SLACK = 1.5  # viewBox units trimmed off each side of a label's box
DEFAULT_FONT_SIZE = 16.0
CURVE_STEPS = 16
MOTION_STEPS = 12
MAX_REPORTS = 6

SKIPPED = {"defs", "marker", "clipPath", "mask", "pattern", "symbol", "title", "desc", "style"}
INHERITED = ("text-anchor", "stroke", "paint-order")
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
SHAPES = {"line", "polyline", "polygon", "path", "rect", "circle", "ellipse"}
GEOMETRY = {"x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "width", "height"}
NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
PATH_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
TRANSFORM = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
KEYFRAMES_START = re.compile(r"@keyframes\s+([\w-]+)\s*\{")
TRANSLATE = re.compile(r"translate(X|Y|)\(\s*([-\d.]+)(?:px)?\s*(?:,\s*([-\d.]+)(?:px)?)?\s*\)")

Point = tuple[float, float]
Segment = tuple[Point, Point]
Affine = tuple[float, float, float, float, float, float]  # a b c d e f, as in matrix()
IDENTITY: Affine = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass
class Label:
    text: str
    x: float
    y: float
    box: tuple[float, float, float, float]  # left, top, right, bottom


@dataclass
class Drawn:
    tag: str
    moving: bool
    segments: list[Segment] = field(default_factory=list)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def numbers(text: str | None) -> list[float]:
    return [float(n) for n in NUMBER.findall(text or "")]


def multiply(m: Affine, n: Affine) -> Affine:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a * a2 + c * b2,
        b * a2 + d * b2,
        a * c2 + c * d2,
        b * c2 + d * d2,
        a * e2 + c * f2 + e,
        b * e2 + d * f2 + f,
    )


def apply(m: Affine, p: Point) -> Point:
    a, b, c, d, e, f = m
    return a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f


def parse_transform(text: str | None) -> Affine:
    result = IDENTITY
    for name, args in TRANSFORM.findall(text or ""):
        v = numbers(args)
        if name == "matrix" and len(v) == 6:
            step = (v[0], v[1], v[2], v[3], v[4], v[5])
        elif name == "translate" and v:
            step = (1.0, 0.0, 0.0, 1.0, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale" and v:
            step = (v[0], 0.0, 0.0, v[1] if len(v) > 1 else v[0], 0.0, 0.0)
        elif name == "rotate" and v:
            t = math.radians(v[0])
            cx, cy = (v[1], v[2]) if len(v) > 2 else (0.0, 0.0)
            cos, sin = math.cos(t), math.sin(t)
            step = (cos, sin, -sin, cos, cx - cos * cx + sin * cy, cy - sin * cx - cos * cy)
        elif name in ("skewX", "skewY") and v:
            k = math.tan(math.radians(v[0]))
            step = (1.0, 0.0, k, 1.0, 0.0, 0.0) if name == "skewX" else (1.0, k, 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        result = multiply(result, step)
    return result


def declarations(text: str) -> dict[str, str]:
    found = {}
    for part in text.split(";"):
        key, _, value = part.partition(":")
        if value:
            found[key.strip().lower()] = value.strip()
    return found


@dataclass
class Styles:
    """The `<style>` rules this check understands: `.class`, `tag` and `tag.class` selectors,
    and CSS keyframe translations by animation name."""

    rules: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    keyframes: dict[str, list[Point]] = field(default_factory=dict)

    @classmethod
    def read(cls, root: ElementTree.Element) -> "Styles":
        styles = cls()
        for element in root.iter():
            if local_name(element.tag) != "style" or not element.text:
                continue
            css = re.sub(r"/\*.*?\*/", "", element.text, flags=re.S)
            css = styles.take_keyframes(css)
            for selectors, body in CSS_RULE.findall(css):
                props = declarations(body)
                for selector in selectors.split(","):
                    styles.rules.append((selector.strip(), props))
        return styles

    def take_keyframes(self, css: str) -> str:
        """Record each `@keyframes` block's translations and return the CSS without them."""
        rest = []
        pos = 0
        while match := KEYFRAMES_START.search(css, pos):
            rest.append(css[pos : match.start()])
            depth, end = 1, match.end()
            while end < len(css) and depth:
                depth += {"{": 1, "}": -1}.get(css[end], 0)
                end += 1
            self.keyframes[match.group(1)] = keyframe_offsets(css[match.end() : end])
            pos = end
        rest.append(css[pos:])
        return "".join(rest)

    def props(self, element: ElementTree.Element) -> dict[str, str]:
        tag = local_name(element.tag)
        classes = set((element.get("class") or "").split())
        found: dict[str, str] = {}
        for selector, props in self.rules:
            name, _, cls = selector.partition(".")
            if (name in ("", tag) and (not cls or cls in classes)) and (name or cls):
                found.update(props)
        for key, value in element.attrib.items():
            found[local_name(key).lower()] = value
        found.update(declarations(element.get("style") or ""))
        return found


def keyframe_offsets(body: str) -> list[Point]:
    offsets = [(0.0, 0.0)]
    for axis, first, second in TRANSLATE.findall(body):
        a = float(first)
        if axis == "X":
            offsets.append((a, 0.0))
        elif axis == "Y":
            offsets.append((0.0, a))
        else:
            offsets.append((a, float(second) if second else 0.0))
    return offsets


def font_size(value: str | None, inherited: float) -> float:
    if not value:
        return inherited
    v = numbers(value)
    if not v:
        return inherited
    if value.strip().endswith("em"):
        return v[0] * inherited
    if value.strip().endswith("%"):
        return v[0] / 100 * inherited
    return v[0]


def has_halo(props: dict[str, str]) -> bool:
    stroke = props.get("stroke", "none").lower()
    return stroke not in ("none", "transparent", "") and "stroke" in props.get("paint-order", "")


def is_rotated(m: Affine) -> bool:
    return abs(m[1]) > 1e-6 or abs(m[2]) > 1e-6


def text_labels(
    element: ElementTree.Element, props: dict[str, str], size: float, ctm: Affine
) -> list[Label]:
    """The text's lines: each `<tspan>` with its own position is a line of its own."""
    anchor = props.get("text-anchor", "start")
    x0, y0 = (numbers(element.get("x")) or [0.0])[0], (numbers(element.get("y")) or [0.0])[0]
    pieces: list[tuple[str, float, float]] = []
    head = (element.text or "").strip()
    current = [head] if head else []
    cx, cy = x0, y0
    for child in element:
        placed = child.get("x") or child.get("y") or child.get("dy")
        if local_name(child.tag) == "tspan" and placed:
            if current:
                pieces.append((" ".join(current), cx, cy))
            cx = (numbers(child.get("x")) or [cx])[0]
            cy = (numbers(child.get("y")) or [cy])[0] + (numbers(child.get("dy")) or [0.0])[0]
            current = ["".join(child.itertext()).strip()]
        else:
            current.append("".join(child.itertext()).strip())
        if child.tail and child.tail.strip():
            current.append(child.tail.strip())
    if current:
        pieces.append((" ".join(p for p in current if p), cx, cy))

    scale = math.hypot(ctm[0], ctm[1])
    labels = []
    for text, x, y in pieces:
        if not text:
            continue
        width = WIDTH_EM * size * len(text)
        left = {"middle": x - width / 2, "end": x - width}.get(anchor, x)
        x0, y0 = apply(ctm, (left, y - ASCENT_EM * size))
        x1, y1 = apply(ctm, (left + width, y + DESCENT_EM * size))
        slack = SLACK * scale
        box = (min(x0, x1) + slack, min(y0, y1) + slack, max(x0, x1) - slack, max(y0, y1) - slack)
        if box[0] < box[2] and box[1] < box[3]:
            labels.append(Label(text, *apply(ctm, (x, y)), box=box))
    return labels


def arc_points(
    start: Point, rx: float, ry: float, phi_deg: float, large: bool, sweep: bool, end: Point
) -> list[Point]:
    """An elliptical arc as points (SVG spec, appendix B.2.4)."""
    if rx == 0 or ry == 0 or start == end:
        return [end]
    phi = math.radians(phi_deg)
    cos, sin = math.cos(phi), math.sin(phi)
    dx, dy = (start[0] - end[0]) / 2, (start[1] - end[1]) / 2
    x1, y1 = cos * dx + sin * dy, -sin * dx + cos * dy
    rx, ry = abs(rx), abs(ry)
    grow = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if grow > 1:
        rx, ry = rx * math.sqrt(grow), ry * math.sqrt(grow)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    k = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        k = -k
    cxp, cyp = k * rx * y1 / ry, -k * ry * x1 / rx
    cx = cos * cxp - sin * cyp + (start[0] + end[0]) / 2
    cy = sin * cxp + cos * cyp + (start[1] + end[1]) / 2

    def angle(ux: float, uy: float) -> float:
        return math.atan2(uy, ux)

    t1 = angle((x1 - cxp) / rx, (y1 - cyp) / ry)
    dt = angle((-x1 - cxp) / rx, (-y1 - cyp) / ry) - t1
    if sweep and dt < 0:
        dt += math.tau
    elif not sweep and dt > 0:
        dt -= math.tau
    points = []
    for i in range(1, CURVE_STEPS + 1):
        t = t1 + dt * i / CURVE_STEPS
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        points.append((cos * ex - sin * ey + cx, sin * ex + cos * ey + cy))
    return points


def path_polylines(d: str) -> list[list[Point]]:
    """A path's subpaths as polylines, curves sampled."""
    tokens = PATH_TOKEN.findall(d or "")
    lines: list[list[Point]] = []
    current: list[Point] = []
    pos: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    control: Point | None = None
    command = ""
    i = 0

    def take(n: int) -> list[float] | None:
        nonlocal i
        if i + n > len(tokens) or any(t.isalpha() for t in tokens[i : i + n]):
            return None
        values = [float(t) for t in tokens[i : i + n]]
        i += n
        return values

    def bezier(points: list[Point]) -> list[Point]:
        out = []
        for step in range(1, CURVE_STEPS + 1):
            t = step / CURVE_STEPS
            level = points
            while len(level) > 1:
                level = [
                    (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                    for a, b in zip(level, level[1:], strict=False)
                ]
            out.append(level[0])
        return out

    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
            if command in "Zz":
                if current:
                    current.append(start)
                pos, control = start, None
                continue
        if not command or command in "Zz":
            i += 1
            continue
        rel = command.islower()
        ox, oy = pos if rel else (0.0, 0.0)
        kind = command.upper()
        sizes = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}
        v = take(sizes[kind])
        if v is None:
            i += 1
            continue
        new_control = None
        if kind == "M":
            if len(current) > 1:
                lines.append(current)
            pos = (v[0] + ox, v[1] + oy)
            start, current = pos, [pos]
            command = "l" if rel else "L"  # later pairs are line-tos
        elif kind == "L":
            pos = (v[0] + ox, v[1] + oy)
            current.append(pos)
        elif kind == "H":
            pos = (v[0] + (pos[0] if rel else 0.0), pos[1])
            current.append(pos)
        elif kind == "V":
            pos = (pos[0], v[0] + (pos[1] if rel else 0.0))
            current.append(pos)
        elif kind in ("C", "S"):
            if kind == "C":
                c1 = (v[0] + ox, v[1] + oy)
                rest = v[2:]
            else:
                c1 = (2 * pos[0] - control[0], 2 * pos[1] - control[1]) if control else pos
                rest = v
            c2, end = (rest[0] + ox, rest[1] + oy), (rest[2] + ox, rest[3] + oy)
            current += bezier([pos, c1, c2, end])
            pos, new_control = end, c2
        elif kind in ("Q", "T"):
            if kind == "Q":
                c1, end = (v[0] + ox, v[1] + oy), (v[2] + ox, v[3] + oy)
            else:
                c1 = (2 * pos[0] - control[0], 2 * pos[1] - control[1]) if control else pos
                end = (v[0] + ox, v[1] + oy)
            current += bezier([pos, c1, end])
            pos, new_control = end, c1
        elif kind == "A":
            end = (v[5] + ox, v[6] + oy)
            current += arc_points(pos, v[0], v[1], v[2], bool(v[3]), bool(v[4]), end)
            pos = end
        if not current:
            current = [pos]
        control = new_control
    if len(current) > 1:
        lines.append(current)
    return lines


def shape_polylines(tag: str, a: dict[str, float], d: str | None) -> list[list[Point]]:
    g = a.get
    if tag == "line":
        return [[(g("x1", 0), g("y1", 0)), (g("x2", 0), g("y2", 0))]]
    if tag == "rect":
        x, y, w, h = g("x", 0), g("y", 0), g("width", 0), g("height", 0)
        if w <= 0 or h <= 0:
            return []
        return [[(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]]
    if tag in ("circle", "ellipse"):
        rx = g("r", 0) if tag == "circle" else g("rx", 0)
        ry = g("r", 0) if tag == "circle" else g("ry", 0)
        cx, cy = g("cx", 0), g("cy", 0)
        n = CURVE_STEPS * 2
        return [
            [
                (cx + rx * math.cos(math.tau * i / n), cy + ry * math.sin(math.tau * i / n))
                for i in range(n + 1)
            ]
        ]
    if tag == "path":
        return path_polylines(d or "")
    return []


def points_attr(tag: str, value: str | None) -> list[list[Point]]:
    v = numbers(value)
    pts = list(zip(v[0::2], v[1::2], strict=False))
    if tag == "polygon" and pts:
        pts.append(pts[0])
    return [pts] if len(pts) > 1 else []


def frames(values: list[float]) -> list[float]:
    """Keyframe values with in-between steps, so a sweep is checked along its way."""
    if len(values) < 2:
        return values
    out = []
    for a, b in zip(values, values[1:], strict=False):
        out += [a + (b - a) * k / MOTION_STEPS for k in range(MOTION_STEPS)]
    return out + [values[-1]]


def animation_values(anim: ElementTree.Element) -> list[str]:
    if anim.get("values"):
        return [v.strip() for v in anim.get("values", "").split(";") if v.strip()]
    return [v for v in (anim.get("from"), anim.get("to"), anim.get("by")) if v]


class Layout:
    def __init__(self, root: ElementTree.Element) -> None:
        self.root = root
        self.styles = Styles.read(root)
        self.ids = {e.get("id"): e for e in root.iter() if e.get("id")}
        self.labels: list[Label] = []
        self.drawn: list[Drawn] = []

    def walk(
        self,
        element: ElementTree.Element,
        ctm: Affine,
        size: float,
        inherited: dict[str, str],
        moves: list[Point],
    ) -> None:
        tag = local_name(element.tag)
        if tag in SKIPPED:
            return
        own = self.styles.props(element)
        props = {k: v for k, v in inherited.items() if k in INHERITED}
        props.update(own)
        ctm = multiply(ctm, parse_transform(element.get("transform")))
        size = font_size(own.get("font-size"), size)
        moves = self.combine(moves, self.moves(element, own))
        if props.get("display") == "none" or props.get("visibility") == "hidden":
            return
        if tag == "text":
            if not is_rotated(ctm) and not has_halo(props):
                self.labels += text_labels(element, props, size, ctm)
            return
        if tag in SHAPES:
            self.add_shape(element, tag, ctm, moves)
            return
        for child in element:
            self.walk(child, ctm, size, props, moves)

    def combine(self, outer: list[Point], inner: list[Point]) -> list[Point]:
        if not inner:
            return outer
        return [(a[0] + b[0], a[1] + b[1]) for a in outer or [(0.0, 0.0)] for b in inner][:400]

    def moves(self, element: ElementTree.Element, props: dict[str, str]) -> list[Point]:
        """Offsets the element is translated by while it animates (static: just (0, 0))."""
        offsets: list[Point] = []
        for anim in element:
            name = local_name(anim.tag)
            if name == "animateTransform" and anim.get("type", "translate") == "translate":
                pairs = [numbers(v) for v in animation_values(anim)]
                xs = frames([p[0] if p else 0.0 for p in pairs])
                ys = frames([p[1] if len(p) > 1 else 0.0 for p in pairs])
                offsets += list(zip(xs, ys, strict=False))
            elif name == "animateMotion":
                d = anim.get("path")
                for child in anim:
                    if local_name(child.tag) == "mpath":
                        href = child.get("href") or child.get(XLINK_HREF) or ""
                        ref = self.ids.get(href[1:])
                        if ref is not None:
                            d = ref.get("d")
                for line in path_polylines(d or ""):
                    offsets += line
        animation = props.get("animation", "") + " " + props.get("animation-name", "")
        for name, keyframe in self.styles.keyframes.items():
            if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", animation):
                xs = frames([p[0] for p in keyframe])
                ys = frames([p[1] for p in keyframe])
                offsets += list(zip(xs, ys, strict=False))
        return offsets

    def add_shape(
        self, element: ElementTree.Element, tag: str, ctm: Affine, moves: list[Point]
    ) -> None:
        base = {k: (numbers(element.get(k)) or [0.0])[0] for k in GEOMETRY if element.get(k)}
        # Animations with the same timing run in step (a bar's y and height), so their frames
        # pair up; animations on different clocks are combined every way.
        clocks: dict[tuple[str, str, int], list[tuple[str, list[float]]]] = {}
        for anim in element:
            attr = anim.get("attributeName", "")
            if local_name(anim.tag) == "animate" and attr in GEOMETRY:
                values = [(numbers(v) or [0.0])[0] for v in animation_values(anim)]
                clock = (anim.get("dur", ""), anim.get("begin", "0"), len(values))
                clocks.setdefault(clock, []).append((attr, frames(values)))
        variants = [base]
        for tracks in clocks.values():
            steps = [{attr: values[i] for attr, values in tracks} for i in range(len(tracks[0][1]))]
            variants = [{**v, **step} for v in variants for step in steps][:400]
        if tag in ("polyline", "polygon"):
            shapes = [points_attr(tag, element.get("points"))]
        else:
            shapes = [shape_polylines(tag, v, element.get("d")) for v in variants]
        moving = len(variants) > 1 or len(moves) > 1
        drawn = Drawn(tag, moving)
        for polylines in shapes:
            for offset in moves or [(0.0, 0.0)]:
                for line in polylines:
                    pts = [apply(ctm, (p[0] + offset[0], p[1] + offset[1])) for p in line]
                    drawn.segments += list(zip(pts, pts[1:], strict=False))
        if drawn.segments:
            self.drawn.append(drawn)


def crosses(seg: Segment, box: tuple[float, float, float, float]) -> bool:
    """Liang-Barsky: does the segment enter the box?"""
    (x0, y0), (x1, y1) = seg
    left, top, right, bottom = box
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - left), (dx, right - x0), (-dy, y0 - top), (dy, bottom - y0)):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


def overlap(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def describe(label: Label) -> str:
    text = label.text if len(label.text) <= 30 else label.text[:29] + "…"
    return f'the label "{text}" at ({label.x:g}, {label.y:g})'


def overlap_issues(root: ElementTree.Element) -> list[str]:
    layout = Layout(root)
    layout.walk(root, IDENTITY, DEFAULT_FONT_SIZE, {}, [])
    found: list[str] = []
    hint = (
        "; move it clear of the drawing (a legend, or just past the end of its series), or give "
        'it a white halo (stroke="#fff" stroke-width="4" paint-order="stroke")'
    )
    for label in layout.labels:
        for drawn in layout.drawn:
            if any(crosses(seg, label.box) for seg in drawn.segments):
                how = "passes over" if drawn.moving else "is crossed by"
                found.append(f"{describe(label)} {how} a <{drawn.tag}>{hint}")
                break
    for i, a in enumerate(layout.labels):
        for b in layout.labels[i + 1 :]:
            if overlap(a.box, b.box):
                found.append(f"{describe(a)} overlaps {describe(b)}; space them apart")
    if len(found) > MAX_REPORTS:
        found = found[:MAX_REPORTS] + [f"and {len(found) - MAX_REPORTS} more overlapping labels"]
    return found


def iter_labels(root: ElementTree.Element) -> Iterator[Label]:
    """The labels this check sees (for tests)."""
    layout = Layout(root)
    layout.walk(root, IDENTITY, DEFAULT_FONT_SIZE, {}, [])
    yield from layout.labels
