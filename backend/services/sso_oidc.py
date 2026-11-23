"""
sso_oidc.py — OpenID Connect sign-in (authorization code flow with PKCE) for services/sso.py.

* Discovery: ``<issuer>/.well-known/openid-configuration``; its ``issuer`` must equal the configured one.
  Metadata and JWKS are cached for an hour (the JWKS is refetched once when a token names an unknown key).
* ``authorize_url()``: ``state`` (single use, in ``sso_states``), ``nonce`` and PKCE S256.
* ``finish()``: exchanges the code (client_secret_basic, or client_secret_post when that's all the IdP
  supports), then verifies the ID token: signature against the IdP's JWKS with an asymmetric algorithm
  (never ``none`` / HMAC), ``iss``, ``aud`` (and ``azp`` when there are several audiences), ``exp``,
  ``iat`` and ``nonce``. ``email_verified: false`` is refused. Claims missing from the ID token (often
  ``groups``) are read from the userinfo endpoint when its ``sub`` matches.

Every URL fetched passes the outbound SSRF guard (services/external_agent.validate_endpoint):
an IdP on a private network needs EXTERNAL_AGENT_ALLOWED_HOSTS (or EXTERNAL_AGENT_ALLOW_PRIVATE=1).
Redirects are not followed.
"""

import base64
import hashlib
import secrets
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, urlparse

import httpx
import jwt

from services.external_agent import validate_endpoint
from services.sso import SSOError, secret

ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"]
CACHE_TTL_S = 3600
LEEWAY_S = 120
TIMEOUT_S = 15.0
CALLBACK_PATH = "/api/auth/sso/oidc/callback"

_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def validate_config(cfg: Dict[str, Any]) -> None:
    issuer = cfg.get("issuer") or ""
    p = urlparse(issuer)
    if p.scheme != "https" and not (p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1")):
        raise SSOError("The issuer must be an https URL, e.g. https://login.example.com/realms/acme.")
    if not cfg.get("client_id"):
        raise SSOError("Enter the client ID from your identity provider.")
    if not cfg.get("client_secret"):
        raise SSOError("Enter the client secret from your identity provider.")


def redirect_uri(base: str) -> str:
    return base.rstrip("/") + CALLBACK_PATH


async def _get_json(url: str) -> Dict[str, Any]:
    try:
        await validate_endpoint(url)
    except ValueError as e:
        raise SSOError(f"Can't reach the identity provider: {e}")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False) as client:
            r = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise SSOError(f"Can't reach the identity provider ({type(e).__name__}).")
    if r.status_code != 200:
        raise SSOError(f"The identity provider answered {r.status_code} for {url}.")
    try:
        data = r.json()
    except ValueError:
        raise SSOError(f"The identity provider sent something other than JSON from {url}.")
    if not isinstance(data, dict):
        raise SSOError(f"Unexpected response from {url}.")
    return data


async def _cached(url: str, refresh: bool = False) -> Dict[str, Any]:
    hit = _cache.get(url)
    if hit and not refresh and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    data = await _get_json(url)
    _cache[url] = (time.time(), data)
    return data


async def metadata(cfg: Dict[str, Any]) -> Dict[str, Any]:
    issuer = cfg["issuer"].rstrip("/")
    meta = await _cached(issuer + "/.well-known/openid-configuration")
    if str(meta.get("issuer", "")).rstrip("/") != issuer:
        raise SSOError(f"The identity provider's issuer is {meta.get('issuer')!r}, not {cfg['issuer']!r}.")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not meta.get(key):
            raise SSOError(f"The identity provider's discovery document has no {key}.")
    return meta


def _pkce() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def authorize_url(p: Dict[str, Any], base: str, return_to: str) -> str:
    from services import sso

    cfg = p["config"]
    meta = await metadata(cfg)
    verifier, challenge = _pkce()
    nonce = secrets.token_urlsafe(24)
    state = sso.put_state(p["id"], "login", {"nonce": nonce, "verifier": verifier, "return_to": return_to},
                          sso.LOGIN_TTL)
    scopes = cfg.get("scopes") or "openid email profile"
    if "openid" not in scopes.split():
        scopes = "openid " + scopes
    params = {"response_type": "code", "client_id": cfg["client_id"], "redirect_uri": redirect_uri(base),
              "scope": scopes, "state": state, "nonce": nonce, "code_challenge": challenge,
              "code_challenge_method": "S256"}
    endpoint = meta["authorization_endpoint"]
    return endpoint + ("&" if "?" in endpoint else "?") + urlencode(params)


async def _exchange(p: Dict[str, Any], meta: Dict[str, Any], code: str, verifier: str, base: str) -> Dict[str, Any]:
    cfg = p["config"]
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(base),
            "code_verifier": verifier}
    methods = meta.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    auth = None
    if "client_secret_basic" in methods:
        auth = (cfg["client_id"], secret(p, "client_secret"))
    else:
        form.update({"client_id": cfg["client_id"], "client_secret": secret(p, "client_secret")})
    url = meta["token_endpoint"]
    try:
        await validate_endpoint(url)
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False) as client:
            r = await client.post(url, data=form, auth=auth, headers={"Accept": "application/json"})
    except ValueError as e:
        raise SSOError(f"Can't reach the identity provider: {e}")
    except httpx.HTTPError as e:
        raise SSOError(f"Can't reach the identity provider ({type(e).__name__}).")
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200 or not isinstance(body, dict) or not body.get("id_token"):
        why = body.get("error_description") or body.get("error") if isinstance(body, dict) else ""
        raise SSOError(f"The identity provider refused the sign-in code{': ' + str(why) if why else ''}.")
    return body


async def _signing_key(meta: Dict[str, Any], token: str) -> Any:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise SSOError("The identity provider sent a malformed ID token.")
    if header.get("alg") not in ALGORITHMS:
        raise SSOError(f"ID token algorithm {header.get('alg')!r} isn't accepted.")
    kid = header.get("kid")
    for refresh in (False, True):
        jwks = await _cached(meta["jwks_uri"], refresh=refresh)
        keys = [k for k in jwks.get("keys", []) if isinstance(k, dict) and k.get("use", "sig") == "sig"]
        match = [k for k in keys if k.get("kid") == kid] if kid else keys
        if len(match) == 1 or (match and not kid):
            try:
                return jwt.PyJWK(match[0], algorithm=header["alg"]).key
            except jwt.PyJWTError as e:
                raise SSOError(f"The identity provider's signing key can't be used: {e}")
    raise SSOError("The ID token was signed with a key the identity provider doesn't publish.")


def verify_id_token(token: str, key: Any, *, issuer: str, client_id: str, nonce: str) -> Dict[str, Any]:
    try:
        claims = jwt.decode(token, key=key, algorithms=ALGORITHMS, audience=client_id, issuer=issuer,
                            leeway=LEEWAY_S, options={"require": ["iss", "sub", "aud", "exp", "iat"]})
    except jwt.InvalidIssuerError:
        # Some IdPs differ only by a trailing slash
        claims = jwt.decode(token, key=key, algorithms=ALGORITHMS, audience=client_id, leeway=LEEWAY_S,
                            options={"require": ["iss", "sub", "aud", "exp", "iat"]})
        if str(claims.get("iss", "")).rstrip("/") != issuer.rstrip("/"):
            raise SSOError("The ID token was issued by a different identity provider.")
    except jwt.ExpiredSignatureError:
        raise SSOError("The ID token has expired. Check the server clock and try again.")
    except jwt.PyJWTError as e:
        raise SSOError(f"The ID token is not valid: {e}")
    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != client_id:
        raise SSOError("The ID token was issued to a different application.")
    if not nonce or claims.get("nonce") != nonce:
        raise SSOError("The ID token doesn't belong to this sign-in (nonce mismatch).")
    if claims.get("email_verified") is False or str(claims.get("email_verified")).lower() == "false":
        raise SSOError("Your email address isn't verified at the identity provider.")
    return claims


async def _userinfo(meta: Dict[str, Any], access_token: str, sub: str) -> Dict[str, Any]:
    url = meta.get("userinfo_endpoint")
    if not url or not access_token:
        return {}
    try:
        await validate_endpoint(url)
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})
        info = r.json() if r.status_code == 200 else {}
    except (ValueError, httpx.HTTPError):
        return {}
    return info if isinstance(info, dict) and info.get("sub") == sub else {}


async def finish(p: Dict[str, Any], state: Dict[str, Any], code: str, base: str) -> Dict[str, Any]:
    """Verified identity: {subject, email, name, claims} for services/sso.complete_login."""
    cfg = p["config"]
    meta = await metadata(cfg)
    tokens = await _exchange(p, meta, code, state["verifier"], base)
    key = await _signing_key(meta, tokens["id_token"])
    claims = verify_id_token(tokens["id_token"], key, issuer=meta["issuer"], client_id=cfg["client_id"],
                             nonce=state["nonce"])
    email_claim = cfg.get("email_claim") or "email"
    name_claim = cfg.get("name_claim") or "name"
    role_claim = p.get("role_claim") or ""
    wanted = [c for c in (email_claim, name_claim, role_claim) if c]
    if any(c not in claims for c in wanted):
        info = await _userinfo(meta, tokens.get("access_token", ""), claims["sub"])
        claims = {**{k: v for k, v in info.items() if k in wanted}, **claims}
    from services.sso import claim_values

    return {"subject": f"{claims['iss']}|{claims['sub']}", "email": str(claims.get(email_claim) or ""),
            "name": str(claims.get(name_claim) or ""), "claims": claim_values(_dig(claims, role_claim))}


def _dig(claims: Dict[str, Any], path: str) -> Any:
    """A claim by name, or by a dotted path into nested claims (Keycloak's ``realm_access.roles``)."""
    if not path:
        return None
    if path in claims:
        return claims[path]
    value: Any = claims
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value

