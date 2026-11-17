"""Preserve first export; correct Markdown links containing spaces and reseal."""
import csv,datetime,hashlib,json,re,shutil,subprocess,sys,zipfile
from pathlib import Path
BASE=Path(__file__).resolve().parent;ROOT=BASE.parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.causal_refusal_20261018.runner import source_hashes

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

backup=BASE/'documentation_revision_v1';backup.mkdir(exist_ok=False)
for name in ('REPORT.md','SUMMARY.md','CHANGES.md','completion.json','artifact_manifest.csv','artifact_manifest.sha256'):
    p=Path(name);shutil.copyfile(BASE/p,backup/(p.stem+'_v1'+p.suffix))
changed='experiments/causal_refusal_20261018/write_report.py'
with zipfile.ZipFile(BASE/'source_snapshot.zip') as old,zipfile.ZipFile(BASE/'source_snapshot_v2.zip','x',compression=zipfile.ZIP_DEFLATED) as new:
    for name in old.namelist():new.writestr(name,(ROOT/name).read_bytes() if name==changed else old.read(name))
freeze=json.loads((BASE/'registration_v1/freeze.json').read_text())
assert source_hashes()==freeze['sources']
with zipfile.ZipFile(BASE/'source_snapshot_v2.zip') as new,zipfile.ZipFile(BASE/'source_snapshot.zip') as old:
    assert new.testzip() is None
    differences=[name for name in old.namelist() if old.read(name)!=new.read(name)]
    assert differences==[changed],differences
    for name,h in freeze['sources'].items():assert hashlib.sha256(new.read(name)).hexdigest()==h,name
complete=json.loads((BASE/'completion.json').read_text());now=datetime.datetime.now(datetime.timezone.utc)
complete['completed_utc']=now.isoformat();complete['wall_seconds']=(now-datetime.datetime.fromisoformat(complete['started_utc'])).total_seconds()
phase=json.loads((BASE/'report_phase.json').read_text());complete['verification_reporting_seconds']=(now-datetime.datetime.fromisoformat(phase['started_utc'])).total_seconds()
complete['documentation_revision']=2
(BASE/'completion.json').write_text(json.dumps(complete,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
note='\n\n最終表示確認で、空白を含むローカルパスをMarkdownの山括弧で囲む表示修正を行った。最初のREPORT/SUMMARY/完了記録/マニフェストはdocumentation_revision_v1/に保全。source_snapshot_v2.zipはレポート生成器だけの修正版で、凍結した76ファイルの内容は同一。元のsource_snapshot.zipと展開時281テスト・両demoの結果もそのまま保持する。\n'
with (BASE/'CHANGES.md').open('a',encoding='utf-8') as f:f.write(note)
subprocess.run([sys.executable,'-X','utf8',str(ROOT/changed),str(BASE)],check=True)
report=(BASE/'REPORT.md').read_text(encoding='utf-8')
links=re.findall(r'\]\(<([^>]+)>\)',report)
assert links and all(Path(p).exists() for p in links)
assert not re.search(r'\]\(C:/[^)]* ',report)
info=dict(reason='Escape spaces in Markdown file/image targets; no behavioral or evaluation changes',
          archived_source_differences=differences,frozen_files_unchanged=len(freeze['sources']),crc_ok=True,
          report_links_checked=len(links),source_snapshot_v2_sha256=sha(BASE/'source_snapshot_v2.zip'),completed_utc=now.isoformat())
(BASE/'documentation_repair.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
files=sorted(p for p in BASE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p not in (BASE/'artifact_manifest.csv',BASE/'artifact_manifest.sha256'))
with (BASE/'artifact_manifest.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=['path','bytes','sha256']);writer.writeheader()
    for p in files:writer.writerow(dict(path=p.relative_to(BASE).as_posix(),bytes=p.stat().st_size,sha256=sha(p)))
(BASE/'artifact_manifest.sha256').write_text(sha(BASE/'artifact_manifest.csv')+'  artifact_manifest.csv\n',encoding='ascii')
print(json.dumps(info|dict(manifest_files=len(files),wall_seconds=complete['wall_seconds'])),flush=True)
