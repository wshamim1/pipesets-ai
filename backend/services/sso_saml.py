"""
sso_saml.py — SAML 2.0 Web Browser SSO (SP-initiated) for services/sso.py.

* The SP's entity id and metadata URL is ``<public>/api/auth/sso/saml/<provider>/metadata``; the
  Assertion Consumer Service is ``<public>/api/auth/sso/saml/<provider>/acs`` (HTTP-POST binding).
* ``authorize_url()`` sends an unsigned AuthnRequest with the HTTP-Redirect binding; ``RelayState`` is
  the single-use ``login`` state, which also stores the request ID.
* ``finish()`` verifies the response signature against the IdP certificate configured by the admin
  (signxml; SHA-1 and unsigned responses are refused), then reads **only the signed element** — the
  signed Response's assertion, or the signed Assertion itself — so a wrapped / injected assertion is
  never used. Checks: Status Success, Issuer, ``InResponseTo`` (IdP-initiated sign-in is not accepted),
  Destination / Recipient = the ACS URL, AudienceRestriction = the SP entity id, NotBefore /
  NotOnOrAfter with a 2-minute skew, and a bearer SubjectConfirmation.
* Encrypted assertions are not supported yet: turn assertion encryption off at the IdP.

The XML parser refuses DTDs, entities and network access.
"""

import base64
import secrets
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlparse
from xml.sax.saxutils import escape, quoteattr

from cryptography import x509
from lxml import etree
from signxml import XMLVerifier
from signxml.exceptions import InvalidInput, InvalidSignature

from services.sso import SSOError

NS = {"samlp": "urn:oasis:names:tc:SAML:2.0:protocol", "saml": "urn:oasis:names:tc:SAML:2.0:assertion"}
SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
BEARER = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
EMAIL_FORMAT = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
SKEW = timedelta(minutes=2)
MAX_RESPONSE_BYTES = 512 * 1024


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False,
                           huge_tree=False, remove_comments=True)


def load_certificate(pem: str) -> x509.Certificate:
    pem = (pem or "").strip()
    if pem and "BEGIN CERTIFICATE" not in pem:   # a bare base64 body, as IdP metadata shows it
        body = "".join(pem.split())
        pem = "-----BEGIN CERTIFICATE-----\n" + "\n".join(body[i:i + 64] for i in range(0, len(body), 64)) + \
              "\n-----END CERTIFICATE-----"
    try:
        return x509.load_pem_x509_certificate(pem.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise SSOError("The IdP signing certificate isn't a valid X.509 certificate (PEM).")


def validate_config(cfg: Dict[str, Any]) -> None:
    if not cfg.get("idp_entity_id"):
        raise SSOError("Enter the IdP entity ID (Issuer) from your identity provider's metadata.")
    p = urlparse(cfg.get("idp_sso_url") or "")
    if p.scheme != "https" and not (p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1")):
        raise SSOError("The IdP single sign-on URL must be an https URL.")
    if not cfg.get("idp_certificate"):
        raise SSOError("Paste the IdP's signing certificate.")
    load_certificate(cfg["idp_certificate"])


def sp_entity_id(p: Dict[str, Any], base: str) -> str:
    return f"{base.rstrip('/')}/api/auth/sso/saml/{p['id']}/metadata"


def acs_url(p: Dict[str, Any], base: str) -> str:
    return f"{base.rstrip('/')}/api/auth/sso/saml/{p['id']}/acs"


def _instant(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def sp_metadata(p: Dict[str, Any], base: str) -> str:
    fmt = p["config"].get("name_id_format") or EMAIL_FORMAT
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID={quoteattr(sp_entity_id(p, base))}>'
        '<md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" '
        'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        f"<md:NameIDFormat>{escape(fmt)}</md:NameIDFormat>"
        '<md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        f'Location={quoteattr(acs_url(p, base))} index="0" isDefault="true"/>'
        "</md:SPSSODescriptor></md:EntityDescriptor>"
    )


async def authorize_url(p: Dict[str, Any], base: str, return_to: str) -> str:
    from services import sso

    cfg = p["config"]
    request_id = "_" + secrets.token_hex(20)
    state = sso.put_state(p["id"], "login", {"request_id": request_id, "return_to": return_to}, sso.LOGIN_TTL)
    fmt = cfg.get("name_id_format") or EMAIL_FORMAT
    xml = (
        '<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{request_id}" Version="2.0" IssueInstant="{_instant()}" '
        f'Destination={quoteattr(cfg["idp_sso_url"])} AssertionConsumerServiceURL={quoteattr(acs_url(p, base))} '
        'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f"<saml:Issuer>{escape(sp_entity_id(p, base))}</saml:Issuer>"
        f'<samlp:NameIDPolicy Format={quoteattr(fmt)} AllowCreate="true"/>'
        "</samlp:AuthnRequest>"
    )
    deflated = zlib.compress(xml.encode("utf-8"))[2:-4]   # raw DEFLATE (RFC 1951), as the binding requires
    query = urlencode({"SAMLRequest": base64.b64encode(deflated).decode("ascii"), "RelayState": state})
    url = cfg["idp_sso_url"]
    return url + ("&" if "?" in url else "?") + query


def _time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise SSOError("The SAML response has an invalid timestamp.")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _text(el: Optional[etree._Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


def finish(p: Dict[str, Any], state: Dict[str, Any], saml_response: str, base: str,
           now: Optional[datetime] = None) -> Dict[str, Any]:
    """Verified identity: {subject, email, name, claims} for services/sso.complete_login."""
    cfg = p["config"]
    now = now or datetime.now(timezone.utc)
    if not saml_response or len(saml_response) > MAX_RESPONSE_BYTES * 4 // 3 + 4:
        raise SSOError("The identity provider sent no SAML response, or one that is too large.")
    try:
        raw = base64.b64decode(saml_response, validate=False)
        doc = etree.fromstring(raw, parser=_parser())
    except (ValueError, etree.XMLSyntaxError):
        raise SSOError("The SAML response isn't valid XML.")
    if doc.tag != f"{{{NS['samlp']}}}Response":
        raise SSOError("The identity provider didn't send a SAML Response.")

    # Status is read from the unsigned envelope only to explain a failure; success is re-checked below
    code = doc.find("samlp:Status/samlp:StatusCode", NS)
    if code is None or code.get("Value") != SUCCESS:
        msg = _text(doc.find("samlp:Status/samlp:StatusMessage", NS))
        raise SSOError("The identity provider didn't sign you in" + (f": {msg}" if msg else "."))
    if doc.find("saml:EncryptedAssertion", NS) is not None:
        raise SSOError("Encrypted assertions aren't supported yet. Turn assertion encryption off at the IdP.")

    try:
        result = XMLVerifier().verify(raw, x509_cert=load_certificate(cfg["idp_certificate"]), parser=_parser())
    except (InvalidSignature, InvalidInput) as e:
        raise SSOError(f"The SAML response signature is not valid: {e}")
    if isinstance(result, list):
        result = result[0]
    signed = result.signed_xml

    if signed.tag == f"{{{NS['samlp']}}}Response":
        response, assertions = signed, signed.findall("saml:Assertion", NS)
    elif signed.tag == f"{{{NS['saml']}}}Assertion":
        response, assertions = None, [signed]
    else:
        raise SSOError("The SAML signature doesn't cover the response or the assertion.")
    if len(assertions) != 1:
        raise SSOError("The SAML response must contain exactly one assertion.")
    assertion = assertions[0]
    acs = acs_url(p, base)

    if response is not None:
        sc = response.find("samlp:Status/samlp:StatusCode", NS)
        if sc is None or sc.get("Value") != SUCCESS:
            raise SSOError("The identity provider didn't sign you in.")
        if response.get("Destination") and response.get("Destination") != acs:
            raise SSOError("The SAML response was sent to a different address.")
        if response.get("InResponseTo") and response.get("InResponseTo") != state["request_id"]:
            raise SSOError("The SAML response doesn't belong to this sign-in.")

    if _text(assertion.find("saml:Issuer", NS)) != cfg["idp_entity_id"]:
        raise SSOError("The SAML assertion was issued by a different identity provider.")

    subject = assertion.find("saml:Subject", NS)
    name_id = subject.find("saml:NameID", NS) if subject is not None else None
    if name_id is None or not _text(name_id):
        raise SSOError("The SAML assertion has no NameID.")
    confirmed = False
    for sc in subject.findall("saml:SubjectConfirmation", NS):
        data = sc.find("saml:SubjectConfirmationData", NS)
        if sc.get("Method") != BEARER or data is None:
            continue
        if data.get("InResponseTo") != state["request_id"] or data.get("Recipient") != acs:
            continue
        not_after = _time(data.get("NotOnOrAfter"))
        if not_after is None or now >= not_after + SKEW:
            continue
        confirmed = True
        break
    if not confirmed:
        raise SSOError("The SAML assertion isn't confirmed for this sign-in (InResponseTo, Recipient or expiry).")

    cond = assertion.find("saml:Conditions", NS)
    if cond is None:
        raise SSOError("The SAML assertion has no Conditions.")
    nb, na = _time(cond.get("NotBefore")), _time(cond.get("NotOnOrAfter"))
    if (nb and now + SKEW < nb) or (na and now >= na + SKEW):
        raise SSOError("The SAML assertion has expired or isn't valid yet. Check the server clock.")
    audiences = [_text(a) for a in cond.findall("saml:AudienceRestriction/saml:Audience", NS)]
    if sp_entity_id(p, base) not in audiences:
        raise SSOError("The SAML assertion is for a different application (Audience). Check the SP entity ID at the IdP.")

    attrs: Dict[str, List[str]] = {}
    for a in assertion.findall("saml:AttributeStatement/saml:Attribute", NS):
        values = [_text(v) for v in a.findall("saml:AttributeValue", NS) if _text(v)]
        for key in {a.get("Name"), a.get("FriendlyName")} - {None, ""}:
            attrs.setdefault(key, []).extend(values)

    def attr(name: str) -> str:
        vals = attrs.get(name) if name else None
        return vals[0] if vals else ""

    email = attr(cfg.get("email_attribute") or "")
    if not email:
        email = attr("email") or attr("mail") or \
            attr("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress")
    if not email and (name_id.get("Format") == EMAIL_FORMAT or "@" in _text(name_id)):
        email = _text(name_id)
    name = attr(cfg.get("name_attribute") or "") or attr("displayName") or attr("name") or \
        attr("http://schemas.microsoft.com/identity/claims/displayname")
    role_claim = p.get("role_claim") or ""
    return {"subject": f"{cfg['idp_entity_id']}|{_text(name_id)}", "email": email, "name": name,
            "claims": attrs.get(role_claim, []) if role_claim else []}
