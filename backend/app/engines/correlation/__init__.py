"""Deterministic correlation of normalized evidence (Phase 6).

Groups evidence records that describe the same underlying issue, using
explicit, explainable rules over the structured fields the normalizer wrote.
No model, no embeddings, no fuzzy matching: every group names the rule that
formed it and the stable key it shares.
"""
