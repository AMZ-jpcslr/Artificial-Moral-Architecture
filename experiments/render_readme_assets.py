"""Render real CLI stdout into README PNGs (not OS screenshots).

Optional documentation tool: requires Pillow and a Japanese font. Runtime demos
and tests do not depend on Pillow. Example: python experiments/render_readme_assets.py
"""
import argparse
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, help="Japanese-capable TTF/TTC/OTF font")
    args = parser.parse_args()
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise SystemExit("PNG regeneration requires Pillow; demos and tests do not.")
    font_path = args.font or Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "meiryo.ttc"
    if not font_path.exists():
        raise SystemExit("Supply a Japanese-capable font with --font.")
    font = ImageFont.truetype(str(font_path), 24)
    small = ImageFont.truetype(str(font_path), 20)
    title = ImageFont.truetype(str(font_path), 32)
    output = ROOT / "docs" / "assets"
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"kind": "Rendered unedited stdout, not an operating-system screenshot", "captures": []}
    for stem, script, heading in (("cli-demo", "examples/demo.py", "01 / Moral judgment — actual CLI output"),
                                   ("affect-demo", "examples/affect_demo.py", "02 / Functional affect — controlled probes")):
        command = [sys.executable, script]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
        raw = result.stdout
        (output / f"{stem}.txt").write_text(raw, encoding="utf-8", newline="")
        lines = raw.splitlines()
        canvas = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(canvas)
        width = max(1280, int(max(draw.textlength(line, font=font) for line in lines))+100)
        height = 172 + 37*len(lines) + 62
        canvas = Image.new("RGB", (width, height), "#0b1220")
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, width, 7), fill="#55d6bd")
        draw.text((44, 28), heading, font=title, fill="#eef5fc")
        draw.text((44, 87), "$ python " + script, font=font, fill="#55d6bd")
        draw.line((44, 140, width-44, 140), fill="#29364a", width=2)
        for index, line in enumerate(lines):
            color = "#dce5ef"
            if line.startswith("["):
                color = "#7fc6ff"
            elif "ASK_HUMAN" in line or "BLOCK" in line:
                color = "#f5cd85"
            elif "MODIFY" in line or "ALLOW" in line:
                color = "#87dcc2"
            draw.text((44, 163+37*index), line, font=font, fill=color)
        draw.text((44, height-46), "Captured from the local demo · stdout rendered as an image · no GUI / no external actions", font=small, fill="#8ea1b9")
        canvas.save(output / f"{stem}.png", optimize=True)
        manifest["captures"].append({"command": "python " + script, "stdout": f"{stem}.txt", "image": f"{stem}.png",
            "stdout_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "width": width, "height": height})
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("Rendered actual demo output to docs/assets/cli-demo.png and affect-demo.png")


if __name__ == "__main__":
    main()
