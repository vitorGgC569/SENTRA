# SENTRA Mobile: direct LAN and private VPN

This guide applies to the Android preview published on the [download page](https://vitorggc569.github.io/SENTRA/). It connects directly to your Windows host. GitHub Pages serves the presentation and download files; it does not host your Dots or conversations.

## First Android connection

1. Download the Android APK from the page. The current preview targets **ARM64**. If Android requests permission to install from your browser, grant that permission only to the browser you used for this installation.
2. Open the updated SENTRA on Windows. Open the Dot's **Canvas → Dispositivos** and activate **LAN / VPN**.
3. Connect Android and Windows to the same local network. For a private VPN, select the Windows VPN address that the phone can reach; do not leave the physical Wi-Fi address selected for a remote phone.
4. Display the pairing QR on Windows. Open pairing in SENTRA Mobile and scan it. The invitation expires after **120 seconds**; display a new one if necessary.
5. Confirm the device on Windows and select its authorized project, Space, Dot and actions. Finish claiming the pairing in the mobile app.
6. Open an existing conversation and refresh it. Check that the selected Dot and its messages match the desktop before sending a new task.

Pairing does not grant unrestricted execution. The host continues to apply its existing permissions. Model credentials and Web account cookies stay on the host.

## If the phone cannot connect

The next APK built from the 2026-10-22 closure sources adds **Buscar endereços na
LAN** beside saved pairings. It scans `_sentra._tcp` for up to eight seconds and
shows address hints only for already paired host keys. Tap **Verificar e
conectar** to authenticate that saved identity before the address is persisted.
An mDNS announcement never grants access or resends commands. Unknown hosts
still require a fresh QR and desktop approval. QR recovery and manual address
entry remain available when multicast or native discovery is unavailable.
Most private VPNs do not forward local multicast, so use the VPN's reachable
private address in that case. This feature still requires physical-device
acceptance after rebuilding; the existing preview2 APK predates it.

- Keep the host running and the LAN connection activated. A QR code from a stopped host cannot establish a connection.
- Check the selected address in **Dispositivos**. DHCP changes, switching networks or switching to a VPN can make an older address unreachable. The mobile app can update a saved host address without replacing its pinned identity.
- Check whether the Wi-Fi is a guest network or isolates clients. Two devices using the same network name may still be unable to reach each other.
- Check Windows Firewall if Android cannot reach the host. If Windows asks about the bundled SENTRA runtime, allow only the intended trusted network. Do not disable the firewall or expose the mobile listener through public port forwarding.
- On a VPN, verify direct reachability between devices and select the correct private interface. SENTRA does not configure or operate the VPN.
- If pairing reaches the Windows approval request, the network and pairing handshake have worked. Complete the approval before expecting conversations or tools to be accessible.
- A changed host identity requires investigation and new explicit pairing; changing only the address must not silently accept a different host key.

## Physical-device acceptance checklist

These checks are still pending on the owner's physical Android and iPhone; automated protocol tests do not replace them.

1. Pair and approve the intended scope; confirm that a different Dot is inaccessible.
2. Open a conversation, read messages and send one small task once. Follow its receipt rather than repeatedly sending it.
3. Suspend and resume the app; check reconnection and that pending actions were not submitted again.
4. Disconnect and restore Wi-Fi or the private VPN; consult uncertain operations without resending them.
5. If using remote control, switch away or suspend the app and confirm that input possession is released or expires. Then reacquire control explicitly.
6. Revoke the device on Windows and confirm that its old credential no longer works.

For a useful report, include the APK version, Android version, connection type, last successful step and the visible error. Do not include a pairing QR, pairing invitation, credentials or account cookies.

## iPhone availability

The iOS source exists, but there is no published signed iPhone installation channel yet. Apple Developer and a distribution channel are still required. The download page does not advertise an installable iOS build.

## Acceptance record

See [delivery evidence and remaining qualification](DELIVERY_ACCEPTANCE_2026-10-22.md). A working local desktop patch is separate from a newly published full Windows Setup.
