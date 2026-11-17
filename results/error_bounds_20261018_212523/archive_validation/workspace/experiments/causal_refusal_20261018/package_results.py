"""Preserve old bytes, package local sources, restore-test and checksum artifacts."""
import argparse,csv,datetime,hashlib,json,re,subprocess,sys,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.runner import write_json
from experiments.causal_refusal_20261018.runner import source_hashes


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def new_sources():
    return sorted([p for p in (ROOT/'experiments/causal_refusal_20261018').iterdir() if p.is_file()]+
                  [ROOT/'experiments/run_causal_refusal.py',ROOT/'tests/test_causal_refusal.py'])


def archive(base):
    out=base/'archive_validation';out.mkdir(exist_ok=False);start=time.perf_counter()
    originals=json.loads((base/'preservation/original_files.json').read_text())
    files={ROOT/r['path'] for r in originals if not r['path'].startswith('results/')};files.update(new_sources())
    files.update(ROOT/x for x in ('results/v015/summary.json','results/v01/results.json','results/audit_v01/audit.json',
                                'results/v02/comparison.csv','results/v02/decisions.csv'))
    snapshot=base/'source_snapshot.zip'
    with zipfile.ZipFile(snapshot,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(files):z.write(f,f.relative_to(ROOT).as_posix())
    target=(out/'workspace').resolve();target.mkdir(exist_ok=False)
    with zipfile.ZipFile(snapshot) as z:
        for name in z.namelist():
            if not (target/name).resolve().is_relative_to(target):raise ValueError('archive traversal')
        if z.testzip():raise ValueError('archive CRC failure')
        z.extractall(target)
    runs=[]
    for label,args in [('tests',['-m','unittest','discover','-s','tests','-v']),('demo',['examples/demo.py']),('affect_demo',['examples/affect_demo.py'])]:
        tick=time.perf_counter();r=subprocess.run([sys.executable,'-X','utf8',*args],cwd=target,capture_output=True,text=True,encoding='utf-8')
        log=r.stdout+r.stderr;(out/(label+'.log')).write_text(log,encoding='utf-8')
        count=re.search(r'Ran (\d+) tests',log)
        runs.append(dict(label=label,exit_code=r.returncode,seconds=time.perf_counter()-tick,tests=int(count.group(1)) if count else None))
    result=dict(archive_members=len(files),archive_sha256=sha(snapshot),crc_ok=True,runs=runs,
        elapsed_seconds=time.perf_counter()-start,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    write_json(out/'verification.json',result);print(json.dumps(result),flush=True)
    if any(x['exit_code'] for x in runs):raise RuntimeError('archive restore test failed')


def finalize(base):
    out=base/'final_integrity';out.mkdir(exist_ok=False)
    originals=json.loads((base/'preservation/original_files.json').read_text());changed=[]
    for r in originals:
        p=ROOT/r['path']
        if not p.is_file() or sha(p)!=r['sha256']:changed.append(r['path'])
    freeze=json.loads((base/'registration_v1/freeze.json').read_text());git={}
    for name,args in [('git_status',['status','--short']),('git_diff',['diff','--binary']),('git_staged',['diff','--cached','--binary']),
                      ('git_head',['rev-parse','HEAD']),('git_diff_check',['diff','--check'])]:
        r=subprocess.run(['git',*args],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        (out/(name+'.txt')).write_text(r.stdout+r.stderr,encoding='utf-8');git[name]=r.stdout
        if r.returncode:raise RuntimeError('git read-only check failed: '+name)
    equal={k:git[k].strip()==(base/'preservation'/(k+'.txt')).read_text(encoding='utf-8-sig').strip() for k in ('git_diff','git_staged','git_head')}
    before=set((base/'preservation/git_status.txt').read_text(encoding='utf-8-sig').splitlines());after=set(git['git_status'].splitlines())
    integrity=dict(original_files_checked=len(originals),original_files_changed=changed,source_freeze_equal=source_hashes()==freeze['sources'],
        git_unchanged=equal,status_added=sorted(after-before),status_removed=sorted(before-after))
    write_json(out/'verification.json',integrity)
    if changed or not integrity['source_freeze_equal'] or not all(equal.values()) or before-after:raise RuntimeError('preservation failed')
    session=json.loads((base/'session.json').read_text());now=datetime.datetime.now(datetime.timezone.utc)
    phase=json.loads((base/'report_phase.json').read_text());meta=json.loads((base/'prospective_v1/metadata.json').read_text())
    acceptance=json.loads((base/'analysis/acceptance.json').read_text());restored=json.loads((base/'archive_validation/verification.json').read_text())
    complete=dict(started_utc=session['started_utc'],completed_utc=now.isoformat(),wall_seconds=(now-datetime.datetime.fromisoformat(session['started_utc'])).total_seconds(),
        verification_reporting_seconds=(now-datetime.datetime.fromisoformat(phase['started_utc'])).total_seconds(),
        prospective_decisions=meta['decision_runs'],development_decisions=96,old_baseline_replay_decisions=640,
        old_refusal_diagnostic_decisions=132,shared_state_diagnostic_decisions=11520,cross_runtime_replay_decisions=960,
        total_recorded_decision_runs=meta['decision_runs']+96+640+132+11520+960,
        unique_tests_passed=next(x['tests'] for x in restored['runs'] if x['label']=='tests'),
        main_experiment_seconds=meta['elapsed_seconds'],model_policy_seconds=meta['policy_seconds'],
        adoption={a['variant']:dict(adopt=a['adopt'],criteria_passed=sum(x['passed'] for x in a['checks']),criteria_total=len(a['checks'])) for a in acceptance},
        existing_files_changed=0,source_files_added=len(new_sources()),
        prohibited_actions=dict(external_transmission=0,paid_api_calls=0,installations=0,commits=0,pushes=0,real_world_actions=0),
        incomplete=['Independent human annotation and external validity','Real source authentication and reliability calibration',
                    'Natural-language evidence interpretation','Many-candidate or free-form alternative generation',
                    'Combined H1+H2 effect (intentionally not run in this one-factor study)','Default model promotion/deployment'])
    write_json(base/'completion.json',complete)
    changes=['# 変更ファイルと保全','',f'開始時の既存{len(originals)}ファイルはすべてSHA256一致。既存ソース・結果・未コミット差分の内容変更0。追加ソース/設定/テスト:','']
    changes.extend('- `'+p.relative_to(ROOT).as_posix()+'`' for p in new_sources())
    changes.extend(['','新規結果は`results/causal_refusal_20261018_100656/`配下。source_snapshot.zipは旧依存コードと新規コード、および既存テストが参照する5件の結果fixtureを含む。展開先で全テストと両demoを確認。全成果物の一覧・ハッシュはartifact_manifest.csv。'])
    (base/'CHANGES.md').write_text('\n'.join(changes),encoding='utf-8')
    r=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'experiments/causal_refusal_20261018/write_report.py'),str(base)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    if r.returncode:raise RuntimeError(r.stdout+r.stderr)
    files=sorted(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ('artifact_manifest.csv','artifact_manifest.sha256'))
    with (base/'artifact_manifest.csv').open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['path','bytes','sha256']);writer.writeheader()
        for p in files:writer.writerow(dict(path=p.relative_to(base).as_posix(),bytes=p.stat().st_size,sha256=sha(p)))
    (base/'artifact_manifest.sha256').write_text(sha(base/'artifact_manifest.csv')+'  artifact_manifest.csv\n',encoding='ascii')
    print(json.dumps(complete|dict(manifest_files=len(files),manifest_bytes=sum(p.stat().st_size for p in files))),flush=True)


def verify_manifest(base):
    manifest=base/'artifact_manifest.csv'
    if sha(manifest)!=(base/'artifact_manifest.sha256').read_text().split()[0]:raise ValueError('manifest checksum mismatch')
    with manifest.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    errors=[]
    for r in rows:
        p=(base/r['path']).resolve()
        if not p.is_relative_to(base.resolve()) or not p.is_file() or sha(p)!=r['sha256']:errors.append(r['path'])
    print(json.dumps(dict(files_checked=len(rows),errors=errors)),flush=True)
    if errors:raise RuntimeError('artifact hash mismatch')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['archive','finalize','verify']);p.add_argument('base',type=Path);a=p.parse_args()
    {'archive':archive,'finalize':finalize,'verify':verify_manifest}[a.phase](a.base.resolve())
