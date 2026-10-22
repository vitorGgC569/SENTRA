# iOS signing and distribution gate

Status on 2026-10-22: source/configuration only. No signed IPA, installed iPhone
application, Apple Developer membership or Mac is available in this workspace.

The application identifier is `app.sentra.mobile`. Set `SENTRA_IOS_APPLE_TEAM_ID`
to the authorized Apple team's ten-character identifier and record the pinned
EAS CLI version used by the release operator. `SENTRA_IOS_BUILD_NUMBER` accepts
a positive integer for local Xcode builds; EAS profiles manage remote build
numbers and increment them. Keep Apple passwords, signing certificates and
private keys out of this repository and command arguments.

From this directory, using the locked npm dependencies:

```powershell
npm ci
npm run build:terminal
npm run typecheck
npx expo config --type public
npx expo export --platform ios --output-dir ../../../.tmp/closure-mobile/ios-export
eas login
eas project:init
eas device:create
eas build --platform ios --profile preview-ios
```

The EAS project must belong to the authorized owner. Set `SENTRA_EAS_PROJECT_ID` to its project UUID; `app.config.js` validates and
loads that UUID into `expo.extra.eas.projectId`.
The `preview-ios` profile requires registered iPhone/iPad UDIDs and an ad hoc
provisioning profile from the Apple Developer team. Remote credentials remain
with that authorized EAS account. A simulator export cannot satisfy this gate.

For TestFlight, configure the matching App Store Connect application, run
`eas build --platform ios --profile production-ios`, then submit the resulting
build with `eas submit --platform ios --profile production-ios`. Record the
Apple build ID, artifact digest, provisioning expiry, allowed devices/channel,
and installation evidence before describing the channel as available.

For local signing, run Expo prebuild and Xcode Archive on a supported Mac using
the same team, identifier, build number and locked sources. Export using an
owner-approved provisioning profile. No Mac build was performed here.

Physical acceptance must cover QR approval, protected draft restoration after
process termination, suspension/resume, Wi-Fi address change, private VPN,
revocation, chat refresh, terminal input, and VM keyboard/drag possession with
network interruption. The existing Android preview2 key is outside this iOS
workflow and must be retained when building any later Android update.
