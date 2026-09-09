<#
    Apple Developer ID certificate helper - Windows, no Mac needed.

    Run it, do not retype it: the OpenSSL commands are full of hyphens and
    slashes that get mangled when pasted into a terminal.

    Step 1, before you visit developer.apple.com:
        .\tools\apple_csr.ps1 -Step csr -Email you@example.com -Name "Your Name"

    Upload the printed .certSigningRequest at
    https://developer.apple.com/account/resources/certificates
    (+ -> Developer ID -> Developer ID Application) and save the downloaded
    developerID_application.cer into the same working folder.

    Step 2, once you have the .cer:
        .\tools\apple_csr.ps1 -Step p12

    Everything is written to %USERPROFILE%\AppleSigning, deliberately outside
    the repository, because the private key must never be committed.
    See docs/SIGNING.md for what to do with the result.

    This file is deliberately plain ASCII: Windows PowerShell 5.1 reads .ps1
    as ANSI, so a stray em dash or arrow breaks the parse of the whole script.
#>

[CmdletBinding()]
param(
    [ValidateSet("csr", "p12", "readme")]
    [string]$Step = "csr",
    [string]$Email,
    [string]$Name,
    [string]$Country = "CH",
    [string]$WorkDir = (Join-Path $env:USERPROFILE "AppleSigning"),
    [switch]$NewKey
)

$ErrorActionPreference = "Stop"

function Write-FolderReadme {
    param([string]$Folder)

    $path = Join-Path $Folder "README.txt"
    if (Test-Path $path) { return }

    $today = Get-Date -Format "yyyy-MM-dd"
    $lines = @(
        "Apple code-signing material for the Sound xR OSC Bridge",
        "Created $today by $env:USERNAME on $env:COMPUTERNAME",
        "",
        "WHAT THIS IS",
        "  The Developer ID signing identity of the ZHdK Apple Developer team.",
        "  It signs the macOS build of the Sound xR OSC Bridge so that macOS",
        "  opens it without a Gatekeeper warning. It belongs to the school, not",
        "  to one person, and it can sign ANY software as ZHdK.",
        "",
        "  Apple team:  Zurcher Hochschule der Kunste, Team ID ..........",
        "  Repository:  https://github.com/sschiesser/soundXR-OSCbridge",
        "  The full procedure is in that repository, docs/SIGNING.md.",
        "",
        "THE FILES",
        "  developerID.key               the private key. Irreplaceable: the",
        "                                certificate only works with this exact",
        "                                key. Never leaves this machine.",
        "  developerID.certSigningRequest what was sent to Apple. Not secret.",
        "  developerID_application.cer   the certificate Apple issued.",
        "  developerID.pem               the same certificate, PEM encoded.",
        "  DeveloperIDG2CA.cer/.pem      Apple's intermediate, completes the chain.",
        "  certificate.p12               key + certificate + chain in one file,",
        "                                password protected. This is what CI uses.",
        "  certificate.p12.b64           the same, base64 encoded, as pasted into",
        "                                the MACOS_CERTIFICATE_P12 GitHub secret.",
        "",
        "PASSWORDS (not stored here, on purpose)",
        "  - the .p12 password        -> password manager",
        "  - the app-specific password for notarisation, made at",
        "    account.apple.com -> Sign-In and Security -> App-Specific Passwords",
        "",
        "RULES",
        "  - Never commit this folder to git, and never mail it.",
        "  - Back it up encrypted only: password manager, or a 7-Zip archive made",
        "    with -mhe=on before it goes anywhere near OneDrive.",
        "  - Losing these files is recoverable: the team's Account Holder issues",
        "    a new certificate (a team may hold five).",
        "  - Leaking them is not: the certificate must then be revoked, which",
        "    invalidates software already signed with it.",
        "",
        "EXPIRY",
        "  A Developer ID certificate lasts about five years. Check with:",
        "     openssl x509 -in developerID.pem -noout -dates",
        "  Expiry alone does not break already-signed apps - their signatures",
        "  carry a trusted timestamp - but nothing new can be signed after it."
    )
    Set-Content -Path $path -Value $lines -Encoding ASCII
    Write-Host "wrote $path" -ForegroundColor Green
}

function Find-OpenSSL {
    $onPath = Get-Command openssl -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }

    $candidates = @(
        (Join-Path $env:ProgramFiles "Git\usr\bin\openssl.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Git\usr\bin\openssl.exe")
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }

    $sourcetree = Join-Path $env:LOCALAPPDATA "Atlassian\SourceTree\git_local"
    if (Test-Path $sourcetree) {
        $found = Get-ChildItem $sourcetree -Recurse -Filter openssl.exe -ErrorAction SilentlyContinue
        if ($found) { return $found[0].FullName }
    }

    throw "No openssl found. Install Git for Windows:  winget install --id Git.Git -e"
}

if (-not (Test-Path $WorkDir)) { New-Item -ItemType Directory -Path $WorkDir | Out-Null }

# -------------------------------------------------------------- step: readme
# Explains the folder to whoever finds it later. Written by every step; this
# one only writes it, for a folder that already exists.
if ($Step -eq "readme") {
    Write-FolderReadme -Folder $WorkDir
    if (Test-Path (Join-Path $WorkDir "README.txt")) {
        Write-Host "$WorkDir\README.txt is in place. Fill in the Team ID once you know it."
    }
    return
}

$openssl = Find-OpenSSL
Write-Host "openssl: $openssl"

Set-Location $WorkDir
Write-Host "working in: $WorkDir"
Write-FolderReadme -Folder $WorkDir
Write-Host ""

# ----------------------------------------------------------------- step: csr
if ($Step -eq "csr") {
    if (-not $Email -or -not $Name) {
        throw 'Both are required, for example:  -Email you@example.com -Name "Your Name"'
    }

    # An existing key is reused, never overwritten: a certificate Apple has
    # already issued only works with the key its request was made from.
    if ((Test-Path "developerID.key") -and (-not $NewKey)) {
        Write-Host "reusing the key already in this folder (pass -NewKey to start over)"
    }
    else {
        if (Test-Path "developerID.key") {
            $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
            Move-Item "developerID.key" "developerID.key.$stamp.bak"
            Write-Host "previous key kept as developerID.key.$stamp.bak" -ForegroundColor Yellow
        }
        & $openssl genrsa -out developerID.key 2048
        if ($LASTEXITCODE -ne 0) { throw "openssl genrsa failed" }
    }

    # PowerShell passes this through untouched; Git Bash would rewrite the
    # leading slash into a Windows path, which is why this script exists.
    $subject = "/emailAddress=$Email/CN=$Name/C=$Country"
    & $openssl req -new -key developerID.key -out developerID.certSigningRequest -subj $subject
    if ($LASTEXITCODE -ne 0) { throw "openssl req failed" }

    Write-Host ""
    & $openssl req -in developerID.certSigningRequest -noout -subject
    Write-Host ""
    Write-Host "Upload this file:" -ForegroundColor Green
    Write-Host "   $WorkDir\developerID.certSigningRequest"
    Write-Host "at https://developer.apple.com/account/resources/certificates"
    Write-Host "   +  ->  Developer ID  ->  Developer ID Application"
    Write-Host ""
    Write-Host "Save the downloaded developerID_application.cer into $WorkDir,"
    Write-Host "then run:  .\tools\apple_csr.ps1 -Step p12"
    Write-Host ""
    Write-Host "Keep developerID.key. Without it the certificate is worthless." -ForegroundColor Yellow
    return
}

# ----------------------------------------------------------------- step: p12
if (-not (Test-Path "developerID.key")) {
    throw "developerID.key is missing from $WorkDir. Run -Step csr first."
}
if (-not (Test-Path "developerID_application.cer")) {
    throw "developerID_application.cer is missing from $WorkDir. Download it from developer.apple.com first."
}

# Apple's intermediate, so the chain is complete on a bare CI runner
if (-not (Test-Path "DeveloperIDG2CA.cer")) {
    Write-Host "fetching Apple's intermediate certificate..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "https://www.apple.com/certificateauthority/DeveloperIDG2CA.cer" -OutFile "DeveloperIDG2CA.cer" -UseBasicParsing
}
& $openssl x509 -inform DER -in DeveloperIDG2CA.cer -out DeveloperIDG2CA.pem
& $openssl x509 -inform DER -in developerID_application.cer -out developerID.pem
if ($LASTEXITCODE -ne 0) { throw "the .cer could not be read. Is it the file Apple issued?" }

Write-Host ""
Write-Host "Choose a password for the .p12. You will need it again as the" -ForegroundColor Yellow
Write-Host "MACOS_CERTIFICATE_PASSWORD secret, so write it down now." -ForegroundColor Yellow
& $openssl pkcs12 -export -legacy -inkey developerID.key -in developerID.pem -certfile DeveloperIDG2CA.pem -out certificate.p12
if ($LASTEXITCODE -ne 0) { throw "openssl pkcs12 failed" }

$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("certificate.p12"))
Set-Content -Path "certificate.p12.b64" -Value $b64 -NoNewline
$clip = ""
try { Set-Clipboard -Value $b64; $clip = " (also copied to the clipboard)" } catch { }

Write-Host ""
Write-Host "Done. The six GitHub secrets:" -ForegroundColor Green
Write-Host "  MACOS_CERTIFICATE_P12        <- certificate.p12.b64$clip"
Write-Host "  MACOS_CERTIFICATE_PASSWORD   <- the password you just chose"
$subjectLine = & $openssl x509 -in developerID.pem -noout -subject
Write-Host "  MACOS_SIGN_IDENTITY          <- the CN= part of:"
Write-Host "        $subjectLine"
Write-Host "  APPLE_ID                     <- your Apple ID email"
Write-Host "  APPLE_TEAM_ID                <- the 10 characters in brackets above"
Write-Host "  APPLE_APP_PASSWORD           <- app-specific password from account.apple.com"
Write-Host ""
Write-Host "Add them at: the repo -> Settings -> Secrets and variables -> Actions"
