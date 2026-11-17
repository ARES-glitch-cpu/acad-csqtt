$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$version = (Get-Content -LiteralPath VERSION -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'VERSION must contain a version such as 1.1.0' }
if ($env:GITHUB_REF_TYPE -eq 'tag' -and $env:GITHUB_REF_NAME -ne "v$version") {
    throw "Tag $env:GITHUB_REF_NAME does not match VERSION ($version)"
}
$archiveName = "CSQTT-Kolenka-v$version-Win10-x64.zip"

if (Test-Path '.tools\cargo\bin\cargo.exe') {
    $env:CARGO_HOME = Join-Path $PSScriptRoot '.tools\cargo'
    $env:RUSTUP_HOME = Join-Path $PSScriptRoot '.tools\rustup'
    $env:PATH = "$env:CARGO_HOME\bin;$env:PATH"
}
$goExe = if (Get-Command go -ErrorAction SilentlyContinue) { 'go' } elseif (Test-Path 'C:\Go\bin\go.exe') { 'C:\Go\bin\go.exe' } else { throw 'Install Go first.' }

& cargo build --release --locked --manifest-path core\rust-client\Cargo.toml
if ($LASTEXITCODE -ne 0) { throw 'CSQTT build failed' }
New-Item -ItemType Directory -Path bin -Force | Out-Null
Copy-Item -LiteralPath core\rust-client\target\release\client.exe -Destination bin\csqtt-core.exe -Force
Push-Location packet-proxy
try {
    & $goExe build -trimpath -ldflags '-s -w' -o ..\bin\packet-proxy.exe .
    if ($LASTEXITCODE -ne 0) { throw 'Packet proxy build failed' }
} finally { Pop-Location }
$packageDir = Join-Path $PSScriptRoot 'dist\CSQTT-Kolenka'
if (Test-Path -LiteralPath $packageDir) {
    $resolvedPackageDir = (Resolve-Path -LiteralPath $packageDir).Path
    if (-not $resolvedPackageDir.StartsWith($PSScriptRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Package directory must stay inside workspace' }
    Get-ChildItem -LiteralPath $resolvedPackageDir -Recurse -File | ForEach-Object { $_.IsReadOnly = $false }
}
& python -m PyInstaller --noconfirm --onedir --windowed --name CSQTT-Kolenka app.py
if ($LASTEXITCODE -ne 0) { throw 'GUI build failed' }
Copy-Item -LiteralPath bin -Destination $packageDir -Recurse -Force
Copy-Item -LiteralPath "$packageDir\_internal\VCRUNTIME140.dll" -Destination "$packageDir\bin\VCRUNTIME140.dll" -Force
Copy-Item -LiteralPath README.md,LICENSE,NOTICE.md,VERSION -Destination $packageDir -Force
Copy-Item -LiteralPath assets -Destination $packageDir -Recurse -Force
& python collect_licenses.py $packageDir
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
$smoke = Start-Process -FilePath (Join-Path $packageDir 'CSQTT-Kolenka.exe') -ArgumentList '--smoke' -WindowStyle Hidden -PassThru
if (-not $smoke.WaitForExit(15000)) {
    $smoke.Kill()
    throw 'Packaged GUI did not exit within 15 seconds'
}
if ($smoke.ExitCode -ne 0) { throw "Packaged GUI failed: $($smoke.ExitCode)" }
Get-ChildItem -LiteralPath $packageDir -Recurse -File |
    Where-Object Name -ne 'SHA256SUMS.txt' |
    ForEach-Object { '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $_.FullName.Substring($packageDir.Length + 1) } |
    Set-Content -LiteralPath (Join-Path $packageDir 'SHA256SUMS.txt') -Encoding ASCII
& python -c "import pathlib,sys,zipfile; p=pathlib.Path(sys.argv[1]); z=zipfile.ZipFile(sys.argv[2], 'w', zipfile.ZIP_DEFLATED, strict_timestamps=False); [z.write(f, f.relative_to(p)) for f in p.rglob('*') if f.is_file()]; z.close(); z=zipfile.ZipFile(sys.argv[2]); assert z.testzip() is None; assert {'CSQTT-Kolenka.exe','bin/csqtt-core.exe','bin/packet-proxy.exe','bin/VCRUNTIME140.dll','VERSION','SHA256SUMS.txt'}.issubset(z.namelist())" $packageDir $archiveName
if ($LASTEXITCODE -ne 0) { throw 'ZIP packaging failed' }
$archiveHash = (Get-FileHash -LiteralPath $archiveName -Algorithm SHA256).Hash.ToLowerInvariant()
"$archiveHash  $archiveName" | Set-Content -LiteralPath "$archiveName.sha256" -Encoding ASCII
Write-Output "Built $archiveName and $archiveName.sha256"
