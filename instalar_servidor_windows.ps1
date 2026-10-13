# OCTOPUS Zero-Touch - Instalador del SERVIDOR para Windows 10 / 11 / Server 2019-2025 (NATIVO: sin WSL2 ni Docker)
#
#   Doble clic en INSTALAR_SERVIDOR_WINDOWS.bat. Windows pide permiso de administrador una vez y ya esta.
#   o:  powershell -ExecutionPolicy Bypass -File instalar_servidor_windows.ps1 [-IP 192.168.1.10] [-Boveda D:\Copias]
#
# Que hace (sin preguntar nada ni reiniciar):
#   1. Descarga Python portatil, restic y rest-server (versiones fijas, comprobando su huella SHA-256: si una
#      descarga no coincide, no se instala nada).
#   2. Copia OCTOPUS a C:\ProgramData\OCTOPUS-Servidor e instala lo que necesita (solo dentro de esa carpeta).
#   3. Lo deja como tarea del sistema: arranca solo al encender el equipo, aunque nadie inicie sesion, y se vuelve
#      a levantar solo si se para.
#   4. Abre los puertos 8080 (panel) y 8000 (almacen) en el Firewall de Windows y abre el panel en el navegador.
#   Volver a ejecutarlo actualiza a la version de esta carpeta sin perder datos ni copias (y si la nueva no arranca,
#   vuelve sola a la anterior).
param(
    [string]$IP = "",
    [string]$Boveda = "",
    [switch]$SinPreguntas,
    [string]$Registro = "",
    [string]$Destino = "$env:ProgramData\OCTOPUS-Servidor",
    [string]$Descargas = ""      # carpeta con las descargas ya hechas (instalar sin Internet); se comprueban igual
)
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$Raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$R = $Destino.TrimEnd('\')
$Tarea = "OCTOPUS Servidor"

# Versiones fijas y sus huellas (si GitHub o alguien por el camino cambiara un archivo, no se instala)
$PYTHON_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/20250818/cpython-3.12.11%2B20250818-x86_64-pc-windows-msvc-install_only.tar.gz"
$PYTHON_SHA = "a6bc8c4658a758ec0c111b5f887f80595943fd84f28bbbaea6e7e30c7815dd26"
$RESTIC_URL = "https://github.com/restic/restic/releases/download/v0.16.4/restic_0.16.4_windows_amd64.zip"
$RESTIC_SHA = "911a1b84f2100d2ac691c0bb28955fd2ab65e76cb2dbe651b21f6072a508e2be"
$REST_URL   = "https://github.com/restic/rest-server/releases/download/v0.13.0/rest-server_0.13.0_windows_amd64.tar.gz"
$REST_SHA   = "b8c465acfc242985767ed53297eb71ee48eba666d16fafbe324a8883a59251d4"

# Banderines: cada paso queda apuntado con la hora, para saber siempre hasta donde llego y por que se paro
$Progreso = Join-Path $env:ProgramData "OCTOPUS-Servidor-instalacion.txt"
function Marca($t) {
    try { Add-Content -Path $Progreso -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $t) -Encoding UTF8 } catch { }
}
function Paso($t)  { Marca "==> $t"; Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Bien($t)  { Marca "OK  $t"; Write-Host "    $t" -ForegroundColor Green }
function Aviso($t) { Marca "..  $t"; Write-Host "    $t" -ForegroundColor Yellow }
function Pausa { if (-not $SinPreguntas) { Read-Host "Pulsa Intro para cerrar" | Out-Null } }
function Fallo($t) { Marca "ERROR $t"; Write-Host ""; Write-Host "ERROR: $t" -ForegroundColor Red; Pausa; if ($Registro) { Stop-Transcript | Out-Null }; exit 1 }

# ------------------------------------------------------------------ administrador (Windows lo pide una vez)
$yo = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $yo.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $a = "-NoProfile -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`""
    if ($IP) { $a += " -IP `"$IP`"" }
    if ($Boveda) { $a += " -Boveda `"$Boveda`"" }
    if ($SinPreguntas) { $a += " -SinPreguntas" }
    if ($Registro) { $a += " -Registro `"$Registro`"" }
    if ($Descargas) { $a += " -Descargas `"$Descargas`"" }
    if ($Destino -ne "$env:ProgramData\OCTOPUS-Servidor") { $a += " -Destino `"$Destino`"" }
    Start-Process powershell -Verb RunAs -ArgumentList $a
    exit 0
}
Marca "---- inicio de la instalacion (PID $PID, usuario $env:USERNAME) ----"
if ($Registro) { try { Start-Transcript -Path $Registro -Append -ErrorAction Stop | Out-Null } catch { } }
if (-not (Test-Path (Join-Path $Raiz "lib\servidor.py"))) { Fallo "No encuentro lib\servidor.py. Ejecuta este archivo desde la carpeta de OCTOPUS." }
$os = Get-CimInstance Win32_OperatingSystem
Write-Host "OCTOPUS Zero-Touch - instalacion del servidor en Windows   ($($os.Caption), compilacion $($os.BuildNumber))" -ForegroundColor White
if ([int]$os.BuildNumber -lt 17763) { Fallo "Hace falta Windows 10 (1809) / Server 2019 o posterior." }
if (-not [Environment]::Is64BitOperatingSystem) { Fallo "Hace falta un Windows de 64 bits." }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ------------------------------------------------------------------ utilidades
function Leer-Ajuste($archivo, $clave) {
    if (-not (Test-Path $archivo)) { return "" }
    $l = Get-Content $archivo -ErrorAction SilentlyContinue | Where-Object { $_ -match "^$clave=" } | Select-Object -Last 1
    if ($l) { return ($l -split "=", 2)[1].Trim().Trim('"') } else { return "" }
}
function Escribir-Texto($ruta, $texto) {
    [IO.File]::WriteAllText($ruta, ($texto -replace "`r`n", "`n"), (New-Object Text.UTF8Encoding($false)))
}
function Descargar($url, $sha, $nombre) {
    $dest = Join-Path $script:Tmp $nombre
    if ($Descargas -and (Test-Path (Join-Path $Descargas $nombre))) { Copy-Item (Join-Path $Descargas $nombre) $dest -Force }
    else {
        for ($i = 1; $i -le 3; $i++) {
            try { Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -TimeoutSec 600 -ErrorAction Stop; break }
            catch { Marca "descarga de $nombre fallida (intento $i): $($_.Exception.Message)"; Start-Sleep -Seconds (5 * $i) }
        }
    }
    if (-not (Test-Path $dest)) { Fallo "No se pudo descargar $nombre. Comprueba la conexion a Internet y vuelve a intentarlo." }
    $h = (Get-FileHash -Algorithm SHA256 $dest).Hash.ToLower()
    if ($h -ne $sha) { Remove-Item $dest -Force; Fallo "La descarga de $nombre no es la oficial (huella distinta): por seguridad no se instala nada." }
    Bien "$nombre descargado y comprobado"
    return $dest
}
function Procesos-Octopus {
    # todo lo que esta corriendo desde la carpeta de OCTOPUS (python del servidor, rest-server, el lanzador)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($R, [StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine -like "*$R\arrancar_servidor.ps1*") }
}
function Parar-Octopus {
    Stop-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 3; $i++) {
        $p = @(Procesos-Octopus)
        if ($p.Count -eq 0) { return }
        $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 2
    }
}
# los certificados son propios de OCTOPUS: para comprobar que responde no se valida el certificado
Add-Type @"
using System.Net; using System.Security.Cryptography.X509Certificates;
public class OctopusSinValidar : ICertificatePolicy {
  public bool CheckValidationResult(ServicePoint s, X509Certificate c, WebRequest r, int p) { return true; } }
"@ -ErrorAction SilentlyContinue
function Responde($url) {
    $ant = [Net.ServicePointManager]::CertificatePolicy
    try { [Net.ServicePointManager]::CertificatePolicy = New-Object OctopusSinValidar
          $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop; return $r.StatusCode -lt 500 }
    catch { return $false } finally { [Net.ServicePointManager]::CertificatePolicy = $ant }
}

$script:Tmp = Join-Path $env:TEMP ("octopus_inst_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $script:Tmp | Out-Null
$HostEnv = Join-Path $R "install\.env"
$yaEstaba = Test-Path (Join-Path $R "lib\servidor.py")

# ------------------------------------------------------------------ direccion y ajustes
Paso "Direccion del servidor"
if (-not $IP) { $IP = Leer-Ajuste $HostEnv "OCTOPUS_IP" }
if (-not $IP) {
    $IP = (Get-NetIPConfiguration -ErrorAction SilentlyContinue | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
           Select-Object -First 1).IPv4Address.IPAddress
}
if (-not $IP) { Fallo "No se pudo averiguar la IP de este equipo. Ejecuta: instalar_servidor_windows.ps1 -IP <ip>" }
Bien "Los equipos llegaran al servidor por $IP"
if (-not $Boveda) { $Boveda = Leer-Ajuste $HostEnv "OCTOPUS_BOVEDA_DIR" }
if (-not $Boveda) { $Boveda = Join-Path $R "boveda" }
$pPanel = Leer-Ajuste $HostEnv "ADMIN_PORT"; if (-not $pPanel) { $pPanel = "8080" }
$pAlm = "8000"

# ------------------------------------------------------------------ descargas
Paso "Descargando lo necesario (Python portatil, restic y rest-server)"
$fPy = Descargar $PYTHON_URL $PYTHON_SHA "python.tar.gz"
$fRestic = Descargar $RESTIC_URL $RESTIC_SHA "restic.zip"
$fRest = Descargar $REST_URL $REST_SHA "rest-server.tar.gz"

# ------------------------------------------------------------------ copia de la version actual (por si hay que volver)
$Anterior = "$R.anterior"
$Excluir = @("datos", "boveda", "python", "bin", "data", ".git", "__pycache__")
if ($yaEstaba) {
    Paso "Guardando la version instalada por si hay que volver a ella"
    Parar-Octopus
    if (Test-Path $Anterior) { Remove-Item -Recurse -Force $Anterior -ErrorAction SilentlyContinue }
    & robocopy $R $Anterior /E /NFL /NDL /NJH /NJS /NP /XD @Excluir | Out-Null
    Bien "copia guardada en $Anterior"
}

# ------------------------------------------------------------------ instalar
Paso "Instalando OCTOPUS en $R"
New-Item -ItemType Directory -Force -Path $R, "$R\bin", "$R\datos\logs", "$R\install", $Boveda | Out-Null
if ($Raiz.TrimEnd('\') -ne $R) {
    & robocopy $Raiz $R /E /NFL /NDL /NJH /NJS /NP /XD @Excluir "tests" /XF ".env" "CREDENCIALES_INICIALES.txt" "*.pyc" | Out-Null
    if ($LASTEXITCODE -ge 8) { Fallo "No se pudieron copiar los archivos de OCTOPUS (robocopy $LASTEXITCODE)" }
}
# Python portatil (solo dentro de la carpeta de OCTOPUS: no toca ningun otro Python del equipo)
if (Test-Path "$R\python") { Remove-Item -Recurse -Force "$R\python" -ErrorAction SilentlyContinue }
& tar.exe -xzf $fPy -C $R
if (-not (Test-Path "$R\python\python.exe")) { Fallo "No se pudo descomprimir Python" }
# restic y rest-server
$t = Join-Path $script:Tmp "restic"; Expand-Archive -Force $fRestic $t
Copy-Item (Get-ChildItem $t -Filter "restic*.exe" -Recurse | Select-Object -First 1).FullName "$R\bin\restic.exe" -Force
$t = Join-Path $script:Tmp "rest"; New-Item -ItemType Directory -Force $t | Out-Null; & tar.exe -xzf $fRest -C $t
Copy-Item (Get-ChildItem $t -Filter "rest-server.exe" -Recurse | Select-Object -First 1).FullName "$R\bin\rest-server.exe" -Force
if (-not ((Test-Path "$R\bin\restic.exe") -and (Test-Path "$R\bin\rest-server.exe"))) { Fallo "No se pudieron preparar restic y rest-server" }
Bien ((& "$R\bin\restic.exe" version) -join " ")
Aviso "Instalando las librerias de Python (1-3 minutos)..."
& "$R\python\python.exe" -m pip install --disable-pip-version-check --no-warn-script-location -q -r "$R\requirements.txt" 2>&1 |
    ForEach-Object { Marca "pip: $_" }
& "$R\python\python.exe" -c "import flask, cheroot, paramiko, cryptography, bcrypt" 2>$null
if ($LASTEXITCODE -ne 0) { Fallo "No se pudieron instalar las librerias de Python (mira $Progreso)" }
Bien "librerias instaladas"

# ajustes del equipo (los lee el lanzador cada vez que arranca)
$tz = "Europe/Madrid"
try { $iana = $null; if ([TimeZoneInfo]::TryConvertWindowsIdToIanaId((Get-TimeZone).Id, [ref]$iana)) { $tz = $iana } } catch { }
$gestionadas = @("OCTOPUS_NATIVO", "OCTOPUS_IP", "OCTOPUS_PUBLIC_HOST", "OCTOPUS_NOMBRES_EXTRA", "OCTOPUS_BOVEDA_DIR", "ADMIN_PORT", "TZ")
$extra = @(Get-Content $HostEnv -ErrorAction SilentlyContinue | Where-Object {
    $_ -match '^[A-Z_][A-Z0-9_]*=' -and (($_ -split '=', 2)[0] -notin $gestionadas) }) -join "`n"   # ajustes anadidos a mano: se conservan
Escribir-Texto $HostEnv @"
# OCTOPUS - ajustes de este equipo (servidor nativo de Windows). Cambia y vuelve a ejecutar el instalador.
OCTOPUS_NATIVO=1
OCTOPUS_IP=$IP
OCTOPUS_PUBLIC_HOST=$(Leer-Ajuste $HostEnv "OCTOPUS_PUBLIC_HOST")
OCTOPUS_NOMBRES_EXTRA=$(Leer-Ajuste $HostEnv "OCTOPUS_NOMBRES_EXTRA")
OCTOPUS_BOVEDA_DIR=$Boveda
ADMIN_PORT=$pPanel
TZ=$tz
$extra
"@
# lanzador: pone los ajustes y arranca el servidor (que vigila el panel, el almacen y el mantenimiento)
Escribir-Texto "$R\arrancar_servidor.ps1" @'
# OCTOPUS - arranca el servidor (lo lanza la tarea "OCTOPUS Servidor" al encender el equipo). No hace falta tocarlo.
$ErrorActionPreference = "Continue"
$R = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Force -Path "$R\datos\logs" | Out-Null
$log = "$R\datos\logs\servidor.log"
if ((Test-Path $log) -and (Get-Item $log).Length -gt 10MB) { Move-Item -Force $log "$log.1" }
foreach ($l in (Get-Content "$R\install\.env" -ErrorAction SilentlyContinue)) {
    if ($l -match '^\s*([A-Z_][A-Z0-9_]*)=(.*)$' -and $Matches[2].Trim()) { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2].Trim().Trim('"') }
}
$env:OCTOPUS_NATIVO = "1"
$env:OCTOPUS_DATA = "$R\datos"
if (-not $env:OCTOPUS_BOVEDA_DIR) { $env:OCTOPUS_BOVEDA_DIR = "$R\boveda" }
$env:OCTOPUS_BIN = "$R\bin"
$env:RESTIC_CACHE_DIR = "$R\datos\.cache\restic"
$env:PYTHONUTF8 = "1"; $env:PYTHONUNBUFFERED = "1"; $env:PYTHONDONTWRITEBYTECODE = "1"
$env:PATH = "$R\bin;$R\python;$env:PATH"
# si el servidor se para por lo que sea, se vuelve a arrancar a los 10 segundos (octopus.ps1 parar para este lanzador)
while ($true) {
    Add-Content -Path $log -Value ("===== {0} arrancando OCTOPUS" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")) -Encoding UTF8
    & cmd.exe /c "`"$R\python\python.exe`" `"$R\lib\servidor.py`" >> `"$log`" 2>&1"
    Add-Content -Path $log -Value ("===== {0} OCTOPUS se ha parado (codigo {1}); se vuelve a arrancar en 10 s" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $LASTEXITCODE) -Encoding UTF8
    Start-Sleep -Seconds 10
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 10MB) { Move-Item -Force $log "$log.1" }
}
'@
Bien "archivos en su sitio"

# ------------------------------------------------------------------ tarea del sistema (arranca sola con Windows)
Paso "Dejando OCTOPUS en marcha (arranca solo al encender el equipo)"
$ocupado = Get-NetTCPConnection -LocalPort ([int]$pPanel) -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; -not ($p.Path -and $p.Path.StartsWith($R, [StringComparison]::OrdinalIgnoreCase)) }
if ($ocupado) {
    $quien = (Get-Process -Id ($ocupado | Select-Object -First 1).OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Fallo "El puerto $pPanel lo esta usando otro programa ($quien). Si es la version antigua de OCTOPUS con Docker, paralo (octopus.ps1 parar) y vuelve a ejecutar esto."
}
$accion = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $R `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$R\arrancar_servidor.ps1`""
$cuando = New-ScheduledTaskTrigger -AtStartup
$quien = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$como = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $Tarea -Action $accion -Trigger $cuando -Principal $quien -Settings $como `
    -Description "Servidor de copias OCTOPUS (panel, almacen y mantenimiento)" -Force | Out-Null
# actualizador seguro: cada 5 minutos mira si se ha pedido una actualizacion desde el panel (solo instala versiones firmadas)
$accionA = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $R `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$R\actualizador.ps1`""
$cadaRato = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$comoA = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "OCTOPUS Actualizador" -Action $accionA -Trigger $cadaRato -Principal $quien -Settings $comoA `
    -Description "Instala las actualizaciones de OCTOPUS que se piden desde el panel (solo versiones firmadas)" -Force | Out-Null
Parar-Octopus
Start-ScheduledTask -TaskName $Tarea
$ok = $false
for ($i = 0; $i -lt 120; $i++) {
    if (Responde "https://127.0.0.1:$pPanel/healthz") { $ok = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ok) {
    Get-Content "$R\datos\logs\servidor.log" -Tail 30 -ErrorAction SilentlyContinue | ForEach-Object { Marca "  [servidor] $_"; Write-Host "  $_" }
    if ($yaEstaba -and (Test-Path $Anterior)) {
        # una actualizacion nunca debe dejar el servidor sin funcionar: se vuelve sola a la version anterior
        Aviso "La version nueva no arranca bien: volviendo a la anterior automaticamente..."
        Parar-Octopus
        & robocopy $Anterior $R /E /NFL /NDL /NJH /NJS /NP | Out-Null
        Start-ScheduledTask -TaskName $Tarea
        for ($i = 0; $i -lt 60; $i++) { if (Responde "https://127.0.0.1:$pPanel/healthz") { break }; Start-Sleep -Seconds 2 }
        if (Responde "https://127.0.0.1:$pPanel/healthz") {
            Fallo "La version nueva no arrancaba y se ha vuelto a la anterior (todo sigue funcionando como antes). Manda el diagnostico al soporte."
        }
    }
    Fallo "El panel no responde. Mira $R\datos\logs\servidor.log"
}
Bien "panel en marcha"

# ------------------------------------------------------------------ red y energia
Paso "Red"
foreach ($p in @($pPanel, $pAlm)) {
    $nombre = "OCTOPUS $p"
    # En todos los tipos de red: Windows marca muchas redes de oficina como "publicas" (red no identificada, o al cambiar
    # de tarjeta o de router) y entonces los equipos dejarian de llegar sin que nadie toque nada. El panel y el almacen
    # ya se protegen solos (contrasena, HTTPS, bloqueo de atacantes y, si se quiere, "solo desde la red de la oficina").
    if (Get-NetFirewallRule -DisplayName $nombre -ErrorAction SilentlyContinue) {
        Set-NetFirewallRule -DisplayName $nombre -Profile Any -Enabled True -Action Allow | Out-Null
    } else {
        New-NetFirewallRule -DisplayName $nombre -Direction Inbound -Protocol TCP -LocalPort $p -Action Allow -Profile Any | Out-Null
    }
}
Bien "Firewall de Windows: abiertos $pPanel y $pAlm (en cualquier tipo de red, aunque Windows la marque como publica)"
# un servidor no debe dormirse: sin suspension mientras este enchufado (la pantalla si se apaga)
& powercfg /change standby-timeout-ac 0 2>$null | Out-Null
& powercfg /change hibernate-timeout-ac 0 2>$null | Out-Null
Bien "Este equipo ya no se suspende mientras este enchufado (la pantalla se sigue apagando)"

$credOrig = Join-Path $R "data\CREDENCIALES_INICIALES.txt"
$cred = Join-Path $Raiz "CREDENCIALES_INICIALES.txt"
if ((Test-Path $credOrig) -and ($Raiz.TrimEnd('\') -ne $R)) { Copy-Item $credOrig $cred -Force -ErrorAction SilentlyContinue }
Remove-Item -Recurse -Force $script:Tmp -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== OCTOPUS instalado ===" -ForegroundColor Green
Write-Host "  Panel:        https://$($IP):$pPanel   (el navegador avisara del certificado propio la primera vez)"
Write-Host "  Usuario:      admin"
if (Test-Path $credOrig) { Write-Host "  Contrasena:   en $credOrig (un solo uso; borralo despues de entrar)" }
Write-Host "  Copias en:    $Boveda"
Write-Host "  Gestion:      $R\octopus.ps1 (estado, registros, parar, arrancar, mantenimiento...)"
Write-Host "  Arranca solo al encender el equipo, aunque nadie inicie sesion."
Marca "---- instalacion terminada correctamente ----"
if (-not $SinPreguntas) {
    if (Test-Path $credOrig) { Start-Process notepad.exe $credOrig -ErrorAction SilentlyContinue }
    Start-Process "https://$($IP):$pPanel" -ErrorAction SilentlyContinue
    Write-Host ""
    $resp = Read-Host "Busco ahora los equipos de la red para protegerlos? [S/n]"
    if ($resp -eq "" -or $resp -match "^[sS]") {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $R "octopus.ps1") buscar-equipos
    } else {
        Write-Host "Cuando quieras: boton 'Buscar los equipos de la red' en el panel, o $R\octopus.ps1 buscar-equipos"
    }
}
if ($Registro) { Stop-Transcript | Out-Null }
Pausa
exit 0
