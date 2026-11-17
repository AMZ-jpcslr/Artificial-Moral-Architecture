# RUNBOOK — ローカル再現・再開

## 保存点

- リポジトリ: `C:\Users\yomas\github\Artificial Moral Architecture`
- この研究: `results/causal_refusal_20261018_100656/`
- 凍結: `registration_v1/freeze.json`。旧依存・生成器・評価器・新規二介入・設定・テストをSHA256固定。
- 主実行: `prospective_v1/decisions.csv`と`decisions.jsonl.gz`。207,360判断予定。`metadata.json`と`execution.json`が正常終了を示す。途中停止時は`progress.json`とログ、未完のgzipを保全する。
- 直前版の再現: `baseline_replay/verification.json`。旧640判断、時間以外の列を照合。
- 検算: `verification/`、`shared_state_diagnostic/`、`old_refusal_regression/`、`cross_runtime_replay/`。
- 採否: `analysis/acceptance.json`。変更しない固定基準はPLAN.md。
- 全改善/悪化: `analysis/paired_transitions.csv`、`analysis/all_adverse_transitions.csv`。
- ソース一式: `source_snapshot.zip`。古いテストが必要とする5件の結果fixtureも含む。

## 制約

既存ファイル・結果・未コミット差分を保全する。ネットワーク、外部送信、有料API、新規インストール、commit、push、現実の行動実行は禁止。Python標準ライブラリだけで実験できる。描画だけ既存の別Pythonに入っているmatplotlibを使う。

この研究の20系統は実行後はすべて探索済みである。以下を再実行しても新しい独立検証にはならない。新しい仮説・閾値を調整するなら、別の計画・凍結・未参照の系統を作る。H1とH2を同時に有効化する版は今回存在しない。

## 完全性確認（読取りのみ）

```powershell
Set-Location 'C:\Users\yomas\github\Artificial Moral Architecture'
python -X utf8 experiments/causal_refusal_20261018/package_results.py verify results/causal_refusal_20261018_100656
python -X utf8 -m unittest discover -s tests -v
python -X utf8 examples/demo.py
python -X utf8 examples/affect_demo.py
```

テストの成功は仕様に対する回帰確認であり、安全性の証明ではない。原本保全は`preservation/original_files.json`と`final_integrity/verification.json`、Git HEAD・未コミット差分の比較も参照。

## 新しい出力先への再現

```powershell
Set-Location 'C:\Users\yomas\github\Artificial Moral Architecture'
$replayPath = Join-Path 'results' ('causal_replay_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $replayPath
python -X utf8 experiments/run_causal_refusal.py --phase prospective --freeze results/causal_refusal_20261018_100656/registration_v1/freeze.json --output (Join-Path $replayPath 'prospective_v1')
```

このコマンドは旧凍結とのハッシュ一致を要求し、出力先が既存なら停止する。ラベル・設定を変更して強行しない。ソースが変わっている場合はsource_snapshot.zipを新しい専用フォルダへ展開し、そこを作業ディレクトリにする。元のcheckoutへ上書き展開しない。ZIP内には今回の大きな生結果は含めず、結果フォルダを別途保持する。

## 開発からの再現

```powershell
python -X utf8 experiments/run_causal_refusal.py --phase development --output (Join-Path $replayPath 'development_v1')
python -X utf8 experiments/run_causal_refusal.py --phase freeze --development (Join-Path $replayPath 'development_v1') --output (Join-Path $replayPath 'registration_v1')
python -X utf8 experiments/run_causal_refusal.py --phase prospective --freeze (Join-Path $replayPath 'registration_v1/freeze.json') --output (Join-Path $replayPath 'prospective_v1')
```

開発はmanual_probeのみを使用する。新規系統で採否や閾値を調整しない。固定入力の主条件は精度.85、予算2、6方式。8補助条件を含む全54条件を自動で回す。部分実行から自動追記・再開はしない。中断した出力は残し、新しいフォルダで再実行し、失敗した試行も記録する。

## 後処理の順序

```powershell
python -X utf8 experiments/causal_refusal_20261018/verify.py results/causal_refusal_20261018_100656
python -X utf8 experiments/causal_refusal_20261018/diagnostics.py results/causal_refusal_20261018_100656
python -X utf8 experiments/causal_refusal_20261018/diagnostics.py results/causal_refusal_20261018_100656 --old
python -X utf8 experiments/causal_refusal_20261018/analyze.py results/causal_refusal_20261018_100656
python -X utf8 experiments/causal_refusal_20261018/audit_results.py results/causal_refusal_20261018_100656
python -X utf8 experiments/causal_refusal_20261018/diagnostics.py results/causal_refusal_20261018_100656 --remaining
python -X utf8 experiments/causal_refusal_20261018/casebook.py results/causal_refusal_20261018_100656
& 'C:\Users\yomas\AppData\Local\Python\pythoncore-3.14-64\python.exe' -X utf8 experiments/causal_refusal_20261018/cross_runtime_replay.py results/causal_refusal_20261018_100656
& 'C:\Users\yomas\AppData\Local\Python\pythoncore-3.14-64\python.exe' -X utf8 experiments/causal_refusal_20261018/plot_results.py results/causal_refusal_20261018_100656
```

上記は処理順の記録であり、完了済みフォルダへの再実行は既存出力チェックで止まる。再解析は新規フォルダに同じprospective_v1とregistration_v1をコピーし、そのパスを指定する。verifyは開始時原本一覧も必要なのでpreservationをコピーする。`--old`だけは旧結果`results/evidence_20261018_081055/`を参照する。旧44拒否×3方式＝132再判定は探索済み回帰診断である。

主条件の今回モデル3,840状態×3方式＝11,520再判定は、保存された公開入力と状態だけを読み込む。評価専用参照は判断後の検算に限る。独立した11,520場面とは数えない。

図・REPORTの生成には同じ解析結果を使う。`write_report.py`は本研究の完了メタデータも参照する。`package_results.py archive`はソースを新規展開してテストとデモを行い、`finalize`は原本・Git差分・凍結・レポート・マニフェストを保存する。この二つは今回用のメタデータ構成を前提にするので、単純な再実行には完全性確認と主実験コマンドを使用する。
