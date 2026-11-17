$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$version = (Get-Content -LiteralPath VERSION -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'VERSION must contain a version such as 1.1.0' }
if ($env:GITHUB_REF_TYPE -eq 'tag' -and $env:GITHUB_REF_NAME -ne "v$version") {
    throw "Tag $env:GITHUB_REF_NAME does not match VERSION ($version)"
}
$archiveName = "CSQTT-v$version-Win10-x64.zip"

if (Test-Path '.tools\cargo\bin\cargo.exe') {
    $env:CARGO_HOME = Join-Path $projectRoot '.tools\cargo'
    $env:RUSTUP_HOME = Join-Path $projectRoot '.tools\rustup'
    $env:PATH = "$env:CARGO_HOME\bin;$env:PATH"
}
$goExe = if (Get-Command go -ErrorAction SilentlyContinue) { 'go' } elseif (Test-Path 'C:\Go\bin\go.exe') { 'C:\Go\bin\go.exe' } else { throw 'Install Go first.' }

& cargo build --release --locked --manifest-path core\rust-client\Cargo.toml
if ($LASTEXITCODE -ne 0) { throw 'CSQTT build failed' }
New-Item -ItemType Directory -Path bin -Force | Out-Null

# WireGuard Go loads the signed Wintun DLL from the helper executable directory.
# Pin both the upstream archive SHA-256 and the architecture-specific DLL.
$wintunVersion = '0.14.1'
$wintunSha256 = '07c256185d6ee3652e09fa55c0b673e2624b565e02c4b9091c79ca7d2f24ef51'
$wintunArchive = Join-Path $env:TEMP "wintun-$wintunVersion.zip"
$wintunExtract = Join-Path $env:TEMP "csqtt-wintun-$wintunVersion"
Invoke-WebRequest -Uri "https://www.wintun.net/builds/wintun-$wintunVersion.zip" -OutFile $wintunArchive
$actualWintunHash = (Get-FileHash -LiteralPath $wintunArchive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualWintunHash -ne $wintunSha256) {
    throw "Wintun archive SHA-256 mismatch: expected $wintunSha256, got $actualWintunHash"
}
if (Test-Path -LiteralPath $wintunExtract) { Remove-Item -LiteralPath $wintunExtract -Recurse -Force }
Expand-Archive -LiteralPath $wintunArchive -DestinationPath $wintunExtract -Force
$wintunDll = Join-Path $wintunExtract 'wintun\bin\amd64\wintun.dll'
$wintunLicense = Join-Path $wintunExtract 'wintun\LICENSE.txt'
if (-not (Test-Path -LiteralPath $wintunDll) -or -not (Test-Path -LiteralPath $wintunLicense)) {
    throw 'Official Wintun archive is missing the AMD64 DLL or license file.'
}
Copy-Item -LiteralPath $wintunDll -Destination bin\wintun.dll -Force
Copy-Item -LiteralPath $wintunLicense -Destination bin\WINTUN-LICENSE.txt -Force

Copy-Item -LiteralPath core\rust-client\target\release\client.exe -Destination bin\csqtt-core.exe -Force
Push-Location packet-proxy
try {
    & $goExe build -trimpath -ldflags '-s -w' -o ..\bin\packet-proxy.exe .
    if ($LASTEXITCODE -ne 0) { throw 'Packet proxy build failed' }
} finally { Pop-Location }
$packageDir = Join-Path $projectRoot 'dist\CSQTT'
if (Test-Path -LiteralPath $packageDir) {
    $resolvedPackageDir = (Resolve-Path -LiteralPath $packageDir).Path
    if (-not $resolvedPackageDir.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Package directory must stay inside workspace' }
    Get-ChildItem -LiteralPath $resolvedPackageDir -Recurse -File | ForEach-Object { $_.IsReadOnly = $false }
}
& python scripts\prepare_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icon preparation failed' }
& python -m PyInstaller --noconfirm --onedir --windowed --name CSQTT --icon assets\icons\CSQTT.ico main.py
if ($LASTEXITCODE -ne 0) { throw 'GUI build failed' }
Copy-Item -LiteralPath bin -Destination $packageDir -Recurse -Force
Copy-Item -LiteralPath "$packageDir\_internal\VCRUNTIME140.dll" -Destination "$packageDir\bin\VCRUNTIME140.dll" -Force
Copy-Item -LiteralPath README.md,LICENSE,NOTICE.md,VERSION -Destination $packageDir -Force
Copy-Item -LiteralPath assets -Destination $packageDir -Recurse -Force
& python scripts\collect_licenses.py $packageDir
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
$smoke = Start-Process -FilePath (Join-Path $packageDir 'CSQTT.exe') -ArgumentList '--smoke' -WindowStyle Hidden -PassThru
if (-not $smoke.WaitForExit(15000)) {
    $smoke.Kill()
    throw 'Packaged GUI did not exit within 15 seconds'
}
if ($smoke.ExitCode -ne 0) { throw "Packaged GUI failed: $($smoke.ExitCode)" }
Get-ChildItem -LiteralPath $packageDir -Recurse -File |
    Where-Object Name -ne 'SHA256SUMS.txt' |
    ForEach-Object { '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $_.FullName.Substring($packageDir.Length + 1) } |
    Set-Content -LiteralPath (Join-Path $packageDir 'SHA256SUMS.txt') -Encoding ASCII
& python -c "import pathlib,sys,zipfile; p=pathlib.Path(sys.argv[1]); z=zipfile.ZipFile(sys.argv[2], 'w', zipfile.ZIP_DEFLATED, strict_timestamps=False); [z.write(f, f.relative_to(p)) for f in p.rglob('*') if f.is_file()]; z.close(); z=zipfile.ZipFile(sys.argv[2]); assert z.testzip() is None; assert {'CSQTT.exe','bin/csqtt-core.exe','bin/packet-proxy.exe','bin/wintun.dll','bin/WINTUN-LICENSE.txt','bin/VCRUNTIME140.dll','assets/icons/CSQTT.ico','VERSION','SHA256SUMS.txt'}.issubset(z.namelist())" $packageDir $archiveName
if ($LASTEXITCODE -ne 0) { throw 'ZIP packaging failed' }
$archiveHash = (Get-FileHash -LiteralPath $archiveName -Algorithm SHA256).Hash.ToLowerInvariant()
"$archiveHash  $archiveName" | Set-Content -LiteralPath "$archiveName.sha256" -Encoding ASCII
Write-Output "Built $archiveName and $archiveName.sha256"
