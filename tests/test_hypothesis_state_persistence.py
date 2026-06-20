from __future__ import annotations

from ultrab.core.smc.hypothesis import (
    Hypothesis,
    HypothesisClassifier,
    hypothesis_state_from_dict,
    hypothesis_state_to_dict,
)


def _hypothesis(phase: str, direction: str = "long") -> Hypothesis:
    return Hypothesis(
        hypothesis_id="hyp-1",
        status="watching",
        phase=phase,
        direction=direction,
        swing_alignment="pro_swing",
        internal_alignment="pro_internal",
        poi_id=None,
        poi_type=None,
        reason="test",
        required_evidence=[],
        invalidation="test",
        target_policy="htf_pd_level",
        fallback_target_policy=None,
        entry_policy="wait",
        created_at="2026-01-30T20:45:00+00:00",
        updated_at="2026-01-30T20:45:00+00:00",
        phase_sub_status="watch",
        debug_facts={"phase_b_shadow_commitment_extreme_level": 1.0834},
    )


def test_hypothesis_state_roundtrip_preserves_shadow_thesis_journal_fields():
    classifier = HypothesisClassifier()
    classifier.state.hypothesis_id = "state-hyp"
    classifier.state.phase_episode_id = "episode-1"
    classifier.state.previous_phase = "A"
    classifier.state.htf_pd_epoch_id = "epoch-1"
    classifier.state.active_phase_e_direction = "long"
    classifier.state.current_hypothesis = _hypothesis("A")

    shadow = classifier.state.shadow_thesis
    shadow.phase_e.source_orderflow_leg_id = "of-leg-1"
    shadow.phase_c.origin_node = "D.watch_isb"
    shadow.phase_c.entered_at = "2026-01-30T10:00:00+00:00"
    shadow.phase_b.commitment_extreme_level = 1.0834
    shadow.phase_b.commitment_extreme_event_id = "SC01:2026-01-30T12:00:00+00:00:up:1.0834"
    shadow.phase_a.entered_at = "2026-01-30T18:00:00+00:00"
    shadow.phase_a.pro_extreme_at_weaken = 1.0912

    payload = hypothesis_state_to_dict(classifier.state)
    restored = hypothesis_state_from_dict(payload)

    assert restored.hypothesis_id == "state-hyp"
    assert restored.phase_episode_id == "episode-1"
    assert restored.previous_phase == "A"
    assert restored.htf_pd_epoch_id == "epoch-1"
    assert restored.active_phase_e_direction == "long"
    assert restored.current_hypothesis is not None
    assert restored.current_hypothesis.phase == "A"
    assert restored.shadow_thesis.phase_e.source_orderflow_leg_id == "of-leg-1"
    assert restored.shadow_thesis.phase_c.origin_node == "D.watch_isb"
    assert restored.shadow_thesis.phase_c.entered_at == "2026-01-30T10:00:00+00:00"
    assert restored.shadow_thesis.phase_b.commitment_extreme_level == 1.0834
    assert restored.shadow_thesis.phase_b.commitment_extreme_event_id.startswith("SC01:")
    assert restored.shadow_thesis.phase_a.entered_at == "2026-01-30T18:00:00+00:00"
    assert restored.shadow_thesis.phase_a.pro_extreme_at_weaken == 1.0912


def test_hypothesis_state_roundtrip_tolerates_missing_current_hypothesis():
    classifier = HypothesisClassifier()
    payload = hypothesis_state_to_dict(classifier.state)
    restored = hypothesis_state_from_dict(payload)

    assert restored.previous_phase == "X"
    assert restored.current_hypothesis is None
