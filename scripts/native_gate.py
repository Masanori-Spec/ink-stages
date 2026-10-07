"""Run the actual CLI producer and genuine official-renderer controls."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
E = ROOT / 'evidence'
F = E / 'fixture'
X = str(Path(os.environ['INKSTAGES_XOURNALPP']).resolve())
Q = str(Path(os.environ['INKSTAGES_QPDF']).resolve())


def run(label, command, *, success=True):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=240)
    (E / (label + '.log')).write_bytes(result.stdout + b'\nSTDERR\n' + result.stderr)
    if success:
        assert result.returncode == 0, (label, result.returncode, result.stderr[-3000:])
    return result


def hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(F.iterdir()) if p.is_file()}


assert F.is_dir() and not (E / 'original.pdf').exists()
(E / 'originals-before.json').write_text(json.dumps(hashes(), indent=2) + '\n')
recipe = ROOT / 'scripts/recipe.json'
common = ['--xournalpp', X, '--qpdf', Q]
for name in ['original', 'inserted']:
    run(name, [sys.executable, '-m', 'ink_stages', str(F / (name + '.xopp')), str(recipe),
               '--output', str(E / (name + '.pdf')), '--report', str(E / (name + '-report.json')), *common])

# Deliberately use old positions against the actually inserted native layer.
run('fixed-index-control', [X, '--disable-audio', '--create-pdf=' + str(E / 'fixed-index-control.pdf'),
                            '--export-range=1', '--export-layer-range=1,3', str(F / 'inserted.xopp')])
# Native progressive export is a cumulative prefix, so its third frame has A+B+C.
run('native-prefix-control', [X, '--disable-audio', '--create-pdf=' + str(E / 'native-prefix-control.pdf'),
                              '--export-range=1', '--export-layers-progressively', str(F / 'original.xopp')])

negatives = {}
for name in ['missing', 'duplicate']:
    pdf, report = E / (name + '-rejected.pdf'), E / (name + '-rejected.json')
    assert not pdf.exists() and not report.exists()
    result = run(name + '-negative', [sys.executable, '-m', 'ink_stages', str(F / (name + '.xopp')), str(recipe),
                                      '--output', str(pdf), '--report', str(report), *common], success=False)
    negatives[name] = {'returncode': result.returncode, 'no_pdf': not pdf.exists(), 'no_report': not report.exists()}
    assert result.returncode != 0 and not pdf.exists() and not report.exists()
(E / 'negative-results.json').write_text(json.dumps(negatives, indent=2) + '\n')

for name in ['original', 'inserted', 'fixed-index-control', 'native-prefix-control']:
    run(name + '-qpdf-check', [Q, '--check', str(E / (name + '.pdf'))])
(E / 'originals-after.json').write_text(json.dumps(hashes(), indent=2) + '\n')
assert (E / 'originals-before.json').read_bytes() == (E / 'originals-after.json').read_bytes()
run('independent-oracle', [sys.executable, str(ROOT / 'scripts/oracle.py'), str(E)])
(E / 'native-gate-result.json').write_text(json.dumps({
    'status': 'pass', 'producer': 'Actual InkStages Linux CLI',
    'author': 'Pinned unmodified official C++ model and SaveHandler/LoadHandler APIs',
    'consumer': 'Official Xournal++ 1.3.8 AppImage CLI and qpdf 12.4.2',
    'nativeGuiTest': False, 'backgroundResource': 'Synthetic same-directory PDF',
    'inputRewrites': False, 'scriptsExecutedFromInputs': False,
}, indent=2) + '\n')
print('Actual CLI, official exports/combine/check, negative controls and independent oracle passed')
