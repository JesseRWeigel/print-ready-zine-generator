#!/usr/bin/env python3
"""Inspect compiled PDF behavior without importing the generator."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path


def fail(message: str) -> None:
    raise AssertionError(message)


def run(*command: str) -> str:
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        fail(f"command failed ({' '.join(command)}): {result.stderr.strip()}")
    return result.stdout


def pdf_info(path: Path) -> tuple[int, tuple[float, float, float, float]]:
    output = run("mutool", "info", str(path))
    pages = re.search(r"^Pages:\s+(\d+)\s*$", output, re.MULTILINE)
    box = re.search(r"Mediaboxes \(1\):\s*\n\s*\d+\s+\([^)]*\):\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", output)
    if not pages or not box:
        fail(f"could not parse page count and media box from {path}")
    return int(pages.group(1)), tuple(float(box.group(index)) for index in range(1, 5))


def structured_text(path: Path) -> list[dict]:
    return json.loads(run("mutool", "draw", "-q", "-F", "stext.json", str(path)))["pages"]


def all_lines(page: dict) -> list[dict]:
    return [line for block in page["blocks"] for line in block.get("lines", [])]


def page_labels(page: dict) -> list[tuple[int, dict]]:
    found = []
    for line in all_lines(page):
        match = re.fullmatch(r"ZINE PAGE (\d+)", line.get("text", ""))
        if match:
            found.append((int(match.group(1)), line["bbox"]))
    return found


def read_ppm(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if not data.startswith(b"P6"):
        fail(f"{path} is not a binary PPM image")
    position = 2

    def token() -> bytes:
        nonlocal position
        while position < len(data):
            if data[position : position + 1] == b"#":
                position = data.index(b"\n", position) + 1
            elif data[position] in b" \t\r\n":
                position += 1
            else:
                break
        start = position
        while position < len(data) and data[position] not in b" \t\r\n":
            position += 1
        return data[start:position]

    width, height, maximum = int(token()), int(token()), int(token())
    if maximum != 255:
        fail(f"unsupported PPM maximum value {maximum}")
    while position < len(data) and data[position] in b" \t\r\n":
        position += 1
    pixels = data[position:]
    if len(pixels) != width * height * 3:
        fail(f"PPM pixel length mismatch in {path}")
    return width, height, pixels


def colors_in_region(image: tuple[int, int, bytes], box: tuple[int, int, int, int]) -> tuple[int, int]:
    width, height, pixels = image
    x0, y0, x1, y1 = box
    dark = cyan = 0
    for y in range(max(0, y0), min(height, y1)):
        for x in range(max(0, x0), min(width, x1)):
            offset = (y * width + x) * 3
            red, green, blue = pixels[offset : offset + 3]
            if red < 235 and green < 235 and blue < 235:
                dark += 1
            if green > red + 20 and blue > red + 20:
                cyan += 1
    return dark, cyan


def render_first_page(pdf: Path, destination: Path) -> tuple[int, int, bytes]:
    run("mutool", "draw", "-q", "-r", "72", "-F", "ppm", "-o", str(destination), str(pdf), "1")
    return read_ppm(destination)


def inspect_saddle(directory: Path, expected_titles: list[str], render_dir: Path) -> None:
    content = directory / "content.pdf"
    imposed = directory / "zine-saddle.pdf"
    content_pages, content_box = pdf_info(content)
    imposed_pages, imposed_box = pdf_info(imposed)
    if content_pages != 8:
        fail(f"saddle content has {content_pages} pages, expected 8")
    if imposed_pages != 4:
        fail(f"saddle output has {imposed_pages} pages, expected 4")
    if any(abs(actual - expected) > 0.2 for actual, expected in zip(content_box, (0, 0, 378, 594))):
        fail(f"unexpected saddle content media box {content_box}")
    if any(abs(actual - expected) > 0.2 for actual, expected in zip(imposed_box, (0, 0, 792, 612))):
        fail(f"unexpected saddle output media box {imposed_box}")

    content_text = "\n".join(line.get("text", "") for page in structured_text(content) for line in all_lines(page))
    for required in ["Contents", "Colophon", *expected_titles]:
        if required not in content_text:
            fail(f"saddle content is missing '{required}'")

    expected_spreads = [(8, 1), (2, 7), (6, 3), (4, 5)]
    for output_page, expected in zip(structured_text(imposed), expected_spreads):
        labels = sorted(page_labels(output_page), key=lambda item: item[1]["x"])
        if tuple(number for number, _ in labels) != expected:
            fail(f"wrong saddle spread labels: {labels}, expected {expected}")
        if not labels[0][1]["x"] < 396 < labels[1][1]["x"]:
            fail(f"saddle labels are not placed on opposite sides: {labels}")

    image = render_first_page(imposed, render_dir / "saddle.ppm")
    corners = ((15, 0, 50, 25), (742, 0, 777, 25), (15, 587, 50, 612), (742, 587, 777, 612))
    for corner in corners:
        dark, cyan = colors_in_region(image, corner)
        if dark < 10 or cyan < 5:
            fail(f"missing trim or bleed marks in saddle corner {corner}: dark={dark}, cyan={cyan}")
    for fold in ((388, 0, 404, 25), (388, 587, 404, 612)):
        dark, _ = colors_in_region(image, fold)
        if dark < 3:
            fail(f"missing center fold mark in saddle region {fold}")


def inspect_mini(directory: Path, expected_titles: list[str], render_dir: Path) -> None:
    content = directory / "content.pdf"
    imposed = directory / "zine-mini.pdf"
    content_pages, content_box = pdf_info(content)
    imposed_pages, imposed_box = pdf_info(imposed)
    if content_pages != 8 or imposed_pages != 1:
        fail(f"mini page counts are content={content_pages}, output={imposed_pages}")
    if any(abs(actual - expected) > 0.2 for actual, expected in zip(content_box, (0, 0, 198, 306))):
        fail(f"unexpected mini content media box {content_box}")
    if any(abs(actual - expected) > 0.2 for actual, expected in zip(imposed_box, (0, 0, 792, 612))):
        fail(f"unexpected mini output media box {imposed_box}")

    page = structured_text(imposed)[0]
    labels = page_labels(page)
    expected = {
        5: (0, "top"),
        4: (1, "top"),
        3: (2, "top"),
        2: (3, "top"),
        6: (0, "bottom"),
        7: (1, "bottom"),
        8: (2, "bottom"),
        1: (3, "bottom"),
    }
    if {number for number, _ in labels} != set(range(1, 9)):
        fail(f"mini output page labels are incomplete: {labels}")
    for number, box in labels:
        column, row = expected[number]
        center_x = box["x"] + box["w"] / 2
        if not column * 198 < center_x < (column + 1) * 198:
            fail(f"mini page {number} is in the wrong column at x={center_x}")
        if row == "top" and box["y"] > 40:
            fail(f"mini page {number} top panel is not inverted")
        if row == "bottom" and box["y"] < 570:
            fail(f"mini page {number} bottom panel has the wrong orientation")

    full_text = "\n".join(line.get("text", "") for line in all_lines(page))
    for required in ["Contents", "Colophon", *expected_titles]:
        if required not in full_text:
            fail(f"mini output is missing '{required}'")
    if "CUT" not in full_text:
        fail("mini output is missing its cut guide label")

    image = render_first_page(imposed, render_dir / "mini.ppm")
    width, height, pixels = image
    if (width, height) != (792, 612):
        fail(f"unexpected mini raster size {(width, height)}")
    cut_dark, _ = colors_in_region(image, (198, 302, 594, 310))
    if cut_dark < 250:
        fail(f"mini center cut guide is too sparse: {cut_dark} dark pixels")


def inspect_manifests(saddle: Path, mini: Path) -> None:
    saddle_data = json.loads((saddle / "manifest.json").read_text())
    mini_data = json.loads((mini / "manifest.json").read_text())
    saddle_pairs = [(item["left"], item["right"]) for item in saddle_data["placements"]]
    if saddle_pairs != [(8, 1), (2, 7), (6, 3), (4, 5)]:
        fail(f"saddle manifest order is wrong: {saddle_pairs}")
    mini_order = [item["page"] for item in mini_data["placements"]]
    if mini_order != [5, 4, 3, 2, 6, 7, 8, 1]:
        fail(f"mini manifest order is wrong: {mini_order}")
    if "short edge" not in saddle_data["printing"] or "center slit" not in mini_data["printing"]:
        fail("printing instructions are incomplete")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--saddle", type=Path, required=True)
    parser.add_argument("--mini", type=Path, required=True)
    args = parser.parse_args()
    publication = json.loads(args.input.read_text())
    titles = [publication["title"], *(article["title"] for article in publication["articles"])]
    with tempfile.TemporaryDirectory(prefix="zine-inspect-") as temp:
        render_dir = Path(temp)
        inspect_saddle(args.saddle, titles, render_dir)
        inspect_mini(args.mini, titles, render_dir)
    inspect_manifests(args.saddle, args.mini)
    print("PASS saddle: 8 content pages, 4 imposed spreads, trim and bleed marks, verified fold order")
    print("PASS mini: 8 panels on 1 sheet, inverted top row, cut guide, contents and colophon")


if __name__ == "__main__":
    main()
