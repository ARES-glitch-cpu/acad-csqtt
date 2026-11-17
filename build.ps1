# Keep the existing build command working; build tools live in scripts/.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'scripts/build.ps1')
