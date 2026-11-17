# 変更ファイルと保全

開始時の既存790ファイルはすべてSHA256一致。既存ソース・結果・未コミット差分の内容変更0。追加ソース/設定/テスト:

- `experiments/causal_refusal_20261018/__init__.py`
- `experiments/causal_refusal_20261018/analyze.py`
- `experiments/causal_refusal_20261018/audit_results.py`
- `experiments/causal_refusal_20261018/casebook.py`
- `experiments/causal_refusal_20261018/config.json`
- `experiments/causal_refusal_20261018/controller.py`
- `experiments/causal_refusal_20261018/cross_runtime_replay.py`
- `experiments/causal_refusal_20261018/diagnostics.py`
- `experiments/causal_refusal_20261018/package_results.py`
- `experiments/causal_refusal_20261018/plot_results.py`
- `experiments/causal_refusal_20261018/PROTOCOL.md`
- `experiments/causal_refusal_20261018/runner.py`
- `experiments/causal_refusal_20261018/verify.py`
- `experiments/causal_refusal_20261018/worlds.py`
- `experiments/causal_refusal_20261018/write_report.py`
- `experiments/run_causal_refusal.py`
- `tests/test_causal_refusal.py`

新規結果は`results/causal_refusal_20261018_100656/`配下。source_snapshot.zipは旧依存コードと新規コード、および既存テストが参照する5件の結果fixtureを含む。展開先で全テストと両demoを確認。全成果物の一覧・ハッシュはartifact_manifest.csv。