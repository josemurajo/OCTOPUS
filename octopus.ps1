# OCTOPUS Zero-Touch - gestion del servidor en Windows (lo mismo que octopus.sh en Linux y Mac)
#   powershell -ExecutionPolicy Bypass -File "C:\ProgramData\OCTOPUS-Servidor\octopus.ps1" <orden>
param([string]$Orden = "ayuda", [string]$Arg = "")
$ErrorActionPreference = "Continue"
$Raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$Tarea = "OCTOPUS Servidor"
$Nativo = Test-Path (Join-Path $Raiz "python\python.exe")

function Ayuda {
    Write-Host @"
Uso: powershell -ExecutionPolicy Bypass -File octopus.ps1 <orden>
  estado          como esta todo (servidor, equipos conectados, almacen)
  logs            registro en directo del servidor (Ctrl+C para salir)
  credenciales    contrasena inicial del panel
  buscar-equipos  busca los equipos de la red y los protege, con ventanas y raton (sin usar el panel)
  acceso-emergencia  si te has quedado fuera del panel: quita bloqueos, "solo red de la oficina" y doble aprobacion
  kit             kit de recuperacion (claves de las copias) - guardalo fuera del servidor
  mantenimiento   limpieza, verificacion y copia del servidor ahora (normalmente cada noche)
  ajustes         cambia los ajustes del servidor (almacen externo...) en el Bloc de notas y reinicia
  recuperar-servidor <almacen>   monta este servidor con la configuracion del que se perdio
  actualizar      instala la version de la carpeta desde la que ejecutes esto (conserva datos y copias)
  actualizar-pedido   lo usa el actualizador automatico (actualizaciones firmadas desde el panel)
  volver          vuelve a la version anterior si la actualizacion da problemas
  parar | arrancar | reiniciar
  desinstalar     quita OCTOPUS de este equipo (las copias y los datos se quedan, salvo que se pida)
"@
}

if (-not $Nativo) {
    Write-Host "OCTOPUS no esta instalado en esta carpeta. Instalalo con doble clic en INSTALAR_SERVIDOR_WINDOWS.bat"
    Write-Host "(despues, la gestion esta en C:\ProgramData\OCTOPUS-Servidor\octopus.ps1)."
    exit 1
}

# ----------------------------------------------------------------- servidor nativo
function Entorno {
    foreach ($l in (Get-Content (Join-Path $Raiz "install\.env") -ErrorAction SilentlyContinue)) {
        if ($l -match '^\s*([A-Z_][A-Z0-9_]*)=(.*)$' -and $Matches[2].Trim()) { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2].Trim().Trim('"') }
    }
    $env:OCTOPUS_NATIVO = "1"; $env:OCTOPUS_DATA = "$Raiz\datos"; $env:OCTOPUS_BIN = "$Raiz\bin"
    if (-not $env:OCTOPUS_BOVEDA_DIR) { $env:OCTOPUS_BOVEDA_DIR = "$Raiz\boveda" }
    $env:RESTIC_CACHE_DIR = "$Raiz\datos\.cache\restic"; $env:PYTHONUTF8 = "1"; $env:PATH = "$Raiz\bin;$env:PATH"
}
function Py {
    # ejecuta un programa de OCTOPUS con los ajustes del servidor; lo que escribe sale en pantalla y devuelve su codigo
    param([Parameter(ValueFromRemainingArguments = $true)] $a)
    Entorno; Push-Location $Raiz
    & "$Raiz\python\python.exe" @a | Out-Host
    $rc = $LASTEXITCODE; Pop-Location; return $rc
}
function Procesos {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Raiz, [StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine -like "*$Raiz\arrancar_servidor.ps1*") }
}
function Parar {
    Stop-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 3; $i++) {
        $p = @(Procesos); if ($p.Count -eq 0) { break }
        $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Seconds 2
    }
}
# los certificados son propios de OCTOPUS: para mirar si responde no se valida el certificado
# (en Windows PowerShell 5.1 hace falta esta clase: un scriptblock como validador no funciona en otros hilos)
Add-Type @"
using System.Net; using System.Security.Cryptography.X509Certificates;
public class OctopusSinValidar : ICertificatePolicy {
  public bool CheckValidationResult(ServicePoint s, X509Certificate c, WebRequest r, int p) { return true; } }
"@ -ErrorAction SilentlyContinue
function Salud {
    $puerto = (Get-Content (Join-Path $Raiz "install\.env") -ErrorAction SilentlyContinue | Where-Object { $_ -match '^ADMIN_PORT=' } | ForEach-Object { ($_ -split '=', 2)[1].Trim() }) | Select-Object -First 1
    if (-not $puerto) { $puerto = "8080" }
    $ant = [Net.ServicePointManager]::CertificatePolicy
    try {
        [Net.ServicePointManager]::CertificatePolicy = New-Object OctopusSinValidar
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        return (Invoke-WebRequest "https://127.0.0.1:$puerto/healthz" -UseBasicParsing -TimeoutSec 5).Content
    } catch { return "" } finally { [Net.ServicePointManager]::CertificatePolicy = $ant }
}
function Esperar { for ($i = 0; $i -lt 60; $i++) { if (Salud) { return $true }; Start-Sleep -Seconds 2 }; return $false }

switch ($Orden) {
    "estado" {
        $t = Get-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue
        Write-Host ("Tarea '{0}': {1}" -f $Tarea, $(if ($t) { $t.State } else { "NO EXISTE" }))
        Write-Host ("Procesos de OCTOPUS: {0}" -f @(Procesos).Count)
        $s = Salud; Write-Host ("Panel: {0}" -f $(if ($s) { $s } else { "NO RESPONDE" }))
        $null = Py "lib\equipos_cli.py" "lista"
    }
    "logs"          { Get-Content "$Raiz\datos\logs\servidor.log" -Tail 100 -Wait }
    "credenciales"  { Get-Content "$Raiz\data\CREDENCIALES_INICIALES.txt" -ErrorAction SilentlyContinue }
    "kit"           { $null = Py "lib\mantenimiento.py" "kit" }
    "acceso-emergencia" { $null = Py "lib\seguridad.py" "emergencia" }
    "buscar-equipos" {
        # sin "| Out-Host": las ventanas necesitan la consola de verdad
        Entorno; Push-Location $Raiz
        if ($Arg) { & "$Raiz\python\python.exe" "lib\consola.py" $Arg } else { & "$Raiz\python\python.exe" "lib\consola.py" }
        $rc = $LASTEXITCODE; Pop-Location; exit $rc
    }
    "mantenimiento" { $t = if ($Arg) { $Arg } else { "todo" }; $null = Py "lib\mantenimiento.py" $t }
    "ajustes" {
        $f = Join-Path $Raiz ".env"; $antes = (Get-FileHash $f).Hash
        Start-Process notepad.exe -ArgumentList $f -Wait
        if ((Get-FileHash $f).Hash -ne $antes) {
            $txt = [IO.File]::ReadAllText($f) -replace "`r`n", "`n"
            [IO.File]::WriteAllText($f, $txt, (New-Object Text.UTF8Encoding($false)))
            Parar; Start-ScheduledTask -TaskName $Tarea; Esperar | Out-Null
            Write-Host "Ajustes guardados. OCTOPUS se ha reiniciado."
        } else { Write-Host "Sin cambios." }
    }
    "recuperar-servidor" {
        if (-not $Arg) { Write-Host "Uso: octopus.ps1 recuperar-servidor <carpeta octopus-backups del disco antiguo | almacen externo>"; exit 2 }
        Entorno; $repo = $Arg
        if (Test-Path $Arg -PathType Container) {
            $dest = Join-Path $env:OCTOPUS_BOVEDA_DIR "octopus-backups"
            if ((Test-Path "$dest\snapshots") -and @(Get-ChildItem "$dest\snapshots").Count -gt 0) {
                Write-Host "Este servidor ya tiene copias en su almacen: no se sobrescriben. Usa un servidor recien instalado."; exit 1 }
            Parar
            Write-Host "Copiando el almacen (puede tardar)..."
            & robocopy $Arg $dest /E /NFL /NDL /NJH /NJS /NP | Out-Null
            $cuar = Join-Path (Split-Path $Arg -Parent) "octopus-cuarentena"
            if (Test-Path $cuar) { & robocopy $cuar (Join-Path $env:OCTOPUS_BOVEDA_DIR "octopus-cuarentena") /E /NFL /NDL /NJH /NJS /NP | Out-Null }
            $repo = $dest
        }
        $rc = Py "lib\recuperar_servidor.py" $repo
        Start-ScheduledTask -TaskName $Tarea
        if ($rc -eq 0) { Esperar | Out-Null; Write-Host "OCTOPUS reiniciado con la configuracion recuperada." }
    }
    "actualizar" {
        $origen = if ($Arg) { $Arg } else { (Get-Location).Path }
        $inst = Join-Path $origen "instalar_servidor_windows.ps1"
        if (-not (Test-Path $inst) -or ((Resolve-Path $origen).Path.TrimEnd('\') -eq $Raiz)) {
            Write-Host "Ejecuta esto desde la carpeta de la VERSION NUEVA (o: octopus.ps1 actualizar <carpeta de la version nueva>)."
            Write-Host "Lo mas facil: actualizar desde el panel (Ajustes -> Actualizaciones) o doble clic en INSTALAR_SERVIDOR_WINDOWS.bat de la version nueva."
            exit 2
        }
        & powershell -NoProfile -ExecutionPolicy Bypass -File $inst -Destino $Raiz
    }
    "actualizar-pedido" { & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Raiz "actualizador.ps1") }
    "volver" {
        $ant = "$Raiz.anterior"
        if (-not (Test-Path "$ant\lib\servidor.py")) { Write-Host "No hay version anterior guardada"; exit 1 }
        Parar
        & robocopy $ant $Raiz /E /NFL /NDL /NJH /NJS /NP | Out-Null
        Start-ScheduledTask -TaskName $Tarea
        if (Esperar) { Write-Host "Vuelto a la version anterior." } else { Write-Host "Vuelto a la version anterior, pero el panel no responde: mira 'octopus.ps1 logs'." }
    }
    "parar"     { Parar; Write-Host "OCTOPUS parado (volvera a arrancar al reiniciar el equipo; para que no: octopus.ps1 desinstalar)." }
    "arrancar"  { Start-ScheduledTask -TaskName $Tarea; if (Esperar) { Write-Host "OCTOPUS en marcha." } else { Write-Host "No responde todavia: mira 'octopus.ps1 logs'." } }
    "reiniciar" { Parar; Start-ScheduledTask -TaskName $Tarea; if (Esperar) { Write-Host "OCTOPUS reiniciado." } else { Write-Host "No responde todavia: mira 'octopus.ps1 logs'." } }
    "desinstalar" {
        Entorno
        Write-Host "Se quitara OCTOPUS de este equipo. Las COPIAS ($env:OCTOPUS_BOVEDA_DIR) y los datos se quedan, salvo que escribas BORRAR TODO."
        $r = if ($Arg) { $Arg } else { Read-Host "Escribe SI para desinstalar (o BORRAR TODO para quitar tambien las copias)" }
        if ($r -notin @("SI", "BORRAR TODO")) { Write-Host "Cancelado."; exit 1 }
        Parar
        Unregister-ScheduledTask -TaskName $Tarea -Confirm:$false -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName "OCTOPUS Actualizador" -Confirm:$false -ErrorAction SilentlyContinue
        Get-NetFirewallRule -DisplayName "OCTOPUS *" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        foreach ($d in @("python", "bin", "lib", "templates", "agentes", "install", "herramientas", "soporte", "ansible")) {
            Remove-Item -Recurse -Force (Join-Path $Raiz $d) -ErrorAction SilentlyContinue }
        if ($r -eq "BORRAR TODO") {
            Remove-Item -Recurse -Force $env:OCTOPUS_BOVEDA_DIR, $Raiz, "$Raiz.anterior" -ErrorAction SilentlyContinue
            Write-Host "OCTOPUS y sus copias se han quitado de este equipo."
        } else {
            Write-Host "OCTOPUS se ha quitado. Se quedan las copias en $env:OCTOPUS_BOVEDA_DIR y la configuracion en $Raiz\data y $Raiz\.env"
            Write-Host "(para volver a instalar con todo como estaba, ejecuta de nuevo INSTALAR_SERVIDOR_WINDOWS.bat)."
        }
    }
    default { Ayuda }
}
