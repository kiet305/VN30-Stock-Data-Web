$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

python (Join-Path $PSScriptRoot "server.py") --source auto --host 127.0.0.1 --port 8765
