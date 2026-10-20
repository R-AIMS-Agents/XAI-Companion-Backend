"""The roster: the next participant ID, and which file a participant's next session is written to."""

import pytest

from agent import roster


def _logs(directory, *stems):
    """Create empty study logs with the given names."""
    for stem in stems:
        (directory / f"{stem}.jsonl").touch()


def test_an_empty_study_suggests_the_first_participant(tmp_path):
    """With no logs yet, the first ID is P01."""
    assert roster.suggest(tmp_path) == "P01"


def test_a_missing_directory_suggests_the_first_participant(tmp_path):
    """The study directory exists only once a session has run, so its absence means no participant has been seen."""
    assert roster.suggest(tmp_path / "not-yet") == "P01"


def test_the_suggestion_is_one_past_the_highest_number(tmp_path):
    """Gaps are not refilled: a skipped number may belong to a participant whose log was moved away."""
    _logs(tmp_path, "P01", "P03")
    assert roster.suggest(tmp_path) == "P04"


def test_a_rerun_counts_as_its_participant_being_used(tmp_path):
    """P05-2 means participant 5 has been seen, so the next participant is 6."""
    _logs(tmp_path, "P04", "P05-2")
    assert roster.suggest(tmp_path) == "P06"


def test_files_that_are_not_sessions_are_ignored(tmp_path):
    """Anything else in the directory has no participant number to count."""
    _logs(tmp_path, "P02", "notes", "P99-draft")
    (tmp_path / "P50.txt").touch()
    assert roster.suggest(tmp_path) == "P03"


def test_a_first_session_takes_the_bare_id(tmp_path):
    """A participant's first session is written under their ID alone."""
    assert roster.session_path("P04", tmp_path) == tmp_path / "P04.jsonl"


def test_a_rerun_takes_the_next_free_suffix(tmp_path):
    """An existing log is never reused: a second session is P04-2, a third P04-3."""
    _logs(tmp_path, "P04")
    assert roster.session_path("P04", tmp_path).name == "P04-2.jsonl"
    _logs(tmp_path, "P04-2")
    assert roster.session_path("P04", tmp_path).name == "P04-3.jsonl"


@pytest.mark.parametrize(
    "text, canonical",
    [
        ("P04", "P04"),
        ("p4", "P04"),
        (" P12 ", "P12"),
        ("P100", "P100"),
        ("P0", "P00"),
        ("test", "test"),
        (" anna ", "anna"),
        ("pilot run 3", "pilot run 3"),
    ],
)
def test_an_id_is_stored_in_one_form(text, canonical):
    """A numbered participant typed two ways ends up as one ID, and any other string is kept as typed, without surrounding spaces."""
    assert roster.normalise(text) == canonical


@pytest.mark.parametrize("text", ["", "   ", "a/b", "x:y", "why?", "trailing.", "con", "LPT1"])
def test_text_that_cannot_name_a_log_file_is_refused(text):
    """The ID becomes the log's file name, so anything Windows refuses as one is refused as an ID."""
    assert roster.normalise(text) is None


def test_test_sessions_are_never_counted_as_participants(tmp_path):
    """Trying the platform out leaves logs, but they belong to no participant and move the suggestion nowhere."""
    _logs(tmp_path, "P02", "test", "test-2")
    assert roster.suggest(tmp_path) == "P03"


def test_test_sessions_take_suffixes_like_any_other(tmp_path):
    """Repeated test runs never overwrite one another."""
    _logs(tmp_path, "test")
    assert roster.session_path(roster.TEST, tmp_path).name == "test-2.jsonl"


def test_free_ids_are_never_counted_as_participants(tmp_path):
    """Only numbered participants move the suggestion, so a log under any other ID leaves it where it was."""
    _logs(tmp_path, "P02", "anna", "P07x")
    assert roster.suggest(tmp_path) == "P03"
