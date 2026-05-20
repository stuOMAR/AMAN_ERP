"""
Static regression test: invoice_state._dispatch_side_effects must wire
actual GL posting for draft→posted transition (ACC-01).
"""
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
INVOICE_STATE = BACKEND / "services" / "sales" / "invoice_state.py"


def test_dispatch_side_effects_calls_gl_create():
    """ACC-01: _dispatch_side_effects must call gl_service.create_journal_entry
    for draft→posted, not just log a stub message."""
    src = INVOICE_STATE.read_text(encoding="utf-8")

    # Find the _dispatch_side_effects function
    assert "_dispatch_side_effects" in src, "Function must exist"

    # Must call the actual GL create function
    assert "gl_create" in src or "create_journal_entry" in src, (
        "ACC-01: _dispatch_side_effects must call create_journal_entry for GL posting"
    )

    # Must NOT be a stub (just a logger.info)
    # Find the draft→posted block
    draft_posted_idx = src.find('from_state == "draft" and to_state == "posted"')
    assert draft_posted_idx != -1, "draft→posted block must exist"

    block = src[draft_posted_idx:draft_posted_idx + 8000]

    # The stub comment should be gone
    assert "will be wired by T026" not in block, (
        "ACC-01: stub comment 'will be wired by T026' must be removed"
    )

    # Must have actual GL call
    assert "_gl_create(" in block or "create_journal_entry(" in block, (
        "ACC-01: GL create call must be present in draft→posted block"
    )


def test_dispatch_side_effects_enqueues_zatca():
    """ACC-01: _dispatch_side_effects must enqueue ZATCA outbox for draft→posted."""
    src = INVOICE_STATE.read_text(encoding="utf-8")
    draft_posted_idx = src.find('from_state == "draft" and to_state == "posted"')
    block = src[draft_posted_idx:draft_posted_idx + 8000]

    assert "enqueue" in block, (
        "ACC-01: ZATCA outbox enqueue must be called in draft→posted block"
    )
