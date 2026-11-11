from types import SimpleNamespace

from app import security
from app.services import audit


def test_password_hash_verifies_and_rejects_wrong_password():
    stored = security.hash_password("correct horse", n=2**10)
    assert stored.startswith("scrypt$") and "correct horse" not in stored
    assert security.verify_password("correct horse", stored)
    assert not security.verify_password("wrong horse", stored)


def test_same_password_gets_different_hashes_because_of_salt():
    assert security.hash_password("same", n=2**10) != security.hash_password("same", n=2**10)


def test_malformed_stored_hashes_never_crash_and_never_match():
    for bad in ["", "plain", "scrypt$1$2", "bcrypt$a$b$c$d$e", "scrypt$x$8$1$AAAA$AAAA"]:
        assert security.verify_password("anything", bad) is False


def test_tokens_are_random_and_only_their_hash_is_comparable():
    first, second = security.new_token(), security.new_token()
    assert first != second and len(first) >= 40
    assert security.hash_token(first) == security.hash_token(first)
    assert security.hash_token(first) != first and len(security.hash_token(first)) == 64


# ---------- audit hash chain (pure logic, no database) ----------
def make_chain(count: int):
    events, prev = [], audit.GENESIS_HASH
    for number in range(1, count + 1):
        event = SimpleNamespace(
            id=number, ts=f"2026-11-10T00:00:0{number}.000000Z", user_id="u1", user_email="a@b.com",
            action="document.upload", status="success", resource_type="document", resource_id=f"d{number}",
            detail={"filename": f"f{number}.pdf"}, ip="127.0.0.1", request_id="r", prev_hash=prev, event_hash="",
        )
        event.event_hash = audit.compute_hash(prev, audit._content(event))
        events.append(event)
        prev = event.event_hash
    return events


def test_untouched_chain_verifies_and_reports_head():
    events = make_chain(4)
    result = audit.verify_chain(events)
    assert result == {"valid": True, "events_checked": 4, "first_invalid_id": None, "head_hash": events[-1].event_hash}


def test_empty_log_is_valid():
    assert audit.verify_chain([])["valid"] is True


def test_editing_an_event_is_detected():
    events = make_chain(4)
    events[1].detail = {"filename": "evil.pdf"}
    result = audit.verify_chain(events)
    assert result["valid"] is False and result["first_invalid_id"] == 2


def test_removing_an_event_from_the_middle_is_detected():
    events = make_chain(4)
    del events[1]
    result = audit.verify_chain(events)
    assert result["valid"] is False and result["first_invalid_id"] == 3


def test_clip_shortens_long_text():
    assert audit.clip("x" * 500).endswith("...") and len(audit.clip("x" * 500)) == 200
    assert audit.clip("short") == "short"
