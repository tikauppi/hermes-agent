"""Isolated verification of externally issued THESEUS authority evidence.

This module verifies evidence only. It does not issue evidence, load signing
keys, choose a production trust store, or mutate lifecycle state.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class AuthorityEvidenceRejected(ValueError):
    """Signed authority evidence failed closed."""


@dataclass(frozen=True)
class AuthorityExpectation:
    version: int
    algorithm: str
    issuer: str
    key_id: str
    principal: str
    principal_role: str
    evidence_type: str
    action: str
    scope: str
    package_id: str
    task_id: str
    run_id: int
    stop_token: str
    code_sha: str
    issued_at: int
    expires_at: int
    nonce: str


@dataclass(frozen=True)
class VerifiedAuthorityEvidence:
    payload: dict
    evidence_digest: str


_PAYLOAD_FIELDS = frozenset(AuthorityExpectation.__dataclass_fields__)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuthorityEvidenceRejected("authority evidence contains duplicate keys")
        result[key] = value
    return result


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


class AuthorityVerifier:
    """Verify against an injected, externally owned issuer/key trust map."""

    def __init__(
        self,
        *,
        trusted_keys: Mapping[tuple[str, str], bytes],
        authorized_principals: Mapping[tuple[str, str], frozenset[str] | set[str]],
        revoked_issuers: set[str] | frozenset[str] = frozenset(),
        revoked_keys: set[tuple[str, str]] | frozenset[tuple[str, str]] = frozenset(),
        revoked_nonces: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        self._trusted_keys = dict(trusted_keys)
        self._authorized_principals = {
            key: frozenset(roles) for key, roles in authorized_principals.items()
        }
        self._revoked_issuers = frozenset(revoked_issuers)
        self._revoked_keys = frozenset(revoked_keys)
        self._revoked_nonces = frozenset(revoked_nonces)

    def verify_and_consume(
        self,
        envelope: str | bytes,
        *,
        expected: AuthorityExpectation | Mapping[str, object],
        now: int,
        consume_once: Callable[[str, str, str], bool],
    ) -> VerifiedAuthorityEvidence:
        try:
            raw = envelope.decode("utf-8") if isinstance(envelope, bytes) else envelope
            parsed = json.loads(raw, object_pairs_hook=_reject_duplicate_pairs)
            if not isinstance(parsed, dict) or set(parsed) != {"payload", "signature"}:
                raise AuthorityEvidenceRejected("authority evidence envelope is malformed")
            payload = parsed["payload"]
            if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
                raise AuthorityEvidenceRejected("authority evidence payload is malformed")
            signature = base64.b64decode(parsed["signature"], validate=True)
            issuer = payload["issuer"]
            key_id = payload["key_id"]
            nonce = payload["nonce"]
            public_bytes = self._trusted_keys[(issuer, key_id)]
            canonical = _canonical(payload)
            Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature, canonical)
        except (InvalidSignature, KeyError, TypeError, ValueError, UnicodeError, binascii.Error) as exc:
            raise AuthorityEvidenceRejected("authority evidence signature is invalid") from exc

        expected_payload = (
            {field: getattr(expected, field) for field in AuthorityExpectation.__dataclass_fields__}
            if isinstance(expected, AuthorityExpectation)
            else dict(expected)
        )
        if any(
            field not in _PAYLOAD_FIELDS or payload.get(field) != value
            for field, value in expected_payload.items()
        ):
            raise AuthorityEvidenceRejected("authority evidence binding mismatch")
        if issuer in self._revoked_issuers or (issuer, key_id) in self._revoked_keys:
            raise AuthorityEvidenceRejected("authority evidence issuer or key was revoked")
        authorized_roles = self._authorized_principals.get((issuer, payload["principal"]))
        if authorized_roles is None or payload["principal_role"] not in authorized_roles:
            raise AuthorityEvidenceRejected("authority evidence principal authorization failed")
        integer_fields = ("version", "run_id", "issued_at", "expires_at")
        integers_are_safe = all(
            isinstance(payload[field], int)
            and not isinstance(payload[field], bool)
            and 0 <= payload[field] < 2**63
            for field in integer_fields
        )
        if (
            not integers_are_safe
            or payload["version"] != 1
            or payload["algorithm"] != "Ed25519"
            or not _SHA_RE.fullmatch(payload["code_sha"])
            or not all(
                isinstance(payload[field], str) and bool(payload[field])
                for field in _PAYLOAD_FIELDS
                if field not in integer_fields
            )
        ):
            raise AuthorityEvidenceRejected("authority evidence payload is malformed")
        if payload["issued_at"] > int(now):
            raise AuthorityEvidenceRejected("authority evidence is not yet valid")
        if payload["expires_at"] <= int(now) or payload["expires_at"] <= payload["issued_at"]:
            raise AuthorityEvidenceRejected("authority evidence expired")
        if nonce in self._revoked_nonces:
            raise AuthorityEvidenceRejected("authority evidence was revoked")

        digest = hashlib.sha256(canonical + b"\0" + signature).hexdigest()
        if not consume_once(issuer, nonce, digest):
            raise AuthorityEvidenceRejected("authority evidence replay rejected")
        return VerifiedAuthorityEvidence(payload=dict(payload), evidence_digest=digest)
