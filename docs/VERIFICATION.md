# Verified native CLI result

Verified 2026-10-07. InkStages produced its actual PDF through the official Xournal++ renderer and qpdf on a standard Ubuntu 24.04 hosted runner. The fixture was authored, saved, reopened and resaved using unchanged official C++ model/SaveHandler/LoadHandler APIs. This is native API and CLI evidence; no GUI editing, browser UI or graphical application acceptance is claimed.

## Reproducible identity

- Producer commit: [`609912605e503849665c31c9665ecde852f587ab`](https://github.com/Masanori-Spec/ink-stages/commit/609912605e503849665c31c9665ecde852f587ab)
- Successful [GitHub Actions run 37568755911](https://github.com/Masanori-Spec/ink-stages/actions/runs/37568755911)
- Artifact ID: `11460023530`, 138,084 bytes, 67 files; raw ZIP SHA-256: `1e9741c2a20bf68ee838cf99a57ca67cc06d9fed97a54b5b7a47784c3da8a9c9`
- Actual `original.pdf`: 34,978 bytes; SHA-256: `46004770007b04664989751a0086f7ee24f929a7379e973a85c4f4d97f10913e`
- Native source: Xournal++ `938bdb8de4d32f38f48dd7f6544886722157a848`; rendered by the official 1.3.8 Ubuntu noble DEB executable
- Combiner: official qpdf 12.4.2 Linux release; independent inspection: Poppler 24.02.0 and Python 3.12.3

The [release asset sizes and SHA-256 pins](SOURCES.md) were checked before execution. The installed renderer matched its verified DEB payload byte-for-byte. The pinned source remained clean, and all 17 recorded binary/package/core integrity checks passed after execution. The artifact contains evidence and synthetic inputs/outputs, with no vendor binaries or source tree. GitHub artifact retention is 14 days; the workflow can reproduce the gate from source. PDF metadata can vary between runs, so the displayed PDF digest identifies this actual run rather than promising deterministic PDF bytes.

## Actual output and controls

All 51 unit tests passed. Hosted CI built the unchanged official core and the separate fixture author in 365 build steps. The authored, reopened and resaved/reopened native snapshots matched the complete handwritten model; decompressed saved XML was identical after native resaving.

The actual CLI generated four pages in this order:

| Entry | Selection | Background | Native dimensions | Independently checked content |
| --- | --- | --- | --- | --- |
| 1 | Page 1: A | Omitted | 360×240 pt | ALPHA/red, white background; no B or C |
| 2 | Page 1: B+A | Included | 360×240 pt | ALPHA/red and BRAVO/green in original stacking order; BACKGROUND_ONE |
| 3 | Page 1: A+C | Included | 360×240 pt | ALPHA/red and CHARLIE/blue; no B; BACKGROUND_ONE |
| 4 | Page 2: D | Included | 240×360 pt | DELTA/purple and BACKGROUND_TWO |

A fresh native edit inserted a magenta UNUSED layer before B. Resolving the same recipe again changed the native index sets from `[1]`, `[1,2]`, `[1,3]`, `[1]` to `[1]`, `[1,3]`, `[1,4]`, `[1]`. All four resulting pages retained identical dimensions, extracted text and full rendered pixel bytes. The two PDF files themselves have different byte hashes.

Both genuine native controls visibly differed as required: fixed indices `1,3` on the inserted file rendered A+B instead of A+C, while native cumulative-prefix export retained B in its third A+B+C page. Independent inspection confirmed the intended four pages and both controls. Literal pixel regions also established background omission and overlapping-layer stacking.

The original and inserted producer reports each record status `complete`, actual native execution, four official exports and one qpdf assembly. All 38 recorded native commands across both producer runs completed. qpdf validated the resulting PDFs. Native-saved missing-name and duplicate-name fixtures were rejected before any PDF/report was created.

Every original fixture/resource hash matched before and after exports and controls. In particular, the original XOPP SHA-256 remained `f6aefba840e391151cc6dd5d63a103f5a74efd245a76cfda2c21a71444edf9e3`, and the PDF background remained `09814aa162edbbde6bf6e616f4efb6bd2e8460fc663b2a682c6eea51a1ede5f7`. No XOPP rewrite, reference repair or input script execution was used.

## Evidence limits

This verifies the documented bounded trusted-local-input profile on the pinned Linux tools, including real PDF backgrounds, text and filled strokes. It does not establish arbitrary hostile-file safety, all XOPP features, every supported PNG/background variant, other native versions, GUI behavior, PDF interactive metadata preservation or round-trip editing. See the [input profile](INPUT-PROFILE.md) and [test contract](TEST-DESIGN.md).

The earlier official AppImage route did not pass startup; the accepted route uses the same release's official DEB CLI. Its failure and packaging rationale remain documented in [Sources](SOURCES.md). A source-only distribution requires separately installed native dependencies and does not grant a new license for original InkStages code.
