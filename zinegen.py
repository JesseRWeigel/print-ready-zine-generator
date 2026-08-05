#!/usr/bin/env python3
"""Build imposed zine PDFs from a small JSON publication description."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


PAPER_PROFILES = {
    "letter": {"width": 11.0, "height": 8.5, "unit": "in"},
    "a4": {"width": 297.0 / 25.4, "height": 210.0 / 25.4, "unit": "mm"},
}


class BuildError(RuntimeError):
    """A user-facing build failure."""


def latex_escape(value: str) -> str:
    """Escape untrusted plain text for use in LaTeX text mode."""
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "#": r"\#",
        "$": r"\$",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "^": r"\textasciicircum{}",
        "~": r"\textasciitilde{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def render_paragraphs(body: str) -> str:
    paragraphs = [part.strip() for part in body.replace("\r\n", "\n").split("\n\n")]
    return "\n\n".join(latex_escape(part.replace("\n", " ")) + r"\par" for part in paragraphs if part)


def require_text(container: dict[str, Any], key: str, context: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BuildError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def optional_text(container: dict[str, Any], key: str, context: str) -> str:
    value = container.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise BuildError(f"{context}.{key} must be a string when provided")
    return value.strip()


def validate_publication(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise BuildError("the input root must be a JSON object")
    publication: dict[str, Any] = {
        "title": require_text(raw, "title", "publication"),
        "subtitle": optional_text(raw, "subtitle", "publication"),
        "issue": optional_text(raw, "issue", "publication"),
        "editor": optional_text(raw, "editor", "publication"),
        "date": optional_text(raw, "date", "publication"),
    }
    articles = raw.get("articles")
    if not isinstance(articles, list) or not articles:
        raise BuildError("publication.articles must be a non-empty array")
    clean_articles = []
    for index, article in enumerate(articles):
        context = f"publication.articles[{index}]"
        if not isinstance(article, dict):
            raise BuildError(f"{context} must be an object")
        clean_articles.append(
            {
                "title": require_text(article, "title", context),
                "author": optional_text(article, "author", context),
                "body": require_text(article, "body", context),
            }
        )
    publication["articles"] = clean_articles

    raw_colophon = raw.get("colophon", {})
    if not isinstance(raw_colophon, dict):
        raise BuildError("publication.colophon must be an object when provided")
    publication["colophon"] = {
        key: optional_text(raw_colophon, key, "publication.colophon")
        for key in ("publisher", "location", "license", "printing", "notes")
    }
    return publication


def saddle_spreads(page_count: int) -> list[dict[str, Any]]:
    """Return front and back spreads in physical print order."""
    if page_count < 4 or page_count % 4:
        raise ValueError("saddle-stitch page count must be a positive multiple of four")
    spreads: list[dict[str, Any]] = []
    for sheet_index in range(page_count // 4):
        spreads.append(
            {
                "sheet": sheet_index + 1,
                "side": "front",
                "left": page_count - (2 * sheet_index),
                "right": 1 + (2 * sheet_index),
            }
        )
        spreads.append(
            {
                "sheet": sheet_index + 1,
                "side": "back",
                "left": 2 + (2 * sheet_index),
                "right": page_count - 1 - (2 * sheet_index),
            }
        )
    return spreads


def mini_panels() -> list[dict[str, Any]]:
    """Return standard eight-page one-cut mini-zine panel placement."""
    placements: list[dict[str, Any]] = []
    for column, page in enumerate((5, 4, 3, 2)):
        placements.append({"page": page, "row": "top", "column": column + 1, "rotation": 180})
    for column, page in enumerate((6, 7, 8, 1)):
        placements.append({"page": page, "row": "bottom", "column": column + 1, "rotation": 0})
    return placements


def content_dimensions(mode: str, paper: dict[str, float | str]) -> dict[str, float]:
    if mode == "mini":
        return {
            "trim_width": float(paper["width"]) / 4.0,
            "trim_height": float(paper["height"]) / 2.0,
            "bleed": 0.0,
        }
    if paper["unit"] == "mm":
        return {"trim_width": 135.0 / 25.4, "trim_height": 198.0 / 25.4, "bleed": 3.0 / 25.4}
    return {"trim_width": 5.0, "trim_height": 8.0, "bleed": 0.125}


def tex_length(value: float) -> str:
    return f"{value:.6f}in"


def make_colophon(publication: dict[str, Any]) -> str:
    fields = []
    labels = {
        "publisher": "Publisher",
        "location": "Location",
        "license": "License",
        "printing": "Printing",
        "notes": "Notes",
    }
    for key, label in labels.items():
        if publication["colophon"][key]:
            fields.append(
                rf"\textbf{{{label}:}} {latex_escape(publication['colophon'][key])}\par"
            )
    if publication["editor"]:
        fields.insert(0, rf"\textbf{{Editor:}} {latex_escape(publication['editor'])}\par")
    if publication["date"]:
        fields.insert(0, rf"\textbf{{Date:}} {latex_escape(publication['date'])}\par")
    fields.append(r"\medskip Typeset and imposed with zinegen.\par")
    return "\n".join(fields)


def content_tex(publication: dict[str, Any], mode: str, dimensions: dict[str, float]) -> str:
    bleed = dimensions["bleed"]
    page_width = dimensions["trim_width"] + 2 * bleed
    page_height = dimensions["trim_height"] + 2 * bleed
    if mode == "mini":
        side_margin = 0.18
        top_margin = 0.22
        foot_skip = "9pt"
        base_size = r"\fontsize{7.2}{8.5}\selectfont"
        section_size = r"\fontsize{10}{11}\bfseries"
    else:
        side_margin = bleed + 0.55
        top_margin = bleed + 0.52
        foot_skip = "24pt"
        base_size = r"\fontsize{9.5}{12}\selectfont"
        section_size = r"\fontsize{18}{21}\bfseries"

    article_parts = []
    for index, article in enumerate(publication["articles"]):
        if index:
            article_parts.append(r"\clearpage")
        author = ""
        if article["author"]:
            author = rf"\textit{{By {latex_escape(article['author'])}}}\par\medskip"
        article_parts.append(
            "\n".join(
                [
                    rf"\section{{{latex_escape(article['title'])}}}",
                    author,
                    render_paragraphs(article["body"]),
                ]
            )
        )

    subtitle = ""
    if publication["subtitle"]:
        subtitle = rf"{{\large {latex_escape(publication['subtitle'])}\par}}\medskip"
    issue = ""
    if publication["issue"]:
        issue = rf"{{\small {latex_escape(publication['issue'])}\par}}"

    if mode == "mini":
        finish = r"""
\clearpage
\ifnum\value{page}>8
  \PackageError{zinegen}{Mini-zine content exceeds seven pages before the colophon}{Shorten the articles or build saddle mode.}
\fi
\loop\ifnum\value{page}<8 \null\clearpage\repeat
\section*{Colophon}
%COLOPHON%
"""
    else:
        finish = r"""
\clearpage
\section*{Colophon}
%COLOPHON%
\clearpage
\newcount\zinepad
\zinepad=\value{page}
\advance\zinepad by -1
\loop\ifnum\zinepad>3 \advance\zinepad by -4\repeat
\ifnum\zinepad>0
  \multiply\zinepad by -1
  \advance\zinepad by 4
  \loop\ifnum\zinepad>0 \null\clearpage\advance\zinepad by -1\repeat
\fi
"""
    finish = finish.replace("%COLOPHON%", make_colophon(publication))

    return rf"""\documentclass[10pt]{{article}}
\usepackage{{geometry}}
\geometry{{paperwidth={tex_length(page_width)},paperheight={tex_length(page_height)},left={tex_length(side_margin)},right={tex_length(side_margin)},top={tex_length(top_margin)},bottom={tex_length(top_margin)}}}
\usepackage[T1]{{fontenc}}
\usepackage[utf8]{{inputenc}}
\usepackage{{lmodern}}
\usepackage{{microtype}}
\usepackage{{xcolor}}
\usepackage{{fancyhdr}}
\usepackage{{hyperref}}
\usepackage{{titlesec}}
\definecolor{{zineink}}{{HTML}}{{172033}}
\definecolor{{zineaccent}}{{HTML}}{{B33A3A}}
\color{{zineink}}
\hypersetup{{hidelinks,pdftitle={{{latex_escape(publication['title'])}}},pdfauthor={{{latex_escape(publication['editor'])}}}}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{0.7em}}
\setlength{{\headheight}}{{12pt}}
\setlength{{\footskip}}{{{foot_skip}}}
\pagestyle{{fancy}}
\fancyhf{{}}
\fancyhead[L]{{\scriptsize\MakeUppercase{{{latex_escape(publication['title'])}}}}}
\fancyfoot[C]{{\tiny ZINE PAGE \thepage}}
\renewcommand{{\headrulewidth}}{{0.25pt}}
\titleformat{{\section}}{{{section_size}\color{{zineaccent}}}}{{}}{{0pt}}{{}}
\titlespacing*{{\section}}{{0pt}}{{0pt}}{{0.7em}}
\AtBeginDocument{{{base_size}}}
\begin{{document}}
\thispagestyle{{fancy}}
\vspace*{{0.14\textheight}}
\begin{{center}}
{{\fontsize{{26}}{{29}}\selectfont\bfseries\color{{zineaccent}} {latex_escape(publication['title'])}\par}}
\medskip
{subtitle}
{issue}
\vfill
{{\small A foldable publication\par}}
\end{{center}}
\clearpage
\renewcommand{{\contentsname}}{{Contents}}
\tableofcontents
\clearpage
{"\n".join(article_parts)}
{finish}
\end{{document}}
"""


def mark_commands(x0: float, x1: float, y0: float, y1: float, bleed: float) -> str:
    """Draw crop, bleed, and fold registration marks around the two trims."""
    center = (x0 + x1) / 2
    bleft, bright = x0 - bleed, x1 + bleed
    bbottom, btop = y0 - bleed, y1 + bleed
    crop = 0.18
    gap = 0.035
    lines = [r"\begin{scope}[line width=0.35pt,draw=black]"]
    for x in (x0, x1):
        lines.extend(
            [
                rf"\draw ({x:.6f},{y0-gap:.6f}) -- ({x:.6f},{y0-gap-crop:.6f});",
                rf"\draw ({x:.6f},{y1+gap:.6f}) -- ({x:.6f},{y1+gap+crop:.6f});",
            ]
        )
    for y in (y0, y1):
        lines.extend(
            [
                rf"\draw ({x0-gap:.6f},{y:.6f}) -- ({x0-gap-crop:.6f},{y:.6f});",
                rf"\draw ({x1+gap:.6f},{y:.6f}) -- ({x1+gap+crop:.6f},{y:.6f});",
            ]
        )
    lines.extend(
        [
            rf"\draw[densely dashed] ({center:.6f},{y0-gap:.6f}) -- ({center:.6f},{y0-gap-crop:.6f});",
            rf"\draw[densely dashed] ({center:.6f},{y1+gap:.6f}) -- ({center:.6f},{y1+gap+crop:.6f});",
            r"\end{scope}",
            r"\begin{scope}[line width=0.25pt,draw=cyan!70!black]",
        ]
    )
    bleed_mark = 0.09
    for x in (bleft, bright):
        lines.extend(
            [
                rf"\draw ({x:.6f},{bbottom-0.02:.6f}) -- ({x:.6f},{bbottom-0.02-bleed_mark:.6f});",
                rf"\draw ({x:.6f},{btop+0.02:.6f}) -- ({x:.6f},{btop+0.02+bleed_mark:.6f});",
            ]
        )
    for y in (bbottom, btop):
        lines.extend(
            [
                rf"\draw ({bleft-0.02:.6f},{y:.6f}) -- ({bleft-0.02-bleed_mark:.6f},{y:.6f});",
                rf"\draw ({bright+0.02:.6f},{y:.6f}) -- ({bright+0.02+bleed_mark:.6f},{y:.6f});",
            ]
        )
    lines.append(r"\end{scope}")
    return "\n".join(lines)


def saddle_imposition_tex(
    source_name: str,
    paper: dict[str, float | str],
    dimensions: dict[str, float],
    spreads: list[dict[str, Any]],
) -> str:
    paper_width, paper_height = float(paper["width"]), float(paper["height"])
    trim_width, trim_height, bleed = (
        dimensions["trim_width"],
        dimensions["trim_height"],
        dimensions["bleed"],
    )
    x0 = (paper_width - 2 * trim_width) / 2
    xmid = x0 + trim_width
    x1 = xmid + trim_width
    y0 = (paper_height - trim_height) / 2
    y1 = y0 + trim_height
    source_width, source_height = trim_width + 2 * bleed, trim_height + 2 * bleed
    left_origin = x0 - bleed
    right_origin = xmid - bleed
    bottom_origin = y0 - bleed

    pages = []
    for spread in spreads:
        pages.append(
            rf"""\begin{{tikzpicture}}[remember picture,overlay,x=1in,y=1in]
\begin{{scope}}[shift={{(current page.south west)}}]
  \begin{{scope}}
    \clip ({left_origin:.6f},{bottom_origin:.6f}) rectangle ({xmid:.6f},{y1+bleed:.6f});
    \node[anchor=south west,inner sep=0] at ({left_origin:.6f},{bottom_origin:.6f}) {{\includegraphics[page={spread['left']},width={tex_length(source_width)},height={tex_length(source_height)}]{{{source_name}}}}};
  \end{{scope}}
  \begin{{scope}}
    \clip ({xmid:.6f},{bottom_origin:.6f}) rectangle ({x1+bleed:.6f},{y1+bleed:.6f});
    \node[anchor=south west,inner sep=0] at ({right_origin:.6f},{bottom_origin:.6f}) {{\includegraphics[page={spread['right']},width={tex_length(source_width)},height={tex_length(source_height)}]{{{source_name}}}}};
  \end{{scope}}
  {mark_commands(x0, x1, y0, y1, bleed)}
  \node[anchor=south,font=\fontsize{{5}}{{6}}\selectfont] at ({paper_width/2:.6f},0.01) {{SHEET {spread['sheet']} {spread['side'].upper()}}};
\end{{scope}}
\end{{tikzpicture}}
\null"""
        )
    return rf"""\documentclass{{article}}
\usepackage{{geometry}}
\geometry{{paperwidth={tex_length(paper_width)},paperheight={tex_length(paper_height)},margin=0in}}
\usepackage{{graphicx}}
\usepackage{{tikz}}
\pagestyle{{empty}}
\setlength{{\parindent}}{{0pt}}
\begin{{document}}
{"\n\\newpage\n".join(pages)}
\end{{document}}
"""


def mini_imposition_tex(source_name: str, paper: dict[str, float | str]) -> str:
    width, height = float(paper["width"]), float(paper["height"])
    panel_width, panel_height = width / 4.0, height / 2.0
    nodes = []
    for placement in mini_panels():
        x = (placement["column"] - 0.5) * panel_width
        y = panel_height * (1.5 if placement["row"] == "top" else 0.5)
        nodes.append(
            rf"\node[anchor=center,inner sep=0,rotate={placement['rotation']}] at ({x:.6f},{y:.6f}) {{\includegraphics[page={placement['page']},width={tex_length(panel_width)},height={tex_length(panel_height)}]{{{source_name}}}}};"
        )
    folds = []
    for column in range(1, 4):
        x = panel_width * column
        folds.append(rf"\draw[white,line width=1.4pt] ({x:.6f},0) -- ({x:.6f},{height:.6f});")
        folds.append(rf"\draw[black!55,densely dashed,line width=0.3pt] ({x:.6f},0) -- ({x:.6f},{height:.6f});")
    folds.extend(
        [
            rf"\draw[white,line width=1.4pt] (0,{panel_height:.6f}) -- ({width:.6f},{panel_height:.6f});",
            rf"\draw[black!55,densely dashed,line width=0.3pt] (0,{panel_height:.6f}) -- ({width:.6f},{panel_height:.6f});",
            rf"\draw[white,line width=2pt] ({panel_width:.6f},{panel_height:.6f}) -- ({3*panel_width:.6f},{panel_height:.6f});",
            rf"\draw[black,line width=0.65pt] ({panel_width:.6f},{panel_height:.6f}) -- ({3*panel_width:.6f},{panel_height:.6f});",
            rf"\node[fill=white,inner sep=1pt,font=\fontsize{{5}}{{6}}\selectfont] at ({2*panel_width:.6f},{panel_height:.6f}) {{CUT}};",
        ]
    )
    return rf"""\documentclass{{article}}
\usepackage{{geometry}}
\geometry{{paperwidth={tex_length(width)},paperheight={tex_length(height)},margin=0in}}
\usepackage{{graphicx}}
\usepackage{{tikz}}
\pagestyle{{empty}}
\begin{{document}}
\begin{{tikzpicture}}[remember picture,overlay,x=1in,y=1in]
\begin{{scope}}[shift={{(current page.south west)}}]
{"\n".join(nodes)}
{"\n".join(folds)}
\end{{scope}}
\end{{tikzpicture}}
\null
\end{{document}}
"""


def run_latex(tex_path: Path, passes: int) -> None:
    command = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        tex_path.name,
    ]
    combined = []
    for pass_number in range(1, passes + 1):
        result = subprocess.run(command, cwd=tex_path.parent, text=True, capture_output=True)
        combined.append(f"=== pass {pass_number} ===\n{result.stdout}\n{result.stderr}")
        if result.returncode:
            (tex_path.parent / f"{tex_path.stem}.build.log").write_text("\n".join(combined))
            tail = "\n".join((result.stdout + result.stderr).splitlines()[-24:])
            raise BuildError(f"pdfLaTeX failed while building {tex_path.name}:\n{tail}")
    (tex_path.parent / f"{tex_path.stem}.build.log").write_text("\n".join(combined))


def pdf_page_count(pdf_path: Path) -> int:
    result = subprocess.run(["mutool", "info", str(pdf_path)], text=True, capture_output=True)
    if result.returncode:
        raise BuildError(f"mutool could not inspect {pdf_path.name}: {result.stderr.strip()}")
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError as error:
                raise BuildError(f"mutool returned an invalid page count for {pdf_path.name}") from error
    raise BuildError(f"mutool did not report a page count for {pdf_path.name}")


def clean_known_outputs(output: Path) -> None:
    names = {
        "content.aux",
        "content.build.log",
        "content.log",
        "content.out",
        "content.pdf",
        "content.tex",
        "content.toc",
        "imposition.aux",
        "imposition.build.log",
        "imposition.log",
        "imposition.pdf",
        "imposition.tex",
        "manifest.json",
        "zine-mini.pdf",
        "zine-saddle.pdf",
    }
    for name in names:
        path = output / name
        if path.is_file():
            path.unlink()


def build(input_path: Path, output: Path, mode: str, paper_name: str) -> Path:
    for tool in ("pdflatex", "mutool"):
        if shutil.which(tool) is None:
            raise BuildError(f"required executable '{tool}' was not found on PATH")
    try:
        raw = json.loads(input_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise BuildError(f"could not read {input_path}: {error}") from error
    except json.JSONDecodeError as error:
        raise BuildError(f"invalid JSON in {input_path}: {error}") from error
    publication = validate_publication(raw)
    paper = PAPER_PROFILES[paper_name]
    dimensions = content_dimensions(mode, paper)

    output.mkdir(parents=True, exist_ok=True)
    clean_known_outputs(output)
    content_path = output / "content.tex"
    content_path.write_text(content_tex(publication, mode, dimensions), encoding="utf-8")
    run_latex(content_path, passes=2)
    content_pdf = output / "content.pdf"
    page_count = pdf_page_count(content_pdf)

    if mode == "mini":
        if page_count != 8:
            raise BuildError(f"mini mode must produce exactly 8 content pages, got {page_count}")
        placements = mini_panels()
        imposition_source = mini_imposition_tex(content_pdf.name, paper)
        output_name = "zine-mini.pdf"
        expected_output_pages = 1
    else:
        if page_count % 4:
            raise BuildError(f"saddle mode content page count must be divisible by 4, got {page_count}")
        placements = saddle_spreads(page_count)
        imposition_source = saddle_imposition_tex(content_pdf.name, paper, dimensions, placements)
        output_name = "zine-saddle.pdf"
        expected_output_pages = page_count // 2

    imposition_path = output / "imposition.tex"
    imposition_path.write_text(imposition_source, encoding="utf-8")
    run_latex(imposition_path, passes=2)
    imposed_pdf = output / "imposition.pdf"
    actual_output_pages = pdf_page_count(imposed_pdf)
    if actual_output_pages != expected_output_pages:
        raise BuildError(
            f"imposed PDF has {actual_output_pages} pages, expected {expected_output_pages}"
        )
    final_pdf = output / output_name
    imposed_pdf.replace(final_pdf)

    manifest = {
        "format_version": 1,
        "title": publication["title"],
        "mode": mode,
        "paper": {
            "name": paper_name,
            "width_inches": paper["width"],
            "height_inches": paper["height"],
        },
        "content_pages": page_count,
        "output_pages": actual_output_pages,
        "output_pdf": final_pdf.name,
        "placements": placements,
    }
    if mode == "saddle":
        manifest["trim"] = {
            "width_inches": dimensions["trim_width"],
            "height_inches": dimensions["trim_height"],
            "bleed_inches": dimensions["bleed"],
        }
        manifest["printing"] = "Duplex, actual size, landscape, flip on short edge. Stack sheets and fold at the center."
    else:
        manifest["printing"] = (
            "Print one-sided at actual size. Fold on the guides, cut the center slit, collapse, and refold with page 1 outside."
        )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return final_pdf


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an imposed zine PDF from JSON articles.")
    parser.add_argument("input", type=Path, help="publication JSON file")
    parser.add_argument("--output", type=Path, required=True, help="directory for PDF, TeX, and manifest files")
    parser.add_argument("--mode", choices=("saddle", "mini"), default="saddle")
    parser.add_argument("--paper", choices=tuple(PAPER_PROFILES), default="letter")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = build(args.input, args.output, args.mode, args.paper)
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"built {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
