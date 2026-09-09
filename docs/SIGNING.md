# Signing the macOS app

Without a signature, macOS shows a Gatekeeper warning and the user has to
right-click → Open. With one, the DMG installs like any other app. Everything
below is optional: CI produces a working unsigned build when the secrets are
absent, and only switches to the signed path once they exist.

Your Apple ID and your git commit email have nothing to do with each other.
Apple never sees the repository, GitHub never sees your Apple account. The
Apple ID goes in one repository secret and that is its only appearance.

## What you need

Membership of an **Apple Developer Program** team (ZHdK's), and a
*Developer ID Application* certificate belonging to that team. The signature
names the **organisation**, not you — `Developer ID Application: Zürcher
Hochschule der Künste (TEAMID)` — which is correct for institutional software.

> **The certificate can only be created by the team's Account Holder.**
> Apple restricts Developer ID certificates to that one role; Admin is not
> enough. If you are not the Account Holder, ask them either to create the
> certificate and send you the exported `.p12` with its password, or to sign
> the request you generate in step 1. A team may hold at most five Developer ID
> Application certificates, and one certificate covers every app the team
> ships — so if ZHdK already signs software, ask for the existing one rather
> than burning a slot.

Notarisation is separate and needs no special role: any team member's Apple ID
with an app-specific password can submit. Yours (`…@a3.epfl.ch`) is fine.

## 1 · Get the certificate as a `.p12`

**If someone hands you a `.p12`**, skip to step 2.

**On a Mac**, in Xcode: Settings → Accounts → Manage Certificates → + →
Developer ID Application. Then in Keychain Access, right-click the certificate
→ Export → save as `certificate.p12` with a password.

**On Windows, with no Mac**, OpenSSL does the same job. Rather than retyping
commands whose hyphens and slashes are easy to mangle, run the script — in
PowerShell, from the project folder:

```powershell
.\tools\apple_csr.ps1 -Step csr -Email you@example.com -Name "Your Name"
#   ... upload the .certSigningRequest, save the .cer it gives you back ...
.\tools\apple_csr.ps1 -Step p12
```

It finds OpenSSL (PATH, Git for Windows, or SourceTree's bundled copy), works
in `%USERPROFILE%\AppleSigning` — outside the repository, where a private key
belongs — fetches Apple's intermediate certificate, builds the `.p12`, and
prints the six secrets with the identity string already filled in.

The rest of this section is what the script does, for when you would rather do
it by hand in Git Bash:

```bash
# a) your private key and a signing request
openssl genrsa -out developerID.key 2048
MSYS_NO_PATHCONV=1 openssl req -new -key developerID.key \
  -out developerID.certSigningRequest \
  -subj "/emailAddress=YOUR_APPLE_ID/CN=Your Name/C=CH"
```

> `MSYS_NO_PATHCONV=1` is not optional in Git Bash. Any argument starting with
> `/` is treated as a Unix path and rewritten to a Windows one, so `-subj`
> arrives as `C:/Users/…/git_local/emailAddress=…` and OpenSSL rejects it. The
> variable turns that translation off for one command. In PowerShell, run the
> same command without it — `& "C:\Program Files\Git\usr\bin\openssl.exe" …` —
> since PowerShell does not rewrite arguments.

Upload `developerID.certSigningRequest` at
<https://developer.apple.com/account/resources/certificates> → **+** →
*Developer ID* → *Developer ID Application*, and download the resulting
`developerID_application.cer`. (If the Account Holder does this for you, send
them the `.certSigningRequest` — never the `.key`.)

```bash
# b) Apple's intermediate, so the chain is complete on a bare CI runner
curl -O https://www.apple.com/certificateauthority/DeveloperIDG2CA.cer
openssl x509 -inform DER -in DeveloperIDG2CA.cer -out DeveloperIDG2CA.pem

# c) certificate + key + chain -> one .p12
openssl x509 -inform DER -in developerID_application.cer -out developerID.pem
openssl pkcs12 -export -legacy \
  -inkey developerID.key -in developerID.pem -certfile DeveloperIDG2CA.pem \
  -out certificate.p12
```

Choose a password when prompted; that is `MACOS_CERTIFICATE_PASSWORD`. Read the
identity string straight out of the certificate — you do not need a Mac for it:

```bash
openssl x509 -in developerID.pem -noout -subject
#  subject=UID=…, CN=Developer ID Application: Zürcher Hochschule der Künste (AB12CD34EF), …
```

### Keeping the key safe

`developerID.key` and `certificate.p12` are ZHdK's signing identity, not
personal files: whoever holds them can sign software that macOS attributes to
the school. Weigh the two failure modes accordingly — **losing** them is an
afternoon's inconvenience (the Account Holder issues another certificate, up to
the team's limit of five), while **leaking** them forces a revocation, and
revocation is the destructive event: expiry is harmless because the signatures
carry a secure timestamp, but revoking invalidates what was signed with that
certificate.

So back them up, but never in a way that widens who can read them.

- **A password manager is the right home.** Store `certificate.p12`, its
  password and the app-specific password together as one entry. If it supports
  file attachments, put `developerID.key` there too and you are done.
- **Institutional OneDrive is fine as a second copy — encrypted.** Use the
  ZHdK work account, never a personal one. Do not upload the raw `.key`, and do
  not rely on the `.p12` password alone: it was written with OpenSSL's
  `-legacy` cipher for macOS compatibility, which is weak by today's standards.
  Wrap the folder first:

  ```powershell
  winget install 7zip.7zip     # if needed
  & "C:\Program Files\7-Zip\7z.exe" a -t7z -mhe=on -p `
      "$env:USERPROFILE\AppleSigning-backup.7z" "$env:USERPROFILE\AppleSigning\*"
  ```

  `-mhe=on` encrypts the file names as well as the contents. Put the passphrase
  in the password manager — an encrypted archive whose passphrase lives only in
  your head is a second way to lose the key.
- **Not** in this repository, not in a mail to yourself, and not "backed up" to
  GitHub Secrets — secrets are write-only, you cannot read them back.

Leave a short note in the folder saying what the files are and which Apple team
they belong to. A Developer ID certificate is valid for about five years, and
by then someone — possibly you — has to work out what this is and what to
renew.

## 2 · Create an app-specific password

At <https://account.apple.com> → Sign-In and Security → App-Specific Passwords.
Notarisation uses this; your account password will not work.

## 3 · Add six repository secrets

GitHub → the repo → Settings → Secrets and variables → Actions → New secret:

| Secret | Value |
|---|---|
| `MACOS_CERTIFICATE_P12` | the `.p12`, base64 encoded, on one line |
| `MACOS_CERTIFICATE_PASSWORD` | the password from step 1 |
| `MACOS_SIGN_IDENTITY` | `Developer ID Application: Zürcher Hochschule der Künste (AB12CD34EF)` |
| `APPLE_ID` | the Apple account email — the one enrolled in the team |
| `APPLE_TEAM_ID` | the 10-character team id, the part in brackets above |
| `APPLE_APP_PASSWORD` | the app-specific password from step 2 |

Base64 on Windows, straight to the clipboard:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("certificate.p12")) | Set-Clipboard
```

or on a Mac, `base64 -i certificate.p12 | pbcopy`.

## 4 · Push a tag

```bash
git tag 1.1.0 && git push origin 1.1.0
```

The macOS jobs sign every binary in the bundle, sign the bundle, build a DMG,
submit it to Apple, wait for the result and staple the ticket. The release gets
`.dmg` files instead of `.zip`. Nothing else in the workflow changes — the
signing steps are skipped automatically when the secrets are missing, so a fork
still builds.

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

## When it fails

| Message | Cause |
|---|---|
| `errSecInternalComponent` while signing | the `.p12` reached the runner without its private key — re-export including the key |
| `The signature of the binary is invalid` at notarisation | something inside the bundle is unsigned; the script signs inner Mach-O files first for exactly this reason |
| `HTTP 401` from notarytool | wrong app-specific password, or the Apple ID is not a member of that team |
| `Team ID … is not associated` | `APPLE_TEAM_ID` does not match the certificate's bracketed id |
| Gatekeeper still complains after a successful build | the ticket was not stapled, or the DMG was rebuilt after stapling |

`xcrun notarytool log <submission-id> --apple-id … --team-id … --password …`
prints Apple's actual verdict, file by file. It is worth reading in full before
changing anything.
