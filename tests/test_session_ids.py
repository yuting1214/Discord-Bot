"""Session ID handling for /resume_session.

Browser testing found that a well-formed UUID for a session that does not exist
was reported as malformed — sending the user back to /search to copy the same ID
again. Shape and existence are different failures and need different messages.
"""

import uuid

import pytest

from src.backend.discord.utils import extract_uuid


@pytest.mark.parametrize(
    "value",
    [
        "52e9d6ce-7fda-462c-9983-71fa6bedf6c4",       # v4, as generated today
        "00000000-0000-0000-0000-000000000000",       # nil: valid shape, no version
        "018f6e3a-1b2c-7def-8123-456789abcdef",       # v7, what PostgreSQL 18 emits
        "6ba7b810-9dad-11d1-80b4-00c04fd430c8",       # v1
    ],
)
def test_every_uuid_version_is_accepted(value):
    """Not UUID4-specific. PostgreSQL 18 ships uuidv7() and this template's own
    database image documents it, so a v4-only check would reject every session
    ID the day they come from the database — and reject them as malformed."""
    assert extract_uuid(value) == value


def test_the_returned_id_is_the_id_that_was_given():
    """uuid.UUID(x, version=4) *forces* the version and variant bits rather than
    checking them, so the previous code could hand back a different ID than the
    user typed."""
    for value in ("018f6e3a-1b2c-7def-8123-456789abcdef",
                  "6ba7b810-9dad-11d1-80b4-00c04fd430c8"):
        assert uuid.UUID(extract_uuid(value)) == uuid.UUID(value)


@pytest.mark.parametrize("value", ["not-a-uuid", "", "12345", "session one", None])
def test_garbage_is_rejected_without_raising(value):
    """extract_uuid is called outside the caller's try block, so raising here
    would surface as the generic failure message instead of an actionable one."""
    assert extract_uuid(value) == ""


def test_an_id_embedded_in_text_is_found_and_normalised():
    assert extract_uuid("resume 52E9D6CE-7FDA-462C-9983-71FA6BEDF6C4 please") == (
        "52e9d6ce-7fda-462c-9983-71fa6bedf6c4"
    )


def test_the_two_failures_do_not_share_a_message():
    """The bug, stated as a test: garbage and a valid-but-unknown ID must not
    produce byte-identical replies."""
    import inspect

    from src.backend.discord import run_async

    source = inspect.getsource(run_async.resume_session)
    assert "not a session ID" in source
    assert "No session with ID" in source
    # The unknown-ID branch is only reachable if extract_uuid accepts the ID.
    assert extract_uuid("00000000-0000-0000-0000-000000000000") != ""
