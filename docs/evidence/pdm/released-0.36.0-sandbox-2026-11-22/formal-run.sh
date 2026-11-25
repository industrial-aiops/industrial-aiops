set -eu
R=/home/wei/workspace/release036-20261122
C=$(docker ps --filter label=com.docker.compose.service=iaiops --format '{{.Names}}')
test -n "$C"
mkdir -p "$R/evidence"
test "$(docker inspect "$C" --format '{{.State.Health.Status}}')" = healthy
docker inspect "$C" --format '{{.Image}} {{.Config.User}} readonly={{.HostConfig.ReadonlyRootfs}}' > "$R/evidence/runtime.txt"
docker inspect "$C" --format '{{json .State}}' > "$R/evidence/container-state.json"
docker image inspect ghcr.io/industrial-aiops/iaiops:0.36.0-factory --format '{{json .RepoDigests}}' > "$R/evidence/runtime-repo-digests.json"
docker exec "$C" python -c 'import os,inspect,importlib.metadata;from iaiops.core.evaluation import pdm,feedback,bundle;assert importlib.metadata.version("iaiops")=="0.36.0";assert not os.environ.get("PYTHONPATH");assert not os.path.exists("/tmp/candidate");assert all("/site-packages/" in inspect.getfile(m) for m in (pdm,feedback,bundle));print("installed",importlib.metadata.version("iaiops"),inspect.getfile(pdm),inspect.getfile(feedback),"no overlay")' > "$R/evidence/installed-package.txt"
docker exec -i "$C" sh -c 'cat > /tmp/expected-module-hashes.json' < "$R/wheel-module-hashes.json"
docker exec "$C" python -c 'import pathlib,hashlib,json,iaiops;root=pathlib.Path(iaiops.__file__).parent.parent;names=json.loads(pathlib.Path("/tmp/expected-module-hashes.json").read_text());print(json.dumps({n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in names},indent=2))' > "$R/evidence/installed-module-hashes.json"
cmp "$R/wheel-module-hashes.json" "$R/evidence/installed-module-hashes.json"
tar -cf - -C "$R/data" . | docker exec -i "$C" sh -c 'mkdir -p /tmp/pdm036-input; tar -xf - -C /tmp/pdm036-input'
docker exec "$C" sh -c 'umask 077; exec python /tmp/pdm036-input/run_demo.py --out-dir /tmp/pdm036-result' > "$R/evidence/scenario.log" 2>&1
docker exec "$C" sh -c 'umask 077; exec python /tmp/pdm036-input/pdm036-extra-harness.py' > "$R/evidence/extended-scenario.log" 2>&1
docker exec "$C" tar -cf - -C /tmp/pdm036-result evaluation.zip pending.zip confirmed.zip inconclusive.zip false-positive.zip revised-policy.zip complete-summary.json pending.json confirmed.json > "$R/result.tar"
tar -xf "$R/result.tar" -C "$R/evidence"
python3 - <<'PY'
import json,pathlib,hashlib,zipfile,urllib.request,urllib.error
r=pathlib.Path('/home/wei/workspace/release036-20261122');e=r/'evidence'
summary=json.loads((e/'complete-summary.json').read_text())
for case in ('evaluation','pending','confirmed','inconclusive','false-positive','revised-policy'):
 with zipfile.ZipFile(e/(case+'.zip')) as z:
  m=json.loads(z.read('manifest.json'));assert m['package_version']=='0.36.0'
  assert all(hashlib.sha256(z.read(n)).hexdigest()==v['sha256'] for n,v in m['files'].items())
url='http://127.0.0.1:8000/mcp'
try: urllib.request.urlopen(urllib.request.Request(url,data=b'{}',headers={'Content-Type':'application/json'}))
except urllib.error.HTTPError as error: summary['unauthenticated_http']=error.code
assert summary['unauthenticated_http']==401
secrets=dict(line.split('=',1) for line in (r/'test.env').read_text().splitlines())
body=json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'formal036-reference','version':'1'}}}).encode()
request=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream','Authorization':'Bearer '+secrets['IAIOPS_MCP_TOKEN']})
with urllib.request.urlopen(request) as response: summary['authenticated_initialize_http']=response.status
assert summary['authenticated_initialize_http']==200
(e/'verified-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({'states':{k:summary[k] for k in ('pending','confirmed','inconclusive','false-positive')},'refusals':summary['refusals'],'http':[summary['unauthenticated_http'],summary['authenticated_initialize_http']]},indent=2))
PY
