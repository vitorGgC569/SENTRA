# WhatsApp transport and third-party notices

The implemented transport is the official WhatsApp Cloud API over HTTPS using a
host-approved Graph API version, vault credentials and signed webhooks. Its
SENTRA adapter is original code. No WhatsApp client implementation, libsignal,
QR-session code or Invisible Dots source was copied or embedded.

The OpenDots study records optional libsignal under GPL-3.0 in Invisible Dots'
THIRD_PARTY_NOTICES. That is a distinct client/QR transport and dependency. Its
clone was not available in the local research directory during this work. It
must not be added to the Cloud API dependency inventory or described as already
incorporated. The QR/libsignal variant is explicitly unavailable.

If a QR/libsignal implementation is later selected, pin and inspect that exact
source, retain its full GPL-3.0 license/copyright and applicable notices, and
package its lifecycle/provenance separately. Cloud API operation still requires
the owner's Meta application/business/phone configuration, actual messaging
scopes, supported Graph API version and provider terms. Configuration alone is
not evidence of an account, scope or message delivery.
