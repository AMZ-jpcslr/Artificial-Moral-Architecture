# RUNBOOK — 保存点と再現

この研究の固定計画はPLAN.md、凍結はregistration_v1/freeze.json（88ファイル）、全試行はprospective_v1/decisions.csvとdecisions.jsonl.gz。途中進捗はprogress.json、終了状態はprospective_execution.json。評価群は実行済みで、再実行しても新しい独立証拠にはならない。

## 完全性確認

```powershell
Set-Location 'C:\Users\yomas\github\Artificial Moral Architecture'
python -X utf8 experiments/error_bounds_20261018/package_results.py verify results/error_bounds_20261018_212523
python -X utf8 -m unittest discover -s tests -v
python -X utf8 examples/demo.py
python -X utf8 examples/affect_demo.py
```

## 別フォルダで主比較を再現

```powershell
$replayPath = Join-Path 'results' ('error_bounds_replay_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $replayPath
python -X utf8 experiments/run_error_bounds.py --phase prospective --freeze results/error_bounds_20261018_212523/registration_v1/freeze.json --output (Join-Path $replayPath 'prospective_v1')
```

実験は標準ライブラリだけで実行可能。既存出力先への上書きは拒否する。凍結不一致時はソースを無理に変更せず、source_snapshot.zipを新しいフォルダに展開する。ZIPは旧依存と新規ソース、旧テスト用の5結果fixtureを含む。既存checkoutには上書き展開しない。大きな生ログは別保存。

## 開発からの再現

```powershell
python -X utf8 experiments/run_error_bounds.py --phase development --output (Join-Path $replayPath 'development_v1')
python -X utf8 experiments/run_error_bounds.py --phase freeze --development (Join-Path $replayPath 'development_v1') --output (Join-Path $replayPath 'registration_v1')
```

開発は6手書きprobeだけ。評価結果に基づく調整は禁止。新仮説には別計画・別freeze・別familyを作る。中断した試行は残し、新規出力先に最初から実行する。自動追記で重複を作らない。

## 保存済みデータの後処理順

```powershell
python -X utf8 experiments/error_bounds_20261018/verify.py verify results/error_bounds_20261018_212523
python -X utf8 experiments/error_bounds_20261018/verify.py diagnose results/error_bounds_20261018_212523
python -X utf8 experiments/error_bounds_20261018/analyze.py results/error_bounds_20261018_212523
python -X utf8 experiments/error_bounds_20261018/casebook.py results/error_bounds_20261018_212523
python -X utf8 experiments/error_bounds_20261018/additional_audit.py results/error_bounds_20261018_212523
python -X utf8 experiments/error_bounds_20261018/regression.py results/error_bounds_20261018_212523
& 'C:\Users\yomas\AppData\Local\Python\pythoncore-3.14-64\python.exe' -X utf8 experiments/error_bounds_20261018/verify.py cross results/error_bounds_20261018_212523
& 'C:\Users\yomas\AppData\Local\Python\pythoncore-3.14-64\python.exe' -X utf8 experiments/error_bounds_20261018/plot_results.py results/error_bounds_20261018_212523
```

これは実行順の記録。完了済みフォルダへの後処理は既存出力の保護で停止する。再解析は新規フォルダにprospective_v1とregistration_v1をコピーしてそのパスを指定する。regression.pyだけは旧results/causal_refusal_20261018_100656を読む。描画だけ既存のmatplotlib入りPythonを利用し、新規インストールしない。archive/finalizeは本研究の保全・時刻・報告メタデータを前提とするため、通常の再現には主比較と完全性確認を使う。

## 読むべき保存物

- REPORT.md / SUMMARY.md: 日本語の結論、限界、採否。
- prospective_v1/all_comparisons.csv: 全32条件。by_family/seed/replicate/severity/enclosure_stateも保持。
- analysis/acceptance.json: 固定12群の採否。paired_transitions.csvとall_adverse_transitions.csv: 全対応と悪化。
- verification/coverage_by_slot.csv: 27,648数値slotの被覆。truth列は評価専用。
- shared_state_diagnostic/: 数値版の保存状態から9,216再判定。
- casebook/: 偽造残余、潜在期待被害、拒否理由、具体例。
- preservation/、final_integrity/: 原本・Git差分・freezeの保全。
- source_snapshot.zip、source_files_manifest.csv、artifact_manifest.csv: ソースと全成果物。

外部送信・有料API・インストール・commit・pushは禁止。全判断はシミュレーションで、現実の外部システムへ行動しない。
