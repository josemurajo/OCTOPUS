# OCTOPUS Zero-Touch - Instalador del SERVIDOR para Windows 10 (22H2) / 11 / Server 2022-2025
#
#   Doble clic en INSTALAR_SERVIDOR_WINDOWS.bat (pide permiso de administrador)
#   o:  powershell -ExecutionPolicy Bypass -File instalar_servidor_windows.ps1 [-IP 192.168.1.10]
#
# Que hace:
#   1. Activa WSL2 si falta (la primera vez puede pedir reiniciar; despues se vuelve a ejecutar).
#   2. Si no hay Docker, instala Rancher Desktop (gratis y de codigo abierto) con el motor "moby" (Docker)
#      y sin Kubernetes, y lo deja arrancando solo con Windows.
#   3. Construye y arranca OCTOPUS en un contenedor (el mismo que en Linux).
#   4. Abre los puertos 8080 y 8000 en el Firewall de Windows y comprueba que se llega a ellos desde la red
#      (si Docker solo escucha en esta maquina, crea el reenvio necesario con netsh portproxy).
#   Volver a ejecutarlo actualiza a la version de esta carpeta sin perder datos ni copias.
param([string]$IP = "", [switch]$SinPreguntas, [string]$Registro = "")
# -SinPreguntas: no espera a que se pulse Intro (instalaciones automaticas). -Registro <archivo>: guarda toda la salida
# "Continue": en PowerShell 5.1 el texto que Docker escribe en la salida de errores se volveria "error" con "Stop".
# Los fallos se comprueban uno a uno con $LASTEXITCODE.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$Raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$ComposeFile = Join-Path $Raiz "install\docker-compose.yml"
$HostEnv = Join-Path $Raiz "install\.env"

function Paso($t)  { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Bien($t)  { Write-Host "    $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "    $t" -ForegroundColor Yellow }
function Pausa { if (-not $SinPreguntas) { Read-Host "Pulsa Intro para cerrar" | Out-Null } }
function Fallo($t) { Write-Host ""; Write-Host "ERROR: $t" -ForegroundColor Red; Pausa; if ($Registro) { Stop-Transcript | Out-Null }; exit 1 }
function Refrescar-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

# ------------------------------------------------------------------ administrador
$yo = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $yo.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $args2 = "-NoProfile -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`""
    if ($IP) { $args2 += " -IP $IP" }
    if ($SinPreguntas) { $args2 += " -SinPreguntas" }
    if ($Registro) { $args2 += " -Registro `"$Registro`"" }
    Start-Process powershell -Verb RunAs -ArgumentList $args2
    exit 0
}
if ($Registro) { Start-Transcript -Path $Registro -Append | Out-Null }
if (-not (Test-Path $ComposeFile)) { Fallo "No encuentro $ComposeFile. Ejecuta este archivo desde la carpeta de OCTOPUS." }
$os = Get-CimInstance Win32_OperatingSystem
Write-Host "OCTOPUS Zero-Touch - instalacion del servidor en Windows   ($($os.Caption), compilacion $($os.BuildNumber))" -ForegroundColor White
if ([int]$os.BuildNumber -lt 19045) { Fallo "Hace falta Windows 10 22H2 (compilacion 19045) o posterior." }

# ------------------------------------------------------------------ Docker / Rancher Desktop
function Buscar-RD {
    foreach ($d in @("$env:ProgramFiles\Rancher Desktop", "$env:LOCALAPPDATA\Programs\Rancher Desktop")) {
        $bin = Join-Path $d "resources\resources\win32\bin"
        if (Test-Path (Join-Path $bin "rdctl.exe")) { return $bin }
    }
    return $null
}
function Docker-Va { try { & docker info *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false } }

Paso "Docker"
Refrescar-Path
$rdBin = Buscar-RD
if ($rdBin) { $env:Path = "$rdBin;$env:Path" }
if (-not (Docker-Va)) {
    # WSL2: Rancher Desktop lo necesita
    $wslOk = $false
    try { & wsl.exe --status *> $null; $wslOk = ($LASTEXITCODE -eq 0) } catch { }
    $marca = Join-Path $env:ProgramData "OctopusServidor_wsl_reinicio.txt"
    if (-not $wslOk -and (Test-Path $marca)) {
        # Ya se pidio reiniciar: si de verdad se ha reiniciado, terminar de instalar WSL sin pedir otro reinicio
        $arranque = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
        if ($arranque -gt (Get-Item $marca).LastWriteTime) {
            Aviso "Terminando de instalar WSL2 despues del reinicio..."
            & wsl.exe --install --no-distribution
            & wsl.exe --update *> $null
            try { & wsl.exe --status *> $null; $wslOk = ($LASTEXITCODE -eq 0) } catch { }
            if (-not $wslOk) { Fallo "WSL2 sigue sin funcionar tras reiniciar. Comprueba que la virtualizacion esta activada en la BIOS." }
            Remove-Item $marca -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not $wslOk) {
        Aviso "Activando WSL2 (subsistema de Linux de Windows)..."
        & wsl.exe --install --no-distribution
        Set-Content -Path $marca -Value (Get-Date) -ErrorAction SilentlyContinue
        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 3010) {
            Fallo "No se pudo activar WSL2. Comprueba que la virtualizacion esta activada en la BIOS y vuelve a intentarlo."
        }
        Write-Host ""
        Write-Host "WSL2 activado. REINICIA el equipo y vuelve a hacer doble clic en INSTALAR_SERVIDOR_WINDOWS.bat." -ForegroundColor Yellow
        Pausa
        if ($Registro) { Stop-Transcript | Out-Null }
        exit 3010
    }
    & wsl.exe --update *> $null
    if (-not $rdBin) {
        Aviso "Instalando Rancher Desktop (gratis, de codigo abierto; 3-5 minutos)..."
        $hecho = $false
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            & winget install -e --id SUSE.RancherDesktop --source winget --silent --scope machine --accept-package-agreements --accept-source-agreements
            $hecho = ($LASTEXITCODE -eq 0) -or [bool](Buscar-RD)
        }
        if (-not $hecho) {
            # sin winget: el .msi de la ultima version, desde GitHub
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $rel = Invoke-RestMethod "https://api.github.com/repos/rancher-sandbox/rancher-desktop/releases/latest" -UseBasicParsing -ErrorAction Stop
            $msi = $rel.assets | Where-Object { $_.name -like "*.msi" } | Select-Object -First 1
            if (-not $msi) { Fallo "No se encontro el instalador de Rancher Desktop. Instalalo a mano desde rancherdesktop.io" }
            $dest = Join-Path $env:TEMP $msi.name
            Invoke-WebRequest $msi.browser_download_url -OutFile $dest -UseBasicParsing -ErrorAction Stop
            $p = Start-Process msiexec.exe -Wait -PassThru -ArgumentList "/i `"$dest`" /qn /norestart WSLINSTALLED=1 MSIINSTALLPERUSER=0"
            if ($p.ExitCode -notin 0, 3010) { Fallo "El instalador de Rancher Desktop termino con codigo $($p.ExitCode)" }
        }
        $rdBin = Buscar-RD
        if (-not $rdBin) { Fallo "Rancher Desktop no aparece instalado. Instalalo a mano desde rancherdesktop.io y vuelve a ejecutar esto." }
        $env:Path = "$rdBin;$env:Path"
    }
    Aviso "Arrancando Rancher Desktop con Docker (moby) y sin Kubernetes (la primera vez 2-5 minutos)..."
    # En segundo plano: "rdctl start" puede quedarse esperando a la ventana de Rancher Desktop y no volver nunca
    Start-Process -FilePath (Join-Path $rdBin "rdctl.exe") -WindowStyle Hidden -ArgumentList @(
        "start", "--container-engine.name=moby", "--kubernetes.enabled=false",
        "--application.start-in-background=true", "--application.auto-start=true") | Out-Null
    for ($i = 0; $i -lt 120 -and -not (Docker-Va); $i++) { Start-Sleep -Seconds 5 }
    if (-not (Docker-Va)) { Fallo "Docker no arranca. Abre Rancher Desktop desde el menu Inicio, espera a que termine y vuelve a ejecutar esto." }
} elseif ($rdBin) {
    & (Join-Path $rdBin "rdctl.exe") set --application.auto-start=true 2>&1 | Out-Null
}
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Fallo "Falta 'docker compose'." }
Bien ((& docker version --format "Docker {{.Server.Version}}") 2>$null)

# ------------------------------------------------------------------ direccion
Paso "Direccion del servidor"
function Leer($clave) {
    if (-not (Test-Path $HostEnv)) { return "" }
    $l = Get-Content $HostEnv | Where-Object { $_ -match "^$clave=" } | Select-Object -Last 1
    if ($l) { return ($l -split "=", 2)[1].Trim('"') } else { return "" }
}
if (-not $IP) { $IP = Leer "OCTOPUS_IP" }
if (-not $IP) {
    $IP = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
           Select-Object -First 1).IPv4Address.IPAddress
}
if (-not $IP) { Fallo "No se pudo averiguar la IP. Ejecuta: instalar_servidor_windows.ps1 -IP <ip>" }
Bien "Los equipos llegaran al servidor por $IP (cambialo con -IP si usas otra IP o un nombre)"

$pPanel = Leer "PANEL_PUERTO"; if (-not $pPanel) { $pPanel = "8080" }
$pAlm = Leer "ALMACEN_PUERTO"; if (-not $pAlm) { $pAlm = "8000" }
$vol = Leer "OCTOPUS_VOLUMEN_BOVEDA"; if (-not $vol) { $vol = "octopus_boveda" }
$tz = "Europe/Madrid"
try { $iana = $null; if ([TimeZoneInfo]::TryConvertWindowsIdToIanaId((Get-TimeZone).Id, [ref]$iana)) { $tz = $iana } } catch { }
$version = (Get-Content (Join-Path $Raiz "VERSION") -ErrorAction SilentlyContinue | Select-Object -First 1)
if (-not $version) { $version = "local" }
$contenido = @"
# OCTOPUS - ajustes del anfitrion (los usa docker compose). Cambia y vuelve a ejecutar el instalador
OCTOPUS_IP=$IP
OCTOPUS_PUBLIC_HOST=$(Leer "OCTOPUS_PUBLIC_HOST")
OCTOPUS_NOMBRES_EXTRA=$(Leer "OCTOPUS_NOMBRES_EXTRA")
PANEL_PUERTO=$pPanel
ALMACEN_PUERTO=$pAlm
TZ=$tz
OCTOPUS_VOLUMEN_BOVEDA=$vol
OCTOPUS_VERSION=$($version.Trim())
"@
[IO.File]::WriteAllText($HostEnv, ($contenido -replace "`r`n", "`n"), (New-Object Text.UTF8Encoding($false)))

# ------------------------------------------------------------------ imagen y arranque
Paso "Construyendo OCTOPUS (la primera vez tarda unos minutos)"
$dc = @("compose", "--env-file", $HostEnv, "-f", $ComposeFile)
$ant = (& docker image inspect -f "{{.Id}}" "octopus-servidor:$($version.Trim())" 2>$null)
if ($ant) { & docker tag $ant octopus-servidor:anterior 2>$null | Out-Null }
& docker @dc build --pull
if ($LASTEXITCODE -ne 0) { Fallo "No se pudo construir la imagen" }
Paso "Arrancando OCTOPUS"
& docker @dc up -d --remove-orphans octopus
if ($LASTEXITCODE -ne 0) { Fallo "No se pudo arrancar el contenedor" }

# los certificados son propios: para comprobar que responde no se valida el certificado
Add-Type @"
using System.Net; using System.Security.Cryptography.X509Certificates;
public class OctopusSinValidar : ICertificatePolicy {
  public bool CheckValidationResult(ServicePoint s, X509Certificate c, WebRequest r, int p) { return true; } }
"@ -ErrorAction SilentlyContinue
[Net.ServicePointManager]::CertificatePolicy = New-Object OctopusSinValidar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
function Responde($url) { try { $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop; return $r.StatusCode -lt 500 } catch { return $false } }
$ok = $false
for ($i = 0; $i -lt 90; $i++) {
    if (Responde "https://127.0.0.1:$pPanel/login") { $ok = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ok) { & docker logs --tail 40 octopus; Fallo "El panel no responde" }
Bien "panel en marcha"

# ------------------------------------------------------------------ red: cortafuegos y reenvio
Paso "Red"
foreach ($p in @($pPanel, $pAlm)) {
    $nombre = "OCTOPUS $p"
    if (-not (Get-NetFirewallRule -DisplayName $nombre -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $nombre -Direction Inbound -Protocol TCP -LocalPort $p -Action Allow -Profile Domain, Private | Out-Null
    }
}
Bien "Firewall de Windows: abiertos $pPanel y $pAlm (redes privadas y de dominio)"
# Con WSL2, Docker a veces solo escucha en 127.0.0.1: se comprueba por la IP de la red y, si no llega, se reenvia
foreach ($p in @($pPanel, $pAlm)) {
    $t = Test-NetConnection -ComputerName $IP -Port $p -WarningAction SilentlyContinue
    if (-not $t.TcpTestSucceeded) {
        & netsh interface portproxy delete v4tov4 listenport=$p listenaddress=$IP 2>$null | Out-Null
        & netsh interface portproxy add v4tov4 listenport=$p listenaddress=$IP connectport=$p connectaddress=127.0.0.1 | Out-Null
        Set-Service iphlpsvc -StartupType Automatic -ErrorAction SilentlyContinue
        Start-Service iphlpsvc -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        $t = Test-NetConnection -ComputerName $IP -Port $p -WarningAction SilentlyContinue
        if ($t.TcpTestSucceeded) { Bien "puerto $p reenviado a Docker (netsh portproxy)" } else { Aviso "No se llega al puerto $p por $($IP): revisa el antivirus o el firewall" }
    } else {
        Bien "puerto $p accesible por $IP"
    }
}

$cred = Join-Path $Raiz "CREDENCIALES_INICIALES.txt"
$txt = (& docker exec octopus cat /data/panel/CREDENCIALES_INICIALES.txt 2>$null)
if ($txt) { [IO.File]::WriteAllText($cred, ($txt -join "`r`n")) }

Write-Host ""
Write-Host "=== OCTOPUS instalado ===" -ForegroundColor Green
Write-Host "  Panel:        https://$($IP):$pPanel   (el navegador avisara del certificado propio la primera vez)"
Write-Host "  Usuario:      admin"
if (Test-Path $cred) { Write-Host "  Contrasena:   en $cred (un solo uso; borralo despues de entrar)" }
Write-Host "  Gestion:      octopus.ps1 (clic derecho -> Ejecutar con PowerShell, o: powershell -File octopus.ps1 ayuda)"
Write-Host "  IMPORTANTE:   este equipo tiene que quedarse encendido y con la sesion iniciada (Rancher Desktop"
Write-Host "                arranca al iniciar sesion). Desactiva la suspension en Configuracion -> Sistema -> Energia."
if ($Registro) { Stop-Transcript | Out-Null }
Pausa
