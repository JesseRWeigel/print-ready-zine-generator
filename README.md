# media038

Take a collection of articles and emit a LaTeX-built PDF imposed for saddle-stitch printing, with correct page ordering for folding, bleed marks, and a generated table of contents and colophon. Include an eight-page single-sheet mini-zine imposition mode because that is the format people actually print at home.

Catalog task: `MEDIA-038`. Part of [thousand](../../README.md).

## What this is

`zinegen.py` turns a JSON collection of plain-text articles into press sheets composed by
pdfLaTeX. It generates the reading pages, table of contents, colophon, imposed PDF, retained
LaTeX sources, and a machine-readable placement manifest.

Saddle mode pads the publication to a four-page signature. It places each front and back spread
in folding order on landscape letter or A4 paper. The default letter profile produces a 5 by 8
inch trimmed page with 0.125 inch bleed, trim marks, bleed marks, and center fold marks.

Mini mode produces the common eight-page, one-cut zine on a single sheet. Its top row is
`5, 4, 3, 2`, rotated 180 degrees. Its bottom row is `6, 7, 8, 1`. Fold guides and the center cut
guide are printed over the imposed panels.

## Running it

```bash
python3 zinegen.py examples/field-notes.json \
  --output build/my-zine \
  --mode saddle \
  --paper letter
```

Use `--mode mini` for the single-sheet version. Use `--paper a4` for an A4 parent sheet.
The build requires Python 3, pdfLaTeX, and MuPDF's `mutool`. No Python packages or network
services are required. Characters supported by the installed pdfLaTeX fonts are accepted.
Unsupported scripts and emoji stop the build with a compiler error that names the failing input.

The input file has this shape:

```json
{
  "title": "Issue title",
  "subtitle": "Optional subtitle",
  "issue": "Optional issue label",
  "editor": "Optional editor credit",
  "date": "Optional date",
  "articles": [
    {"title": "Article title", "author": "Optional author", "body": "Plain text paragraphs"}
  ],
  "colophon": {
    "publisher": "Optional publisher",
    "location": "Optional location",
    "license": "Optional license",
    "printing": "Optional printing note",
    "notes": "Optional final note"
  }
}
```

Each output directory contains `content.pdf`, `content.tex`, `imposition.tex`, build logs,
`manifest.json`, and either `zine-saddle.pdf` or `zine-mini.pdf`. Print saddle output duplex at
actual size in landscape orientation with short-edge flipping. Print mini output one-sided at
actual size.

The exact project verification command is:

```bash
bash scripts/verify.sh
```

## Status

```text
PASS unit: 8 tests
PASS saddle: 8 content pages, 4 imposed spreads, trim and bleed marks, verified fold order
PASS mini: 8 panels on 1 sheet, inverted top row, cut guide, contents and colophon
PASS project: README status, tracked text, size, and credential scan
PASS clean clone: verified committed snapshot from outside the source tree
```

## Unfinished

- Article bodies accept plain text paragraphs. Inline Markdown, images, and rich footnotes are
  not implemented.
- Mini mode stops with an error when the articles occupy more than seven reading pages before
  the page-eight colophon. It does not shrink overflowing material automatically.
- The PDFs use process colors and do not embed a printer-specific ICC output profile.
- The bundled pdfLaTeX font setup does not typeset every Unicode script or emoji. Unsupported
  characters produce a clean build error.
