# OCTOPUS - Instala el agente en la VM Windows del laboratorio con el INSTALADOR DEL PANEL
# (el mismo zip que se descarga en "Anadir equipo"). Lo ejecuta Vagrant al aprovisionar win2022.
# Antes, el cerebro deja el zip en C:\vagrant_host\.runtime\octopus-win2022.zip
#   (pruebas_cerebro.sh instalador win2022 windows)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Zip     = "C:\vagrant_host\.runtime\octopus-win2022.zip"
$TestDir = "C:\OctopusTest"
$Inst    = Join-Path $env:TEMP "octopus_inst"

Write-Host "== OCTOPUS: instalando el agente Windows con el instalador del panel =="
for ($i = 0; $i -lt 60 -and -not (Test-Path $Zip); $i++) { Start-Sleep -Seconds 5 }
if (-not (Test-Path $Zip)) { throw "No existe $Zip. El cerebro tiene que generarlo antes (pruebas_cerebro.sh instalador win2022 windows)." }

# Datos de prueba (la carpeta protegida)
New-Item -ItemType Directory -Force -Path "$TestDir\critico" | Out-Null
Set-Content -Path "$TestDir\critico\config.txt" -Value "config original" -Encoding ASCII
if (-not (Test-Path "$TestDir\datos.txt")) { Set-Content -Path "$TestDir\datos.txt" -Value "datos importantes" -Encoding ASCII }

# Quitar restos del agente de laboratorio antiguo (si no existen, no pasa nada)
if (Get-ScheduledTask -TaskName "OCTOPUS_Agent" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "OCTOPUS_Agent" -Confirm:$false -ErrorAction SilentlyContinue
}
Get-NetFirewallRule -DisplayName "OCTOPUS Agent 9999" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue

Remove-Item -Recurse -Force $Inst -ErrorAction SilentlyContinue
Expand-Archive -Path $Zip -DestinationPath $Inst -Force
Write-Host ("Contenido del instalador: " + ((Get-ChildItem $Inst).Name -join ", "))
# Por WinRM, cualquier texto que un programa escriba en la salida de errores se convierte en "error"
# de PowerShell: aqui solo cuenta el codigo de salida del instalador.
$ErrorActionPreference = "Continue"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Inst "instalar_windows.ps1") 2>&1 | ForEach-Object { "$_" }
$rc = $LASTEXITCODE
$ErrorActionPreference = "Stop"
Remove-Item -Recurse -Force $Inst -ErrorAction SilentlyContinue
if ($rc -ne 0) { throw "El instalador del panel termino con codigo $rc" }

# Permitir ping (para las pruebas de conectividad)
Enable-NetFirewallRule -Name "FPS-ICMP4-ERQ-In" -ErrorAction SilentlyContinue
Write-Host "== Agente instalado con el instalador del panel =="
