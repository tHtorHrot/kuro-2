param([switch]$CleanupTestVolumes)
$ErrorActionPreference = 'Stop'
$kuroRoot = Split-Path -Parent $PSScriptRoot
Set-Location $kuroRoot
Get-Command python -ErrorAction Stop | Out-Null
Get-Command docker -ErrorAction Stop | Out-Null
$kuroEvidence = Join-Path $kuroRoot 'docs\evidence\native-candidate'
New-Item -ItemType Directory -Force -Path $kuroEvidence | Out-Null
$kuroRun = Join-Path $kuroEvidence 'run'
if (Test-Path $kuroRun) {
    $kuroArchive = Join-Path $kuroEvidence ('run-' + (Get-Date -Format 'yyyyMMddTHHmmssfff'))
    Move-Item -LiteralPath $kuroRun -Destination $kuroArchive
}
# The standalone project is a fixed disposable target; no production Compose overlay is merged.
# Reset it because bootstrap intentionally refuses a populated test cluster.
docker compose -p personal-jarvis-tests -f compose.test.yaml down --volumes
$kuroResetExit = $LASTEXITCODE
if ($kuroResetExit -ne 0) { throw 'Reset project TEST gagal; gate dihentikan.' }
$kuroLog = Join-Path $kuroEvidence 'compose-gate.log'
# Docker writes ordinary progress to stderr. Windows PowerShell can promote
# redirected native stderr to NativeCommandError under ErrorActionPreference=Stop.
# Python merges the native streams before PowerShell sees them, preserving bytes
# in the log and returning the actual Compose exit code. No policy is relaxed.
python (Join-Path $PSScriptRoot 'run_test_compose.py') --log $kuroLog
$kuroTestExit = $LASTEXITCODE
Set-Content -Encoding ASCII -LiteralPath (Join-Path $kuroEvidence 'compose-exit-code.txt') -Value $kuroTestExit
if ($CleanupTestVolumes) {
    docker compose -p personal-jarvis-tests -f compose.test.yaml down --volumes
    $kuroCleanupExit = $LASTEXITCODE
    if ($kuroCleanupExit -ne 0) { Write-Warning 'Cleanup TEST gagal; volume produksi tidak disentuh.' }
}
if ($kuroTestExit -ne 0) { throw "Gate gagal (exit $kuroTestExit); jangan rollout." }
if (-not (Test-Path (Join-Path $kuroRun 'verification.json'))) { throw 'Bukti JSON gate tidak tersimpan.' }
Write-Output 'Gate selesai. Log, pytest.xml, verification.json ada di docs/evidence/native-candidate/run.'
exit $kuroTestExit
