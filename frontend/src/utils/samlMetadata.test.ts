import { describe, expect, it } from 'vitest'
import { certificateFromBytes, parseSamlMetadata, toPem } from './samlMetadata'

const CERT = 'MIIC' + 'A'.repeat(120)

const metadata = (keyUse = 'signing') => `<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" xmlns:ds="http://www.w3.org/2000/09/xmldsig#" entityID="https://idp.example.com/saml">
  <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:KeyDescriptor use="encryption"><ds:KeyInfo><ds:X509Data><ds:X509Certificate>MIIEncryptionKey</ds:X509Certificate></ds:X509Data></ds:KeyInfo></md:KeyDescriptor>
    <md:KeyDescriptor ${keyUse ? `use="${keyUse}"` : ''}><ds:KeyInfo><ds:X509Data><ds:X509Certificate>
      ${CERT}
    </ds:X509Certificate></ds:X509Data></ds:KeyInfo></md:KeyDescriptor>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="https://idp.example.com/post"/>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="https://idp.example.com/redirect"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>`

describe('parseSamlMetadata', () => {
  it('reads entity ID, the redirect sign-on URL and the signing (not encryption) certificate', () => {
    const m = parseSamlMetadata(metadata())
    expect(m.idp_entity_id).toBe('https://idp.example.com/saml')
    expect(m.idp_sso_url).toBe('https://idp.example.com/redirect')
    expect(m.idp_certificate).toBe(toPem(CERT))
  })

  it('accepts a key without a use attribute', () => {
    expect(parseSamlMetadata(metadata('')).idp_certificate).toBe(toPem(CERT))
  })

  it('explains bad input', () => {
    expect(() => parseSamlMetadata('<nope')).toThrow(/valid XML/)
    expect(() => parseSamlMetadata('<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="x"><md:SPSSODescriptor/></md:EntityDescriptor>'))
      .toThrow(/IDPSSODescriptor/)
  })
})

describe('certificateFromBytes', () => {
  it('keeps PEM, wraps bare base64 and encodes DER', () => {
    const pem = toPem(CERT)
    expect(certificateFromBytes(new TextEncoder().encode(`junk\n${pem}\n`))).toBe(pem)
    expect(certificateFromBytes(new TextEncoder().encode(CERT))).toBe(pem)
    const der = new Uint8Array([0x30, 0x82, 0x01, 0x0a])
    expect(certificateFromBytes(der)).toBe(toPem(btoa(String.fromCharCode(...der))))
    expect(() => certificateFromBytes(new TextEncoder().encode('hello'))).toThrow(/certificate/)
  })
})
