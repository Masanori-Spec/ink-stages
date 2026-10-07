# Supported input profile

This first version deliberately accepts a subset of Xournal++ 1.3.8. Unsupported inputs fail before a native export. It does not rewrite an input to make it fit.

## Project and recipe

Only a single gzip-compressed UTF-8 XML XOPP with `fileversion="4"` is accepted. Packaged ZIP XOPP, plain XML, concatenated/trailing gzip data, DTD/entities, processing instructions, comments, CDATA, non-UTF-8 declarations, unknown XML elements/attributes and invalid nesting are rejected. Native SaveHandler emits no comments or CDATA; rejecting them avoids differences in how native leaf-text callbacks treat fragments. ZIP-directory signatures inside a gzip stream are conservatively rejected too, avoiding disagreement with the native loader, which probes ZIP first. That can reject an otherwise valid gzip file with coincidental signature bytes.

Every page needs one supported background followed by 1–64 layers, all with distinct nonempty names. Layer names are exact and case-sensitive, with no trimming or renaming. Duplicate names on different pages are allowed because each entry names its page explicitly. Empty layer selections are unsupported.

Recipes contain exactly `format` and `entries`; every entry contains exactly `page`, `layers` and `background`. Pages are 1-based integers, `background` is a JSON boolean, and duplicate JSON keys are errors. Entries may repeat deliberately; duplicate layer names within one entry are errors. Names select a set in original native stacking order. They do not alter the drawing order.

## Drawing subset

- Native text with font, size, x/y position and color
- Native pen, highlighter and eraser strokes, bounded point/pressure values, optional fill and recognized cap style
- Inline PNG images and PNG previews with validated base64, framing, CRC, dimensions and bounded scanline inflation
- Solid backgrounds with plain, ruled, lined, graph, staves, dotted, isodotted or isograph style
- PDF backgrounds and PNG pixmap backgrounds within the resource rules below

Audio fields, LaTeX images, dashed strokes, custom background configuration, cloned pixmap references, unknown attributes and other drawing types are unsupported. PNGs must be noninterlaced and use the accepted native PNG encodings; compressed metadata chunks and unknown critical or ancillary chunks are rejected. No Lua, plugin, shell or document-supplied script is invoked. Text is left to the official renderer; InkStages does not rebuild or reinterpret artwork.

## Local trusted resources

Only simple same-directory PDF/PNG basenames are allowed. Names use ASCII letters/digits, spaces, periods, underscores or hyphens; they start with a letter/digit and have at most 160 characters. A `..` sequence, slash/backslash, drive path, URL, absolute filename, symlink, FIFO or nonregular file is rejected. Every parent directory is opened without following symlinks. This restriction applies to all pages, even those excluded from the recipe.

The native legacy `domain="absolute"` accepts a relative basename; this profile only permits that relative form. Gzip `domain="attach"` preserves the native source-basename-plus-suffix convention. The first PDF background names its resource, and later PDF backgrounds inherit it as native saves do. Missing resources or a referenced PDF page beyond the available page count fail; paths are never repaired.

The source and supported resources are read within byte limits, hashed and staged byte-for-byte in a private temporary directory, retaining their basenames. Native tools receive those copies. Original files are rechecked before publishing output, and staged source/resource hashes are checked after each rendered entry. This prevents a recipe from turning an arbitrary resource path into an exported file.

These checks are a bounded local-file profile, not a security sandbox for hostile native PDF/image exploits. Supply projects and resources you trust. PDF resources receive a header check during inspection and actual qpdf validation/page-count checks before rendering. A dry run does not certify their full native contents.

## Limits and output behavior

| Bound | Limit |
| --- | --- |
| Compressed XOPP | 8 MiB |
| Decompressed XML | 32 MiB |
| Pages / layers per page | 64 / 64 |
| Recipe bytes / entries | 512 KiB / 128 |
| XML depth / parser events | 8 / 200,000 |
| Attributes on one element | 1 MiB total UTF-8 bytes |
| Text / title | 1 MiB / 64 KiB |
| Stroke data | 2–50,000 coordinate pairs; at most 4 MiB text |
| Image/preview XML text | 24 MiB per element |
| PNG dimensions / decoded bytes | 8,192 pixels per side, 16,777,216 pixels total / 64 MiB scanlines |
| External resource | 16 MiB each; at most 64 files |
| Resources plus inline images | 32 MiB total |
| Source page dimensions | At most 20,000 points per side |
| Referenced PDF document | At most 10,000 pages |
| Component PDF / total output | 32 MiB / 256 MiB |
| Native command timeout | 1–300 seconds each, default 60 |
| Native logs | 1 MiB each / 16 MiB total; report retains 4,096-character tails |

Native subprocesses also have process-local CPU, memory, output-file and descriptor limits. They use a private XDG profile and temporary directory; the caller's HOME is preserved. Commands are argument arrays with no shell expansion. Tool paths are supplied by the caller or resolved from PATH, and exact versions 1.3.8/12.4.2 are required. No automatic dependency installation occurs.

PDF and report destinations must be fresh, distinct files. Existing files and input aliases are refused. An input-validation failure produces neither output; a native execution failure can retain a clearly marked failed report while removing the unfinished PDF. The report may contain local paths, layer names and native log text. The final PDF is a visual page assembly; interactive PDF structures and metadata preservation are outside scope.
