<#
OCTOPUS - Prueba del SERVIDOR OCTOPUS NATIVO en Windows 11 (sin WSL2 ni Docker), en una maquina virtual del laboratorio.

Lo que no se puede probar en GitHub y aqui si:
  - que otro equipo de la red (este PC) llega al panel y al almacen,
  - que tras un REINICIO DE VERDAD del equipo el servidor vuelve a estar en marcha SIN QUE NADIE INICIE SESION,
  - un agente de verdad (en la misma VM) haciendo copia y restaurando contra el servidor de Windows.

  1. Apaga las demas maquinas (memoria) y levanta win11srv (o la que se pase con -VM, p. ej. win2022).
  2. Ejecuta el instalador nativo (lo mismo que el doble clic en INSTALAR_SERVIDOR_WINDOWS.bat).
  3. Comprueba desde fuera de la VM, reinicia la VM y vuelve a comprobar, y prueba un agente.
Informe en reportes\informe_<fecha>.txt; registros del servidor copiados a reportes\servidor_windows_*.
#>
param([string]$VM = "win11srv")
. "$PSScriptRoot\scripts\comun.ps1"
$IP = if ($VM -eq "win2022") { "192.168.10.40" } else { "192.168.10.70" }
$R = "C:\ProgramData\OCTOPUS-Servidor"
Write-Log "=== OCTOPUS - prueba del SERVIDOR NATIVO en Windows ($VM, sin WSL2 ni Docker) ===" "Green"

Write-Log "Apagando las demas maquinas para dejar memoria libre..." "Yellow"
$otras = @("cerebro", "cliente1", "cliente2", "debian12", "rocky9", "win2022", "win11srv") | Where-Object { $_ -ne $VM }
Invoke-Vagrant (@("halt") + $otras) | Out-Null

Write-Log "Levantando $VM (la primera vez descarga la maquina: puede tardar mucho)..." "Yellow"
$rc = Invoke-VagrantLimite @("up", $VM) 120
if ($rc -ne 0) { Add-Result "FAIL" "vagrant up $VM" "codigo $rc (ver log)"; exit (Write-Report) }
Add-Result "PASS" "vagrant up $VM" $IP

# Desde FUERA de la VM (este PC hace de equipo de la red)
Add-Type @"
using System.Net; using System.Security.Cryptography.X509Certificates;
public class OctoSinValidar : ICertificatePolicy {
  public bool CheckValidationResult(ServicePoint s, X509Certificate c, WebRequest r, int p) { return true; } }
"@ -ErrorAction SilentlyContinue
[Net.ServicePointManager]::CertificatePolicy = New-Object OctoSinValidar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
function Panel { try { return (Invoke-WebRequest "https://$($IP):8080/healthz" -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop).Content } catch { return "" } }
function Esperar-Panel($minutos) { $fin = (Get-Date).AddMinutes($minutos); while ((Get-Date) -lt $fin) { $p = Panel; if ($p) { return $p }; Start-Sleep -Seconds 10 }; return "" }
function Almacen {
    try { Invoke-WebRequest "https://$($IP):8000/" -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop | Out-Null; return "responde" }
    catch { if ("$($_.Exception.Message)" -match "401") { return "pide contrasena (401)" } else { return "" } }
}

# 1. La red de laboratorio de VirtualBox sale como «red publica» (como muchas redes de oficina sin identificar). No se
#    toca: el instalador tiene que funcionar igual, sin que nadie cambie el tipo de red.
$perfiles = Invoke-WinVM $VM "(Get-NetConnectionProfile).NetworkCategory -join ','"
Write-Log "Tipo de red en ${VM}: $((@($perfiles.Output) -join ' ').Trim()) (se deja como esta)" "Gray"

# 2. Instalar como lo haria una persona (el .bat llama a este mismo instalador; aqui ya somos administrador)
Write-Log "Instalando el servidor nativo en $VM (unos minutos: descarga Python, restic y rest-server)..." "Cyan"
$t0 = Get-Date
$i = Invoke-WinVM $VM "Remove-Item 'C:\OctopusServidor' -Recurse -Force -ErrorAction SilentlyContinue; robocopy C:\OCTOPUS C:\OctopusServidor /MIR /XD __pycache__ .git data datos /XF .env /NFL /NDL /NJH /NJS | Out-Null; & powershell -NoProfile -ExecutionPolicy Bypass -File C:\OctopusServidor\instalar_servidor_windows.ps1 -SinPreguntas -IP $IP -Registro C:\OctopusServidor\instalacion.log; `"CODIGO=`$LASTEXITCODE`""
$codigo = if (($i.Output -join " ") -match "CODIGO=(-?\d+)") { [int]$Matches[1] } else { -1 }
Invoke-WinVM $VM "Copy-Item C:\OctopusServidor\instalacion.log C:\vagrant_host\reportes\servidor_windows_instalacion.log -Force -ErrorAction SilentlyContinue; Copy-Item `$env:ProgramData\OCTOPUS-Servidor-instalacion.txt C:\vagrant_host\reportes\servidor_windows_progreso.txt -Force -ErrorAction SilentlyContinue" | Out-Null
if ($codigo -eq 0) { Add-Result "PASS" "${VM}: instalador nativo terminado sin errores" ("{0:N0} s, sin WSL2 ni Docker" -f ((Get-Date) - $t0).TotalSeconds) }
else { Add-Result "FAIL" "${VM}: instalador nativo" ("codigo $codigo. " + (($i.Output | Select-Object -Last 8) -join " | ")); exit (Write-Report) }

$p = Esperar-Panel 3
if ($p) { Add-Result "PASS" "servidor en Windows: panel accesible desde la red (8080)" $p } else { Add-Result "FAIL" "servidor en Windows: panel accesible desde la red (8080)" "no responde en https://$($IP):8080" }
$a = Almacen
if ($a) { Add-Result "PASS" "servidor en Windows: almacen accesible desde la red (8000)" $a } else { Add-Result "FAIL" "servidor en Windows: almacen accesible desde la red (8000)" }
$w = (Invoke-WinVM $VM "if (Get-Command wsl.exe -ErrorAction SilentlyContinue) { try { wsl.exe --status *> `$null; if (`$LASTEXITCODE -eq 0) { 'wsl-activo' } else { 'sin-wsl' } } catch { 'sin-wsl' } } else { 'sin-wsl' }; if (Get-Process 'Rancher Desktop', 'dockerd', 'com.docker*' -ErrorAction SilentlyContinue) { 'docker' }").Output -join " "
if ($w -notmatch "wsl-activo|docker") { Add-Result "PASS" "${VM}: funciona sin WSL2 ni Docker" $w } else { Add-Result "WARN" "${VM}: hay WSL2 o Docker en la maquina (OCTOPUS no los usa)" $w }

# 3. Reinicio de verdad, sin iniciar sesion: tiene que volver solo
Write-Log "Reiniciando $VM (sin iniciar sesion despues): el servidor tiene que volver a arrancar solo..." "Yellow"
Invoke-WinVM $VM "Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' AutoAdminLogon '0' -ErrorAction SilentlyContinue" | Out-Null
$rc = Invoke-VagrantLimite @("reload", $VM) 30
$p = Esperar-Panel 10
if ($p) { Add-Result "PASS" "tras reiniciar el equipo, el servidor vuelve solo (sin iniciar sesion)" $p }
else { Add-Result "FAIL" "tras reiniciar el equipo, el servidor vuelve solo (sin iniciar sesion)" "reload=$rc; el panel no responde a los 10 min" }
$s = (Invoke-WinVM $VM "query user 2>`$null; if (`$LASTEXITCODE -ne 0) { 'nadie con sesion iniciada' }").Output -join " "
Write-Log "  sesiones en $($VM): $s" "DarkGray"

# 4. Si se para de golpe, vuelve solo
Invoke-WinVM $VM "Get-CimInstance Win32_Process | Where-Object { `$_.ExecutablePath -like '$R\*' } | ForEach-Object { Stop-Process -Id `$_.ProcessId -Force }" | Out-Null
Start-Sleep -Seconds 5
$p = Esperar-Panel 4
if ($p) { Add-Result "PASS" "${VM}: si se para de golpe, vuelve a arrancar solo" } else { Add-Result "FAIL" "${VM}: si se para de golpe, vuelve a arrancar solo" }

# 5. Un agente de verdad en la misma VM: alta, instalacion, copia y restauracion contra el servidor de Windows
Write-Log "Probando un agente contra el servidor de Windows (copia y restauracion)..." "Cyan"
$agente = @"
`$env:OCTOPUS_NATIVO='1'; `$env:OCTOPUS_DATA='$R\datos'; `$env:OCTOPUS_BOVEDA_DIR='$R\boveda'; `$env:OCTOPUS_BIN='$R\bin'
`$env:RESTIC_CACHE_DIR='$R\datos\.cache\restic'; `$env:PYTHONUTF8='1'; `$env:PATH='$R\bin;' + `$env:PATH
New-Item -ItemType Directory -Force '$R\tests\ci' | Out-Null; Copy-Item C:\OCTOPUS\tests\ci\prueba_agente.py '$R\tests\ci\' -Force
& '$R\python\python.exe' '$R\tests\ci\prueba_agente.py' preparar windows lab-agente C:\octopus_lab C:\octopus_lab_inst
& powershell -NoProfile -ExecutionPolicy Bypass -File C:\octopus_lab_inst\instalar_windows.ps1 *> C:\octopus_lab_inst\agente.log
& '$R\python\python.exe' '$R\tests\ci\prueba_agente.py' probar lab-agente C:\octopus_lab
"@
$g = Invoke-WinVM $VM $agente
foreach ($l in @($g.Output | Where-Object { "$_" -like "RESULT|*" })) {
    $c = "$l" -split "\|", 4
    Add-Result $c[1] "agente en $($VM): $($c[2])" $c[3]
}
if (-not @($g.Output | Where-Object { "$_" -like "RESULT|*" }).Count) { Add-Result "FAIL" "agente en $($VM)" (($g.Output | Select-Object -Last 6) -join " | ") }

Invoke-WinVM $VM "Copy-Item '$R\datos\logs\servidor.log' C:\vagrant_host\reportes\servidor_windows_servidor.log -Force -ErrorAction SilentlyContinue" | Out-Null
Write-Log "Panel del servidor en Windows: https://$($IP):8080  (usuario admin; contrasena en $R\data\CREDENCIALES_INICIALES.txt dentro de la VM)" "Cyan"
exit (Write-Report "PRUEBA DEL SERVIDOR NATIVO EN WINDOWS")
