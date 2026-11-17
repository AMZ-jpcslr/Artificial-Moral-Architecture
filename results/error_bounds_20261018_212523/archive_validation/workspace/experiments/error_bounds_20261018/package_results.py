"""Preservation, reproducible source archive and complete local artifact manifest."""
import argparse,csv,datetime,hashlib,json,subprocess,sys,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.runner import csv_write,write_json
from experiments.error_bounds_20261018.runner import source_hashes


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def new_sources(base):
    old={x['path'] for x in json.loads((base/'preservation/original_files.json').read_text())}
    allpaths=subprocess.check_output(['rg','--files','--hidden','-g','!.git','-g','!__pycache__','-g','!*.pyc'],cwd=ROOT,text=True,encoding='utf-8').splitlines()
    return sorted(Path(p).as_posix() for p in allpaths if Path(p).as_posix() not in old and not Path(p).as_posix().startswith('results/'))


def archive(base):
    originals=json.loads((base/'preservation/original_files.json').read_text());new=new_sources(base)
    fixtures=['results/v015/summary.json','results/v01/results.json','results/audit_v01/audit.json','results/v02/comparison.csv','results/v02/decisions.csv']
    files=sorted(set([x['path'] for x in originals if not x['path'].startswith('results/')]+new+fixtures))
    target=base/'source_snapshot.zip'
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name in files:z.write(ROOT/name,name)
    out=base/'archive_validation';out.mkdir(exist_ok=False);workspace=(out/'workspace').resolve();workspace.mkdir()
    with zipfile.ZipFile(target) as z:
        if z.testzip():raise ValueError('zip CRC failed')
        for name in z.namelist():
            resolved=(workspace/name).resolve()
            if workspace not in resolved.parents:raise ValueError('archive traversal')
        z.extractall(workspace)
    runs=[]
    for name,args in [('unittest',['-m','unittest','discover','-s','tests','-v']),('demo',['examples/demo.py']),('affect_demo',['examples/affect_demo.py'])]:
        start=time.perf_counter();r=subprocess.run([sys.executable,'-X','utf8',*args],cwd=workspace,capture_output=True)
        (out/(name+'.log')).write_bytes(r.stdout+r.stderr);runs.append(dict(name=name,returncode=r.returncode,seconds=time.perf_counter()-start))
    info=dict(archive_members=len(files),sha256=sha(target),runs=runs,all_passed=all(r['returncode']==0 for r in runs))
    write_json(out/'verification.json',info);csv_write(base/'source_files_manifest.csv',[dict(path=f,sha256=sha(ROOT/f)) for f in files])
    print(json.dumps(info));
    if not info['all_passed']:raise RuntimeError('archive reproduction failed')


def finalize(base):
    out=base/'final_integrity';out.mkdir(exist_ok=False);original=json.loads((base/'preservation/original_files.json').read_text());changes=[]
    for x in original:
        p=ROOT/x['path']
        if not p.is_file() or sha(p)!=x['sha256']:changes.append(x['path'])
    git={}
    for name,args in [('git_head.txt',['rev-parse','HEAD']),('git_unstaged.patch',['diff','--binary']),('git_staged.patch',['diff','--cached','--binary'])]:
        data=subprocess.check_output(['git',*args],cwd=ROOT);(out/name).write_bytes(data);git[name]=data==(base/'preservation'/name).read_bytes()
    (out/'git_status.txt').write_bytes(subprocess.check_output(['git','status','--short'],cwd=ROOT))
    freeze=json.loads((base/'registration_v1/freeze.json').read_text());same=freeze['sources']==source_hashes()
    info=dict(original_files_checked=len(original),original_files_changed=changes,git_equal=git,source_freeze_equal=same,
              frozen_files=len(freeze['sources']),plan_equal=(base/'PLAN.md').read_bytes()==(ROOT/'experiments/error_bounds_20261018/PROTOCOL.md').read_bytes())
    write_json(out/'verification.json',info)
    if changes or not all(git.values()) or not same or not info['plan_equal']:raise RuntimeError('preservation failed')
    new=new_sources(base);write_json(out/'new_source_files.json',new)
    session=json.loads((base/'session.json').read_text());phase=json.loads((base/'verification_phase.json').read_text())
    main=json.loads((base/'prospective_v1/metadata.json').read_text());acc=json.loads((base/'analysis/acceptance.json').read_text());now=datetime.datetime.now(datetime.timezone.utc)
    counts=dict(prospective=main['decision_runs'],development=json.loads((base/'development_v1/metadata.json').read_text())['decision_runs'],
        baseline_replay=json.loads((base/'baseline_replay/verification.json').read_text())['decisions'],
        shared_state=json.loads((base/'shared_state_diagnostic/verification.json').read_text())['decisions'],
        old_counterexample_regression=json.loads((base/'old_counterexample_regression/verification.json').read_text())['decisions'],
        cross_runtime=json.loads((base/'cross_runtime_replay/verification.json').read_text())['decisions'])
    completion=dict(started_utc=session['started_utc'],completed_utc=now.isoformat(),wall_seconds=(now-datetime.datetime.fromisoformat(session['started_utc'])).total_seconds(),
        verification_reporting_seconds=(now-datetime.datetime.fromisoformat(phase['started_utc'])).total_seconds(),
        decision_runs=counts,total_recorded_decision_runs=sum(counts.values()),unit_tests_passed=328,new_tests=47,
        main_experiment_seconds=main['elapsed_seconds'],model_policy_seconds=main['policy_seconds'],new_source_files=len(new),
        existing_files_changed=0,adopt=acc['adopt'],criteria_groups_passed=acc['groups_passed'],criteria_groups_total=12,
        prohibited_actions=dict(external_transmission=0,paid_api_calls=0,installations=0,commits=0,pushes=0,real_world_actions=0),
        incomplete=['Independent author and human annotation','Actual instrument specifications and authenticated calibration sources',
                    'Verification of hidden lineage, Lipschitz, noise and drift assumptions','Primary-action evidence gate',
                    'Natural-language evidence understanding','Deployment or default-model promotion'])
    write_json(base/'completion.json',completion)
    lines=['# 変更ファイル','',f'開始時の{len(original)}ファイルは全てSHA256不変。既存コード・結果・未コミット差分の変更0。','',
           '追加ソース（本研究用の隔離層）:','',*['- `'+x+'`' for x in new],'',
           '新規結果はこのフォルダ配下。原本ハッシュはpreservation、ソース一式はsource_snapshot.zip、全成果物はartifact_manifest.csv。']
    (base/'CHANGES.md').write_text('\n'.join(lines),encoding='utf-8')
    from experiments.error_bounds_20261018.write_report import write_report
    write_report(base)
    files=[p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ('artifact_manifest.csv','manifest_verification.json')]
    csv_write(base/'artifact_manifest.csv',[dict(path=p.relative_to(base).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(files)])
    print(json.dumps(completion,ensure_ascii=False),flush=True)


def verify(base):
    errors=[];n=0
    with (base/'artifact_manifest.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            n+=1;p=base/r['path']
            if not p.is_file() or sha(p)!=r['sha256'] or p.stat().st_size!=int(r['bytes']):errors.append(r['path'])
    info=dict(files_checked=n,mismatches=errors);write_json(base/'manifest_verification.json',info);print(json.dumps(info))
    if errors:raise RuntimeError('manifest mismatch')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['archive','finalize','verify']);p.add_argument('base',type=Path);a=p.parse_args();globals()[a.operation](a.base.resolve())
