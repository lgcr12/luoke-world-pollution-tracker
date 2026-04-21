$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$py = Join-Path $root '.packenv\Scripts\python.exe'
$requirements = @(
  'pyinstaller',
  'rapidocr-onnxruntime',
  'opencv-python',
  'numpy',
  'mss',
  'PyGetWindow',
  'PySide6==6.8.2.1'
)
$distName = 'luoke_pollution_tracker'
$releaseDir = Join-Path $root 'release'
$workDir = Join-Path $root '.pyi_build'

if (-not (Test-Path $py)) {
  py -3.12 -m venv .packenv
}

& $py -m pip install --upgrade pip
& $py -m pip install @requirements

& $py -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name $distName `
  --distpath $releaseDir `
  --workpath $workDir `
  --add-data "assets;assets" `
  --add-data "species_names.json;." `
  --add-data "species_attributes.json;." `
  --add-data "config.json;." `
  --add-data "state.json;." `
  --add-data "report.csv;." `
  --hidden-import rapidocr_onnxruntime `
  --hidden-import pygetwindow `
  gui_qt.py
