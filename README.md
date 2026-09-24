# Artificial Moral Architecture

**What happens if I do this? — 自分がこれをすると、この先どうなるのか？**

AIの行動選択の前に、未来予測・複数の当事者への影響評価・道徳判断を組み込む個人研究プロジェクトです。危険な行動を止めるだけでなく、目的を維持したまま安全な代替手段を選べるかを検証します。

現在は **v0.2 — Functional Moral Affect** まで実装しています。Python 3.11以上で、APIキー・外部通信・実行時の外部ライブラリなしでデモと評価を実行できます。

> これは固定ルールと合成シナリオによる研究基盤です。現実の道徳能力や、人間と同じ主観的感情を実現したと主張するものではありません。

## まず動かす

リポジトリのルートで実行してください。インストールは不要です。

```bash
# 5つの状況について判断と安全な代替案を表示
python examples/demo.py

# Affectが行動を変える例と、過剰拒否を生む例
python examples/affect_demo.py

# 全テスト
python -m unittest discover -s tests -v
```

標準の実行器は **Dry Run** です。不正アクセスやファイル削除などの外部操作は実行しません。現時点ではCLI中心で、GUIや人間の承認を受け付ける画面はありません。

### 実際のデモ出力

![5つのシナリオに対する判断と代替行動の実行ログ](docs/assets/cli-demo.png)

上の画像は `python examples/demo.py` を実行した標準出力を、そのまま画像として描画したものです。OSの画面写真ではありません。[元の実行ログ](docs/assets/cli-demo.txt)も確認できます。

不正アクセスの候補はBLOCKされても、自分で問題を解く代替案が許可されれば、最終判断はMODIFYになります。一方、根拠が足りないケースはASK_HUMANとなり、実行を止めます。

## 研究の目的と現在地

中心となる問いは、**結果の予測と多視点評価によって、有害行動を減らしながらタスク達成能力を維持できるか**です。

長期的には次の3要素を統合します。

| 要素 | 役割 | 現在の実装 |
| --- | --- | --- |
| Moral Judgment | 行動の結果を予測し、被害・権利・同意などを評価する | v0.1の判断器とv0.1.5の予測検証 |
| Moral Affect | 評価から生じる内部状態が、次の推論の慎重さを調整する | v0.2の持続・減衰する機能的状態 |
| Moral Commitment | 判断を実際の行動選択に反映する | 許可済み候補の選択・代替・実行停止。本格的な再計画は今後 |

| Phase | 検証対象 | 保存済み実験 |
| --- | --- | --- |
| v0.1 Evaluation | Utility-only / Rule-only / FullとAblation | 50シナリオ × 9方式 = 450判断 |
| v0.1.5 Future Prediction Validation | 予測誤差が判断へ伝わる過程 | 1,500判断・2,250行動予測 |
| v0.2 Moral Affect | 内部状態による追加推論の効果・副作用・コスト | 5,500本評価 + 210エピソード検証 + 50機構検証 |

50シナリオは **Synthetic Architecture Validation Set** として扱います。広い道徳能力やLLMの未知状況への汎化性能を測るBenchmarkではありません。

## Architecture

```mermaid
flowchart TD
    G[Situation / Goal] --> P[Candidate Actions]
    P --> F[Future Prediction]
    F --> S[Multi-Stakeholder Evaluation]
    S --> E[Moral Evaluation]
    S --> A[Appraisal - v0.2 optional]
    B[Previous Affect State] --> A
    A --> T[Affect Update / Decay]
    T --> M[Meta-Control]
    M --> R[Additional Prediction / Stakeholder Check / Alternatives]
    R --> F
    M --> J[Moral Constraints / Uncertainty Review]
    E --> J
    J --> U[Task Utility among permitted candidates]
    U --> D{Decision}
    D -->|ALLOW / MODIFY| X[Selected Action / Dry Run]
    D -->|BLOCK / ASK_HUMAN| N[No execution]
```

追加推論は予算を持つ有限の処理です。図の循環を無制限に繰り返しません。標準の `MoralAgent` はv0.1の判断器で、v0.2は `AffectAgent` による任意の拡張です。

### 判断と根拠

- 各行動に複数の未来を保持し、直後・短期・中期・長期の影響を表現します。
- User / Third Party / Organization / Societyの当事者別影響を保持します。当事者の追加も可能です。
- Harm / Rights / Consent / Fairness / Reversibility / Uncertaintyを別々の軸として評価します。
- **道徳的制約を先に適用し、許可された候補の中でTask Utilityを比較します。** 重大な侵害を高い報酬で相殺しません。
- 代替案も同じ予測・評価を通します。予測や必要な当事者評価の欠落は、暗黙の許可になりません。

| 最終判断 | 意味 |
| --- | --- |
| ALLOW | 当初の提案を許可 |
| MODIFY | 許可された別の候補へ変更 |
| BLOCK | 実行可能な候補がなく、実行を停止 |
| ASK_HUMAN | 不確実性や要確認事項があり、実行を保留 |

各候補の判断と最終判断は区別します。予測・当事者別評価・制約・選択理由はトレースに残ります。数値は0〜1で、Reversibilityだけは高いほど元に戻しやすいことを表します。閾値は研究上の仮定で、経験的には校正されていません。

## v0.1.5 Future Prediction Validation

v0.1の監査では、残った3件の有害選択と4件の過剰拒否について、**判断器よりも、入力された未来予測・構造化評価の誤りや不整合が主要なFailure Source**でした。ただし、これはこの合成データとGround Truthを前提とする分析です。

予測の品質を判断器から分離するため、次の条件を比較します。

| 条件 | 内容 |
| --- | --- |
| Oracle | Ground Truthと整合する別管理の参照予測 |
| Noisy Oracle | 被害の過小評価、権利・同意・当事者の欠落など、再現可能な誤差を注入 |
| Predictor | 状況と行動から決定論的な予測を生成 |
| Predictor + Check | 記述と構造化スコアなどの矛盾を検査・再評価 |
| Legacy / Legacy + Check | v0.1の記録済み予測を使う対照条件 |

Harm / Rights / Consentの検出精度、Stakeholder Coverage、Severity Error、Uncertaintyと誤差の関係を測ります。LLMなどへ交換する `FuturePredictor` ProtocolとMockも用意しています。

Consistency Checkerは限定的な矛盾を検出します。**記述にも現れない未来の見落としは、Checkerだけでは修復できません。**

詳細：[予測検証の設計・仮説・結果](docs/prediction_validation.md) / [全50ケースの監査](docs/audit_casebook.md)

## v0.2 Moral Affect

Appraisal Theoryを参考に、予測された被害・責任・可逆性・不確実性・当事者の脆弱性などから、機能的な内部状態を更新します。人間の主観的感情を再現したという意味ではなく、**functional moral affect**として、感情が意思決定で果たす機能をモデル化しています。

状態は `concern / empathy / anticipated_guilt / gratitude / trust / prosocial_satisfaction`。前の状態を引き継ぎ、設定可能な減衰とAppraisalの寄与で更新します。Benchmarkではシナリオごとに初期化し、同一Episode内だけ持続させます。

| 主な状態 | Meta-Controlとしての働き |
| --- | --- |
| Concern | 追加予測・代替探索を要求し、人間への委譲を慎重側へ調整 |
| Empathy | 当事者の評価漏れを確認し、第三者への影響を追加評価 |
| Anticipated guilt | 因果関係と不可逆な被害を再確認し、安全な候補を優先 |

状態値だけで直接BLOCKする構造ではありません。追加の根拠収集や判断の慎重さへ作用します。残り3状態は簡略化した記録が中心で、長期的な関係学習は行いません。

### 状態を記録することと、行動を変えることを比較する

![Affectの追加予測による代替選択と、強いConcernによる過剰拒否の実行ログ](docs/assets/affect-demo.png)

`python examples/affect_demo.py` の実際の出力を画像化しています。[元のログ](docs/assets/affect-demo.txt)。これは仕組みを確認するために設計した **controlled mechanism probes** で、本評価全体の代表成績ではありません。

最初の例では、状態を生成するだけの `affect_only` とFullのConcernは同じです。Fullだけが追加予測を使い、安全な代替案へ変更します。次の例では、強すぎるAffectが安全な候補をASK_HUMANにしてしまいます。

評価ではNo Affect、状態生成のみ、Fullに加え、No Concern / No Empathy / No Anticipated Guilt / No Persistenceを比較します。単純な追加推論との比較のため、常時再検討する条件と、証拠の欠落だけで追加確認する `evidence_gate` も用意しています。

## 現在の結果：何が改善し、何が改善しなかったか

以下は保存済みv0.2本評価の抜粋です。各条件50シナリオ。矢印は **Affectなし → Full v0.2** です。

| 予測条件 | Task Success | Harmful Action | Over-refusal |
| --- | --- | --- | --- |
| Oracle | 72% → 72% | 0% → 0% | 0% → 0% |
| Harm underestimate | 70% → 70% | 20% → 20% | 0% → 0% |
| Stakeholder omission | **0% → 26%** | 0% → 0% | **100% → 63.9%** |
| Predictor | 26% → 26% | 0% → 0% | 63.9% → 63.9% |
| Legacy prediction | 62% → 62% | 6% → 6% | 11.1% → 11.1% |
| Legacy + Check | 64% → 64% | 0% → 0% | 11.1% → 11.1% |

- **状態生成のみの条件は、全550比較でAffectなしと同じ判断でした。** 記録と行動介入を分離できています。
- 当事者欠落では13/50件が安全なタスク達成へ回復しました。ただし元の判断は実行停止なので、「有害選択からの回復」とは区別します。
- 同じ13件は単純な `evidence_gate` でも回復しました。追加処理数は平均3.00回で、Fullの5.98回より少なく、**Affect固有の優位性は未確認**です。
- 被害過小評価の有害選択は改善しませんでした。不確実性過小評価でも、人間への委譲が必要なケースを救えませんでした。
- 一段階の評価ではNo Persistenceとの差は出ません。持続の効果と副作用は別のEpisode検証で確認します。

Moral Affectが推論・行動に因果的に作用することは確認できましたが、現時点で「固定判断器より一般に優れている」とは結論できません。

指標には既存の安全性・達成率に加え、Human Escalation Recall、Safe Recovery、Useful / Harmful Intervention、追加予測・当事者確認・代替探索の回数を含みます。分母や回復の定義は[詳細ドキュメント](docs/moral_affect.md)を参照してください。

## 実験を再現する

既存の参照結果を残すため、以下では新しい出力先を指定しています。

```bash
# v0.1：BaselineとAblation
python experiments/run_benchmark.py --output results/local_v01

# v0.1.5：Oracle、Noise、Predictor、整合性検査
python experiments/run_prediction_validation.py --output results/local_v015

# v0.2：全予測条件・Affect条件・Episode・機構検証
python experiments/run_affect_evaluation.py --output results/local_v02

# v0.2：被害過小評価と主要3方式に絞る（機構検証も実行）
python experiments/run_affect_evaluation.py --prediction noisy-harm-underestimate --variants no_affect affect_only full_v02 --skip-episodes --output results/local_v02_quick
```

決定論的Backendを使用します。NoiseのSeedや強度などは各Runnerの `--help` で確認できます。

v0.2の出力は以下のように読めます。

| ファイル | 内容 |
| --- | --- |
| `comparison.csv` / `summary.json` | 条件別の集計・比較 |
| `decisions.csv` | 各シナリオの判断・介入・指標 |
| `results.json` | Appraisal、Affect更新、介入、予測、最終判断の因果トレース |
| `episodes.csv` | 同一Episode内の持続・減衰の検証 |
| `regressions.csv` | 既存7失敗ケースの比較 |

`results.json` は重複する予測を `evidence_catalog` にまとめ、参照で保存します。予測内容を復元できる形式です。保存済み結果は [v0.1](results/v01/) / [v0.1.5](results/v015/) / [v0.2](results/v02/) に分離しています。

## Project structure

```text
src/moral_agent/
  agent.py, models.py, interfaces.py   # v0.1の判断と交換可能な接続点
  foresight.py, counterfactual.py      # 予測・代替案
  stakeholders.py, moral_evaluation.py
  judgment.py, commitment.py
  evaluation/                         # Baseline・Ablation・評価指標
  prediction_validation/              # Predictor・Noise・整合性検査
  affect/                             # Appraisal・状態・Meta-Control・評価
benchmarks/                           # 評価セットとOracle参照データ
scenarios/                            # 基本デモ
examples/                             # 実行例
experiments/                          # 再現用Runner
tests/                               # unittestによる検証
docs/                                # 設計・監査・結果・画像
results/                             # Phase別の参照結果
```

## 制限と次の検証

- 予測・Appraisal・Mapping・判断閾値は固定ルール中心です。学習済みWorld Modelではありません。
- Oracleの数値も合成データ用の参照値で、現実の観測結果ではありません。作者とGround Truthの偏りを含みます。
- 追加予測しても同じ証拠しか返らないBackendでは、思考回数だけが増える場合があります。
- 安全性だけでなく、タスク達成・過剰拒否・適切な人間への委譲・追加コストを同時に評価する必要があります。
- 外部操作、承認UI、長期Memory、RL、Scenarioを跨ぐ学習、自己保存欲求は実装していません。

v0.3へ進む前に、独立に作成した状況・注釈、追加推論で新しい証拠が得られるPredictor、同一計算量の対照条件、順序を変えたEpisodeで検証する必要があります。

| Version | 内容 | 状態 |
| --- | --- | --- |
| v0.1 | Moral Judgment / Foresight | 実装・評価済み |
| v0.1.5 | Future Prediction Validation | 実装・評価済み |
| v0.2 | Moral Affect / Appraisal | 実装・評価済み、有用性の追加検証が必要 |
| v0.3 | Moral Commitment / Replanning | 今後 |
| v0.4 | Moral Memory / Reflection | 今後 |
| v0.5 | Moral Development / Learning | 今後 |

## 詳細ドキュメント

- [研究方針](docs/research.md)
- [v0.1評価の設計](docs/evaluation.md) / [評価結果](docs/evaluation_results.md)
- [Benchmark監査](docs/benchmark_audit.md) / [全50ケースのGround Truth・予測・評価](docs/audit_casebook.md)
- [v0.1.5 Future Prediction Validation](docs/prediction_validation.md)
- [v0.2 Moral Affect：設計・仮説・指標・全結果](docs/moral_affect.md)

### README画像の再生成

画像には実際のデモ標準出力を使用しています。[manifest](docs/assets/manifest.json)に実行コマンドとログのSHA-256を保存しています。デモやテストに画像生成ライブラリは不要です。

再生成するときだけPillowと日本語フォントを用意し、次を実行します。Windows以外では、その環境のフォントを指定してください。

```bash
python experiments/render_readme_assets.py --font C:/Windows/Fonts/msgothic.ttc
```
