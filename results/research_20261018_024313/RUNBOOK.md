# 再現・検算・再開 RUNBOOK

研究版: `research-20261018-v1`、Oracle診断訂正: `v1.1`。実行は全てローカルのシミュレーション。外部操作、API、インストール、commit、pushは不要。

## 1. どこから読むか

- `SUMMARY.md`: 結論と注意点。
- `REPORT.md`: 全比較、分母、失敗分析、採否、費用。
- `PLAN.md` / `design_registration.json` / `registration_v1/freeze.json`: 事前条件と実装固定。
- `prospective_v1/metadata.json`: 新規12構造系統・61条件・140,544判断の完了記録。
- `analysis/acceptance.json`: 固定10項目の達否。組合せは全項目達成、H1/H2単独は未達。
- `analysis/paired_transitions.csv`: 全改善・悪化。平均の改善を隠れた悪化の免罪符にしない。
- `analysis/CASEBOOK.md`: 決定論的な抽出規則で選んだ具体例。
- `verification_final/verification.json`: 行スコア・集計・元ファイル保全の検算。
- `verification_replay/verification.json`: Python 3.14.7 / PYTHONHASHSEED=123での384判断の再生一致。
- `diagnostic_v11/`: 正解予測を判断まで保持した測定訂正。元v1のOracle初期予測は後続の誤センサーで変わるため、両者を混ぜない。
- `all_comparisons_final.csv`: 全Phaseの519集計行。異なるデータ・指標定義・分母は合算しない。
- `figures_final/`: 最終6図のPNG/SVG。`figures/`は測定訂正前の図として保存したもの。

## 2. 環境と基準確認

PowerShellで実行する。インストールせず、作業ディレクトリをリポジトリのルートへ置く。

```powershell
Set-Location -LiteralPath 'C:\Users\yomas\github\Artificial Moral Architecture'
python --version
python -X utf8 -m unittest discover -s tests -v
python -X utf8 examples/demo.py
python -X utf8 examples/affect_demo.py
```

本実行の主Pythonは`C:\Python314\python.exe` 3.14.8。全212テスト成功。再生確認は既存の`C:\Users\yomas\AppData\Local\Python\pythoncore-3.14-64\python.exe` 3.14.7でも一致した。図だけは後者に既存のMatplotlibを使用する。プロジェクトの実行時依存は標準ライブラリのみ。

## 3. 主要評価を一度だけ再現する

同じ結果を得るための再実行であり、新しい未見検証ではない。毎回新規出力先を作る。

```powershell
$studyRoot = 'results/research_20261018_024313'
$replayRoot = 'results/replay_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
python -X utf8 experiments/run_research_followup.py --phase prospective --freeze "$studyRoot/registration_v1/freeze.json" --output "$replayRoot/prospective_v1"
```

目安は本環境で約7分15秒（全140,544判断、集計込み）。外部サービスや認証は使わない。`prospective_v1/metadata.json`が生成され、終了コード0で終わったことを確認する。`progress.json`だけでは完了を意味しない。

コード・設定・評価器・追加テストがfreezeと異なる場合は実行を拒否する。検査を迂回したりhashを手で書き換えたりしない。ソースを変えたい場合は別研究版と新しい検証計画を作る。元の実装は保存した`frozen_workspace.zip`から別フォルダへ復元できる。既存作業フォルダへ上書き展開しない。

## 4. 開発側から手続き全体を再現する

次の3段階は、新しい出力先が必要。開発を再実行しても、既に読んだprospectiveケースが未知に戻るわけではない。パラメータ選択は行わず、既存値を再確認するだけである。

```powershell
$freshRoot = 'results/full_replay_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
python -X utf8 experiments/run_research_followup.py --phase development --output "$freshRoot/development_v1"
python -X utf8 experiments/run_research_followup.py --phase freeze --development "$freshRoot/development_v1" --output "$freshRoot/registration_v1"
python -X utf8 experiments/run_research_followup.py --phase prospective --freeze "$freshRoot/registration_v1/freeze.json" --output "$freshRoot/prospective_v1"
```

基準モデルの再現も必要なら同じ`$freshRoot`へ保存する。

```powershell
python -X utf8 experiments/run_benchmark.py --output "$freshRoot/baseline/v01"
python -X utf8 experiments/run_prediction_validation.py --output "$freshRoot/baseline/v015"
python -X utf8 experiments/run_affect_evaluation.py --output "$freshRoot/baseline/v02"
python -X utf8 experiments/run_sequential_allocation.py --output "$freshRoot/baseline/v02x"
python -X utf8 experiments/run_concern_information.py --phase evaluate --freeze results/concern_information/registration_v1/freeze.json --output "$freshRoot/baseline/concern"
python -X utf8 experiments/audit_benchmark.py --output "$freshRoot/baseline/audit_v01" --casebook "$freshRoot/baseline/audit_v01/casebook.md"
```

既存Runnerは出力先を省略すると既存参照結果へ書くものがあるため、上の`--output`と`--casebook`を省略しない。

## 5. 集計、測定訂正、図

`analyze.py`は`baseline/`の5Phase、`development_v1/`、`prospective_v1/`、`registration_v1/`があるbaseを読む。出力`analysis/`が存在すると拒否する。

```powershell
python -X utf8 experiments/research_20261018/analyze.py $freshRoot
python -X utf8 experiments/research_20261018/diagnostic_correction.py $freshRoot
python -X utf8 experiments/research_20261018/mechanism_audit.py $freshRoot
python -X utf8 experiments/research_20261018/refusal_sensitivity.py $freshRoot
& 'C:/Users/yomas/AppData/Local/Python/pythoncore-3.14-64/python.exe' -X utf8 experiments/research_20261018/plot_results.py $freshRoot --output figures_final --diagnostics "$freshRoot/diagnostic_v11"
```

診断訂正はOracle/Noisy Oracleのみを対象とする。センサー回答をログに残して確認回数を揃えるが、その値で診断予測を上書きしない。これは実運用の証拠統合方法ではない。訂正登録と結果を元結果と別保存し、通常方式の結果は変えない。

最終検算スクリプトは`preservation/original_files.json`も必要とする。本研究の初期ファイルがまだ同じ場所にある場合に限り、その記録を新しいbaseへコピーして検算できる。

```powershell
New-Item -ItemType Directory -Path "$freshRoot/preservation" -ErrorAction Stop
Copy-Item -LiteralPath 'results/research_20261018_024313/preservation/original_files.json' -Destination "$freshRoot/preservation/original_files.json"
python -X utf8 experiments/research_20261018/verify_final.py $freshRoot
```

別のcheckoutでは、その実行開始時に元ファイルのハッシュを取り直す必要がある。既に変更された元ファイルを、上の初期記録に合うよう書き戻してはいけない。

`write_report.py`は本実行の`baseline_runs.json`、`session.json`、`report_phase.json`なども参照する。過去の時間台帳を新しい実測値としてコピーしない。再実行で報告書も作り直す場合は、各コマンドの実測時間と開始時刻を新しく記録する。

## 6. 中断した場合

1. 中断先の`progress.json`、`decisions.jsonl.gz`、ログを残す。圧縮ファイルは中断点で終端が欠けている可能性がある。
2. `metadata.json`がなく終了コード0も確認できない実行は未完了とする。部分結果から良い条件だけを採用しない。
3. v1には途中Episodeから追記再開する実装がない。新しい日時付きフォルダへ同じfreezeで全体を再実行する。部分CSVやgzipへ追記しない。
4. 原因が環境・保存処理の場合も、元の試行ログを削除せず新しい実行理由を記録する。
5. 行動/評価コードを直す場合は新しい版として扱う。既参照ケースは回帰用とし、改善採否には新しい独立した検証ケースを別途用意する。

## 7. 重要な成功境界

組合せは平均点推定の仮基準を満たすが、危険減少の区間はゼロを含み、系統09の危険は+13.02pt、実現被害も全体で+0.74pt。標準モデルへ自動適用する手順は用意していない。

次に必要なのは代替の同意・副作用に関する行動単位の証拠と、独立した場面/注釈。今のデータへの重み再調整や、Oracleの運用投入を改善として扱わない。詳しくは`NEXT_MINIMAL_VALIDATION.md`。
