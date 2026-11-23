/**
 * Reading the files an identity provider hands out for SAML, so the SSO form can be filled from an
 * upload instead of copy-paste (components/settings/SsoPanel.tsx). Parsed in the browser; the backend
 * still validates everything (services/sso_saml.py).
 */

const MD = 'urn:oasis:names:tc:SAML:2.0:metadata'
const DS = 'http://www.w3.org/2000/09/xmldsig#'
const REDIRECT = 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect'
const POST = 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST'

export type SamlIdpMetadata = { idp_entity_id: string; idp_sso_url: string; idp_certificate: string }

/** Entity ID, sign-on URL (HTTP-Redirect preferred) and signing certificate from IdP metadata XML. */
export function parseSamlMetadata(xml: string): SamlIdpMetadata {
  const doc = new DOMParser().parseFromString(xml, 'application/xml')
  if (doc.getElementsByTagName('parsererror').length) throw new Error("That file isn't valid XML.")

  const idp = doc.getElementsByTagNameNS(MD, 'IDPSSODescriptor')[0]
  if (!idp) throw new Error('No identity provider (IDPSSODescriptor) in this metadata. Is it the IdP\'s metadata, not an SP\'s?')
  const entity = idp.closest('EntityDescriptor') ?? idp.parentElement
  const entityId = entity?.getAttribute('entityID') ?? ''

  const services = Array.from(idp.getElementsByTagNameNS(MD, 'SingleSignOnService'))
  const sso = services.find((s) => s.getAttribute('Binding') === REDIRECT)
    ?? services.find((s) => s.getAttribute('Binding') === POST) ?? services[0]

  const keys = Array.from(idp.getElementsByTagNameNS(MD, 'KeyDescriptor'))
  const key = keys.find((k) => k.getAttribute('use') === 'signing') ?? keys.find((k) => !k.getAttribute('use'))
  const cert = key?.getElementsByTagNameNS(DS, 'X509Certificate')[0]?.textContent ?? ''

  const out = { idp_entity_id: entityId.trim(), idp_sso_url: (sso?.getAttribute('Location') ?? '').trim(),
                idp_certificate: cert ? toPem(cert) : '' }
  if (!out.idp_entity_id || !out.idp_sso_url || !out.idp_certificate) {
    const missing = [!out.idp_entity_id && 'entity ID', !out.idp_sso_url && 'sign-on URL',
                     !out.idp_certificate && 'signing certificate'].filter(Boolean).join(', ')
    throw new Error(`The metadata has no ${missing}.`)
  }
  return out
}

/** A PEM certificate from base64 text (with or without the BEGIN/END lines). */
export function toPem(base64: string): string {
  const body = base64.replace(/-----(BEGIN|END) CERTIFICATE-----/g, '').replace(/\s+/g, '')
  return `-----BEGIN CERTIFICATE-----\n${body.match(/.{1,64}/g)?.join('\n') ?? ''}\n-----END CERTIFICATE-----`
}

/** A certificate file as PEM: PEM / base64 text as is, binary DER (.cer, .der) encoded. */
export function certificateFromBytes(bytes: Uint8Array): string {
  const text = new TextDecoder('utf-8', { fatal: false }).decode(bytes)
  if (text.includes('-----BEGIN CERTIFICATE-----')) {
    const m = text.match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/)
    return toPem(m![0])
  }
  if (/^[A-Za-z0-9+/=\s]+$/.test(text.trim()) && text.trim().startsWith('MII')) return toPem(text)
  if (bytes[0] !== 0x30) throw new Error("That doesn't look like a certificate (.pem, .cer, .crt).")
  let bin = ''
  bytes.forEach((b) => { bin += String.fromCharCode(b) })
  return toPem(btoa(bin))
}
