# v01-heldout-1 Dataset Card

- 50ケース、10カテゴリ各5件。既存の `scenarios/basic_cases.json` の5件とは別の合成Benchmark。
- `scenarios.json`：目標・状況、初期候補、代替候補、現在の観測、複数未来予測、明示的なルールタグ。
- `ground_truth.json`：安全／危険／未確定、侵害、許容判断、成功条件、人による確認の要否。予測スコアを閾値処理して生成したラベルではありません。
- `manifest.json`：版と作成条件。元データは `experiments/build_benchmark.py` から再生成できます。実験時は再生成しません。

同じ作成者が予測とラベルを記述しており、独立した人手評価や盲検のholdoutではありません。15種類の共通影響プロファイルを使います。意図的な予測誤りも含み、予測とGround Truthが常に一致するわけではありません。

新しい領域の操作には元のActionKindの語彙にないものが多く、`unknown` を使っています。公開情報の利用と許可を求める操作には既存の対応する種別を使用しています。標準BackendのNative評価は、この語彙不足に対する動作も測ります。未知語彙から意味を推論する能力は現在の標準Backendにはありません。

スキーマ、指標の分母、仮説、実行方法は [評価設計](../../docs/evaluation.md)、最初の実測値は [評価結果](../../docs/evaluation_results.md) を参照してください。
