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

curl --fail --location --retry 2 --output .native/xournalpp.AppImage 'https://github.com/xournalpp/xournalpp/releases/download/v1.3.8/xournalpp-1.3.8-x86_64.AppImage'
curl --fail --location --retry 2 --output .native/qpdf.zip 'https://github.com/qpdf/qpdf/releases/download/v12.4.2/qpdf-12.4.2-bin-linux-x86_64.zip'
python3 - <<'PY'
from pathlib import Path
import hashlib,json
pins={
 'xournalpp.AppImage':(40053240,'fda3587ace5504275a227d4013ba5da0988bac52be281d04a4040e5e1abd5682'),
 'qpdf.zip':(4040257,'db367d897829f22c4198ce1094143c9d467bd6ee7dfabc44ba6f02056b24f8b1')}
for name,(size,digest) in pins.items():
 p=Path('.native')/name
 assert p.stat().st_size==size and hashlib.sha256(p.read_bytes()).hexdigest()==digest,name
Path('evidence/release-integrity.json').write_text(json.dumps(pins,indent=2)+'\n')
PY
python3 scripts/extract_qpdf.py .native/qpdf.zip .native/qpdf evidence/qpdf-release-members.json
chmod +x .native/xournalpp.AppImage
mkdir .native/xournal
(cd .native/xournal && ../xournalpp.AppImage --appimage-extract > ../appimage-extraction.log)
export INKSTAGES_XOURNALPP="$INK_ROOT/.native/xournal/squashfs-root/AppRun"
INKSTAGES_QPDF="$(find "$INK_ROOT/.native/qpdf" -type f -name qpdf)"
test -n "$INKSTAGES_QPDF"
test "$(printf '%s\n' "$INKSTAGES_QPDF" | wc -l)" -eq 1
chmod +x "$INKSTAGES_QPDF"
export INKSTAGES_QPDF
"$INKSTAGES_XOURNALPP" --version > evidence/xournalpp-version.txt 2>&1
"$INKSTAGES_QPDF" --version > evidence/qpdf-version.txt 2>&1

git clone --depth 1 --branch v1.3.8 https://github.com/xournalpp/xournalpp.git .native/upstream
test "$(git -C .native/upstream rev-parse HEAD)" = 938bdb8de4d32f38f48dd7f6544886722157a848
git -C .native/upstream rev-parse HEAD > evidence/native-source-commit.txt
cmake -S .native/upstream -B .native/build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DENABLE_AUDIO=OFF -DENABLE_PLUGINS=OFF \
  -DENABLE_GTK_SOURCEVIEW=OFF -DENABLE_CPPTRACE=OFF -DENABLE_GTEST=OFF \
  -DCMAKE_PROJECT_INCLUDE="$INK_ROOT/native/add-harness.cmake" \
  -DINKSTAGES_HARNESS_SOURCE="$INK_ROOT/native/fixture.cpp" \
  > evidence/native-configure.log 2>&1
cmake --build .native/build --target inkstages-fixture --parallel 2 > evidence/native-build.log 2>&1
git -C .native/upstream diff --exit-code > evidence/native-source-unmodified.txt
sha256sum .native/build/src/core/libxournalpp-core.a "$INKSTAGES_QPDF" .native/xournalpp.AppImage > evidence/native-binaries-before.sha256
find .native/qpdf -type f -print0 | sort -z | xargs -0 sha256sum >> evidence/native-binaries-before.sha256
.native/build/inkstages-fixture "$INK_ROOT/evidence/fixture" > evidence/native-author.log 2>&1
python3 scripts/native_gate.py
sha256sum --check evidence/native-binaries-before.sha256 > evidence/native-binaries-unchanged.txt
git -C .native/upstream diff --exit-code >> evidence/native-source-unmodified.txt
python3 --version > evidence/python-version.txt
pdftoppm -v 2> evidence/poppler-version.txt
printf 'Pinned source clean before and after fixture execution\n' >> evidence/native-source-unmodified.txt
