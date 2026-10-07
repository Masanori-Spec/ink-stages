"""Recipe resolution and bounded native export orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import resource
import selectors
import shutil
import signal
import subprocess
import tempfile
import time

from . import __version__
from .parser import Document, RESOURCE_LIMIT, SOURCE_LIMIT, bounded_text, inspect_xopp
from .safety import FreshFile, InkStagesError, Snapshot, absolute, assert_unchanged, fail, read_regular


RECIPE_LIMIT = 512 * 1024
ENTRY_PDF_LIMIT = 32 * 1024 * 1024
OUTPUT_LIMIT = 256 * 1024 * 1024
LOG_LIMIT = 1024 * 1024
MAX_ENTRIES = 128
PINNED_XOURNALPP = "1.3.8"
PINNED_QPDF = "12.4.2"


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _strict_json(data: bytes):
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise InkStagesError("Recipe must be UTF-8 JSON") from exc
    # Bound nesting before json.loads allocates recursive lists or dictionaries.
    depth, tokens, quoted, escaped = 0, 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
            tokens += 1
        elif char in "[{":
            depth += 1
            tokens += 1
            if depth > 6:
                fail("Recipe JSON nesting limit exceeded")
        elif char in "]}":
            depth -= 1
        elif char == ",":
            tokens += 1
        if tokens > 40_000:
            fail("Recipe JSON token limit exceeded")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                fail(f"Duplicate JSON key: {key}")
            value[key] = item
        return value

    def integer(value):
        if len(value) > 12:
            fail("Recipe integer is too large")
        return int(value)

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_int=integer,
                          parse_constant=lambda _: fail("Non-finite JSON values are unsupported"))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise InkStagesError(f"Invalid recipe JSON: {exc}") from exc


@dataclass
class Plan:
    document: Document
    recipe: Snapshot | None
    entries: list[dict]

    def report(self, status="dry-run") -> dict:
        return {
            "format": "inkstages.report.v1", "inkstages_version": __version__, "status": status,
            "profile": "gzip-xopp-v4-local-resources-v1", "xournalpp_required": PINNED_XOURNALPP,
            "qpdf_required": PINNED_QPDF,
            "source": self.document.source.summary(),
            "recipe": self.recipe.summary() if self.recipe else None,
            "resources": [item.summary() for item in self.document.resources],
            "pages": [{"page": index + 1, "width": page.width, "height": page.height,
                       "layers": [{"name": name, "native_index": number + 1}
                                  for number, name in enumerate(page.layers)],
                       "background": page.background} for index, page in enumerate(self.document.pages)],
            "entries": self.entries,
            "selection_semantics": "Exact-name selection set; original document stacking order; repeated entries retained",
            "native_execution": False,
            "commands": [],
        }


def inspect(source, recipe=None) -> Plan:
    document = inspect_xopp(source)
    if recipe is None:
        return Plan(document, None, [])
    snapshot = read_regular(recipe, RECIPE_LIMIT)
    if (snapshot.device, snapshot.inode) == (document.source.device, document.source.inode):
        fail("Recipe aliases source")
    content = _strict_json(snapshot.data)
    if type(content) is not dict or content.keys() != {"format", "entries"}:
        fail("Recipe requires exactly format and entries")
    if content["format"] != "inkstages.recipe.v1":
        fail("Unsupported recipe format")
    entries = content["entries"]
    if type(entries) is not list or not 1 <= len(entries) <= MAX_ENTRIES:
        fail("Recipe needs 1..128 entries")
    resolved = []
    for ordinal, entry in enumerate(entries, 1):
        if type(entry) is not dict or entry.keys() != {"page", "layers", "background"}:
            fail(f"Entry {ordinal} requires exactly page, layers, background")
        page, names, background = entry["page"], entry["layers"], entry["background"]
        if type(page) is not int or not 1 <= page <= len(document.pages):
            fail(f"Entry {ordinal} page must be a valid 1-based integer")
        if type(background) is not bool:
            fail(f"Entry {ordinal} background must be a JSON boolean")
        if type(names) is not list or not 1 <= len(names) <= 64 or any(type(name) is not str for name in names):
            fail(f"Entry {ordinal} layers must contain 1..64 exact names; empty selections are unsupported")
        for name in names:
            bounded_text(name, "recipe layer name")
        if len(set(names)) != len(names):
            fail(f"Entry {ordinal} has duplicate layer names")
        available = document.pages[page - 1].layers
        missing = set(names) - set(available)
        if missing:
            fail(f"Entry {ordinal}: missing exact layer names on page {page}: {sorted(missing)!r}")
        resolved.append({"ordinal": ordinal, "page": page, "layers": names,
                         "native_layer_indices": sorted(available.index(name) + 1 for name in names),
                         "background": background})
    return Plan(document, snapshot, resolved)


def export_command(executable: str, source: Path, output: Path, entry: dict) -> list[str]:
    command = [executable, "--disable-audio", f"--create-pdf={output}", f"--export-range={entry['page']}",
               "--export-layer-range=" + ",".join(map(str, entry["native_layer_indices"]))]
    if not entry["background"]:
        command.append("--export-no-background")
    command.append(str(source))
    return command


def merge_command(executable: str, inputs: list[Path], output: Path) -> list[str]:
    command = [executable, "--empty", "--pages"]
    for path in inputs:
        command.extend([str(path), "1"])
    return command + ["--", str(output)]


def _executable(value: str, default: str) -> str:
    if value == default:
        found = shutil.which(default)
        if found is None:
            fail(f"Native dependency not found: {default}")
        path = Path(found).resolve()
    else:
        path = Path(value)
        if not path.is_absolute():
            fail(f"Custom {default} executable must be an absolute path")
        path = path.resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        fail(f"Native executable is not an executable regular file: {path}")
    return str(path)


def _limits(timeout):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_LIMIT, OUTPUT_LIMIT))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (math.ceil(timeout) + 1, math.ceil(timeout) + 1))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))


def run_process(command: list[str], *, cwd: Path, env: dict, timeout: float, log: Path) -> dict:
    """No shell; bounded combined output, wall/CPU/memory/file limits, group kill."""
    started = time.monotonic()
    process = None
    chunks, size = [], 0
    with FreshFile(log) as log_file:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, cwd=cwd, env=env, shell=False,
                                       start_new_session=True, preexec_fn=lambda: _limits(timeout))
            selector = selectors.DefaultSelector()
            try:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        fail(f"Native command timed out after {timeout:g}s")
                    for key, _ in selector.select(min(remaining, 0.2)):
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        size += len(data)
                        if size > LOG_LIMIT:
                            fail("Native command log exceeds 1 MiB")
                        chunks.append(data)
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    fail(f"Native command timed out after {timeout:g}s")
                code = process.wait(timeout=remaining)
            finally:
                selector.close()
        except subprocess.TimeoutExpired as exc:
            raise InkStagesError(f"Native command timed out after {timeout:g}s") from exc
        except OSError as exc:
            raise InkStagesError(f"Native command could not start: {exc.strerror}") from exc
        except subprocess.SubprocessError as exc:
            raise InkStagesError(f"Native process setup failed: {exc}") from exc
        finally:
            if process is not None:
                # Descendants may retain pipes or keep running after their parent exits.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                process.stdout.close()
            log_file.write(b"".join(chunks))
    return {"returncode": code, "stdout": b"".join(chunks).decode("utf-8", errors="replace"),
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def _environment(work: Path) -> dict:
    state_dir = work / "state"
    state_dir.mkdir(mode=0o700)
    result = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
              "TMPDIR": str(work), "XDG_CONFIG_DIRS": str(state_dir / "system-config"),
              "XDG_CONFIG_HOME": str(state_dir / "config"), "XDG_DATA_HOME": str(state_dir / "data"),
              "XDG_CACHE_HOME": str(state_dir / "cache"), "XDG_STATE_HOME": str(state_dir / "state")}
    # A caller may start Xvfb; no preexisting application session or loader overrides are inherited.
    for key in ("HOME", "DISPLAY", "XAUTHORITY"):
        if key in os.environ:
            result[key] = os.environ[key]
    return result


def _verify_inputs(plan: Plan) -> dict:
    return {"source": assert_unchanged(plan.document.source, SOURCE_LIMIT),
            "recipe": assert_unchanged(plan.recipe, RECIPE_LIMIT) if plan.recipe else None,
            "resources": [assert_unchanged(item, RESOURCE_LIMIT) for item in plan.document.resources]}


def _validate_destinations(plan: Plan, paths):
    destinations = [absolute(path) for path in paths]
    if len(set(destinations)) != len(destinations):
        fail("Output and report must be distinct")
    inputs = [plan.document.source] + plan.document.resources + ([plan.recipe] if plan.recipe else [])
    for destination in destinations:
        if any(destination == snapshot.path for snapshot in inputs):
            fail("Destination aliases an input")
        # FreshFile enforces O_EXCL. This early check also refuses dangling symlinks/FIFOs.
        if os.path.lexists(destination):
            fail(f"Destination already exists: {destination}")


def dry_run(plan: Plan, report=None, *, xournalpp="xournalpp", qpdf="qpdf") -> dict:
    result = plan.report()
    work = Path("/PRIVATE_TEMP")
    # These are templates, never represented as executed commands.
    tools = [value if Path(value).is_absolute() else f"/PATH/{value}" for value in (xournalpp, qpdf)]
    sources = work / "input" / plan.document.source.path.name
    outputs = [work / f"entry-{entry['ordinal']:03d}.pdf" for entry in plan.entries]
    result["command_templates"] = [export_command(tools[0], sources, output, entry)
                                   for output, entry in zip(outputs, plan.entries)]
    if outputs:
        result["command_templates"].append(merge_command(tools[1], outputs, work / "assembled.pdf"))
    result["after"] = _verify_inputs(plan)
    if report is not None:
        _validate_destinations(plan, [report])
        with FreshFile(report) as destination:
            destination.write(json_bytes(result))
    return result


def render(plan: Plan, output, report, *, xournalpp="xournalpp", qpdf="qpdf", timeout=60.0,
           runner=run_process) -> dict:
    if not plan.entries or plan.recipe is None:
        fail("Rendering requires a nonempty recipe")
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 1 <= timeout <= 300:
        fail("Timeout must be between 1 and 300 seconds per native command")
    _validate_destinations(plan, [output, report])
    _verify_inputs(plan)
    native = _executable(xournalpp, "xournalpp")
    merger = _executable(qpdf, "qpdf")
    result = plan.report("running")
    result["native_execution"] = True
    with FreshFile(output) as output_file, FreshFile(report) as report_file:
        try:
            # Never point native applications at user files: preserve exact bytes in a private staging directory.
            with tempfile.TemporaryDirectory(prefix="inkstages-") as temporary:
                work = Path(temporary)
                input_dir = work / "input"
                input_dir.mkdir(mode=0o700)
                staged = []
                for snapshot in [plan.document.source] + plan.document.resources:
                    target = input_dir / snapshot.path.name
                    with FreshFile(target) as fresh:
                        fresh.write(snapshot.data)
                    target.chmod(0o400)
                    staged.append(read_regular(target, max(SOURCE_LIMIT, RESOURCE_LIMIT)))
                source = input_dir / plan.document.source.path.name
                env = _environment(work)
                log_total = 0

                def execute(command):
                    nonlocal log_total
                    item = {"argv": command, "returncode": None}
                    result["commands"].append(item)
                    log = work / f"command-{len(result['commands']):04d}.log"
                    try:
                        response = runner(command, cwd=work, env=env, timeout=timeout, log=log)
                    except Exception as exc:
                        item["error"] = str(exc)
                        try:
                            item["log_tail"] = read_regular(log, LOG_LIMIT).data.decode("utf-8", errors="replace")[-4096:]
                        except InkStagesError:
                            item["log_tail"] = "No bounded log was available"
                        raise
                    log_total += len(response["stdout"].encode("utf-8"))
                    if log_total > 16 * 1024 * 1024:
                        fail("Total native log budget exceeded")
                    item.update({"returncode": response["returncode"],
                                 "log_tail": response["stdout"][-4096:],
                                 "elapsed_seconds": response.get("elapsed_seconds")})
                    if response["returncode"] != 0:
                        fail(f"Native command failed ({response['returncode']}): {Path(command[0]).name}; "
                             f"{response['stdout'][-1024:]}")
                    return response["stdout"]

                version = execute([native, "--version"])
                if not re.search(r"(?:xournalpp|Xournal\+\+)\s+1\.3\.8(?:\s|$)", version):
                    fail("Only Xournal++ 1.3.8 is supported; native --version did not match")
                qpdf_version = execute([merger, "--version"])
                if not re.search(r"qpdf version 12\.4\.2(?:\s|$)", qpdf_version):
                    fail("Only qpdf 12.4.2 is supported; native --version did not match")
                result["native_versions"] = {"xournalpp": version.strip(), "qpdf": qpdf_version.strip()}

                def page_count(path):
                    raw = execute([merger, "--show-npages", str(path)]).strip()
                    if not re.fullmatch(r"[1-9][0-9]{0,5}", raw):
                        fail("qpdf returned an invalid page count")
                    return int(raw)

                for filename, maximum_page in plan.document.pdf_pages.items():
                    path = input_dir / filename
                    execute([merger, "--check", str(path)])
                    count = page_count(path)
                    if count > 10_000 or maximum_page > count:
                        fail("PDF background page is missing or the PDF has more than 10000 pages")
                outputs = []
                total_bytes = 0
                for entry in plan.entries:
                    path = work / f"entry-{entry['ordinal']:03d}.pdf"
                    execute(export_command(native, source, path, entry))
                    generated = read_regular(path, ENTRY_PDF_LIMIT)
                    if not generated.data.startswith(b"%PDF-"):
                        fail("Native export did not produce a PDF")
                    total_bytes += len(generated.data)
                    if total_bytes > OUTPUT_LIMIT:
                        fail("Entry PDF total exceeds 256 MiB")
                    execute([merger, "--check", str(path)])
                    if page_count(path) != 1:
                        fail("Each native export must contain exactly one page")
                    outputs.append(path)
                    for snapshot in staged:
                        assert_unchanged(snapshot, max(SOURCE_LIMIT, RESOURCE_LIMIT))
                assembled = work / "assembled.pdf"
                execute(merge_command(merger, outputs, assembled))
                final = read_regular(assembled, OUTPUT_LIMIT)
                if not final.data.startswith(b"%PDF-"):
                    fail("qpdf did not produce a PDF")
                execute([merger, "--check", str(assembled)])
                if page_count(assembled) != len(plan.entries):
                    fail("Assembled PDF page count does not match recipe")
                result["after"] = _verify_inputs(plan)
                result["output"] = {"path": str(absolute(output)), "bytes": len(final.data),
                                    "sha256": final.sha256, "pages": len(plan.entries)}
                result["status"] = "complete"
                output_file.write(final.data)
                report_file.write(json_bytes(result))
                return result
        except Exception as exc:
            # If the report cannot be finalized, do not leave an apparent successful output.
            output_file.committed = False
            result["status"] = "failed"
            result["error"] = str(exc)
            try:
                result["after"] = _verify_inputs(plan)
            except InkStagesError as check:
                result["input_integrity_error"] = str(check)
            if not report_file.committed:
                report_file.write(json_bytes(result))
            raise
