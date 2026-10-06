"""Make the site's line drawings with the Gemini image API (the 6 Oct 2026 "civic look" revamp).

    .venv/bin/python tools/gen_illustrations.py --list-models          # which image models this key can use
    .venv/bin/python tools/gen_illustrations.py --model MODEL [--only a-shop]
    .venv/bin/python tools/gen_illustrations.py --convert-only           # redo the web files from the raw ones

Run from 11_Platform_Draft. The key is GOOGLE_API_KEY (or GEMINI_API_KEY) in the uncommitted .env; it is never printed.
Raw answers go to tools/illustrations_raw/ (gitignored); the web files to app/static/img/illustrations/ as WebP at 1x
and 2x plus a small PNG fallback, each under MAX_BYTES; PROMPTS.md there records the model, the day and every prompt.

What these are: drawings made with Google Gemini, in one style (technical ink line, an engineering field guide). They
are never photos of a real place, and the page says so in their alt text and credits. The API adds no visible
watermark; Google's invisible SynthID mark is left as it is.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(__file__).resolve().parent / "illustrations_raw"
OUT = ROOT / "app" / "static" / "img" / "illustrations"
MAX_BYTES = 150_000
WEBP_QUALITY = 80
PNG_COLOURS = 16

STYLE = ("Technical ink line drawing in the style of an engineering field guide: an orthographic side cross-section. "
         "Subject: {subject}. Even-weight dark navy (#0c447c) lines on plain white, light hatching only, no gradients, "
         "no shading, no shadows. Flood water, where shown, is one flat pale blue band (#c2e6f5) with a crisp "
         "darker blue waterline (#2b77a7), the only colour besides the navy ink. No text, letters, numbers, signage or "
         "labels anywhere; no logos; no faces (people, if any, are simple outlines seen from the side). Wide white "
         "margins, calm and factual. Not a cartoon, not 3D, not watercolour, not photo-real.")

# name: what it shows, the aspect ratio asked for, and its display size in CSS pixels (the 2x file is twice that)
DRAWINGS = {
    "a-shop": {"subject": "a two-storey Malaysian shophouse seen from the street: a covered five-foot walkway, a "
                          "roller shutter half up, a counter and shelves inside, flood water up to knee height",
               "aspect": "16:9", "size": (320, 180)},
    "b-contents": {"subject": "the same kind of shop cut open: sacks and boxes of stock on the floor, a drinks fridge, "
                              "built-in shelving and a counter, a small car parked at the kerb outside, flood water "
                              "above the shop floor", "aspect": "16:9", "size": (320, 180)},
    "c-cover": {"subject": "a cross-section of a shop where the building shell (walls, roof, floor slab) is drawn in "
                           "plain outline and the contents (shelves, stock, machines) are filled with fine hatching, "
                           "to show what is the building and what is its contents", "aspect": "16:9",
                "size": (320, 180)},
    "d-street": {"subject": "a long row of shophouses along a street, an open monsoon drain in front, a river bank "
                            "behind, with three dashed horizontal lines at rising heights marking flood levels",
                 "aspect": "21:9", "size": (720, 309)},
    "e-ready": {"subject": "inside a shop, a shop owner (a simple outline seen from the side) lifting boxes onto a "
                           "high shelf, sandbags stacked across the doorway, water not yet inside",
                "aspect": "21:9", "size": (560, 240)},
}


def client():
    """A Gemini client from the key in .env; stops with a message (and no key shown) when there is none."""
    load_dotenv(ROOT / ".env")
    from google import genai   # imported here so --convert-only needs no SDK set-up
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        sys.exit("No GOOGLE_API_KEY in 11_Platform_Draft/.env: add the paid key there (never commit it).")
    return genai.Client()


def list_models() -> None:
    for model in client().models.list():
        name = getattr(model, "name", "")
        if "image" in name or "imagen" in name:
            print(name)


def generate(gemini, model: str, name: str, spec: dict) -> Path:
    """Ask for one drawing and keep the raw image."""
    from google.genai import types
    prompt = STYLE.format(subject=spec["subject"])
    answer = gemini.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"],
                                           image_config=types.ImageConfig(aspect_ratio=spec["aspect"])))
    for part in answer.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            RAW.mkdir(exist_ok=True)
            path = RAW / f"{name}.png"
            path.write_bytes(part.inline_data.data)
            return path
    raise RuntimeError(f"{name}: the answer held no image")


def _save_small(image: Image.Image, path: Path, fmt: str) -> int:
    """Save a WebP, or a PNG cut to a few colours, and give its size; refuse one over MAX_BYTES."""
    buffer = io.BytesIO()
    if fmt == "webp":
        image.save(buffer, "WEBP", quality=WEBP_QUALITY, method=6)
    else:
        image.quantize(colors=PNG_COLOURS, method=Image.Quantize.MEDIANCUT).save(buffer, "PNG", optimize=True)
    if buffer.tell() > MAX_BYTES:
        raise RuntimeError(f"{path.name} is {buffer.tell()} bytes, over {MAX_BYTES}")
    path.write_bytes(buffer.getvalue())
    return buffer.tell()


def convert(name: str, spec: dict) -> list[str]:
    """The web files for one drawing: WebP at 1x and 2x, and a PNG fallback at 1x, cropped to the display shape."""
    source = Image.open(RAW / f"{name}.png").convert("RGB")
    width, height = spec["size"]
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for scale, fmt, suffix in ((1, "webp", ""), (2, "webp", "@2x"), (1, "png", "")):
        target = (width * scale, height * scale)
        fitted = _fit(source, target)
        path = OUT / f"{name}{suffix}.{fmt}"
        made.append(f"{path.name} {_save_small(fitted, path, fmt)} bytes")
    return made


def _fit(image: Image.Image, target: tuple[int, int]) -> Image.Image:
    """Crop to the target's shape around the centre, then resize with LANCZOS."""
    tw, th = target
    w, h = image.size
    if w * th > h * tw:   # too wide: trim the sides
        new_w = h * tw // th
        image = image.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
    else:                  # too tall: trim top and bottom
        new_h = w * th // tw
        image = image.crop((0, (h - new_h) // 2, w, (h - new_h) // 2 + new_h))
    return image.resize(target, Image.Resampling.LANCZOS)


def write_prompts(model: str, names: list[str]) -> None:
    lines = [f"# Drawings made with Google Gemini ({date.today().isoformat()})", "",
             f"Model: `{model}`. Generated by tools/gen_illustrations.py; shown as drawings, never as photos. No visible "
             "watermark is added by the API; Google's invisible SynthID mark is kept.", ""]
    for name in names:
        spec = DRAWINGS[name]
        lines += [f"## {name} ({spec['aspect']}, shown at {spec['size'][0]}x{spec['size'][1]})", "",
                  STYLE.format(subject=spec["subject"]), ""]
    (OUT / "PROMPTS.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model")
    parser.add_argument("--only", action="append", choices=sorted(DRAWINGS))
    parser.add_argument("--convert-only", action="store_true")
    parser.add_argument("--list-models", action="store_true")
    args = parser.parse_args(argv)
    if args.list_models:
        list_models()
        return 0
    names = args.only or sorted(DRAWINGS)
    if not args.convert_only:
        if not args.model:
            parser.error("--model is needed to generate (see --list-models)")
        gemini = client()
        for name in names:
            print(f"{name}: {generate(gemini, args.model, name, DRAWINGS[name]).name}")
        write_prompts(args.model, sorted(DRAWINGS))   # all of them: the set is made in one style, by one model
    for name in names:
        print(f"{name}: " + ", ".join(convert(name, DRAWINGS[name])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
