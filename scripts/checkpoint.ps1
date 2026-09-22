# Create a Git checkpoint at a human<->agent handoff.
#   .\checkpoint.ps1 -Message "agent: create rough cut"
#   .\checkpoint.ps1 -Message "human: tighten opening" -Lab C:\path\to\project
# Run from the project root, or pass -Lab. Message must start with agent:, human: or chore:.
#
# Why the guard rails: a checkpoint is the only reliable way back to a known-good edit, so it
# refuses to record a project Shotcut still has open (Shotcut's next save would overwrite the
# agent's work) or a .mlt that no longer parses.
param(
    [Parameter(Mandatory)][string]$Message,
    [string]$Lab = (Get-Location).Path,
    [switch]$AllowShotcutRunning
)
$ErrorActionPreference = 'Stop'
$scripts = $PSScriptRoot
Set-Location $Lab

# In PowerShell 5.1, anything a native command writes to stderr becomes a terminating error while
# ErrorActionPreference is 'Stop' -- and git reports routine things there (line-ending notices,
# "nothing to commit"). Run git through this so only a non-zero exit code counts as failure.
function Invoke-Git {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & git @args 2>&1
        # keep git's own message so a failure can explain itself instead of just "commit failed"
        $script:GitErr = (($out | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] }) |
                          ForEach-Object { $_.ToString() }) -join "`n"
        $out | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }
    } finally { $ErrorActionPreference = $prev }
}

if ($Message -notmatch '^(agent|human|chore): \S') {
    throw "Commit message must look like 'agent: ...', 'human: ...' or 'chore: ...' (got: '$Message')"
}
if (-not (Test-Path (Join-Path $Lab '.git'))) {
    throw "$Lab is not a git repository. Set it up first:`n" +
          "  git init -b main`n" +
          "  git config user.name '<name>'; git config user.email '<email>'`n" +
          "  copy the toolkit's assets\project-gitignore here as .gitignore"
}
if (-not (Invoke-Git config user.email)) {
    throw "This repo has no git identity, so a commit would fail. Set one:`n" +
          "  git config user.name '<name>'; git config user.email '<email>'"
}
if ((Get-Process shotcut -ErrorAction SilentlyContinue) -and -not $AllowShotcutRunning) {
    throw "Shotcut is running. Save (Ctrl+S) and CLOSE Shotcut before checkpointing/agent edits."
}

# every changed/new .mlt must still parse before it goes into history
$changed = Invoke-Git status --porcelain | ForEach-Object { $_.Substring(3).Trim('"') } |
    Where-Object { $_ -like '*.mlt' -and (Test-Path $_) } | Select-Object -Unique
foreach ($f in $changed) {
    uv run "$scripts\mlt_tools.py" validate $f
    if ($LASTEXITCODE -ne 0) { throw "validation failed for $f - not committing" }
}

if (Test-Path (Join-Path $Lab 'media')) {
    uv run "$scripts\media_manifest.py" | Out-Null   # refresh the small text record of source media
}
if (Test-Path (Join-Path $Lab 'projects\backups')) {
    Invoke-Git check-ignore -q projects/backups | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "note: projects/backups is not git-ignored - those are crash copies, not history."
    }
}
Invoke-Git add -A | Out-Null
if (-not (Invoke-Git status --porcelain)) { Write-Host "Nothing to commit."; exit 0 }
Invoke-Git commit -q -m $Message | Out-Null
if ($LASTEXITCODE -ne 0) { throw "git commit failed:`n$script:GitErr" }
Invoke-Git log -1 --format='checkpoint %h  %s'
