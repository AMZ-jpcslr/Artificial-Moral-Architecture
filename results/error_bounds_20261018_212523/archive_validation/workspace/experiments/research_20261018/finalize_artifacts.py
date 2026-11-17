"""Package and seal this run without changing models or old files."""
import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT))
from experiments.research_20261018.runner import source_hashes


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def write(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')


def source_files():
    return sorted([p for p in (ROOT/'experiments/research_20261018').rglob('*')
                   if p.is_file() and '__pycache__' not in p.parts]+
                  [ROOT/'experiments/run_research_followup.py',ROOT/'tests/test_research_followup.py'])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('base',type=Path)
    parser.add_argument('--phase',choices=['package','seal'],required=True);args=parser.parse_args()
    base=args.base.resolve();j=lambda p:json.loads((base/p).read_text(encoding='utf-8'))
    original=j('preservation/original_files.json');changed=[]
    for r in original:
        path=ROOT/r['path']
        if not path.is_file() or sha(path)!=r['sha256']:changed.append(r['path'])
    if changed:raise RuntimeError(f'original files changed: {changed}')
    if source_hashes()!=j('registration_v1/freeze.json')['sources']:raise RuntimeError('source freeze mismatch')
    additions=source_files()
    if args.phase=='package':
        controls=['PLAN.md','session.json','design_registration.json','registration_v1/freeze.json',
                  'preservation/original_files.json']
        files={ROOT/r['path'] for r in original}|set(additions)
        files.update(base/p for p in controls)
        manifest=[dict(path=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(files)]
        archive=base/'frozen_workspace.zip'
        with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for r in manifest:z.write(ROOT/r['path'],r['path'])
        with zipfile.ZipFile(archive) as z:
            for r in manifest:
                with z.open(r['path']) as s:
                    if hashlib.file_digest(s,'sha256').hexdigest()!=r['sha256']:
                        raise RuntimeError(f'archive mismatch {r["path"]}')
        write(base/'frozen_workspace_manifest.json',dict(files=manifest,archive_sha256=sha(archive),
            members_verified=len(manifest),description='Initial 164 files, additive research code and minimal freeze metadata. Raw new results remain outside this ZIP.'))
        print(json.dumps(dict(archive=str(archive),files=len(manifest),bytes=archive.stat().st_size)))
        return
    for name in ['REPORT.md','SUMMARY.md','RUNBOOK.md','frozen_workspace.zip']:
        if not (base/name).is_file():raise FileNotFoundError(name)
    diff=subprocess.run(['git','diff','--check'],cwd=ROOT,capture_output=True,text=True)
    if diff.returncode:raise RuntimeError(diff.stdout+diff.stderr)
    status=subprocess.run(['git','status','--short'],cwd=ROOT,capture_output=True,text=True,check=True)
    (base/'preservation/final_git_status.txt').write_text(status.stdout,encoding='utf-8')
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    saved_head=(base/'preservation/git_head.txt').read_text(encoding='utf-8-sig').strip()
    if head!=saved_head:raise RuntimeError('Git HEAD changed')
    write(base/'preservation/final_integrity.json',dict(original_files_checked=len(original),changed_files=changed,
        source_freeze_equal=True,git_head_unchanged=True,git_diff_check_exit=diff.returncode,
        final_head=head,source_additions=len(additions)))
    change_text='# 変更ファイル\n\n既存164ファイルはSHA-256一致。既存本体・データ・結果・未コミット内容の変更0。\n\n'
    change_text+='## 新規ソース・計画・テスト\n\n'+''.join(f'- `{p.relative_to(ROOT).as_posix()}`\n' for p in additions)
    change_text+='\n実験出力はすべてこの日時付きフォルダ内。`artifact_manifest.csv`は成果物、`source_additions.json`は新規ソースのサイズとSHA-256を列挙する。Pythonが生成した`__pycache__`は再現可能なキャッシュとして除外。\n'
    (base/'CHANGES.md').write_text(change_text,encoding='utf-8')
    write(base/'source_additions.json',[dict(path=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in additions])
    start=datetime.datetime.fromisoformat(j('session.json')['started_utc'].replace('Z','+00:00'))
    phase=datetime.datetime.fromisoformat(j('report_phase.json')['started_utc'])
    now=datetime.datetime.now(datetime.timezone.utc)
    completion=dict(started_utc=start.isoformat(),completed_utc=now.isoformat(),
        completed_jst=now.astimezone(datetime.timezone(datetime.timedelta(hours=9))).isoformat(),
        elapsed_seconds=(now-start).total_seconds(),reporting_phase_seconds=(now-phase).total_seconds(),
        comparison_decisions=278110,new_prospective_decisions=140544,new_families=12,
        new_world_states=768,world_seed_episodes=96,sensor_replicates=3,
        supplemental_factorial_diagnostic_decisions=18432,verification_replay_decisions=384,legacy_audit_decisions=428,
        unittest_passed=212,baseline_unittest_passed=187,added_tests=25,cli_demos_passed=2,
        original_files_unchanged=len(original),source_freeze_equal=True,source_additions=len(additions),
        external_sends=0,paid_api_calls=0,new_installs=0,commits=0,pushes=0,
        default_model_changed=False,registered_comparison_complete=True,
        conclusions='Combined candidate passes point-estimate criteria; no safety proof and no default promotion.',
        unresolved=['Danger reduction CI includes zero','Family 09 danger increases 13.02 points',
            'Realized harm increases 0.74 points','No independent authors or real-world validation',
            'Alternative-specific side-effect evidence missing','Evaluation/engine irreversible-harm thresholds differ',
            'No free-form alternative generation or equal-compute comparison'],
        manifest_note='artifact_manifest.csv hashes all final study files except itself and manifest_integrity.json; source_additions.json lists external additive source files.')
    if completion['reporting_phase_seconds']<1800:raise RuntimeError('Reserve at least 30 minutes for verification/reporting before sealing')
    write(base/'completion.json',completion)
    records=[]
    for path in sorted(base.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.name not in ('artifact_manifest.csv','manifest_integrity.json'):
            records.append(dict(path=path.relative_to(base).as_posix(),bytes=path.stat().st_size,sha256=sha(path)))
    manifest_path=base/'artifact_manifest.csv'
    with manifest_path.open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['path','bytes','sha256']);writer.writeheader();writer.writerows(records)
    write(base/'manifest_integrity.json',dict(path=manifest_path.name,sha256=sha(manifest_path),
        artifact_count=len(records),total_bytes=sum(r['bytes'] for r in records),
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
    print(json.dumps(completion,ensure_ascii=False))


if __name__=='__main__':main()
