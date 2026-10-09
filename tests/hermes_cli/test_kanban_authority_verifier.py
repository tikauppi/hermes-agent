from __future__ import annotations

import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hermes_cli.kanban_authority_verifier import (
    AuthorityEvidenceRejected,
    AuthorityExpectation,
    AuthorityVerifier,
)


PAYLOAD = {
    "version": 1,
    "algorithm": "Ed25519",
    "issuer": "synthetic-r4-issuer",
    "key_id": "synthetic-key-1",
    "principal": "synthetic-architect-1",
    "principal_role": "architect",
    "evidence_type": "architect_decision",
    "action": "resume_after_architect_decision",
    "scope": "theseus.gateway-kanban-lifecycle",
    "package_id": "pkg-r4-synthetic",
    "task_id": "task-r4-synthetic",
    "run_id": 41,
    "stop_token": "stop-token-r4-synthetic",
    "code_sha": "b" * 40,
    "issued_at": 1_000,
    "expires_at": 1_100,
    "nonce": "r4-synthetic-nonce-0001",
}


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _expected() -> AuthorityExpectation:
    return AuthorityExpectation(
        **{key: PAYLOAD[key] for key in AuthorityExpectation.__dataclass_fields__}
    )


def _fixture(payload: dict | None = None, *, revoked_nonces: set[str] | None = None):
    private_key = Ed25519PrivateKey.generate()
    body = dict(PAYLOAD if payload is None else payload)
    signature = private_key.sign(_canonical(body))
    envelope = json.dumps(
        {"payload": body, "signature": base64.b64encode(signature).decode("ascii")},
        sort_keys=True,
    )
    public_key = private_key.public_key().public_bytes_raw()
    verifier = AuthorityVerifier(
        trusted_keys={(PAYLOAD["issuer"], PAYLOAD["key_id"]): public_key},
        revoked_nonces=revoked_nonces or set(),
    )
    return verifier, _expected(), envelope, private_key


def test_synthetic_signed_evidence_is_verified_and_consumed_once():
    consumed: set[tuple[str, str, str]] = set()

    def consume_once(issuer: str, nonce: str, digest: str) -> bool:
        key = (issuer, nonce, digest)
        if key in consumed:
            return False
        consumed.add(key)
        return True

    verifier, expected, envelope, _private_key = _fixture()

    verified = verifier.verify_and_consume(
        envelope,
        expected=expected,
        now=1_050,
        consume_once=consume_once,
    )

    assert verified.payload == PAYLOAD
    assert len(verified.evidence_digest) == 64
    with pytest.raises(AuthorityEvidenceRejected, match="replay"):
        verifier.verify_and_consume(
            envelope,
            expected=expected,
            now=1_050,
            consume_once=consume_once,
        )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("principal", "synthetic-builder"),
        ("principal_role", "builder"),
        ("action", "approve_terminal"),
        ("evidence_type", "terminal_approval"),
        ("scope", "other.scope"),
        ("package_id", "pkg-other"),
        ("task_id", "task-other"),
        ("run_id", 42),
        ("stop_token", "stop-other"),
        ("code_sha", "c" * 40),
    ],
)
def test_signed_evidence_must_match_every_expected_binding(field, bad_value):
    payload = dict(PAYLOAD)
    payload[field] = bad_value
    verifier, expected, envelope, _private_key = _fixture(payload)

    with pytest.raises(AuthorityEvidenceRejected, match="binding"):
        verifier.verify_and_consume(
            envelope,
            expected=expected,
            now=1_050,
            consume_once=lambda *_args: True,
        )


def test_missing_expired_and_revoked_evidence_fail_closed():
    missing = dict(PAYLOAD)
    missing.pop("action")
    missing_verifier, expected, missing_envelope, _ = _fixture(missing)
    with pytest.raises(AuthorityEvidenceRejected):
        missing_verifier.verify_and_consume(
            missing_envelope,
            expected=expected,
            now=1_050,
            consume_once=lambda *_args: True,
        )

    expired_verifier, expected, expired_envelope, _ = _fixture()
    with pytest.raises(AuthorityEvidenceRejected, match="expired"):
        expired_verifier.verify_and_consume(
            expired_envelope,
            expected=expected,
            now=1_101,
            consume_once=lambda *_args: True,
        )

    revoked_verifier, expected, revoked_envelope, _ = _fixture(
        revoked_nonces={PAYLOAD["nonce"]}
    )
    with pytest.raises(AuthorityEvidenceRejected, match="revoked"):
        revoked_verifier.verify_and_consume(
            revoked_envelope,
            expected=expected,
            now=1_050,
            consume_once=lambda *_args: True,
        )


def test_forged_and_malformed_evidence_fail_closed():
    verifier, expected, envelope, _ = _fixture()
    forged = json.loads(envelope)
    forged["signature"] = base64.b64encode(b"x" * 64).decode("ascii")

    with pytest.raises(AuthorityEvidenceRejected, match="signature"):
        verifier.verify_and_consume(
            json.dumps(forged),
            expected=expected,
            now=1_050,
            consume_once=lambda *_args: True,
        )
    with pytest.raises(AuthorityEvidenceRejected):
        verifier.verify_and_consume(
            '{"payload":',
            expected=expected,
            now=1_050,
            consume_once=lambda *_args: True,
        )


def test_concurrent_replay_consumption_has_exactly_one_winner():
    verifier, expected, envelope, _ = _fixture()
    lock = threading.Lock()
    consumed = set()

    def consume_once(issuer, nonce, digest):
        with lock:
            key = (issuer, nonce, digest)
            if key in consumed:
                return False
            consumed.add(key)
            return True

    def attempt(_index):
        try:
            verifier.verify_and_consume(
                envelope,
                expected=expected,
                now=1_050,
                consume_once=consume_once,
            )
            return "accepted"
        except AuthorityEvidenceRejected:
            return "rejected"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(16)))

    assert outcomes.count("accepted") == 1
    assert outcomes.count("rejected") == 15
