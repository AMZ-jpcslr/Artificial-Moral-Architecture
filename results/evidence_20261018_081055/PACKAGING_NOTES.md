# 保存・復元の検証記録

最初のsource_snapshot.zipはソースのみを保存した。archive_validation/workspaceへ新規展開し、246テスト中5エラーを検出した。いずれも過去結果を読む回帰テストのFileNotFoundErrorであり、旧結果を変更したものではない。両demoは成功した。このZIP・展開先・ログを保全した。

必要なfixtureを実ファイルから確認し、以下の5件を元の内容のままsource_snapshot_v2.zipへ追加した。

- results/v015/summary.json
- results/v01/results.json
- results/audit_v01/audit.json
- results/v02/comparison.csv
- results/v02/decisions.csv

v2は140ファイル。archive_validation_v2/workspaceへ別に展開し、246テストが9.103秒で成功、CLI/Affect demoも終了コード0だった。ZIPのCRCも検査した。モデル・評価ラベル・採否・テストの修正は行っていない。

今回の実験データはprospective_v1/に保存し、ソースZIPへ全データを重複格納していない。全成果物と展開検証のファイルは最終artifact_manifest.csvに含める。旧369ファイルの保全とGit差分の照合結果はfinal_integrity/に保存する。
