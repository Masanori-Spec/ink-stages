"""Literal native/output oracle; imports neither InkStages nor fixture author."""
from pathlib import Path
import gzip
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

from PIL import Image

E = Path(sys.argv[1]).resolve()
F = E / 'fixture'


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=60).stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_file(path):
    return json.loads(path.read_text())


def xml(path):
    return ET.fromstring(gzip.decompress(path.read_bytes()))


# These records are handwritten separately from the native author and producer.
ART = {
    'A': ('ALPHA', [220, 30, 40], 30, 60, 60, 50),
    'B': ('BRAVO', [30, 170, 60], 70, 90, 90, 50),
    'C': ('CHARLIE', [40, 80, 220], 200, 60, 70, 50),
    'D': ('DELTA', [135, 55, 175], 60, 80, 80, 80),
    'UNUSED': ('UNUSED', [220, 30, 190], 280, 150, 50, 50),
}


def expected_snapshot(inserted=False):
    pages = []
    names = [['A', 'UNUSED', 'B', 'C'] if inserted else ['A', 'B', 'C'], ['D']]
    for pi, (w, h) in enumerate([(360, 240), (240, 360)]):
        layers = []
        for name in names[pi]:
            label, color, x, y, sw, sh = ART[name]
            layers.append({'name': name, 'elements': [
                {'rgb': color, 'text': label, 'x': x, 'y': y - 25},
                {'rgb': color, 'points': [[x, y], [x + sw, y], [x + sw, y + sh], [x, y + sh], [x, y]], 'fill': 255},
            ]})
        pages.append({'width': w, 'height': h, 'pdfPage': pi + 1, 'layers': layers})
    return {'pages': pages}


for name in ['authored.json', 'reopened.json', 'resaved-reopened.json']:
    assert json_file(F / name) == expected_snapshot(), name
assert json_file(F / 'inserted-reopened.json') == expected_snapshot(True)
assert gzip.decompress((F / 'original.xopp').read_bytes()) == gzip.decompress((F / 'native-resaved.xopp').read_bytes())
original = xml(F / 'original.xopp')
assert original.tag == 'xournal' and original.attrib['fileversion'] == '4'
assert original.attrib['creator'] == 'xournalpp 1.3.8'
assert len(original.findall('page')) == 2
assert original.find('page/background').attrib['filename'] == 'background.pdf'
assert original.find('page/background').attrib['domain'] == 'absolute'
assert [l.attrib['name'] for l in original.findall('page')[0].findall('layer')] == ['A', 'B', 'C']


def check_report(name, expected):
    report = json_file(E / name)
    assert report['status'] == 'complete' and report['native_execution'] is True
    assert re.search(r'(?:xournalpp|Xournal\+\+)\s+1\.3\.8(?:\s|$)', report['native_versions']['xournalpp'], re.I)
    assert re.search(r'qpdf version 12\.4\.2(?:\s|$)', report['native_versions']['qpdf'])
    assert [e['page'] for e in report['entries']] == [1, 1, 1, 2]
    assert [e['layers'] for e in report['entries']] == [['A'], ['B', 'A'], ['A', 'C'], ['D']]
    assert [e['background'] for e in report['entries']] == [False, True, True, True]
    assert [e['native_layer_indices'] for e in report['entries']] == expected
    commands = report['commands']
    assert all(c['returncode'] == 0 for c in commands)
    exports = [c['argv'] for c in commands if any(a.startswith('--create-pdf=') for a in c['argv'])]
    assert len(exports) == 4
    source_name = 'inserted.xopp' if name.startswith('inserted') else 'original.xopp'
    for i, (argv, indices) in enumerate(zip(exports, expected)):
        assert '--export-range=' + str([1, 1, 1, 2][i]) in argv
        assert '--export-layer-range=' + ','.join(map(str, indices)) in argv
        assert ('--export-no-background' in argv) is (i == 0)
        assert '--export-layers-progressively' not in argv
        assert Path(argv[-1]).name == source_name
        assert len([a for a in argv if a.startswith('--create-pdf=')]) == 1
    merges = [c['argv'] for c in commands if '--empty' in c['argv'] and '--pages' in c['argv']]
    assert len(merges) == 1 and len(merges[0]) == 13
    assert merges[0][4:11:2] == ['1', '1', '1', '1']
    return report


check_report('original-report.json', [[1], [1, 2], [1, 3], [1]])
check_report('inserted-report.json', [[1], [1, 3], [1, 4], [1]])


def pdf_evidence(name, pages):
    pdf = E / name
    text = run('pdftotext', '-layout', str(pdf), '-')
    info = run('pdfinfo', '-f', '1', '-l', str(pages), str(pdf))
    (E / (name + '.txt')).write_text(text)
    (E / (name + '.info.txt')).write_text(info)
    assert re.search(rf'^Pages:\s+{pages}$', info, re.M), info
    dimensions = [(float(w), float(h)) for w, h in re.findall(r'Page\s+\d+ size:\s+([\d.]+) x ([\d.]+) pts', info)]
    if not dimensions and pages == 1:
        dimensions = [(float(w), float(h)) for w, h in re.findall(r'Page size:\s+([\d.]+) x ([\d.]+) pts', info)]
    assert len(dimensions) == pages, info
    prefix = E / name.removesuffix('.pdf')
    run('pdftoppm', '-r', '72', '-png', str(pdf), str(prefix))
    images = []
    for i in range(1, pages + 1):
        path = Path(f'{prefix}-{i}.png')
        with Image.open(path) as im:
            images.append(im.convert('RGB').copy())
    texts = text.split('\f')
    if not texts[-1].strip():
        texts.pop()
    assert len(texts) == pages
    return texts, dimensions, images


BG = (247, 237, 211)
WHITE = (255, 255, 255)
RED = (220, 30, 40)
GREEN = (30, 170, 60)
BLUE = (40, 80, 220)
PURPLE = (135, 55, 175)


def region(image, x, y, color):
    pixels = list(image.crop((x - 3, y - 3, x + 4, y + 4)).getdata())
    assert len(pixels) == 49
    assert all(max(abs(a - b) for a, b in zip(pixel, color)) <= 3 for pixel in pixels), (x, y, color, pixels[0])


def check_pages(texts, dimensions, images):
    assert dimensions == [(360, 240), (360, 240), (360, 240), (240, 360)]
    expected_words = [{'ALPHA'}, {'ALPHA', 'BRAVO', 'BACKGROUND_ONE'},
                      {'ALPHA', 'CHARLIE', 'BACKGROUND_ONE'}, {'DELTA', 'BACKGROUND_TWO'}]
    vocabulary = {'ALPHA', 'BRAVO', 'CHARLIE', 'DELTA', 'UNUSED', 'BACKGROUND_ONE', 'BACKGROUND_TWO'}
    for i, (text, image, dimension) in enumerate(zip(texts, images, dimensions)):
        assert {word for word in vocabulary if word in text} == expected_words[i], (i, text)
        assert image.size == tuple(map(int, dimension))
        region(image, 10, 10, WHITE if i == 0 else BG)
    for i in [0, 1, 2]:
        region(images[i], 45, 80, RED)
        # This overlap proves original stacking order, even when recipe is [B,A].
        region(images[i], 80, 100, GREEN if i == 1 else RED)
        region(images[i], 130, 120, GREEN if i == 1 else (WHITE if i == 0 else BG))
        region(images[i], 230, 85, BLUE if i == 2 else (WHITE if i == 0 else BG))
        region(images[i], 305, 175, WHITE if i == 0 else BG)
    region(images[3], 95, 115, PURPLE)


normal = pdf_evidence('original.pdf', 4)
inserted = pdf_evidence('inserted.pdf', 4)
check_pages(*normal)
check_pages(*inserted)
assert normal[:2] == inserted[:2]
for one, two in zip(normal[2], inserted[2]):
    assert one.tobytes() == two.tobytes(), 'Name recipe changed after unrelated insertion'

fixed = pdf_evidence('fixed-index-control.pdf', 1)
assert 'BRAVO' in fixed[0][0] and 'CHARLIE' not in fixed[0][0]
region(fixed[2][0], 130, 120, GREEN)
region(fixed[2][0], 230, 85, BG)
assert fixed[2][0].tobytes() != normal[2][2].tobytes()
prefix = pdf_evidence('native-prefix-control.pdf', 3)
assert 'BRAVO' in prefix[0][2] and 'CHARLIE' in prefix[0][2]
region(prefix[2][2], 130, 120, GREEN)
assert prefix[2][2].tobytes() != normal[2][2].tobytes()

before = json_file(E / 'originals-before.json')
after = json_file(E / 'originals-after.json')
assert before == after
assert before == {p.name: sha(p) for p in sorted(F.iterdir()) if p.is_file()}
negatives = json_file(E / 'negative-results.json')
assert set(negatives) == {'missing', 'duplicate'}
for name, result in negatives.items():
    assert result['returncode'] != 0 and result['no_pdf'] and result['no_report'], name

(E / 'independent-oracle-result.json').write_text(json.dumps({
    'status': 'pass', 'nativeApiAuthored': True, 'nativeGuiTest': False,
    'officialCliRendered': True, 'pages': 4, 'literalDimensionsTextColorRegions': True,
    'originalStackingOrder': True, 'nameSelectionSurvivesInsertedLayer': True,
    'fixedIndexControlDiffers': True, 'nativeCumulativePrefixControlDiffers': True,
    'originalsAndResourcesUnchanged': True, 'missingDuplicateNamesRejected': True,
    'pdfSha256': sha(E / 'original.pdf'),
}, indent=2) + '\n')
print('Literal native model, names, PDF geometry/text/pixels, controls and immutability passed')
