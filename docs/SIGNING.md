# Signing the macOS app

Without a signature, macOS shows a Gatekeeper warning and the user has to
right-click → Open. With one, the DMG installs like any other app. Everything
below is optional: the CI produces a working unsigned build when the secrets
are absent, and only switches to the signed path once they exist.

## What you need

An **Apple Developer Program** membership (about USD 99 a year). ZHdK may
already have one — ask whoever administers the institution's Apple accounts
for a *Developer ID Application* certificate, or to be added to the team so you
can create one. A free Apple ID cannot sign for distribution.

## 1 · Create the certificate

On a Mac, in Xcode: **Settings → Accounts → Manage Certificates → + →
Developer ID Application**. Then in **Keychain Access**, right-click the new
certificate → **Export** → save as `certificate.p12` with a password.

## 2 · Create an app-specific password

At <https://account.apple.com> → Sign-In and Security → App-Specific Passwords.
This is what notarisation uses; the account password will not work.

## 3 · Add four repository secrets

GitHub → the repo → Settings → Secrets and variables → Actions → New secret:

| Secret | Value |
|---|---|
| `MACOS_CERTIFICATE_P12` | `base64 -i certificate.p12 \| pbcopy` — the whole base64 blob |
| `MACOS_CERTIFICATE_PASSWORD` | the password you set when exporting |
| `MACOS_SIGN_IDENTITY` | e.g. `Developer ID Application: Zürcher Hochschule der Künste (AB12CD34EF)` |
| `APPLE_ID` | the Apple account email |
| `APPLE_TEAM_ID` | the 10-character team id, shown in the identity above |
| `APPLE_APP_PASSWORD` | the app-specific password from step 2 |

Find the exact identity string with `security find-identity -v -p codesigning`.

## 4 · Push a tag

```bash
git tag v1.0.0 && git push origin v1.0.0
```

The macOS jobs then sign every binary in the bundle, sign the bundle, build a
DMG, submit it to Apple, wait for the result and staple the ticket. The release
gets `.dmg` files instead of `.zip`.

## Running it by hand

```bash
export SIGN_IDENTITY="Developer ID Application: … (TEAMID)"
export APPLE_ID="you@example.com" APPLE_TEAM_ID="TEAMID" APPLE_PASSWORD="abcd-efgh-ijkl-mnop"
python -m PyInstaller packaging/soundxr_bridge.spec --noconfirm --clean
bash packaging/sign_macos.sh
```

## Why the entitlements

`packaging/entitlements.plist` grants three things CPython needs under the
hardened runtime — JIT, unsigned executable memory and library validation off —
plus the two network entitlements the OSC sockets need. Without the first three
the signed app crashes on launch; without the last two it runs but hears
nothing.

## When notarisation fails

`xcrun notarytool log <submission-id> --apple-id … --team-id … --password …`
gives the actual reason. The usual causes are a binary inside the bundle that
was not signed (the script signs inner Mach-O files first for exactly this
reason) or a missing `--options runtime`.
