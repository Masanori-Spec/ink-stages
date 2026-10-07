# InkStages

An ordered layer-name recipe for Xournal++ PDF exports. Linux CLI, native verification pending.

InkStages turns one saved XOPP and a small JSON recipe into a multipage PDF. Each entry chooses a source page, exact layer names and whether to include its background. It resolves those names afresh, asks the official Xournal++ renderer for one page per entry, and combines the results with qpdf. It preserves the original layer stacking order and keeps repeated recipe entries.

For example, a recipe can produce **A → A+B → A+C**. Xournal++ already exports selected numeric layer ranges and cumulative progressive layers. This tool is a modest adapter that saves noncumulative, name-based choices across exports. [inklayers](https://github.com/toolleeo/inklayers) already offers similar layer recipes for SVG/Inkscape; InkStages targets XOPP and its native renderer. [Demand and existing tools](docs/SOURCES.md)

## Requirements

- Linux with Python 3.11 or later; the product uses only the standard library
- Official Xournal++ **1.3.8** native `xournalpp` executable; the verification route uses its official Ubuntu 24.04 x86-64 DEB
- Official qpdf **12.4.2**
- A working display or standard `xvfb-run` for the native renderer
- A trusted local project within the [supported input profile](docs/INPUT-PROFILE.md)

Dependencies are installed separately. InkStages does not download software or run input scripts. The hosted verification harness additionally builds the pinned official Xournal++ source solely to author the synthetic test fixture; using InkStages does not require that source build.

## Use

Run from this source directory. Inspect the actual saved page/layer names first:

```sh
python3 -m ink_stages drawing.xopp --dry-run
```

Create a UTF-8 recipe, for example:

```json
{
  "format": "inkstages.recipe.v1",
  "entries": [
    {"page": 1, "layers": ["A"], "background": false},
    {"page": 1, "layers": ["A", "B"], "background": true},
    {"page": 1, "layers": ["A", "C"], "background": true}
  ]
}
```

Validate the recipe without starting either native tool, then export to fresh destinations:

```sh
python3 -m ink_stages drawing.xopp recipe.json --dry-run --report plan.json
xvfb-run -a python3 -m ink_stages drawing.xopp recipe.json --output stages.pdf --report export.json
```

For tools outside `PATH`, pass absolute `--xournalpp /path/to/xournalpp` and `--qpdf /path/to/qpdf` paths. Use the native CLI executable, not the AppImage's graphical crash wrapper, which captures CLI stdout and can wait in a dialog. Versions are checked. Neither a prior PDF nor a prior report is overwritten. `--timeout` sets the limit per native command, from 1 to 300 seconds, default 60.

Pages start at 1. Names are case-sensitive and must match exactly; unnamed or duplicate source layer names, missing names, duplicate names within an entry and empty selections are rejected. An entry's layer array selects a set: reversing names does not reverse native stacking order. All pages and their resources are validated, including pages not selected by the recipe. When a layer is inserted before B, the recipe still finds B by name; its native index is recorded in the next report.

The report contains the source/resource hashes, current names and indices, explicit background choices, native versions and commands, and final PDF identity. The original XOPP and supported resources are copied byte-for-byte into private temporary storage for rendering. Their paths inside the project are preserved, and their original bytes are checked afterward. There is no XOPP rewriting, reference repair, Lua/plugin invocation or custom rendering engine.

## Boundaries and verification

The first profile supports **gzip XOPP fileversion 4**, named layers, bounded native text/strokes/PNG images, solid backgrounds and explicitly bounded same-directory PDF/PNG resources. Packaged ZIP XOPP, unknown fields, audio, LaTeX, custom background configuration and unsafe resource references fail closed. See [the exact profile and limits](docs/INPUT-PROFILE.md).

Inputs and local PDF resources must be trusted. Bounds and path checks are not a sandbox for hostile native PDF/rendering exploits. PDFs are exported as presentation pages; bookmarks, forms, annotations, original document metadata and interactive behavior are not promised to survive. Original XOPP/resource files remain the editable source.

The [native-first test contract](docs/TEST-DESIGN.md) requires real official API authoring/save/reopen, the official release renderer and qpdf, independent Poppler dimensions/text/pixel checks, native layer insertion, wrong-index and progressive-prefix controls, missing/duplicate-name failures and unchanged original bytes. Source review and local tests alone are not native success. Actual hosted evidence is still pending.

The repository distributes original source and synthetic test instructions. It includes no upstream binaries, copied upstream source tree, original-code license grant, hosted interface or paid service. It does not add a browser UI.
