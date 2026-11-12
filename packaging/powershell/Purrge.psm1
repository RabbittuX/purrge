# Purrge PowerShell module. Install-Purrge runs the installer bundled in this module, using the bundled
# Purrge code (no need to download Purrge from GitHub). Keep this file ASCII-only: Windows PowerShell 5.1
# reads module files in the system code page.
#   Install-Module Purrge -Scope CurrentUser
#   Install-Purrge                      # optional: --engine claude|codex|workbuddy|deepseek|pi --threshold 15 --yes

function Install-Purrge {
    $passThru = $args
    $installer = Join-Path $PSScriptRoot 'install.ps1'
    $old = $env:PURRGE_SRC
    $env:PURRGE_SRC = $PSScriptRoot
    try {
        $code = Get-Content -Raw -Encoding UTF8 $installer
        & ([scriptblock]::Create($code)) @passThru
    } finally {
        $env:PURRGE_SRC = $old
    }
}

Export-ModuleMember -Function Install-Purrge
