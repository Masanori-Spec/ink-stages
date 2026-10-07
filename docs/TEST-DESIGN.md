# Native-first acceptance contract

This lane is a Linux CLI. The fixture is API-authored and CLI-rendered; no graphical editing or GUI acceptance is claimed.

## Actual native fixture

Hosted CI checks out the exact Xournal++ `938bdb8de4d32f38f48dd7f6544886722157a848` source and builds its unmodified production core with a separate original C++ fixture program. An external CMake hook adds the harness target without editing upstream source. Normal build options omit audio, plugins, syntax highlighting and debug tracing. No scripts from input files are executed.

The fixture uses actual Document, XojPage, Layer, Text and Stroke objects. Layer pointers enter the public owning collection during model-only construction; there are no GUI listeners, private-state setters or test subclasses. Selected-layer IDs stay in bounds. A synthetic two-page Cairo PDF is solely a local background resource, not an XOPP renderer. Official Document PDF loading creates pages of 360×240 and 240×360 points. SaveHandler saves the real gzip XOPP, LoadHandler reopens it, and a fresh native save/reopen must preserve the entire literal model snapshot and XML.

Page 1 has A/B/C layers containing ALPHA/BRAVO/CHARLIE text and red/green/blue filled shapes. Their positions overlap in one region so the oracle can detect reversed stacking order. Page 2 has D with DELTA and a purple shape. The source background resource contains distinct BACKGROUND_ONE/BACKGROUND_TWO text.

The four-entry recipe requests page 1 A without background, page 1 B+A with background, page 1 A+C with background, then page 2 D with background. The deliberately reversed B+A names still render A below B. Expected native indices are `[1]`, `[1,2]`, `[1,3]`, `[1]`.

## Consumer and independent output proof

The official Xournal++ 1.3.8 AppImage and qpdf 12.4.2 release ZIP are size/SHA-256 checked before extraction. The real InkStages CLI validates all input, stages exact source/resource bytes, invokes the official renderer once per entry, combines those real PDFs with qpdf and saves its actual PDF/report. A synthetic or hand-constructed PDF cannot substitute for this route.

A separate Python oracle imports neither the producer nor fixture author. It compares the native authored/reopened/resaved snapshots with handwritten layer, text, coordinate, color and shape records. Poppler reads all PDF page sizes and texts, then renders at 72 dpi. Literal interior pixel regions verify each layer's presence/absence, the white versus PDF background, and the original stacking order. qpdf validates every component and combined result. The assembled output must have dimensions 360×240, 360×240, 360×240 and 240×360 points in recipe order.

## Distinguishing controls

The unchanged official APIs reopen the original, insert a visibly magenta UNUSED layer before B, save a fresh XOPP and reopen it. The same name recipe must now resolve to `[1]`, `[1,3]`, `[1,4]`, `[1]`, and produce identical output text, dimensions and pixels.

Two genuine native-renderer controls must visibly differ:

1. Old numeric indices `1,3` against the inserted document render A+B instead of A+C. BRAVO/green must appear, CHARLIE/blue must be absent.
2. Native cumulative-prefix export of the original produces A, A+B, A+B+C. Its third frame retains B/green, whereas the required A+C frame omits it.

Separate native-saved fixtures rename C or duplicate A. The product must reject those exact missing/duplicate-name cases before producing a PDF/report. Original source, resources and fixture snapshots are hashed before and after every export/control, and all hashes must remain identical.

## Bounds and limits of evidence

Unit tests separately exercise recipe/schema limits, exact names, unsupported formats and XML, decompression bounds, resource paths and nonblocking regular-file checks, output exclusivity and orchestration failure handling. Mocks used in unit orchestration tests are not native acceptance. Only the hosted official path above can establish that result.

The actual PDFs and Poppler images require independent visual inspection. Native source cleanliness, release integrity, tool versions, commands, native model records and immutable source hashes are retained with the artifact. No upstream source tree or executable is uploaded as an artifact or distributed with the product.

Source-level review is not runtime success. The first hosted native result remains pending. The profile does not promise arbitrary hostile-file safety, PDF interactive metadata preservation, a UI, round-trip editing, or support for untested tool versions.
