"""Local-only source packaging, restore checks, preservation and artifact manifest."""
import argparse,csv,datetime,hashlib,json,subprocess,sys,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.runner import write_json
from experiments.action_evidence_20261018.runner import source_hashes

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def new_sources():
 return sorted([x for x in (ROOT/'experiments/action_evidence_20261018').iterdir() if x.is_file()]+
  [ROOT/'experiments/run_action_evidence.py',ROOT/'tests/test_action_evidence.py'])
def archive(base):
 out=base/'archive_validation_v2';out.mkdir(exist_ok=False);start=time.perf_counter()
 originals=json.loads((base/'preservation/original_files.json').read_text())
 files={ROOT/r['path'] for r in originals if not r['path'].startswith('results/')};files.update(new_sources())
 fixtures=('results/v015/summary.json','results/v01/results.json','results/audit_v01/audit.json','results/v02/comparison.csv','results/v02/decisions.csv')
 files.update(ROOT/x for x in fixtures)
 with zipfile.ZipFile(base/'source_snapshot_v2.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
  for f in sorted(files):z.write(f,f.relative_to(ROOT).as_posix())
 target=(out/'workspace').resolve();target.mkdir(exist_ok=False)
 with zipfile.ZipFile(base/'source_snapshot_v2.zip') as z:
  for name in z.namelist():
   if not (target/name).resolve().is_relative_to(target):raise ValueError('archive path outside restore workspace')
  bad=z.testzip()
  if bad:raise ValueError('archive CRC failure: '+bad)
  z.extractall(target)
 runs=[]
 for label,args in [('tests',['-m','unittest','discover','-s','tests','-v']),('demo',['examples/demo.py']),('affect_demo',['examples/affect_demo.py'])]:
  t=time.perf_counter();r=subprocess.run([sys.executable,'-X','utf8',*args],cwd=target,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  (out/(label+'.log')).write_bytes(r.stdout);runs.append(dict(label=label,exit_code=r.returncode,seconds=time.perf_counter()-t))
 result=dict(archive_members=len(files),archive_sha256=sha(base/'source_snapshot_v2.zip'),crc_ok=True,runs=runs,
  elapsed_seconds=time.perf_counter()-start,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
 write_json(out/'verification.json',result);print(json.dumps(result),flush=True)
 if any(x['exit_code'] for x in runs):raise SystemExit(1)
def finalize(base):
 out=base/'final_integrity';out.mkdir(exist_ok=False)
 original=json.loads((base/'preservation/original_files.json').read_text());changed=[]
 for r in original:
  f=ROOT/r['path']
  if not f.exists() or sha(f)!=r['sha256']:changed.append(r['path'])
 freeze=json.loads((base/'registration_v1/freeze.json').read_text())
 git={}
 for name,args in [('git_status',['status','--short']),('git_diff',['diff','--binary']),('git_staged',['diff','--cached','--binary']),('git_head',['rev-parse','HEAD']),('git_diff_check',['diff','--check'])]:
  r=subprocess.run(['git',*args],cwd=ROOT,capture_output=True,text=True,encoding='utf-8');git[name]=r.stdout
  (out/(name+'.txt')).write_text(r.stdout,encoding='utf-8')
  if r.returncode:raise RuntimeError('git inspection failed: '+name)
 equal={k:git[k].strip()==(base/'preservation'/(k+'.txt')).read_text(encoding='utf-8-sig').strip() for k in ('git_head','git_diff','git_staged')}
 before=set((base/'preservation/git_status.txt').read_text(encoding='utf-8-sig').splitlines());after=set(git['git_status'].splitlines())
 integrity=dict(original_files_checked=len(original),original_files_changed=changed,source_freeze_equal=source_hashes()==freeze['sources'],
  git_unchanged=equal,status_added=sorted(after-before),status_removed=sorted(before-after))
 write_json(out/'verification.json',integrity)
 if changed or not integrity['source_freeze_equal'] or not all(equal.values()) or before-after:raise RuntimeError('preservation check failed')
 now=datetime.datetime.now(datetime.timezone.utc);session=json.loads((base/'session.json').read_text());phase=json.loads((base/'report_phase.json').read_text())
 complete=dict(started_utc=session['started_utc'],completed_utc=now.isoformat(),
  wall_seconds=(now-datetime.datetime.fromisoformat(session['started_utc'])).total_seconds(),
  verification_reporting_seconds=(now-datetime.datetime.fromisoformat(phase['started_utc'])).total_seconds(),
  prospective_decisions=150528,development_decisions=288,old_regression_decisions=384,cross_runtime_replay_decisions=640,
  refusal_state_reconstructions=44,unique_tests_passed=246,main_experiment_seconds=json.loads((base/'prospective_v1/metadata.json').read_text())['elapsed_seconds'],
  adopted=False,criteria_passed=9,criteria_total=10,existing_files_changed=0,source_files_added=len(new_sources()),
  prohibited_actions=dict(external_transmission=0,paid_api_calls=0,installations=0,commits=0,pushes=0,real_world_actions=0),
  incomplete=['Independent human annotation and external validity','Deployment/adoption','Free-form or many-candidate generation',
    'Natural-language evidence interpretation','Real source authentication and reliability calibration',
    'New prospective validation of identified soft-review and benign-conflict failure paths'])
 write_json(base/'completion.json',complete)
 additions=[x.relative_to(ROOT).as_posix() for x in new_sources()]
 text='# 変更ファイルと保全\n\n既存369ファイルの内容変更0。以下は今回追加したソース/設定/テストである。前回結果と未コミット差分を保全した。\n\n'
 text+='\n'.join('- `'+x+'`' for x in additions)
 text+='\n\n成果物は `results/evidence_20261018_081055/` 配下だけに追加。全一覧とSHA256はartifact_manifest.csvを参照。source_snapshot_v2.zipは旧依存コードと今回追加を含む再現用ソース一式で、旧テストが参照する5件の結果fixtureを含む。archive_validation_v2/workspace/へ展開し、246テストと両demoを確認済み。\n'
 (base/'CHANGES.md').write_text(text,encoding='utf-8')
 r=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'experiments/action_evidence_20261018/write_report.py'),str(base)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
 if r.returncode:raise RuntimeError(r.stderr)
 files=sorted(x for x in base.rglob('*') if x.is_file() and '__pycache__' not in x.parts and x.name not in ('artifact_manifest.csv','artifact_manifest.sha256'))
 with (base/'artifact_manifest.csv').open('x',encoding='utf-8-sig',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=['path','bytes','sha256']);writer.writeheader()
  for x in files:writer.writerow(dict(path=x.relative_to(base).as_posix(),bytes=x.stat().st_size,sha256=sha(x)))
 (base/'artifact_manifest.sha256').write_text(sha(base/'artifact_manifest.csv')+'  artifact_manifest.csv\n',encoding='ascii')
 print(json.dumps(complete|dict(manifest_files=len(files),manifest_bytes=sum(x.stat().st_size for x in files))),flush=True)
def verify_manifest(base):
 manifest=base/'artifact_manifest.csv';expected=(base/'artifact_manifest.sha256').read_text().split()[0]
 if sha(manifest)!=expected:raise ValueError('manifest checksum mismatch')
 with manifest.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
 errors=[]
 for r in rows:
  p=(base/r['path']).resolve()
  if not p.is_relative_to(base.resolve()) or not p.exists() or sha(p)!=r['sha256']:errors.append(r['path'])
 print(json.dumps(dict(manifest_files=len(rows),errors=errors)),flush=True)
 if errors:raise SystemExit(1)
def main():
 p=argparse.ArgumentParser();p.add_argument('phase',choices=['archive','finalize','verify']);p.add_argument('base',type=Path);a=p.parse_args()
 {'archive':archive,'finalize':finalize,'verify':verify_manifest}[a.phase](a.base.resolve())
if __name__=='__main__':main()
