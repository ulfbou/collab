#!/usr/bin/env bash
set -Eeuo pipefail
H=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."&&pwd -P);T=$(mktemp -d);trap 'rm -rf "$T"' EXIT;cp "$H/collab-evidence.py" "$T/";cp -R "$H/collab" "$T/";cd "$T";git init -q;git config user.name T;git config user.email t@x;git remote add origin https://github.com/example/evidence.git;printf 'ok\n'>a.txt;printf '\0x'>binary.bin;printf '\377\376'>nonutf.bin;python3 - <<'PY'
from pathlib import Path
Path('large.txt').write_text('x'*100)
PY
git add .;git commit -qm init;mkdir out mock
cat >mock/gh <<'SH'
#!/usr/bin/env bash
exit 1
SH
chmod +x mock/gh;COLLAB_GH_BIN=$PWD/mock/gh python3 collab-evidence.py export-json --out-dir out;python3 - <<'PY'
import json
x=json.load(open('out/github-evidence.json'));assert x['available'] is False;assert all(v=='unavailable' for v in x['queryStatus'].values())
PY
cat >mock/gh <<'SH'
#!/usr/bin/env bash
[[ $1 == auth ]]&&exit 0
[[ $1 == pr ]]&&{ echo failed >&2;exit 1; }
printf '[]\n'
SH
chmod +x mock/gh;COLLAB_GH_BIN=$PWD/mock/gh python3 collab-evidence.py export-json --out-dir out --include a.txt --include binary.bin --include nonutf.bin --include large.txt --include missing --max-bytes 10
python3 - <<'PY'
import json
x=json.load(open('out/github-evidence.json'));assert x['available'];assert x['queryStatus']['openIssues']=='ok';assert x['queryStatus']['openPullRequests']=='failed';assert 'openIssues' in x['data'] and 'openPullRequests' not in x['data']
f=json.load(open('out/repository-facts.json'))['selectedFiles'];d={x['path']:x for x in f};assert d['missing']['status']=='missing';assert d['large.txt']['reason']=='oversized';assert d['binary.bin']['reason']=='binary';assert d['nonutf.bin']['reason']=='non-utf8';assert [x['path'] for x in f]==sorted(x['path'] for x in f)
PY
printf sentinel>out/target;ln -s target out/link;! python3 collab-evidence.py render-context --out out/link >/dev/null 2>&1;[[ $(cat out/target)==sentinel ]];! find out -name '*.tmp.*'|grep -q .;echo 'PASS: collector-tests'
