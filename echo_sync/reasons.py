"""M1 (ARCH_ONE): the ONE closed registry of the names a verdict carries. ``Resolutions.resolve`` (utterance_judge) reads it; the acts (P01, ``ACTS`` keys) and the ledger's end reasons (P09) import
their names from here and add none of their own: a name that is not in a group below is refused (``known``), never invented at the place that writes it. Pure data: it imports nothing."""

# What a verdict of the judge may be: the kinds of ``classifier`` (ACK .. QUIET, GREETING, CORRECTION, CLARIFY_REPAIR, RESUME, NEXT). A test (``test_m1_rules``) holds the two equal.
KINDS = ('ack', 'repeat', 'stop', 'question', 'replay', 'silent', 'greeting', 'correction', 'clarify_repair', 'resume', 'next')

# Why a LATER look at the same words may revise the verdict of an utterance (a typed second decision, ``final_rev`` + 1). Closed: exactly seven.
REVISE_CAUSES = ('cloud_final', 'early_tail', 'ear_take', 'ear_overruled', 'redo', 'resume', 'local_ear')

# What the FIRST look at an utterance is called (the boundary the judge was asked at): it names the record, it never revises one.
FIRST_CAUSES = ('stable_partial', 'lead_cue', 'delegation', 'utterance', 'fast_command')

REASONS = {'kind': KINDS, 'revise': REVISE_CAUSES, 'first': FIRST_CAUSES}


def known(group, name):
    """Is ``name`` in the closed list ``group`` ('kind', 'revise', 'first')? An unknown group is a bug of the caller and raises."""
    return name in REASONS[group]


def is_revise_cause(cause):
    return cause in REVISE_CAUSES
