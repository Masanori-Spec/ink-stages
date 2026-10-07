"""Pure Python safety/orchestration tests. Native correctness has a separate oracle."""

import base64
import binascii
import gzip
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import zlib

from ink_stages import core
from ink_stages.__main__ import main
from ink_stages.parser import decode_gzip, inspect_xopp, validate_png
from ink_stages.safety import FreshFile, InkStagesError, read_regular


def chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", binascii.crc32(kind + body) & 0xFFFFFFFF)


def png(width=1, height=1, raw=b"\x00\xff\x00\x00\xff"):
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def page(layers=("A", "B", "C"), background=None, content=""):
    background = background or '<background type="solid" color="#ffffffff" style="plain"/>'
    return '<page width="360" height="240">' + background + ''.join(
        f'<layer name="{name}">{content}</layer>' for name in layers) + '</page>'


def document(body=None):
    return '<xournal creator="Xournal++ 1.3.8" fileversion="4">' + (body or page()) + '</xournal>'


def recipe(entries=None):
    return {"format": "inkstages.recipe.v1", "entries": entries if entries is not None else [
        {"page": 1, "layers": ["C", "A"], "background": True}]}


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "drawing.xopp"
        self.recipe = self.root / "recipe.json"
        self.output = self.root / "output.pdf"
        self.report = self.root / "report.json"
        self.write_source(document())
        self.write_recipe(recipe())

    def tearDown(self):
        self.temp.cleanup()

    def write_source(self, xml):
        self.source.write_bytes(gzip.compress(xml.encode("utf-8")))

    def write_recipe(self, value):
        self.recipe.write_text(json.dumps(value), encoding="utf-8")

    def inspect(self):
        return core.inspect(self.source, self.recipe)


class RecipeTests(Workspace):
    def test_exact_names_sorted_indices_and_repetition(self):
        entry = {"page": 1, "layers": ["C", "A"], "background": False}
        self.write_recipe(recipe([entry, entry]))
        plan = self.inspect()
        self.assertEqual([item["native_layer_indices"] for item in plan.entries], [[1, 3], [1, 3]])
        self.assertEqual([item["ordinal"] for item in plan.entries], [1, 2])
        self.assertEqual(plan.entries[0]["layers"], ["C", "A"])

    def test_indices_resolve_fresh_after_layer_insertion(self):
        before = self.inspect()
        self.write_source(document(page(("A", "UNUSED", "B", "C"))))
        after = self.inspect()
        self.assertEqual(before.entries[0]["native_layer_indices"], [1, 3])
        self.assertEqual(after.entries[0]["native_layer_indices"], [1, 4])

    def test_layer_names_are_case_sensitive_and_not_trimmed(self):
        for names in (["a"], [" A"], ["A "]):
            with self.subTest(names=names):
                self.write_recipe(recipe([{"page": 1, "layers": names, "background": True}]))
                with self.assertRaises(InkStagesError):
                    self.inspect()

    def test_bad_entries(self):
        bad = [
            {"page": True, "layers": ["A"], "background": True},
            {"page": 1.0, "layers": ["A"], "background": True},
            {"page": 0, "layers": ["A"], "background": True},
            {"page": 2, "layers": ["A"], "background": True},
            {"page": 1, "layers": [], "background": True},
            {"page": 1, "layers": ["A", "A"], "background": True},
            {"page": 1, "layers": [1], "background": True},
            {"page": 1, "layers": "A", "background": True},
            {"page": 1, "layers": ["A"], "background": 1},
            {"page": 1, "layers": ["A"], "background": "true"},
            {"page": 1, "layers": ["A"], "background": True, "script": "anything"},
            {"page": 1, "layers": ["A"]},
        ]
        for entry in bad:
            with self.subTest(entry=entry):
                self.write_recipe(recipe([entry]))
                with self.assertRaises(InkStagesError):
                    self.inspect()

    def test_bad_top_level_and_entry_count(self):
        for value in ([], {}, {"format": "v2", "entries": []}, {**recipe(), "extra": True}, recipe([]),
                      recipe([recipe()["entries"][0]] * 129)):
            with self.subTest(value=str(value)[:80]):
                self.write_recipe(value)
                with self.assertRaises(InkStagesError):
                    self.inspect()

    def test_duplicate_json_keys_nonfinite_depth_and_huge_integer(self):
        for value in ('{"format":"inkstages.recipe.v1","format":"inkstages.recipe.v1","entries":[]}',
                      '{"format":"inkstages.recipe.v1","entries":NaN}', '[' * 10000 + ']' * 10000,
                      '{"format":"inkstages.recipe.v1","entries":12345678901234567890}'):
            with self.subTest(value=value[:80]):
                self.recipe.write_text(value)
                with self.assertRaises(InkStagesError):
                    self.inspect()

    def test_recipe_byte_limit(self):
        self.recipe.write_bytes(b" " * (core.RECIPE_LIMIT + 1))
        with self.assertRaisesRegex(InkStagesError, "exceeds"):
            self.inspect()

    def test_inventory_needs_no_recipe(self):
        plan = core.inspect(self.source)
        self.assertEqual(plan.entries, [])
        self.assertEqual(plan.report()["pages"][0]["layers"][2], {"name": "C", "native_index": 3})


class XmlTests(Workspace):
    def test_native_style_strokes_text_images(self):
        body = ('<stroke tool="pen" color="#001122ff" width="2" fill="255" capStyle="round">'
                '10 10 90 90 90 10</stroke>'
                '<text font="Sans" size="12" x="10" y="12" color="#000000ff">A &amp; B</text>'
                '<image left="10" top="10" right="20" bottom="20">'
                + base64.b64encode(png()).decode() + '</image>')
        self.write_source(document(page(content=body)))
        self.assertEqual(len(self.inspect().document.pages), 1)

    def test_dtd_entities_processing_instructions_and_encoding(self):
        bad = [
            '<!DOCTYPE xournal [<!ENTITY x "bad">]>' + document(),
            '<!DOCTYPE xournal SYSTEM "file:///etc/passwd">' + document(),
            '<?xml-stylesheet href="https://example.invalid/style"?>' + document(),
            '<?xml version="1.0" encoding="UTF-16"?>' + document(),
            '<?xml version="1.1"?>' + document(),
            document().replace('<layer name="A">', '<layer name="A">&unknown;'),
            document() + '<?after bad?>',
        ]
        for xml in bad:
            with self.subTest(xml=xml[:100]):
                self.write_source(xml)
                with self.assertRaises(InkStagesError):
                    self.inspect()
        self.source.write_bytes(gzip.compress(document().encode("utf-16")))
        with self.assertRaises(InkStagesError):
            self.inspect()

    def test_utf8_declaration_allowed(self):
        self.write_source('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + document())
        self.inspect()

    def test_leaf_fragmenting_comments_and_cdata_are_rejected(self):
        text = '<text font="Sans" size="12" x="0" y="0" color="black">{}</text>'
        stroke = '<stroke tool="pen" color="black" width="2">{}</stroke>'
        image = '<image left="0" top="0" right="1" bottom="1">{}</image>'
        encoded = base64.b64encode(png()).decode()
        cases = [
            text.format('before<!--split-->after'),
            text.format('before<![CDATA[split]]>after'),
            stroke.format('1 2<!--split--> 3 4'),
            stroke.format('1 2<![CDATA[ 3 4]]>'),
            image.format(encoded[:12] + '<!--split-->' + encoded[12:]),
            image.format(encoded[:12] + '<![CDATA[' + encoded[12:] + ']]>'),
        ]
        for content in cases:
            with self.subTest(content=content[:100]):
                self.write_source(document(page(content=content)))
                with self.assertRaisesRegex(InkStagesError, 'comments|CDATA'):
                    self.inspect()
        self.write_source('<!--outside-->' + document())
        with self.assertRaisesRegex(InkStagesError, 'comments'):
            self.inspect()

    def test_unknown_fields_tags_and_unsafe_features_rejected_on_unselected_page(self):
        variants = [
            page(content='<teximage text="execute" left="0" top="0" right="1" bottom="1">abc</teximage>'),
            page(content='<audio fn="outside"/>'),
            page(content='<attachment path="../secret"/>'),
            page(content='<text font="Sans" size="12" x="0" y="0" color="black" fn="recording.ogg">hi</text>'),
            page(content='<stroke tool="pen" color="black" width="2" ts="1">1 2 3 4</stroke>'),
            page().replace('style="plain"', 'style="plain" config="unknown"'),
            page().replace('width="360"', 'width="360" unknown="x"'),
        ]
        for body in variants:
            with self.subTest(body=body[:90]):
                self.write_source(document(page() + body))
                with self.assertRaises(InkStagesError):
                    self.inspect()

    def test_duplicate_unnamed_and_empty_layer_names_rejected(self):
        for body in (page(("A", "A")), page(("A", "")), page().replace(' name="B"', ''), page((" ",))):
            with self.subTest(body=body):
                self.write_source(document(body))
                with self.assertRaises(InkStagesError):
                    self.inspect()

    def test_page_and_layer_bounds(self):
        for body in (page() * 65, page(tuple(f"L{n}" for n in range(65)))):
            self.write_source(document(body))
            with self.assertRaises(InkStagesError):
                self.inspect()

    def test_parser_limits_during_parse(self):
        with patch("ink_stages.parser.MAX_EVENTS", 4), self.assertRaisesRegex(InkStagesError, "event limit"):
            self.inspect()
        with patch("ink_stages.parser.MAX_DEPTH", 2), self.assertRaisesRegex(InkStagesError, "depth limit"):
            self.inspect()
        with patch("ink_stages.parser.MAX_ATTRIBUTE_BYTES", 5), self.assertRaisesRegex(InkStagesError, "attribute limit"):
            self.inspect()
        self.write_source(document(page(content='<text font="Sans" size="12" x="1" y="1" color="black">abcdefgh</text>')))
        with patch("ink_stages.parser.MAX_LEAF_BYTES", 4), self.assertRaisesRegex(InkStagesError, "leaf text"):
            self.inspect()

    def test_nonfinite_and_bad_geometry(self):
        for xml in (document().replace('width="360"', 'width="nan"'),
                    document().replace('height="240"', 'height="0"'),
                    document(page(content='<stroke tool="pen" color="black" width="0">0 0 1 1</stroke>')),
                    document(page(content='<stroke tool="pen" color="black" width="2">0 0 nan 1</stroke>')),
                    document(page(content='<stroke tool="pen" color="black" width="2">0 0 1</stroke>')),
                    document(page(content='<image left="1" top="0" right="0" bottom="1">AAAA</image>'))):
            self.write_source(xml)
            with self.assertRaises(InkStagesError):
                self.inspect()

    def test_missing_background_or_layers(self):
        for body in ('<page width="1" height="1"><layer name="A"/></page>',
                     '<page width="1" height="1"><background type="solid" color="white" style="plain"/></page>',
                     page().replace('</page>', '<background type="solid" color="white" style="plain"/></page>')):
            self.write_source(document(body))
            with self.assertRaises(InkStagesError):
                self.inspect()

    def test_compressed_decompressed_truncation_crc_and_container_bounds(self):
        data = self.source.read_bytes()
        for invalid in (data[:-5], data + b"junk", data + data, b"PK\x03\x04zip", document().encode(),
                        data[:-8] + b"\x00" * 8):
            with self.subTest(data=invalid[:20]):
                with self.assertRaises(InkStagesError):
                    decode_gzip(invalid)
        with patch("ink_stages.parser.XML_LIMIT", 32), self.assertRaisesRegex(InkStagesError, "Decompressed"):
            decode_gzip(gzip.compress(b"a" * 100000))
        with patch("ink_stages.parser.SOURCE_LIMIT", 32), self.assertRaisesRegex(InkStagesError, "exceeds"):
            self.inspect()

    def test_ambiguous_gzip_zip_signature_rejected_before_native_probe(self):
        original = gzip.compress(document().encode())
        # A valid gzip with a filename header containing a ZIP directory signature.
        ambiguous = original[:3] + b"\x08" + original[4:10] + b"PK\x05\x06\x00" + original[10:]
        self.assertEqual(gzip.decompress(ambiguous), document().encode())
        with self.assertRaisesRegex(InkStagesError, "ambiguous container"):
            decode_gzip(ambiguous)


class ResourceTests(Workspace):
    def use_pdf(self, filename="background.pdf", domain="absolute"):
        self.write_source(document(page(background=f'<background type="pdf" domain="{domain}" filename="{filename}" pageno="1"/>')))

    def test_pdf_inheritance_and_immutable_resource_digest(self):
        pdf = self.root / "background.pdf"
        pdf.write_bytes(b"%PDF-1.7\ntrusted placeholder\n")
        self.write_source(document(page(background='<background type="pdf" domain="absolute" filename="background.pdf" pageno="1"/>')
                                   + page(("D",), '<background type="pdf" pageno="2"/>')))
        plan = self.inspect()
        self.assertEqual(plan.document.pdf_pages, {"background.pdf": 2})
        result = core.dry_run(plan)
        self.assertEqual(result["resources"], result["after"]["resources"])
        self.assertEqual(len(plan.document.resources), 1)

    def test_gzip_attached_pdf_resolves_exact_native_basename(self):
        (self.root / "drawing.xopp.bg.pdf").write_bytes(b"%PDF-1.7\nattached\n")
        self.use_pdf("bg.pdf", "attach")
        self.assertEqual(self.inspect().document.resources[0].path.name, "drawing.xopp.bg.pdf")

    def test_bad_resource_paths_and_domains(self):
        for filename, domain in [("/tmp/a.pdf", "absolute"), ("../a.pdf", "absolute"),
                                  ("sub/a.pdf", "absolute"), ("C:\\a.pdf", "absolute"),
                                  ("https://example.invalid/a.pdf", "absolute"), ("a.pdf", "clone"),
                                  ("a.svg", "absolute"), ("a.pdf", "url")]:
            with self.subTest(filename=filename, domain=domain):
                self.use_pdf(filename, domain)
                with self.assertRaises(InkStagesError):
                    self.inspect()

    def test_missing_wrong_format_symlink_fifo_and_alias_resources(self):
        target = self.root / "background.pdf"
        self.use_pdf()
        with self.assertRaises(InkStagesError):
            self.inspect()
        target.write_bytes(b"not pdf")
        with self.assertRaises(InkStagesError):
            self.inspect()
        target.unlink()
        target.symlink_to(self.source)
        with self.assertRaises(InkStagesError):
            self.inspect()
        target.unlink()
        os.mkfifo(target)
        started = time.monotonic()
        with self.assertRaises(InkStagesError):
            self.inspect()
        self.assertLess(time.monotonic() - started, 1)
        target.unlink()
        os.link(self.source, target)
        with self.assertRaisesRegex(InkStagesError, "aliases"):
            self.inspect()

    def test_resource_byte_and_total_limits(self):
        (self.root / "background.pdf").write_bytes(b"%PDF-1.7\n" + b"x" * 100)
        self.use_pdf()
        with patch("ink_stages.parser.RESOURCE_LIMIT", 50), self.assertRaisesRegex(InkStagesError, "exceeds"):
            self.inspect()
        with patch("ink_stages.parser.RESOURCE_TOTAL_LIMIT", 50), self.assertRaisesRegex(InkStagesError, "total"):
            self.inspect()

    def test_png_external_and_inline_validated(self):
        (self.root / "background.png").write_bytes(png())
        self.write_source(document(page(background='<background type="pixmap" domain="absolute" filename="background.png"/>')))
        self.inspect()
        validate_png(png())
        for data in (png()[:-1], png() + b"extra", png(width=9000), png(raw=b"\x00" * 1000),
                     png(raw=b"\x05\xff\x00\x00\xff"), png().replace(b"IDAT", b"ABCD")):
            with self.subTest(data=data[:20]):
                with self.assertRaises(InkStagesError):
                    validate_png(data)

    def test_unselected_resource_still_checked(self):
        self.write_source(document(page() + page(("D",), '<background type="pdf" domain="absolute" filename="missing.pdf" pageno="1"/>')))
        with self.assertRaises(InkStagesError):
            self.inspect()


class SafeIoTests(Workspace):
    def test_fifo_and_symlink_source_and_recipe_refused(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        started = time.monotonic()
        with self.assertRaises(InkStagesError):
            read_regular(fifo, 100)
        self.assertLess(time.monotonic() - started, 1)
        link = self.root / "link"
        link.symlink_to(self.source)
        with self.assertRaises(InkStagesError):
            inspect_xopp(link)
        self.recipe.unlink()
        self.recipe.symlink_to(self.source)
        with self.assertRaises(InkStagesError):
            self.inspect()

    def test_parent_symlinks_refused_for_reads_and_writes(self):
        real = self.root / "real"
        real.mkdir()
        (real / "input").write_bytes(b"data")
        link = self.root / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(InkStagesError):
            read_regular(link / "input", 100)
        with self.assertRaises(InkStagesError):
            FreshFile(link / "output")

    def test_fresh_file_never_overwrites_or_deletes_replacement(self):
        self.output.write_bytes(b"existing")
        with self.assertRaises(InkStagesError):
            FreshFile(self.output)
        self.assertEqual(self.output.read_bytes(), b"existing")
        self.output.unlink()
        with FreshFile(self.output) as fresh:
            self.output.unlink()
            self.output.write_bytes(b"replacement")
            with self.assertRaises(InkStagesError):
                fresh.write(b"our output")
        self.assertEqual(self.output.read_bytes(), b"replacement")

    def test_dry_run_never_executes_and_keeps_original_bytes(self):
        original = self.source.read_bytes()
        with patch("ink_stages.core.subprocess.Popen", side_effect=AssertionError("must never execute")):
            result = core.dry_run(self.inspect(), self.report)
        self.assertFalse(result["native_execution"])
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(json.loads(self.report.read_text())["status"], "dry-run")
        self.assertIn("--export-layer-range=1,3", result["command_templates"][0])

    def test_dry_run_rejects_stale_input_and_existing_report(self):
        plan = self.inspect()
        self.write_source(document(page(("A", "C", "B"))))
        with self.assertRaisesRegex(InkStagesError, "changed"):
            core.dry_run(plan, self.report)
        self.assertFalse(self.report.exists())
        self.report.write_text("existing")
        with self.assertRaises(InkStagesError):
            core.dry_run(self.inspect(), self.report)
        self.assertEqual(self.report.read_text(), "existing")

    def test_dry_run_refuses_report_input_alias(self):
        with self.assertRaisesRegex(InkStagesError, "aliases"):
            core.dry_run(self.inspect(), self.source)


class RenderTests(Workspace):
    def fake_runner(self, command, *, cwd, env, timeout, log):
        self.commands.append(command)
        log.write_text("mock log")
        self.assertEqual(env.get("HOME"), os.environ.get("HOME"))
        self.assertEqual(env["XDG_CONFIG_HOME"], str(cwd / "state" / "config"))
        self.assertNotIn("LD_PRELOAD", env)
        if "--version" in command:
            text = "xournalpp 1.3.8\n" if command[0].endswith("xournalpp") else "qpdf version 12.4.2\n"
        elif "--show-npages" in command:
            text = str(len(self.plan.entries) if command[-1].endswith("assembled.pdf") else 1)
        else:
            text = ""
            export = next((item for item in command if item.startswith("--create-pdf=")), None)
            if export:
                staged = Path(command[-1])
                self.assertNotEqual(staged, self.source)
                self.assertEqual(staged.read_bytes(), self.source.read_bytes())
                Path(export.split("=", 1)[1]).write_bytes(b"%PDF-1.7\nmock entry\n")
            elif "--empty" in command:
                Path(command[-1]).write_bytes(b"%PDF-1.7\nmock merged\n")
        return {"returncode": 0, "stdout": text, "elapsed_seconds": 0.001}

    def run_render(self, runner=None):
        self.commands = []
        self.plan = self.inspect()
        with patch("ink_stages.core._executable", side_effect=lambda _value, default: "/trusted/" + default):
            return core.render(self.plan, self.output, self.report, runner=runner or self.fake_runner)

    def test_native_commands_order_background_and_report(self):
        self.write_recipe(recipe([{"page": 1, "layers": ["C", "A"], "background": False},
                                  {"page": 1, "layers": ["A"], "background": True}]))
        original = self.source.read_bytes()
        result = self.run_render()
        exports = [cmd for cmd in self.commands if any(arg.startswith("--create-pdf=") for arg in cmd)]
        self.assertEqual(len(exports), 2)
        self.assertIn("--export-layer-range=1,3", exports[0])
        self.assertIn("--export-range=1", exports[0])
        self.assertIn("--export-no-background", exports[0])
        self.assertNotIn("--export-no-background", exports[1])
        merge = next(cmd for cmd in self.commands if "--empty" in cmd)
        self.assertEqual(merge[1:3], ["--empty", "--pages"])
        self.assertEqual(merge[4], "1")
        self.assertEqual(merge[6], "1")
        self.assertEqual(merge[-2], "--")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["output"]["pages"], 2)
        self.assertEqual(result["source"], result["after"]["source"])
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(json.loads(self.report.read_text())["status"], "complete")

    def test_wrong_native_version_fails_with_report_and_no_output(self):
        for replacement in ("Xournal++ 1.3.80\n", "Xournal++ 1.3.7\n"):
            with self.subTest(version=replacement):
                def runner(command, **kwargs):
                    response = self.fake_runner(command, **kwargs)
                    if command[0].endswith("xournalpp") and "--version" in command:
                        response["stdout"] = replacement
                    return response
                with self.assertRaisesRegex(InkStagesError, "1.3.8"):
                    self.run_render(runner)
                self.assertFalse(self.output.exists())
                self.assertEqual(json.loads(self.report.read_text())["status"], "failed")
                self.report.unlink()

    def test_wrong_qpdf_version_rejected(self):
        def runner(command, **kwargs):
            response = self.fake_runner(command, **kwargs)
            if command[0].endswith("qpdf") and "--version" in command:
                response["stdout"] = "qpdf version 12.4.20\n"
            return response
        with self.assertRaisesRegex(InkStagesError, "12.4.2"):
            self.run_render(runner)
        self.assertFalse(self.output.exists())

    def test_native_failure_and_timeout_leave_failure_report(self):
        for timedout in (False, True):
            def runner(command, **kwargs):
                if any(arg.startswith("--create-pdf=") for arg in command):
                    if timedout:
                        raise InkStagesError("Native command timed out after 60s")
                    return {"returncode": 2, "stdout": "intentional failure"}
                return self.fake_runner(command, **kwargs)
            with self.assertRaises(InkStagesError):
                self.run_render(runner)
            self.assertFalse(self.output.exists())
            result = json.loads(self.report.read_text())
            self.assertEqual(result["status"], "failed")
            self.assertIn("after", result)
            self.report.unlink()

    def test_multi_page_export_refused(self):
        def runner(command, **kwargs):
            response = self.fake_runner(command, **kwargs)
            if "--show-npages" in command:
                response["stdout"] = "2"
            return response
        with self.assertRaisesRegex(InkStagesError, "exactly one"):
            self.run_render(runner)

    def test_native_input_mutation_detected(self):
        def runner(command, **kwargs):
            response = self.fake_runner(command, **kwargs)
            if any(arg.startswith("--create-pdf=") for arg in command):
                staged = Path(command[-1])
                staged.chmod(0o600)
                staged.write_bytes(b"changed")
            return response
        original = self.source.read_bytes()
        with self.assertRaisesRegex(InkStagesError, "changed"):
            self.run_render(runner)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse(self.output.exists())

    def test_original_mutation_detected_before_publishing(self):
        def runner(command, **kwargs):
            response = self.fake_runner(command, **kwargs)
            if "--empty" in command:
                self.write_source(document(page(("A", "C", "B"))))
            return response
        with self.assertRaisesRegex(InkStagesError, "changed"):
            self.run_render(runner)
        self.assertFalse(self.output.exists())
        self.assertIn("input_integrity_error", json.loads(self.report.read_text()))

    def test_existing_outputs_reports_and_aliases_prevent_all_execution(self):
        self.commands = []
        plan = self.inspect()
        for output, report in ((self.output, self.output), (self.source, self.report), (self.output, self.recipe)):
            with self.assertRaises(InkStagesError):
                core.render(plan, output, report, runner=self.fake_runner)
        for existing in (self.output, self.report):
            existing.write_text("existing")
            with self.assertRaises(InkStagesError):
                core.render(plan, self.output, self.report, runner=self.fake_runner)
            self.assertEqual(existing.read_text(), "existing")
            existing.unlink()
        self.assertEqual(self.commands, [])

    def test_shell_metacharacters_remain_literal_argv(self):
        self.source = self.root / "drawing; touch NEVER_EXECUTED.xopp"
        self.write_source(document())
        result = self.run_render()
        export = next(item["argv"] for item in result["commands"]
                      if any(arg.startswith("--create-pdf=") for arg in item["argv"]))
        self.assertTrue(export[-1].endswith(self.source.name))
        self.assertFalse((self.root / "NEVER_EXECUTED.xopp").exists())

    def test_timeout_bounds_and_missing_recipe(self):
        for timeout in (0, 301, float("nan"), True):
            with self.assertRaises(InkStagesError):
                core.render(self.inspect(), self.output, self.report, timeout=timeout)
        with self.assertRaises(InkStagesError):
            core.render(core.inspect(self.source), self.output, self.report)


class CliTests(Workspace):
    def test_dry_run_inventory_and_recipe(self):
        for args in ([str(self.source), "--dry-run"], [str(self.source), str(self.recipe), "--dry-run"]):
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(main(args), 0)
                self.assertFalse(json.loads(stdout.getvalue())["native_execution"])

    def test_actual_requires_output_and_report(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            main([str(self.source), str(self.recipe)])

    def test_dry_run_rejects_output_and_invalid_source_has_concise_error(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            main([str(self.source), "--dry-run", "--output", str(self.output)])
        self.source.write_bytes(b"bad")
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(main([str(self.source), "--dry-run"]), 2)
            self.assertIn("Only gzip", stderr.getvalue())


class ProcessBoundaryTests(Workspace):
    """Exercise pipes/timeouts without launching any external process."""

    def process(self, data=None):
        read_fd, write_fd = os.pipe()
        fake = Mock()
        fake.pid = 123456
        fake.stdout = os.fdopen(read_fd, "rb")
        fake.wait.return_value = 0
        if data is not None:
            os.write(write_fd, data)
            os.close(write_fd)
        else:
            self.addCleanup(os.close, write_fd)
        self.addCleanup(fake.stdout.close)
        return fake

    def test_runner_captures_bounded_logs_without_a_shell(self):
        fake = self.process(b"native output\n")
        log = self.root / "command.log"
        with patch("ink_stages.core.subprocess.Popen", return_value=fake) as popen, patch("ink_stages.core.os.killpg"):
            response = core.run_process(["/trusted/xournalpp", "--version"], cwd=self.root,
                                        env={"LANG": "C.UTF-8"}, timeout=1, log=log)
        self.assertEqual(response["stdout"], "native output\n")
        self.assertEqual(log.read_bytes(), b"native output\n")
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.args[0], ["/trusted/xournalpp", "--version"])

    def test_runner_log_overflow_kills_group(self):
        fake = self.process(b"too much")
        with (patch("ink_stages.core.subprocess.Popen", return_value=fake),
              patch("ink_stages.core.os.killpg") as kill,
              patch("ink_stages.core.LOG_LIMIT", 4)):
            with self.assertRaisesRegex(InkStagesError, "log exceeds"):
                core.run_process(["/trusted/xournalpp"], cwd=self.root, env={}, timeout=1,
                                 log=self.root / "command.log")
        kill.assert_called_once_with(fake.pid, core.signal.SIGKILL)

    def test_runner_wall_timeout_kills_group_and_keeps_log(self):
        fake = self.process()
        log = self.root / "timeout.log"
        with patch("ink_stages.core.subprocess.Popen", return_value=fake), patch("ink_stages.core.os.killpg") as kill:
            with self.assertRaisesRegex(InkStagesError, "timed out"):
                core.run_process(["/trusted/xournalpp"], cwd=self.root, env={}, timeout=0.01, log=log)
        kill.assert_called_once_with(fake.pid, core.signal.SIGKILL)
        self.assertTrue(log.exists())


if __name__ == "__main__":
    unittest.main()
