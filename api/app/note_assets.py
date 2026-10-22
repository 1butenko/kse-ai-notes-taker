"""Immutable, canonical note images and their per-asset catalog entries."""

import hashlib
import io
import os
import re
import warnings
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, UnidentifiedImageError

from app.notes import NoteAsset

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
ASSET_PATH = re.compile(r"assets/([0-9a-f]{64})\.(png|jpg)\Z")
IMAGE = re.compile(
    r"!\[([^\[\]\n]+)\]\((assets/[0-9a-f]{64}\.(?:png|jpg))\)\{#(fig-[a-zA-Z0-9][a-zA-Z0-9_.-]*)\}"
)


def image_references(markdown: str) -> list[tuple[str, str, str]]:
    """Only explicit inline figures with a caption, local digest path and fig-ID."""
    if re.search(r"!\s*\[", IMAGE.sub("", markdown)):
        raise ValueError("Unsafe image: use a registered PNG/JPEG path, caption and fig- label")
    return [(m[1], m[2], m[3]) for m in IMAGE.finditer(markdown)]


def _asset_root(directory: Path) -> Path:
    root = directory.resolve()
    assets = root / "assets"
    if assets.is_symlink() or not assets.resolve().is_relative_to(root):
        raise ValueError("Invalid assets root")
    assets.mkdir(exist_ok=True)
    return assets


def _publish(path: Path, data: bytes) -> None:
    """Link a complete file atomically; concurrent identical imports never overwrite."""
    with NamedTemporaryFile(dir=path.parent) as temporary:
        temporary.write(data)
        temporary.flush()
        os.fsync(temporary.fileno())
        try:
            os.link(temporary.name, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise ValueError(
                    "An immutable asset already exists with different contents"
                ) from None


def import_asset(directory: Path, data: bytes, name: str) -> NoteAsset:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Image upload must be between 1 byte and 10 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                kind = source.format
                if kind not in ("PNG", "JPEG"):
                    raise ValueError("Only PNG and JPEG images are supported")
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image exceeds 20 million decoded pixels")
                source.verify()
            with Image.open(io.BytesIO(data)) as source:
                # Never enable Pillow LOAD_TRUNCATED_IMAGES.
                source.load()
                mode = "RGBA" if kind == "PNG" and "A" in source.getbands() else "RGB"
                if kind == "PNG" and "transparency" in source.info:
                    mode = "RGBA"
                pixels = source.convert(mode)
                # A fresh image drops EXIF, ICC, text chunks and other supplied metadata.
                clean = Image.frombytes(mode, pixels.size, pixels.tobytes())
                output = io.BytesIO()
                clean.save(output, format=kind)
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ValueError("Malformed, truncated or oversized image") from error
    canonical = output.getvalue()
    digest = hashlib.sha256(canonical).hexdigest()
    extension, media = ("png", "image/png") if kind == "PNG" else ("jpg", "image/jpeg")
    asset = NoteAsset(
        id=digest,
        name=Path(name).name or f"image.{extension}",
        path=f"assets/{digest}.{extension}",
        media_type=media,
        sha256=digest,
        width=clean.width,
        height=clean.height,
    )
    root = _asset_root(directory)
    _publish(root / f"{digest}.{extension}", canonical)
    catalog = root / f"{digest}.json"
    # The first importer owns the display name. Duplicate bytes reuse its metadata.
    if not catalog.exists():
        try:
            _publish(catalog, asset.model_dump_json().encode())
        except ValueError:
            if not catalog.is_file():
                raise
    return load_asset(directory, digest)


def validated_asset_path(directory: Path, asset: NoteAsset) -> Path:
    match = ASSET_PATH.fullmatch(asset.path)
    if not match or match[1] != asset.sha256 or asset.id != asset.sha256:
        raise ValueError("Invalid note asset path or digest")
    expected_media = "image/png" if match[2] == "png" else "image/jpeg"
    if asset.media_type != expected_media:
        raise ValueError("Invalid note asset media type")
    root = directory.resolve()
    path = root / asset.path
    if (
        (root / "assets").is_symlink()
        or path.is_symlink()
        or not path.resolve().is_relative_to(root / "assets")
    ):
        raise ValueError("Note asset escapes its controlled root")
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != asset.sha256:
        raise ValueError("Missing or corrupted note asset")
    return path


def load_asset(directory: Path, asset_id: str) -> NoteAsset:
    if not re.fullmatch(r"[0-9a-f]{64}", asset_id):
        raise ValueError("Unknown note asset")
    root = _asset_root(directory)
    catalog = root / f"{asset_id}.json"
    if catalog.is_symlink() or not catalog.is_file():
        raise ValueError("Unknown note asset")
    asset = NoteAsset.model_validate_json(catalog.read_text())
    if asset.id != asset_id:
        raise ValueError("Invalid asset catalog entry")
    validated_asset_path(directory, asset)
    return asset


def asset_resources(directory: Path, assets: list[NoteAsset], markdown: str) -> dict[str, Path]:
    registry = {asset.path: asset for asset in assets}
    resources = {}
    for _, path, _ in image_references(markdown):
        if path not in registry:
            raise ValueError(f"Unregistered note asset: {path}")
        asset = registry[path]
        stored = load_asset(directory, asset.id)
        if stored != asset:
            raise ValueError(f"Asset metadata differs from the catalog: {path}")
        resources[path] = validated_asset_path(directory, asset)
    return resources
