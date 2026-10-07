#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test ! -e .native
test ! -e evidence
mkdir .native evidence
INK_ROOT="$PWD"
export XDG_CONFIG_HOME="$INK_ROOT/.native/config"
export XDG_CACHE_HOME="$INK_ROOT/.native/cache"
export XDG_DATA_HOME="$INK_ROOT/.native/data"
mkdir -p "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME"
export LC_ALL=C.UTF-8

curl --fail --location --connect-timeout 15 --max-time 120 --retry 1 --output .native/xournalpp.deb 'https://github.com/xournalpp/xournalpp/releases/download/v1.3.8/xournalpp-1.3.8-Ubuntu-noble-x86_64.deb'
curl --fail --location --connect-timeout 15 --max-time 120 --retry 1 --output .native/qpdf.zip 'https://github.com/qpdf/qpdf/releases/download/v12.4.2/qpdf-12.4.2-bin-linux-x86_64.zip'
python3 - <<'PY'
from pathlib import Path
import hashlib,json
pins={
 'xournalpp.deb':(3244468,'246f1767ac135f5cda8e4c0518f3a42e4122ae7710d5ae254709bdee32d42ff0'),
 'qpdf.zip':(4040257,'db367d897829f22c4198ce1094143c9d467bd6ee7dfabc44ba6f02056b24f8b1')}
for name,(size,digest) in pins.items():
 p=Path('.native')/name
 assert p.stat().st_size==size and hashlib.sha256(p.read_bytes()).hexdigest()==digest,name
Path('evidence/release-integrity.json').write_text(json.dumps(pins,indent=2)+'\n')
PY
python3 scripts/extract_qpdf.py .native/qpdf.zip .native/qpdf evidence/qpdf-release-members.json
sudo apt-get install -y ./.native/xournalpp.deb
export INKSTAGES_XOURNALPP=/usr/bin/xournalpp
python3 - <<'PY'
from pathlib import Path
import hashlib,io,json,subprocess,tarfile
payload=subprocess.check_output(['dpkg-deb','--fsys-tarfile','.native/xournalpp.deb'],timeout=30)
with tarfile.open(fileobj=io.BytesIO(payload)) as t:
 matches=[m for m in t.getmembers() if m.name in {'./usr/bin/xournalpp','usr/bin/xournalpp'}]
 assert len(matches)==1 and matches[0].isfile()
 expected=t.extractfile(matches[0]).read()
installed=Path('/usr/bin/xournalpp')
assert not installed.is_symlink() and installed.read_bytes()==expected
record={'distribution':'Official Ubuntu noble x86_64 DEB','path':str(installed),'bytes':len(expected),
        'sha256':hashlib.sha256(expected).hexdigest(),'matchesVerifiedDebPayload':True}
Path('evidence/installed-renderer.json').write_text(json.dumps(record,indent=2)+'\n')
PY
dpkg-query -W xournalpp > evidence/installed-package.txt
INKSTAGES_QPDF="$(find "$INK_ROOT/.native/qpdf" -type f -name qpdf)"
test -n "$INKSTAGES_QPDF"
test "$(printf '%s\n' "$INKSTAGES_QPDF" | wc -l)" -eq 1
chmod +x "$INKSTAGES_QPDF"
export INKSTAGES_QPDF
printf 'Checking official CLI versions with bounded startup\n'
timeout --kill-after=5s 45s "$INKSTAGES_XOURNALPP" --version > evidence/xournalpp-version.txt 2>&1
timeout --kill-after=5s 15s "$INKSTAGES_QPDF" --version > evidence/qpdf-version.txt 2>&1

timeout --kill-after=5s 120s git clone --depth 1 --branch v1.3.8 https://github.com/xournalpp/xournalpp.git .native/upstream
test "$(git -C .native/upstream rev-parse HEAD)" = 938bdb8de4d32f38f48dd7f6544886722157a848
git -C .native/upstream rev-parse HEAD > evidence/native-source-commit.txt
printf 'Configuring unchanged official source for native fixture authoring\n'
timeout --kill-after=5s 120s cmake -S .native/upstream -B .native/build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DENABLE_AUDIO=OFF -DENABLE_PLUGINS=OFF \
  -DENABLE_GTK_SOURCEVIEW=OFF -DENABLE_CPPTRACE=OFF -DENABLE_GTEST=OFF \
  -DCMAKE_PROJECT_INCLUDE="$INK_ROOT/native/add-harness.cmake" \
  -DINKSTAGES_HARNESS_SOURCE="$INK_ROOT/native/fixture.cpp" \
  > evidence/native-configure.log 2>&1
printf 'Building unchanged official core and separate fixture harness\n'
timeout --kill-after=5s 1200s cmake --build .native/build --target inkstages-fixture --parallel 2 > evidence/native-build.log 2>&1
git -C .native/upstream diff --exit-code > evidence/native-source-unmodified.txt
sha256sum .native/build/src/core/libxournalpp-core.a "$INKSTAGES_QPDF" "$INKSTAGES_XOURNALPP" .native/xournalpp.deb > evidence/native-binaries-before.sha256
find .native/qpdf -type f -print0 | sort -z | xargs -0 sha256sum >> evidence/native-binaries-before.sha256
printf 'Authoring and reopening native fixture\n'
timeout --kill-after=5s 60s .native/build/inkstages-fixture "$INK_ROOT/evidence/fixture" > evidence/native-author.log 2>&1
printf 'Rendering actual named recipe and independent controls\n'
python3 scripts/native_gate.py
sha256sum --check evidence/native-binaries-before.sha256 > evidence/native-binaries-unchanged.txt
git -C .native/upstream diff --exit-code >> evidence/native-source-unmodified.txt
python3 --version > evidence/python-version.txt
pdftoppm -v 2> evidence/poppler-version.txt
printf 'Pinned source clean before and after fixture execution\n' >> evidence/native-source-unmodified.txt
