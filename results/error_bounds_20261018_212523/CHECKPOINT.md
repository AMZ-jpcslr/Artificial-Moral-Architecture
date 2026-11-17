# 途中保存点

記録UTC: 2026-10-18T12:53:44.053042+00:00

基準281テスト、旧480判断一致、新規47テストを含む328テストと両デモ成功。開発48判断の後、registration_v1/freeze.jsonを固定。主147,456判断の生ログ生成は終了。集計の終了メタデータはこの保存点で未確認。モデル・正解・採否の変更は行わない。

既存1,110ファイルの保全はpreservation/original_files.jsonとoriginal_sources.zip。新規生ログはprospective_v1/decisions.jsonl.gz、CSVはdecisions.csv、実行ログはprospective_v1.log。完了はprospective_execution.jsonのreturncodeとmetadata.jsonで確認する。

中断時は部分出力をそのまま残し、新しい出力先で同じfreezeを指定する。既存先への追記や上書きはしない。

```powershell
python -X utf8 experiments/run_error_bounds.py --phase prospective --freeze results/error_bounds_20261018_212523/registration_v1/freeze.json --output results/error_bounds_replay_NEW_TIMESTAMP/prospective_v1
```

完了後はverify.py verify → verify.py diagnose → analyze.py → casebook.py → 別Pythonのverify.py crossとplot_results.py → source archive検証 → 報告・manifestの順。後処理も既存フォルダは拒否する。外部送信/API/インストール/commit/push禁止。
