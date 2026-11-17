from .models import Action, ActionKind, Situation


class RuleCounterfactual:
    """Bounded one-step alternatives; each must pass the same assessment pipeline."""

    def alternatives(self, situation: Situation, action: Action) -> tuple[Action, ...]:
        templates = {
            ActionKind.HACK: ((ActionKind.SOLVE, "自分で問題を解く", .8),),
            ActionKind.PRIVATE_DATA: (
                (ActionKind.PUBLIC_INFO, "公開情報のみを使う", .75),
                (ActionKind.REQUEST_PERMISSION, "本人に利用許可を求める", .5),
            ),
            ActionKind.DELETE: ((ActionKind.REVIEW_FILES, "削除候補を提示し、確認を求める", .6),),
        }
        return tuple(
            Action(f"{action.id}:alternative:{kind.value}", description, kind, utility)
            for kind, description, utility in templates.get(action.kind, ())
        )
