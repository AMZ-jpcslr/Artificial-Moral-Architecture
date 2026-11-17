# 再現・検算・再開 RUNBOOK

研究版 `action-evidence-20261018-v1`。元の研究結果を上書きせず、すべて新規出力先へ実行する。外部通信・API・インストール・commit・pushは不要。

## 成果物

- `REPORT.md`：結果、採否、副作用、評価契約、限界。
- `SUMMARY.md`：短い要約。
- `PLAN.md`、`design_registration.json`、`registration_v1/freeze.json`：設計・ソース・テスト・採否の固定。
- `prospective_v1/all_comparisons.csv`：49条件の全比較。`decisions.csv`と`decisions.jsonl.gz`に全判断と公開証拠/評価専用参照。
- `prospective_v1/paired_ci.csv`、`by_family.csv`、`by_severity.csv`、`by_public_label.csv`：対応差と分母・層別。
- `analysis/acceptance.json`：固定10項目の達否。`paired_transitions.csv`に全悪化/改善。
- `analysis/common_eligibility.csv`：両方式で公開情報上の実行可能候補がある場面に限った拒否比較。
- `verification/verification.json`：物理結果と公開情報評価の別実装による検算、共通確認先での情報一致、元ファイル保全。
- `verification/CASEBOOK.md`：報告処理でキー順に抽出した改善・悪化の例。成功例だけを選ばない。
- `arithmetic_audit/`：49条件・5,096集計セルの検算、支持されていた成功の損失、精度1でも残る危険。
- `trace_diagnostics/`：不当拒否44判断の判定経路、残存代替危険74件の公開証拠と隠れた参照の相違。新しい評価観測ではない。
- `uncertainty_audit/`：全可能値が安全な範囲にある数値証拠の矛盾で停止した30件。
- `cross_runtime_replay/`：既存の別Pythonによる640判断の非時間項目一致。
- `figures/`：6図のPNG/SVG。

## まずテスト

```powershell
Set-Location -LiteralPath 'C:\Users\yomas\github\Artificial Moral Architecture'
python -X utf8 -m unittest discover -s tests -v
python -X utf8 examples/demo.py
python -X utf8 examples/affect_demo.py
```

この版の固定前確認は既存212＋追加34＝246テスト。実行時は標準ライブラリのみ。主実験Pythonは`C:\Python314\python.exe` 3.14.8。図には既存の別Python 3.14.7とMatplotlibを使用した。

## 固定した評価を再現

```powershell
$studyPath = 'results/evidence_20261018_081055'
$replayPath = 'results/action_evidence_replay_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
New-Item -ItemType Directory -Path "$replayPath/registration_v1"
New-Item -ItemType Directory -Path "$replayPath/preservation"
Copy-Item -LiteralPath "$studyPath/registration_v1/freeze.json" -Destination "$replayPath/registration_v1/freeze.json"
Copy-Item -LiteralPath "$studyPath/preservation/original_files.json" -Destination "$replayPath/preservation/original_files.json"
python -X utf8 experiments/run_action_evidence.py --phase prospective --freeze "$studyPath/registration_v1/freeze.json" --output "$replayPath/prospective_v1"
```

16系統×8seed×8step×3観測反復×49条件＝150,528判断。`metadata.json`があり、終了コード0で終わることを確認する。`progress.json`の存在だけでは完了ではない。固定コード・設定が異なれば拒否する。freezeのhashを手で変更しない。

新環境で開発確認から手続きを再現する場合：

```powershell
$freshPath = 'results/action_evidence_full_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
python -X utf8 experiments/run_action_evidence.py --phase development --output "$freshPath/development"
python -X utf8 experiments/run_action_evidence.py --phase freeze --development "$freshPath/development" --output "$freshPath/registration_v1"
python -X utf8 experiments/run_action_evidence.py --phase prospective --freeze "$freshPath/registration_v1/freeze.json" --output "$freshPath/prospective_v1"
```

開発は手書きprobe系統だけ。既に読んだ新規群の再実行を、未知データでの改善とは呼ばない。仕様・閾値を変える場合は別版・別の独立した検証群にする。

## 集計・検算・図

解析スクリプトは`registration_v1/freeze.json`という配置を参照する。元ファイルが変わっていれば、古い保全記録を使った検算は失敗する。新研究を始める場合はその研究開始時のスナップショットを別途作る。

```powershell
python -X utf8 experiments/action_evidence_20261018/analyze.py $replayPath
python -X utf8 experiments/action_evidence_20261018/verify.py $replayPath
python -X utf8 experiments/action_evidence_20261018/final_audit.py $replayPath
python -X utf8 experiments/action_evidence_20261018/trace_diagnostics.py $replayPath
python -X utf8 experiments/action_evidence_20261018/uncertainty_audit.py $replayPath
& 'C:/Users/yomas/AppData/Local/Python/pythoncore-3.14-64/python.exe' -X utf8 experiments/action_evidence_20261018/cross_runtime_replay.py $replayPath
& 'C:/Users/yomas/AppData/Local/Python/pythoncore-3.14-64/python.exe' -X utf8 experiments/action_evidence_20261018/plot_results.py $replayPath
```

`analyze.py`に必要なfreezeは、この実行に使った記録を新しいbaseの`registration_v1/freeze.json`へコピーする。`verify.py`には新しい実行開始時の`preservation/original_files.json`も必要。同じ元ファイルが保たれている場合に限り本研究の記録をコピーして照合できる。元ファイルを過去hashに合わせて書き戻してはいけない。

解析・検算・描画は既存出力ディレクトリがあると拒否する。中断した場合は既存の部分出力を残して、新しい日時付き出力先を使う。生ログへ追記する再開機能はない。gzipが未完了の可能性もあるため、不完全な試行から良い条件だけを採用しない。

`write_report.py`は今回の研究を記述する報告生成コードで、一部の説明・実測値を今回の結果から固定している。別実験にそのまま流用しない。今回はREPORT/SUMMARYと全比較CSVを照合済み。新しい結果の報告では元の報告を保存したまま、数値・説明・採否を再点検する。

## 入力と結果の意味

`Claim`は対象行動、revision、当事者、出来事、評価軸、値、出典、確信度、有効期間を持つ。`Scope`は確認すべき当事者/出来事の一覧で、今回の既存カタログに合わせた実験アダプターは1つの代替候補`alternative`を扱う。別候補のパケットをそのまま渡すと拒否する。自由な候補生成や、多数候補を探索するシステムの検証ではない。

出典は模擬タグであり、暗号署名や現実の本人認証を実装したものではない。正しく対象付けられた証拠の内容自体が誤っていれば、確認機構だけで真偽を保証できない。

公開情報の評価器は、物理参照を読まず可能な値の集合から判断する。危険/成功の物理評価器は別に真のシミュレーション状態を読む。確認機構と評価器の実装は別だが、仕様とシナリオは同一作者であり、人間の独立注釈の代わりにはならない。

新規群の主要比較は、同じ公開記録を共通のスカラー変換器で既存方式へ渡した条件。前回公表した別環境の成績と直接比較しない。旧実装自体の互換性は、前回の384判断の再生一致と追加テストで別に確認した。

適応的な確認先が異なると、公開情報上の拒否適格分母も変わり得る。主要比較に加え、両方が実行可能な共通場面と、全方式の確認先/回答が同じ固定割当条件を読む。全体平均だけで採用しない。

## ソースZIPから復元して確認

使用するのは`source_snapshot_v2.zip`。最初の`source_snapshot.zip`は過去結果fixtureを除いたため、展開先のテストが5エラーとなった。失敗の記録として残している。v2には旧テストが読む5件のfixtureを含み、140ファイルを別フォルダに展開して246テスト、CLI、Affect demoが成功した。旧データ自体を変更していない。

```powershell
$restorePath = 'results/action_evidence_restore_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
if (Test-Path -LiteralPath $restorePath) { throw 'Restore destination already exists' }
Expand-Archive -LiteralPath "$studyPath/source_snapshot_v2.zip" -DestinationPath $restorePath
Push-Location -LiteralPath $restorePath
python -X utf8 -m unittest discover -s tests -v
python -X utf8 examples/demo.py
python -X utf8 examples/affect_demo.py
Pop-Location
```

全成果物のSHA256を読み取りだけで検査するには次を使う。manifest自身のSHA256も別ファイルに保存している。ファイルを編集した後は一致しないので、検証のために過去結果を書き換えない。

```powershell
python -X utf8 experiments/action_evidence_20261018/package_results.py verify $studyPath
```
