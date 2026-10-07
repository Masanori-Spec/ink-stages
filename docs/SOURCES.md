# Primary sources and scope

Checked 2026-10-07. This is an XOPP-specific workflow adapter, not an invention of layer recipes or a replacement renderer.

## Demand and existing functionality

- [Xournal++ issue 6074](https://github.com/xournalpp/xournalpp/issues/6074), open and updated 2026-05-20, requests command-line automation for slides A, A+B and A+C in a Beamer workflow. Its proposed Lua interface is not implemented by InkStages; the existing export CLI is sufficient for the bounded adapter.
- [Related issue 6062](https://github.com/xournalpp/xournalpp/issues/6062) and [6073](https://github.com/xournalpp/xournalpp/issues/6073) describe the native/plugin workflow behind that request.
- [Official v1.3.8 command-line implementation](https://github.com/xournalpp/xournalpp/blob/938bdb8de4d32f38f48dd7f6544886722157a848/src/core/control/XournalMain.cpp) already exposes PDF export, page ranges, numeric layer ranges, background omission and cumulative progressive-layer export. InkStages composes those existing operations; it does not claim they are missing.
- [Official DocumentView](https://github.com/xournalpp/xournalpp/blob/938bdb8de4d32f38f48dd7f6544886722157a848/src/core/view/DocumentView.cpp) resolves chosen numeric indices into ordered layers and draws them in original stacking order. This is retained even if the recipe names are listed in reverse order.
- [inklayers at the reviewed revision](https://github.com/toolleeo/inklayers/tree/c5c6f0bb04ae2e1c47df7aab7420daf91384e7a1) already supports JSON/INI/TOML combinations selected by layer label/index for SVG/Inkscape, including Beamer output. The difference here is the XOPP/native-renderer adapter and exact-name resolution after document edits.
- [qpdf page selection](https://qpdf.readthedocs.io/en/stable/cli.html#page-selection) supplies the final page assembly. This tool uses `--empty --pages ... -- output.pdf` and checks both component and assembled PDFs.

## Native pins

| Component | Official identity |
| --- | --- |
| Xournal++ | [v1.3.8 release](https://github.com/xournalpp/xournalpp/releases/tag/v1.3.8), commit `938bdb8de4d32f38f48dd7f6544886722157a848` |
| Linux x86-64 AppImage | [Official asset](https://github.com/xournalpp/xournalpp/releases/download/v1.3.8/xournalpp-1.3.8-x86_64.AppImage), asset ID `589915555`, 40,053,240 bytes |
| AppImage SHA-256 | `fda3587ace5504275a227d4013ba5da0988bac52be281d04a4040e5e1abd5682` |
| qpdf | [v12.4.2 release](https://github.com/qpdf/qpdf/releases/tag/v12.4.2), commit `4eba95899886e851cc41d76886483b347612f2a8` |
| Linux x86-64 ZIP | [Official asset](https://github.com/qpdf/qpdf/releases/download/v12.4.2/qpdf-12.4.2-bin-linux-x86_64.zip), asset ID `591714098`, 4,040,257 bytes |
| qpdf ZIP SHA-256 | `db367d897829f22c4198ce1094143c9d467bd6ee7dfabc44ba6f02056b24f8b1` |

Sizes and digests were verified against the official release APIs; annotated tags were resolved to the listed commits. Hosted execution must verify downloaded bytes again before use. The pinned upstream source is fetched only into ignored CI scratch storage for fixture authoring, and must remain unmodified.

## Native format and authoring references

- [SaveHandler](https://github.com/xournalpp/xournalpp/blob/938bdb8de4d32f38f48dd7f6544886722157a848/src/core/control/xojfile/SaveHandler.cpp) writes gzip XML, `fileversion=4`, layer names and original text/stroke fields. It does not save transient layer visibility as a reusable export recipe.
- [LoadHandler](https://github.com/xournalpp/xournalpp/blob/938bdb8de4d32f38f48dd7f6544886722157a848/src/core/control/xojfile/LoadHandler.cpp) resolves resource paths. Its legacy `domain="absolute"` can contain a relative path; this profile permits only a safe same-directory basename. Gzip `domain="attach"` refers to the source basename plus the attachment suffix. Native support for more formats does not expand this tool's bounded profile.
- [Document](https://github.com/xournalpp/xournalpp/blob/938bdb8de4d32f38f48dd7f6544886722157a848/src/core/model/Document.h), [XojPage](https://github.com/xournalpp/xournalpp/blob/938bdb8de4d32f38f48dd7f6544886722157a848/src/core/model/XojPage.h), [Layer](https://github.com/xournalpp/xournalpp/blob/938bdb8de4d32f38f48dd7f6544886722157a848/src/core/model/Layer.h), [Text](https://github.com/xournalpp/xournalpp/blob/938bdb8de4d32f38f48dd7f6544886722157a848/src/core/model/Text.h) and [Stroke](https://github.com/xournalpp/xournalpp/blob/938bdb8de4d32f38f48dd7f6544886722157a848/src/core/model/Stroke.h) provide the actual fixture model. No replacement XOPP writer is used.

External tools remain governed by their upstream terms. No original InkStages license grant or vendor executable is included in this source snapshot.
