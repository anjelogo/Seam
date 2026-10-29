# Windows sim env for the taichi engine: gstaichi + numpy only. Run from gen3d/drape.
# Usage: powershell -ExecutionPolicy Bypass -File drape/scripts/setup_taichi.ps1 [-Python C:\Python312\python.exe]
param([string]$Python = "py -3.12")
$ErrorActionPreference = "Stop"
if (-not (Test-Path pyproject.toml) -or -not (Test-Path drape/sim_taichi)) { throw "run from gen3d/drape" }
if (-not (Test-Path .venv-taichi)) { Invoke-Expression "$Python -m venv .venv-taichi" }
$py = ".\.venv-taichi\Scripts\python.exe"
& $py -m pip install -q --upgrade pip
& $py -m pip install -q "gstaichi==4.6.0" "numpy==2.5.4"
& $py -c "import gstaichi as ti; ti.init(arch=ti.vulkan, log_level=ti.TRACE)" 2>&1 | Select-String "Found Vulkan Device"
& $py -m pip freeze
Write-Output "next: $py -m drape.sim_taichi.run --scene <name>_scene.npz --arch vulkan --out <dir>"
