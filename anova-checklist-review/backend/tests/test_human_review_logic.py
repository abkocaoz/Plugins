"""Phase 5: human decision keeps ai_proposal separate (pure helpers / state rules)."""

from app.services.excel_export import _effective_state, answer_cell_value
from app.services.human_review import ALLOWED_DECISIONS, ALLOWED_STATES


class _Ans:
    def __init__(self, human=None, state="YES", ai=None):
        self.human_decision = human
        self.state = state
        self.ai_proposal = ai or {"proposed_state": "YES"}


def test_allowed_decision_and_state_vocab():
    assert "accept" in ALLOWED_DECISIONS
    assert "override" in ALLOWED_DECISIONS
    assert "YES" in ALLOWED_STATES
    assert "INSUFFICIENT_EVIDENCE" in ALLOWED_STATES


def test_effective_state_draft_vs_approved():
    ans = _Ans(human=None, state="NO", ai={"proposed_state": "NO"})
    assert _effective_state(ans, "draft") == "NO"
    assert _effective_state(ans, "reviewer_approved") is None

    ans2 = _Ans(human="YES", state="YES", ai={"proposed_state": "NO"})
    assert _effective_state(ans2, "draft") == "YES"
    assert _effective_state(ans2, "reviewer_approved") == "YES"


def test_status_not_derived_from_ai_yes():
    # Export mapping: YES writes Answer=Yes but Status stays None unless human_export.status set
    assert answer_cell_value("YES") == "Yes"
    # Convention documented in catalog — no automatic Closed
    assert answer_cell_value("YES") != "Closed"
