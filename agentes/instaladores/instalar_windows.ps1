# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jose Murillo Rajo - OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS Zero-Touch - Instalador del agente para Windows 10/11 y Windows Server 2016+
# Lo lanza INSTALAR.bat (como administrador). Compatible con Windows PowerShell 5.1.
#
# Instala: Python (si falta), restic, el agente OCTOPUS como tarea del sistema que se reinicia sola
# y la copia diaria. El agente se conecta EL al servidor por HTTPS: no se abre ningun puerto en el equipo.
param([switch]$Desinstalar)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'

$Aqui    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Prog    = Join-Path $env:ProgramFiles 'Octopus'
$Datos   = Join-Path $env:ProgramData 'Octopus'
$Tarea   = 'OCTOPUS Agente'
$TareaCopia = 'OCTOPUS Copia diaria'
$ReglaFw = 'OCTOPUS Agente'
$WgExe   = Join-Path $env:ProgramFiles 'WireGuard\wireguard.exe'   # solo para quitar restos de versiones anteriores
$ResticVer = '0.16.4'
$PythonVer = '3.12.7'

# Banderines: cada paso con la hora en C:\ProgramData\OCTOPUS\instalacion_agente_progreso.txt
$Progreso = Join-Path $env:ProgramData "OCTOPUS\instalacion_agente_progreso.txt"
function Marca($t) { try { New-Item -ItemType Directory -Force -Path (Split-Path $Progreso) | Out-Null; Add-Content -Path $Progreso -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $t) } catch { } }
function Paso($t)  { Marca "==> $t"; Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Bien($t)  { Marca "OK  $t"; Write-Host "    $t" -ForegroundColor Green }
function Aviso($t) { Marca "..  $t"; Write-Host "    $t" -ForegroundColor Yellow }
function Fallo($t) { Marca "ERROR $t"; Write-Host ""; Write-Host "ERROR: $t" -ForegroundColor Red; exit 1 }

$esAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $esAdmin) { Fallo 'Ejecuta INSTALAR.bat con "Ejecutar como administrador".' }
if (-not [Environment]::Is64BitOperatingSystem) { Fallo 'Hace falta Windows de 64 bits.' }

function Nativo([scriptblock]$bloque) {
    # programas externos: su salida de error no debe parar el instalador
    $antes = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $bloque 2>&1 | Out-Null } finally { $ErrorActionPreference = $antes }
}

function Descargar($url, $destino) {
    for ($i = 1; $i -le 3; $i++) {
        try { Invoke-WebRequest -Uri $url -OutFile $destino -UseBasicParsing; return }
        catch { if ($i -eq 3) { throw "No se pudo descargar $url : $($_.Exception.Message)" }; Start-Sleep -Seconds 5 }
    }
}

function Buscar-Python {
    $candidatos = @(
        (Join-Path $env:ProgramFiles 'Python312\python.exe'),
        (Join-Path $env:ProgramFiles 'Python313\python.exe'),
        (Join-Path $env:ProgramFiles 'Python311\python.exe'),
        (Join-Path $env:ProgramFiles 'Python310\python.exe')
    )
    foreach ($c in $candidatos) { if (Test-Path $c) { return $c } }
    # Pythons instalados para todos los usuarios (registro de Windows). Uno instalado solo para un usuario
    # (carpeta C:\Users\...) no sirve: la tarea del agente corre como SYSTEM.
    foreach ($raiz in @('HKLM:\SOFTWARE\Python\PythonCore', 'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore')) {
        # bucle "foreach" normal: un "return" dentro de ForEach-Object no sale de la funcion
        foreach ($k in @(Get-ChildItem $raiz -ErrorAction SilentlyContinue | Sort-Object { try { [version](($_.PSChildName -split '-')[0]) } catch { [version]'0.0' } } -Descending)) {
            $ip = Get-ItemProperty (Join-Path $k.PSPath 'InstallPath') -ErrorAction SilentlyContinue
            $exe = if ($ip.ExecutablePath) { $ip.ExecutablePath } elseif ($ip.'(default)') { Join-Path $ip.'(default)' 'python.exe' } else { $null }
            if ($exe -and (Test-Path $exe) -and ($exe -notlike "$env:SystemDrive\Users\*")) {
                $v = & $exe -c "import sys, ssl, json; print(sys.version_info >= (3, 8))" 2>$null
                if ($v -eq 'True') { return $exe }
            }
        }
    }
    $propio = Join-Path $env:ProgramFiles 'OctopusPython\python.exe'
    if (Test-Path $propio) { return $propio }
    return $null
}

# ------------------------------------------------------------------ desinstalar
if ($Desinstalar) {
    Paso 'Quitando OCTOPUS de este equipo'
    foreach ($t in @($Tarea, $TareaCopia)) {
        if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $t -Confirm:$false
        }
    }
    Get-NetFirewallRule -DisplayName "$ReglaFw*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Get-NetFirewallRule -DisplayName 'OCTOPUS*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    # por si el equipo estaba aislado por un incidente: volver a la politica normal del cortafuegos
    Set-NetFirewallProfile -Profile Domain,Private,Public -DefaultOutboundAction Allow -ErrorAction SilentlyContinue
    if (Test-Path $WgExe) { Nativo { & $WgExe /uninstalltunnelservice octopus } }
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*zerotouch_agent.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Remove-Item -Recurse -Force $Prog -ErrorAction SilentlyContinue
    Remove-Item -Force (Join-Path $Datos 'config.json'), (Join-Path $Datos 'octopus.conf') -ErrorAction SilentlyContinue
    Bien 'OCTOPUS se ha quitado. Las copias guardadas en el servidor siguen alli.'
    exit 0
}

# ------------------------------------------------------------------ comprobaciones
foreach ($f in @('zerotouch_agent.py', 'config.json')) {
    if (-not (Test-Path (Join-Path $Aqui $f))) { Fallo "Falta $f en esta carpeta. Descarga de nuevo el instalador desde el panel." }
}
$cfg = Get-Content (Join-Path $Aqui 'config.json') -Raw | ConvertFrom-Json
$servidor = $cfg.servidor
if (-not $servidor) { Fallo 'La configuracion no indica el servidor. Descarga de nuevo el instalador desde el panel.' }

Write-Host ''
Write-Host '  OCTOPUS Zero-Touch - instalacion del agente' -ForegroundColor White
Write-Host "  Equipo: $($cfg.hostname)     Servidor: $servidor"
if ($env:COMPUTERNAME -ne $cfg.hostname) {
    Aviso "Este paquete es para el equipo '$($cfg.hostname)' y este equipo se llama '$env:COMPUTERNAME'."
    Aviso 'Las copias se guardaran con el nombre del paquete. Si te has equivocado de equipo, cierra esta ventana.'
    Start-Sleep -Seconds 8
}

New-Item -ItemType Directory -Force -Path $Prog, $Datos | Out-Null
# Instalaciones anteriores pudieron dejar archivos sin permisos: se vuelven a heredar de la carpeta
Nativo { & icacls $Prog /reset /T /C /Q }
Nativo { & icacls $Datos /reset /T /C /Q }
$tmp = Join-Path $env:TEMP ("octopus_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

try {
    # -------------------------------------------------------------- Python
    Paso 'Python'
    $py = Buscar-Python
    if (-not $py) {
        Aviso "Instalando Python $PythonVer (tarda 1-2 minutos)..."
        $exe = Join-Path $tmp 'python.exe'
        Descargar "https://www.python.org/ftp/python/$PythonVer/python-$PythonVer-amd64.exe" $exe
        # Sin el "lanzador" de Python: si el equipo ya tiene uno mas nuevo, el instalador fallaba con 1603
        $opc = @('/quiet', 'InstallAllUsers=1', 'PrependPath=0', 'Include_test=0', 'Include_doc=0', 'Shortcuts=0',
                 'Include_launcher=0', 'InstallLauncherAllUsers=0', 'AssociateFiles=0')
        $p = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList $opc
        if ($p.ExitCode -notin 0, 3010) {
            # segundo intento en una carpeta propia (por si choca con otro Python 3.12 ya instalado)
            Aviso "El instalador de Python devolvio $($p.ExitCode); se reintenta en una carpeta propia..."
            $p = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList ($opc + @("TargetDir=`"$(Join-Path $env:ProgramFiles 'OctopusPython')`""))
        }
        if ($p.ExitCode -notin 0, 3010) { throw "El instalador de Python termino con codigo $($p.ExitCode)" }
        $py = Buscar-Python
        if (-not $py) { throw 'Python no aparece tras instalarlo' }
    }
    Bien "Python: $py"

    # -------------------------------------------------------------- restic
    Paso 'Motor de copias (restic)'
    $restic = Join-Path $Prog 'restic.exe'
    if (-not (Test-Path $restic)) {
        $zip = Join-Path $tmp 'restic.zip'
        Descargar "https://github.com/restic/restic/releases/download/v$ResticVer/restic_${ResticVer}_windows_amd64.zip" $zip
        Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp 'restic') -Force
        Copy-Item (Get-ChildItem (Join-Path $tmp 'restic') -Filter 'restic*.exe' | Select-Object -First 1).FullName $restic -Force
    }
    Bien (& $restic version)

    # -------------------------------------------------------------- conexion con el servidor
    Paso 'Conexion con el servidor'
    $panel = "$($cfg.panel_url)".TrimEnd('/')
    if (-not $panel) { $panel = "https://${servidor}:8080" }
    $uri = [Uri]$panel
    $tcp = New-Object Net.Sockets.TcpClient
    try { $tcp.ConnectAsync($uri.Host, $uri.Port).Wait(8000) | Out-Null } catch { }
    if ($tcp.Connected) { Bien "El servidor responde en $($uri.Host):$($uri.Port)" }
    else { Aviso "No llego al servidor en $($uri.Host):$($uri.Port). El agente lo seguira intentando solo; revisa la red o el cortafuegos del servidor." }
    $tcp.Close()
    # restos de versiones anteriores (tunel WireGuard)
    if (Test-Path $WgExe) { Nativo { & $WgExe /uninstalltunnelservice octopus } }

    # -------------------------------------------------------------- agente
    Paso 'Agente OCTOPUS'
    if (Get-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*zerotouch_agent.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Copy-Item (Join-Path $Aqui 'zerotouch_agent.py') (Join-Path $Prog 'zerotouch_agent.py') -Force
    if (Test-Path (Join-Path $Aqui 'octopus_monitor.py')) { Copy-Item (Join-Path $Aqui 'octopus_monitor.py') (Join-Path $Prog 'octopus_monitor.py') -Force }
    Copy-Item (Join-Path $Aqui 'config.json') (Join-Path $Datos 'config.json') -Force
    # solo SYSTEM y Administradores pueden leer la configuracion (contiene claves)
    # Permisos: se protege la CARPETA y los archivos de dentro heredan de ella. (Antes se aplicaba con /T a
    # cada archivo: en los archivos se quitaban los permisos heredados y no se ponian los nuevos, y el
    # agente quedaba sin permiso de lectura ni para SYSTEM -> Python salia con codigo 2.)
    Nativo { & icacls $Datos /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /Q }
    Nativo { & icacls (Join-Path $Datos '*') /reset /T /C /Q }
    Nativo { & icacls $Prog /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' /Q }
    Nativo { & icacls (Join-Path $Prog '*') /reset /T /C /Q }

    $agente = Join-Path $Prog 'zerotouch_agent.py'
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
    $accion = New-ScheduledTaskAction -Execute $py -Argument "`"$agente`"" -WorkingDirectory $Prog
    Register-ScheduledTask -TaskName $Tarea -Action $accion -Trigger (New-ScheduledTaskTrigger -AtStartup) `
        -Principal $principal -Settings $ajustes -Force | Out-Null
    $accionCopia = New-ScheduledTaskAction -Execute $py -Argument "`"$agente`" --copia" -WorkingDirectory $Prog
    $ajustesCopia = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 12) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TareaCopia -Action $accionCopia -Trigger (New-ScheduledTaskTrigger -Daily -At '20:00') `
        -Principal $principal -Settings $ajustesCopia -Force | Out-Null

    # versiones anteriores abrian el 9999: ya no hace falta (solo escucha en 127.0.0.1)
    Get-NetFirewallRule -DisplayName $ReglaFw -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Start-ScheduledTask -TaskName $Tarea

    $ok = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 2
        try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:9999/health' -TimeoutSec 3; if ($r.status -eq 'ok') { $ok = $true; break } } catch { }
    }
    if (-not $ok) {
        # Explicar por que no arranca (lo vera quien instale y queda en la pantalla)
        Aviso "El agente no responde. Diagnostico:"
        try { $ti = Get-ScheduledTask -TaskName $Tarea | Get-ScheduledTaskInfo; Aviso ("  Tarea: estado={0} ultimo resultado=0x{1:X}" -f (Get-ScheduledTask -TaskName $Tarea).State, $ti.LastTaskResult) } catch { }
        $log = Join-Path $Datos 'agent.log'
        if (Test-Path $log) { Aviso "  Ultimas lineas de $log :"; Get-Content $log -Tail 15 | ForEach-Object { Aviso "    $_" } }
        else { Aviso "  El agente no ha llegado a escribir su registro (no ha arrancado)." }
        Aviso "  Prueba directa del agente (10 s):"
        $out = Join-Path $tmp 'prueba_agente.txt'
        $env:OCTOPUS_CONFIG = Join-Path $Datos 'config.json'
        $pp = Start-Process -FilePath $py -ArgumentList "`"$agente`"" -WorkingDirectory $Prog -PassThru -NoNewWindow `
            -RedirectStandardOutput $out -RedirectStandardError "$out.err"
        Start-Sleep -Seconds 10
        try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:9999/health' -TimeoutSec 3; Aviso "    responde al arrancarlo a mano: $($r.status)" } catch { Aviso "    tampoco responde a mano: $($_.Exception.Message)" }
        if (-not $pp.HasExited) { Stop-Process -Id $pp.Id -Force -ErrorAction SilentlyContinue }
        foreach ($f in @($out, "$out.err")) { if (Test-Path $f) { Get-Content $f -Tail 15 | ForEach-Object { Aviso "    $_" } } }
        throw "El agente no arranca. Registro: $Datos\agent.log"
    }
    Bien 'Agente en marcha (se inicia solo con Windows y se reinicia si falla)'

    Paso 'Primera copia de seguridad'
    Start-ScheduledTask -TaskName $TareaCopia
    Bien 'La primera copia se esta haciendo en segundo plano. Despues, una copia cada dia a las 20:00.'
}
catch {
    Fallo $_.Exception.Message
}
finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host '  OCTOPUS instalado. En el panel este equipo aparecera como protegido en unos minutos.' -ForegroundColor Green
Write-Host '  IMPORTANTE: borra ahora esta carpeta y el .zip descargado (contienen claves).' -ForegroundColor Yellow
