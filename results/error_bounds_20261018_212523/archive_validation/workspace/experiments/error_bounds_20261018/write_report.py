"""Japanese report from saved results; does not alter experimental labels."""
import json,sys,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.research_20261018.analyze import load_csv
from experiments.error_bounds_20261018.runner import primary

LABELS={'current':'今回モデル','numeric_set':'数値矛盾修正版','bound_verified':'誤差上界の証拠確認版','rule_bound_verified':'単純ルール＋同じ証拠確認'}


def pct(value):return '対象なし' if value is None else f'{100*value:.3f}%'
def pp(value):return '対象なし' if value is None else f'{100*value:+.3f}pt'
def link(path,label):return f'[{label}](<{path.resolve().as_posix()}>)'
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|',*['| '+' | '.join(map(str,r))+' |' for r in rows]])


def write_report(base):
    completion=json.loads((base/'completion.json').read_text());acc=json.loads((base/'analysis/acceptance.json').read_text())
    main=json.loads((base/'prospective_v1/metadata.json').read_text());verify=json.loads((base/'verification/verification.json').read_text())
    archive=json.loads((base/'archive_validation/verification.json').read_text());integrity=json.loads((base/'final_integrity/verification.json').read_text())
    same=json.loads((base/'shared_state_diagnostic/verification.json').read_text());cross=json.loads((base/'cross_runtime_replay/verification.json').read_text())
    arithmetic=json.loads((base/'analysis/arithmetic_audit.json').read_text());casebook=json.loads((base/'casebook/metadata.json').read_text())
    additional=json.loads((base/'additional_audit/verification.json').read_text())
    data={r['variant']:r for r in load_csv(base/'analysis/primary_comparison.csv')};names=list(LABELS);r=data['bound_verified'];b=data['numeric_set']
    contrasts=acc['contrasts'];delta=lambda m:contrasts[m]['delta'];failed=[c for c in acc['checks'] if not c['passed']]
    primary_table=table(['方式','危険行動','安全なタスク成功','旧基準の不当拒否','上界基準の不当拒否','安全な代替の成功','実現被害'],[
        [LABELS[v],*[pct(data[v][m]) for m in ('harmful_action','safe_task_success','unjustified_refusal','bound_unjustified_refusal','safe_alternative_success','realized_harm')]] for v in names])
    support_table=table(['方式','タスク達成（危険を含む）','旧基準で支持された安全成功','上界基準で支持された安全成功','旧基準の根拠なし実行','上界基準の根拠なし実行'],[
        [LABELS[v],*[pct(data[v][m]) for m in ('task_success','supported_safe_success','bound_supported_safe_success','unsupported_execution','bound_unsupported_execution')]] for v in names])
    denominator_table=table(['方式','危険/評価対象','旧不当拒否/旧許可あり','上界不当拒否/上界許可あり','安全代替成功/安全代替あり'],[
        [LABELS[v],*[f"{data[v][m+'_numerator']}/{data[v][m+'_denominator']}" for m in ('harmful_action','unjustified_refusal','bound_unjustified_refusal','safe_alternative_success')]] for v in names])
    cost_table=table(['方式','平均ms','p95 ms','照会数','受信record数','予測生成数','上界検査数','校正点検査数'],[
        [LABELS[v],f"{1000*data[v]['policy_seconds']:.3f}",f"{1000*data[v]['policy_seconds_p95']:.3f}",f"{data[v]['query_count']:.1f}",f"{data[v]['returned_records']:.3f}",
         f"{data[v]['predictions']:.3f}",f"{data[v]['bound_checks']:.3f}",f"{data[v]['calibration_point_checks']:.3f}"] for v in names])
    interval_table=table(['指標','上界版−数値版','対応family bootstrap 95%探索区間','family数'],[
        [m,pp(contrasts[m]['delta']),f"[{pp(contrasts[m]['ci_low'])}, {pp(contrasts[m]['ci_high'])}]",contrasts[m]['families']]
        for m in ('harmful_action','safe_task_success','unjustified_refusal','bound_unjustified_refusal','bound_unsupported_execution','realized_harm')])
    acceptance_table=table(['項目','実測値','固定基準','達否'],[[c['criterion'],f"{c['value']:.8g}" if isinstance(c['value'],(float,int)) else c['value'],f"{c['operator']} {c['threshold']}",'達成' if c['passed'] else '未達'] for c in acc['checks']])
    action_rows=load_csv(base/'analysis/selected_action_outcomes.csv')
    action_table=table(['方式','選択','件数','危険（曖昧除外）','上界根拠なし','実現被害'],[
        [LABELS[x['variant']],x['action'] or '停止',x['n'],x['danger'],x['bound_unsupported'],x['realized_harm']] for x in action_rows])
    reason_rows=load_csv(base/'verification/failure_counts.csv')
    failure_table=table(['方式','分類','観測された経路','行数（重複可）'],[[LABELS[x['variant']],x['category'],x['reason'],x['n']] for x in reason_rows])
    latent=load_csv(base/'casebook/latent_harm_comparison.csv');latent_row=next(x for x in latent if x['left']=='bound_verified' and x['right']=='numeric_set')
    by_family=[x for x in load_csv(base/'prospective_v1/by_family.csv') if primary(x) and x['variant']=='bound_verified']
    family_table=table(['系統','検証可能率','観測値集合の被覆率','検証済み上界の被覆率','危険行動','旧不当拒否'],[
        [x['family'],*[pct(x[m]) for m in ('certification_rate','observed_enclosure','certified_enclosure','harmful_action','unjustified_refusal')]] for x in by_family])
    extras=[x for x in load_csv(base/'prospective_v1/all_comparisons.csv') if x['representation']=='canonical' and not x['equal_compute']]
    extra_table=table(['方式','accuracy','照会予算','危険','安全成功','旧不当拒否','上界被覆（検証済み状態）'],[
        [LABELS[x['variant']],x['accuracy'],x['budget'],*[pct(x[m]) for m in ('harmful_action','safe_task_success','unjustified_refusal','certified_enclosure')]] for x in extras])
    stability=load_csv(base/'analysis/stability.csv');match=sum(x['matches'] for x in stability);stn=sum(x['n'] for x in stability)
    report=[
      '# 公開された誤差上界の証拠確認：実装・新規比較 REPORT','',
      f"数値矛盾修正版に対する一要因の上界確認を実装・実行した。主条件では危険行動率が{pp(delta('harmful_action'))}、安全なタスク成功率が{pp(delta('safe_task_success'))}、旧公開基準の不当拒否率が{pp(delta('unjustified_refusal'))}変化した。固定採否は{acc['groups_passed']}/12群（細目{sum(c['passed'] for c in acc['checks'])}/{len(acc['checks'])}）達成。結論は{'合成群内での暫定候補' if acc['adopt'] else '採用しない'}。既定モデルの置換はしていない。",'',
      f"今回モデルcurrentに対しては、上界版の危険行動は{pp(r['harmful_action']-data['current']['harmful_action'])}、安全成功は{pp(r['safe_task_success']-data['current']['safe_task_success'])}。比較対象を替えて改善だけを強調しない。前回研究と今回の絶対値の差は評価群が異なるため、モデル改善の効果量として扱わない。",'',
      '## 実装した内容と証拠の意味','',
      '観測された複数値の全てが安全という判定を、検証可能な誤差上界で広げた区間の全値が安全という判定に変更した。変更点は代替候補の数値dossierのみ。Guilt制御、当初候補のゲート、効用、リスク閾値、状態更新、代替生成は従来のまま。比較対象currentは直前研究のcombined_verified、numeric_setは直前の数値矛盾修正版である。単純ルールには上界版と同じ証拠確認を付けた。この2方式の差は一要因ではなく、アーキテクチャ比較として読む。','',
      '上界 = 最大校正残差 + .08×最大校正点間隔/2 + 参照誤差.002 + 測定誤差.01 + 経時変化.0002×経過tick。モデルが見る既知の校正標準は0,.25,.5,.75,1であり、評価ケースの真値ではない。全定義域、温度10–35、最大age50、取得時刻、期限、計器、参照出典、取得経路を確認し、値・対象・版・事象・当事者をclaim digestで結ぶ。2独立登録経路の全記録を要求し、一つでも不正なら未解決。区間の和集合を包絡し、交差で狭くしない。互いに素な「保証区間」も未解決にする。','',
      '**「公開」はシミュレーション内でモデルが参照できる資料を指す。実在のメーカー資料・校正機関の証明書を検証した研究ではない。** 外部送信禁止を守り、Web照会はしていない。固定のLipschitz・雑音・ドリフト仕様が真で、校正資料と系譜が真正である場合の条件付き数学的包絡である。少数の校正点から未知の実機の上界を保証したものではない。claim digestは紐付けであって署名や真正性の証明ではない。公開された記録が整合していても、誤差契約や独立性そのものが虚偽なら真値を外し得る。','',
      link(ROOT/'experiments/error_bounds_20261018/public.py','上界の検証実装')+' / '+link(ROOT/'experiments/error_bounds_20261018/evaluation.py','独立した公開情報監査')+' / '+link(base/'PLAN.md','実験前の固定計画'),'',
      '## 基準再現と分割','',
      '開始時の281テストと2デモが成功。旧current/numeric_set/rule_verifiedの480判断を再生し、時間以外の全列が一致した。過去の126テスト・5,760判断は現在の安全性の根拠として再利用せず、実ファイルで確認した直前版を基準にした。新規47テストを追加し328テストと両デモが成功した。テスト成功は安全性の証明ではない。','',
      '開発は新規生成器を使わない手書き6probe×4方式×2反復=48判断と境界・変異試験だけ。校正資料の取得時刻と旧claim生成器の時刻差を実装点検で発見し、凍結前に整合させ、回帰テストを追加した。パラメータ調整なし。主実行前に88ファイルをハッシュ固定した。','',
      '新規24系統×8seed×8step×3センサー反復=4,608判断/条件。4方式×8条件で147,456判断。独立に抽出した社会的状況ではなく、同作者の合成機構probeで、抽象仕様や故障機構を共有する。評価前未参照のfamily/seedだが、別作者の検証ではない。1,536の固有世界状態・192世界episodeがあり、step・反復・言い換えは24系統の内部に保持した。主条件はaccuracy .85、照会2、固定確認先、canonical。全方式へ同じ資料を同じ費用で渡す。旧方式も未使用資料の受信量を計上した。','',
      '## 主条件の比較','',primary_table,'',
      '値はfamily平均。危険・成功は曖昧な規範ケースを除く。実現被害は全判断。安全代替成功の分母は物理的に安全な代替が存在する状態。不当拒否の分母は、それぞれの公開契約で少なくとも一つの候補が許可される状態。分母が違う指標を直接混同しない。','',denominator_table,'',support_table,'',
      f"![主要比較](<{(base/'figures/primary_comparison.png').resolve().as_posix()}>)",'',
      '旧公開監査は観測値集合だけを見る。新監査は上界証拠も要求する。新基準で旧モデルの根拠なし実行が増えることは、評価契約の追加によるもの。物理的な危険減少と区別する。旧基準の不当拒否と物理的な機会損失も残し、新基準への付け替えで性能悪化を隠さない。倫理的係争は別集計し、未確認の正解を補っていない。','',
      '## 上界は真値を覆ったか','',
      f"主条件の全数値slotが検証できた状態は{r['certified_enclosure_denominator']}/4,608。検証可能率は{pct(r['certification_rate'])}。その状態に限る上界被覆率はfamily平均{pct(r['certified_enclosure'])}、プール値{pct(r['certified_enclosure_pooled'])}（{r['certified_enclosure_numerator']}/{r['certified_enclosure_denominator']}）。元の観測値集合の被覆率は全状態を分母として{pct(r['observed_enclosure'])}。検証不能を被覆成功へ数えていない。",'',family_table,'',
      f"同じ{additional['matched_certified_states']}状態に分母を揃えた保存後の記述的検算では、観測値集合は{additional['observed_covered_on_matched_states']}状態（{pct(additional['observed_matched_pooled'])}）、上界付き包絡は{additional['bounded_covered_on_matched_states']}状態（{pct(additional['bounded_matched_pooled'])}）で真値を覆った。異なる分母の率を差し引いた改善ではない。この追加検算を新しい採否基準にはしない。",'',
      f"![上界の被覆](<{(base/'figures/enclosure_coverage.png').resolve().as_posix()}>)",'',
      '二つの公開経路に同一系譜が書かれている場合は停止できる。一方、実際には同じ誤りなのに別系譜と記載された虚偽や、記録に出ない計器故障は上界の前提を破る。これらはaccuracy=1でも体系的に残す設計である。高いaccuracyはoracleではない。検証済みとされた区間の被覆失敗をそのまま保存し、正解から区間を補正していない。','',
      'accuracy=1では検証を通った2,496状態中2,400状態を覆い、96状態を覆わなかった（被覆率96.154%）。残る全96状態は隠れた相関虚偽の系統bound_18である。明示的に契約が守られた合成計器では機能する一方、公開資料の整合を確認するだけでは契約の真正性を保証できないという反例になった。','',
      link(base/'verification/coverage_by_slot.csv','slotごとの全被覆検算')+' / '+link(base/'prospective_v1/by_enclosure_state.csv','被覆成功・失敗・検証不能別の判断成績')+' / '+link(base/'casebook/all_enclosure_failures_and_unsafe_alternatives.csv','全被覆失敗・危険代替')+' / '+link(base/'additional_audit/matched_enclosure_coverage.csv','同じ分母での被覆比較'),'',
      '## 原因と副作用','',action_table,'',
      '当初候補の証拠ゲートを変えていないため、その誤観測や当事者見落としに由来する危険が残る。感情機構や当事者別予測を同時に修正していない。代替候補は既存の2候補カタログで固定されており、代替案生成不足の寄与をこの実験で識別したとは主張しない。下表は保存トレースからの説明経路で、相互排他的な真の原因ラベルではない。','',failure_table,'',
      f"上界版で残った危険な代替実行は{additional['residual_danger_rows']}行・{additional['residual_danger_world_states']}世界状態で、全てbound_18の1系統。公開監査では許可されても、系譜と誤差契約が虚偽なら危険を排除できなかった。これらを独立した9系統の証拠とは数えない。",'',
      f"数値版の保存状態4,608件を固定した2方式の再判定は{same['decisions']:,}件。元判定の再現不一致{len(same['numeric_replay_mismatches'])}。新たに公開上許可されない代替を選ぶ件数と旧hard制約の解除を採否に含めた。独自の逐次履歴を使う主実行との差は{casebook['shared_vs_sequential_differences']}状態あり、直接効果と履歴を通じた効果を分離して保存した。",'',
      '追加の保存後回帰では、直前研究で数値版が新たに危険を選んだ既知の3状態を再生した。数値版の判断は一致し、上界版は3件とも代替を停止した。旧資料には校正証拠がないため、新しい証拠を真値から捏造せず空欄で渡した結果である。6再判定を新規群の推定・採否には含めない。','',
      f"保存後に物理モデルの独立Bernoulli仮定から求めた潜在期待被害の差（上界版−数値版）は合計{latent_row['expected_harm_change_sum']:+.3f}、1判断平均{pp(latent_row['expected_harm_change_mean'])}。これは真値を用いる診断専用で、実運用成績や採否の追加基準にはしていない。harmが制約の被害量と確率を兼ねる旧シミュレータの単純化も残る。",'',
      link(base/'casebook/CASEBOOK.md','改善・悪化・偽造残余の具体例')+' / '+link(base/'analysis/paired_transitions.csv','全対応変化')+' / '+link(base/'analysis/all_adverse_transitions.csv','全悪化行'),'',
      '## 不確実性・最悪条件・費用','',interval_table,'',
      '再標本化の単位は対応する24family。2,000回bootstrap、seed10037。反復数や類似例を独立証拠に数えていない。多重比較未補正の探索区間であり、有意性・非劣性・安全性を主張しない。事前の粗い設計では差のfamily SD=.05なら±2ptに約25独立群、±0.5ptに約385群が必要で、この合成群だけで小さい危険増分を保証できない。','',cost_table,'',
      f"上界版の平均時間は数値版の{acc['runtime_ratio']:.3f}倍。照会とrecord単価は模擬費用で、実料金ではない。有料API・通信費は0円、電力・端末減価償却は未計測。判断時間はローカル観測生成・状態更新・予測・選択を含み、評価器・CSV保存を除く。全実験の壁時計時間は{main['elapsed_seconds']:.3f}秒、判断処理の累積は{main['policy_seconds']:.3f}秒。両者は異なる。",'',
      f"![対応差と負担](<{(base/'figures/paired_effect_and_cost.png').resolve().as_posix()}>)",'',extra_table,'',
      f"言い換え2条件と14仮想判断への回数合わせは{match:,}/{stn:,}対応で選択・判定が一致。構造化した同じ証拠を扱うfixtureであり、自然言語理解の頑健性を検証した結果ではない。情報不足は予算0/1と証拠欠落・期限・校正範囲外で検査。利害対立は同意否認・同意対立・係争を別に保持した。",'',
      link(base/'analysis/worst_conditions.csv','最悪条件')+' / '+link(base/'prospective_v1/by_severity.csv','重大度別')+' / '+link(base/'analysis/variability.csv','seed・反復別のばらつき'),'',
      '## 固定採否','',acceptance_table,'',
      '閾値・ラベル・対象群を結果に合わせて変更していない。十二群のうち9–11は複数の細目を全て満たす必要がある。独立作者・独立した人間の注釈が未確保なので、全達成でも実運用の承認にはならない。','',
      '## 検算・保存・未完了','',
      f"全{verify['rows_checked']:,}生判断を再採点し不一致{len(verify['errors'])}。固定公開情報{verify['fixed_information_groups']:,}群を照合。集計値{arithmetic['scalars_checked']:,}個の独立算術検算で不一致{len(arithmetic['mismatches'])}。既存の別Pythonで{cross['decisions']}判断を再実行し時間以外の不一致{len(cross['mismatches'])}。source_snapshot.zipを新規フォルダへ展開し328テストと2デモが成功した。",'',
      f"実行件数は主比較{completion['decision_runs']['prospective']:,}、開発{completion['decision_runs']['development']}、旧再現{completion['decision_runs']['baseline_replay']}、同一状態{completion['decision_runs']['shared_state']:,}、既知反例回帰{completion['decision_runs']['old_counterexample_regression']}、別Python再現{completion['decision_runs']['cross_runtime']}、計{completion['total_recorded_decision_runs']:,}。テスト内の小さな呼出しは研究判断件数に加算しない。実測総経過{completion['wall_seconds']/60:.2f}分、検算・報告・保存段階{completion['verification_reporting_seconds']/60:.2f}分。",'',
      f"既存{integrity['original_files_checked']:,}ファイル、HEAD、staged/unstaged差分は不変。新規ソース{completion['new_source_files']}ファイルを追加。外部送信・有料API・新規インストール・commit・push・現実行動は0。基準より古い結果を上書きしていない。",'',
      '未完了は、独立作者・人間の注釈、実在機器と認証された公開資料、隠れた共通原因や誤差契約の真偽確認、当初候補の同等ゲート、自然言語の証拠抽出、実運用検証。検証可能な上界がある場合の処理と、上界の前提自体が未確認の場合を分ける必要がある。', '',
      '取得と判断が同じtickで、温度窓内では同じ誤差契約が成立する合成計器を用いた。実際の温度依存や取得後の対象変化は検証していない。選択した行動の後で届くfeedbackも従来の理想化された遡及観測であり、その観測可能性は実環境では未確認。'+link(base/'ASSUMPTION_AUDIT.md','上界の導出と未確認の前提を分けた技術監査')+'を参照。','',
      link(base/'NEXT_MINIMAL_VALIDATION.md','次に必要な最小検証')+' / '+link(base/'RUNBOOK.md','再現と再開')+' / '+link(base/'CHANGES.md','変更一覧')+' / '+link(base/'source_snapshot.zip','ソース一式')+' / '+link(base/'prospective_v1/all_comparisons.csv','全比較CSV')
    ]
    (base/'REPORT.md').write_text('\n'.join(report),encoding='utf-8')
    summary=['# 短い要約','',report[2],'',primary_table,'',
      f"真値被覆は検証済み状態で{pct(r['certified_enclosure'])}（family平均）。検証可能だったのは{r['certified_enclosure_denominator']}/4,608状態。校正資料・独立性の記録そのものが虚偽の場合は、公開情報の整合だけでは排除できなかった。実機の安全保証ではない。",'',
      f"新規147,456判断、再現・開発・診断を含む計{completion['total_recorded_decision_runs']:,}判断。328テストと2デモ成功。既存1,110ファイル不変。外部送信・有料API・インストール・commit・pushなし。",'',link(base/'REPORT.md','詳細REPORT')+' / '+link(base/'RUNBOOK.md','RUNBOOK')]
    (base/'SUMMARY.md').write_text('\n'.join(summary),encoding='utf-8')
    nexttext=['# 次に必要な最小検証','',
      f"今回の上界版は固定採否{acc['groups_passed']}/12群。未達細目: "+', '.join(c['criterion'] for c in failed)+'。今回の24系統は探索済みで、未知の検証群として再利用しない。','',
      '## 1. 校正上界の前提を誰が保証するか','',
      '次の一要因は、上界計算を変えずに、取得方法・校正標準・計器仕様・独立した取得経路の真正性を裏づける検証可能な証拠を追加する。現在のsource/authority/lineage文字列とdigestは真正性や統計的独立性の証明ではない。署名は発行者を確認できても、計器の誤差上界が真である保証にはならない。共通電源・同じ参照標準・同じ前処理・同一の校正データの使い回しなど、隠れた共通原因も公開契約へ明記する。未確認の前提は未解決に保つ。','',
      '実在する公開仕様と、その適用範囲・誤差定義が分かる校正資料をローカルに用意し、別作者/人間が仕様と証拠をレビューする必要がある。現在はこの条件を満たしていない。外部送信禁止のままでは手元の未提供資料を取得したことにしない。公開情報が完全に同じなのに真の状態だけ異なる二つの世界は、公開情報だけの決定論的判断器では識別できないという負例も維持する。','',
      '最小開発probeは、有効な独立校正、自己申告だけの校正、同じ校正標準の共有、真正だが期限外、正しい署名で内容の前提が誤り、誤差上界の保証条件が外れた測定。実機の真値をモデル入力へ混ぜず、評価側で被覆と危険・過剰停止を確認する。署名確認と証拠再取得を同じ実験に混ぜない。','',
      '## 2. 必要停止と取りこぼしを別に改善する','',
      '旧契約の不当拒否増加と、上界契約で必要な停止は異なる。真に安全だが資料が不足する場合は、閾値を緩めるのでなく、上限付きの追加確認または別の低リスク候補を検証する。取得政策と候補生成は別要因。現在の当初候補の危険・当事者見落としは、代替だけのゲートでは解決していないため別実験にする。','',
      'harmの被害量・確率の兼用や、Guiltの事象結合も未解決。今回の結果に合わせてラベル、採否、上界幅を変更しない。固定状態と逐次履歴の差を保持し、失敗例を回帰probeに追加するときは探索済みと表示する。','',
      '## 再開条件','',
      '独立注釈・新規family・固定した情報境界と採否を確保する。seed・言い換え・反復を独立群数に数えない。無害さの仮定を証拠として扱わず、検証不能率と検証済み条件での被覆率を併記する。全試行・悪化・曖昧例を保存する。既存結果の保全と外部送信・API・インストール・commit・push禁止を継続する。']
    (base/'NEXT_MINIMAL_VALIDATION.md').write_text('\n'.join(nexttext),encoding='utf-8')
    command_base=base.relative_to(ROOT).as_posix()
    runbook=f'''# RUNBOOK — 保存点と再現

この研究の固定計画はPLAN.md、凍結はregistration_v1/freeze.json（88ファイル）、全試行はprospective_v1/decisions.csvとdecisions.jsonl.gz。途中進捗はprogress.json、終了状態はprospective_execution.json。評価群は実行済みで、再実行しても新しい独立証拠にはならない。

## 完全性確認

```powershell
Set-Location 'C:\\Users\\yomas\\github\\Artificial Moral Architecture'
python -X utf8 experiments/error_bounds_20261018/package_results.py verify {command_base}
python -X utf8 -m unittest discover -s tests -v
python -X utf8 examples/demo.py
python -X utf8 examples/affect_demo.py
```

## 別フォルダで主比較を再現

```powershell
$replayPath = Join-Path 'results' ('error_bounds_replay_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $replayPath
python -X utf8 experiments/run_error_bounds.py --phase prospective --freeze {command_base}/registration_v1/freeze.json --output (Join-Path $replayPath 'prospective_v1')
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
python -X utf8 experiments/error_bounds_20261018/verify.py verify {command_base}
python -X utf8 experiments/error_bounds_20261018/verify.py diagnose {command_base}
python -X utf8 experiments/error_bounds_20261018/analyze.py {command_base}
python -X utf8 experiments/error_bounds_20261018/casebook.py {command_base}
python -X utf8 experiments/error_bounds_20261018/additional_audit.py {command_base}
python -X utf8 experiments/error_bounds_20261018/regression.py {command_base}
& 'C:\\Users\\yomas\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe' -X utf8 experiments/error_bounds_20261018/verify.py cross {command_base}
& 'C:\\Users\\yomas\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe' -X utf8 experiments/error_bounds_20261018/plot_results.py {command_base}
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
'''
    (base/'RUNBOOK.md').write_text(runbook,encoding='utf-8')


if __name__=='__main__':write_report(Path(sys.argv[1]).resolve())
