# -*- coding: utf-8 -*-
"""Who asks, when the server runs behind Google's identity-aware proxy (docs/plans/people-and-graphs.md, phase 5).

On Cloud Run with IAP, the proxy signs each request it lets through: `X-Goog-IAP-JWT-Assertion`, a JWT with the person's email. The server verifies it on
every request, so identity is what Google signed rather than a header a caller states, and removing someone's `roles/iap.httpsResourceAccessor` refuses their
next request. `OTO_IAP_AUDIENCE` is the audience the proxy signs for: /projects/<number>/locations/<region>/services/<service>.

Verifying ES256 takes the `cloud` extra (cryptography): this module imports it only when the server runs this way.
"""
import base64
import binascii
import json
import os
import threading
import time
import urllib.request

AUDIENCE_ENV = "OTO_IAP_AUDIENCE"
KEYS_FILE_ENV = "OTO_IAP_KEYS_FILE"
KEYS_URL = "https://www.gstatic.com/iap/verify/public_key-jwk"
ISSUER = "https://cloud.google.com/iap"
HEADER = "X-Goog-IAP-JWT-Assertion"
SKEW = 30
KEYS_LIFETIME = 3600
_LOCK = threading.Lock()
_CACHE = {"keys": None, "at": 0}


class IapError(Exception):
    """This request isn't signed by the proxy for this service."""


def setup_problem(environ=None):
    """Why the server can't verify anyone, in words, or None. Checked before it starts: a server that can't verify must not serve."""
    env = environ if environ is not None else os.environ
    if not (env.get(AUDIENCE_ENV) or "").strip():
        return "--iap needs %s, the audience the proxy signs for: /projects/<number>/locations/<region>/services/<service>" % AUDIENCE_ENV
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return "--iap needs the cloud extra to verify the proxy's signature: install oto-kg[cloud]"
    return None


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _load_keys():
    path = os.environ.get(KEYS_FILE_ENV)
    if path:
        with open(path, encoding="utf-8") as f:
            found = json.load(f)
    else:
        with urllib.request.urlopen(KEYS_URL, timeout=10) as r:
            found = json.loads(r.read().decode("utf-8"))
    return {k["kid"]: k for k in found.get("keys") or [] if isinstance(k, dict) and k.get("kid")}


def keys(kid=None):
    """The proxy's public keys, by id, cached for an hour, and fetched again for a key not seen yet, since Google rotates them."""
    with _LOCK:
        stale = _CACHE["keys"] is None or time.time() - _CACHE["at"] > KEYS_LIFETIME or (kid is not None and kid not in _CACHE["keys"])
        if stale:
            try:
                _CACHE["keys"], _CACHE["at"] = _load_keys(), time.time()
            except (OSError, ValueError) as exc:
                if _CACHE["keys"] is None:
                    raise IapError("could not read the proxy's public keys: %s" % exc)
        return _CACHE["keys"]


def _check_signature(signed, signature, jwk):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    if len(signature) != 64:
        raise IapError("the signature isn't an ES256 signature")
    public = ec.EllipticCurvePublicNumbers(int.from_bytes(_unb64(jwk["x"]), "big"), int.from_bytes(_unb64(jwk["y"]), "big"), ec.SECP256R1()).public_key()
    der = encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big"))
    try:
        public.verify(der, signed, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise IapError("the signature doesn't match")


def verify(assertion, audience, known_keys=None, now=None):
    """The email of the person a proxy-signed assertion names, or IapError saying why not. Only ES256 is accepted, so `alg: none` is no way in."""
    if not assertion or not isinstance(assertion, str) or assertion.count(".") != 2:
        raise IapError("no signed assertion from the proxy")
    head_text, body_text, signature_text = assertion.split(".")
    try:
        head, body, signature = json.loads(_unb64(head_text)), json.loads(_unb64(body_text)), _unb64(signature_text)
    except (ValueError, binascii.Error):
        raise IapError("the assertion can't be read")
    if not isinstance(head, dict) or not isinstance(body, dict) or head.get("alg") != "ES256":
        raise IapError("the assertion isn't signed with ES256")
    kid = head.get("kid")
    jwk = (known_keys if known_keys is not None else keys(kid)).get(kid)
    if not jwk:
        raise IapError("the assertion was signed by a key the proxy doesn't publish")
    _check_signature(("%s.%s" % (head_text, body_text)).encode("ascii"), signature, jwk)
    moment = now if now is not None else time.time()
    if body.get("iss") != ISSUER:
        raise IapError("the assertion's issuer isn't the proxy")
    if body.get("aud") != audience:
        raise IapError("the assertion's audience isn't this service")
    if not isinstance(body.get("exp"), (int, float)) or body["exp"] < moment - SKEW:
        raise IapError("the assertion has expired")
    if not isinstance(body.get("iat"), (int, float)) or body["iat"] > moment + SKEW:
        raise IapError("the assertion is dated in the future")
    email = str(body.get("email") or "").split(":")[-1].strip()
    if not email:
        raise IapError("the assertion names no email")
    return email
