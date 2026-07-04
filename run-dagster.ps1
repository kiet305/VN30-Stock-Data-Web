param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Env:DAGSTER_HOME = Join-Path $Root "dagster_home"

if ($Install) {
    Push-Location (Join-Path $Root "etl_pipeline")
    pip install -e ".[dev]"
    Pop-Location
}

Push-Location (Join-Path $Root "etl_pipeline")
dagster dev
Pop-Location

