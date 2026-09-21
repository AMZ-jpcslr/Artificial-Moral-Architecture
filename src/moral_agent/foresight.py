"""Hand-authored conditional forecasts, not empirical predictions or a world model."""

from .models import Action, ActionKind, FutureOutcome, Impact, Situation, TimeHorizon


class DeterministicForesight:
    def predict(self, situation: Situation, action: Action) -> tuple[FutureOutcome, ...]:
        harmful = action.kind in (ActionKind.HACK, ActionKind.PRIVATE_DATA)
        deletion = action.kind == ActionKind.DELETE
        unknown = action.kind == ActionKind.UNKNOWN
        descriptions = {
            ActionKind.SOLVE: ("自力で解答し、理解が深まる可能性", "十分な得点が得られず、追加学習が必要になる可能性"),
            ActionKind.HACK: ("無断アクセスによって解答を取得し、アクセス権を侵害する可能性", "情報漏洩と組織・試験への信頼低下が持続する可能性"),
            ActionKind.PRIVATE_DATA: ("本人の同意なく情報を利用し、プライバシーを侵害する可能性", "再共有により本人の不利益が長期化する可能性"),
            ActionKind.PUBLIC_INFO: ("公開情報から必要な情報を提供できる可能性", "情報が不足し、追加の確認が必要になる可能性"),
            ActionKind.REQUEST_PERMISSION: ("本人が利用範囲を判断できる機会を持つ", "拒否や回答待ちにより達成が遅れる可能性"),
            ActionKind.DELETE: ("必要なファイルまで削除する可能性", "復元不能なデータ消失が後で発覚する可能性"),
            ActionKind.REVIEW_FILES: ("削除候補を確認することで誤削除を防ぐ可能性", "確認に時間がかかり、整理が遅れる可能性"),
            ActionKind.UNKNOWN: ("影響を十分に推定できない", "未把握の長期的影響が残る可能性"),
        }
        outcomes = []
        for index, description in enumerate(descriptions[action.kind]):
            impacts = []
            for stakeholder in situation.stakeholders:
                known_role = stakeholder.role in {"user", "third_party", "organization", "society"}
                uncertainty = .95 if unknown or not known_role else (.8 if deletion else .15)
                if harmful:
                    harm = {"user": .3, "third_party": .85, "organization": .8, "society": .6}.get(stakeholder.role, .7)
                    rights, consent, fairness, reversibility = .95, .95, .8, .1
                elif deletion:
                    harm = .9 if stakeholder.role in ("user", "organization") else .25
                    rights, consent, fairness, reversibility = .3, .5, .2, .1
                else:
                    harm, rights, consent, fairness, reversibility = .05, .0, .0, .05, .95
                impacts.append(Impact(
                    stakeholder.id, harm, rights, consent, fairness, reversibility,
                    uncertainty, .7 if stakeholder.role == "user" and index == 0 else .1,
                    f"{stakeholder.name}: {description}（固定ルールによる仮説）",
                ))
            outcomes.append(FutureOutcome(
                description,
                TimeHorizon.IMMEDIATE if index == 0 else TimeHorizon.LONG_TERM,
                tuple(s.id for s in situation.stakeholders),
                .8 if index == 0 else .3,
                max(i.harm for i in impacts), min(i.reversibility for i in impacts),
                max(i.uncertainty for i in impacts), tuple(impacts),
            ))
        return tuple(outcomes)
