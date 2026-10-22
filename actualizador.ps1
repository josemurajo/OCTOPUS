# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jose Murillo Rajo - OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS - Actualizador seguro del servidor nativo de Windows. Lo lanza solo la tarea "OCTOPUS Actualizador"
# cada 5 minutos (como SYSTEM). Hace lo mismo que actualizador.sh en Linux y Mac:
#   - El panel NUNCA ejecuta nada en el equipo: solo deja una peticion (datos\actualizacion\pedida). Esto la recoge.
#   - Solo descarga de la direccion oficial fija (GitHub de OCTOPUS, por HTTPS). No escucha en ningun puerto.
#   - Solo instala si la version viene FIRMADA con la clave de publicacion de ESTA instalacion
#     (install\firma_publicacion.pub, no la que venga en la descarga), y si cada archivo coincide con lo firmado.
#     La comprobacion la hace el Python y el codigo YA INSTALADOS (lib\firma.py), nunca los descargados.
#   - Nunca instala una version mas antigua. El instalador guarda la version actual y, si la nueva no arranca,
#     vuelve solo a la anterior.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$R = Split-Path -Parent $MyInvocation.MyCommand.Path
$D = Join-Path $R "datos\actualizacion"
$Py = Join-Path $R "python\python.exe"
$Clave = Join-Path $R "install\firma_publicacion.pub"
New-Item -ItemType Directory -Force -Path $D | Out-Null

function Leer($clave) {
    $l = Get-Content (Join-Path $R "install\.env") -ErrorAction SilentlyContinue | Where-Object { $_ -match "^$clave=" } | Select-Object -Last 1
    if ($l) { return ($l -split "=", 2)[1].Trim().Trim('"') } else { return "" }
}
function Escribir($nombre, $texto) { [IO.File]::WriteAllText((Join-Path $D $nombre), $texto, (New-Object Text.UTF8Encoding($false))) }
function Estado($t) { Escribir "estado" $t; Add-Content (Join-Path $R "datos\logs\actualizador.log") ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $t) -Encoding UTF8 }
function Resultado($ok, $texto) {
    $j = @{ ok = [bool]$ok; fecha = (Get-Date).ToString("o"); detalle = $texto } | ConvertTo-Json -Compress
    Escribir "resultado.json" $j
    Remove-Item (Join-Path $D "pedida") -Force -ErrorAction SilentlyContinue
    Estado $texto
}

# senal de vida: el panel sabe que el actualizador esta activado en este equipo
Escribir "actualizador_vivo" (Get-Date).ToString("o")
if (-not (Test-Path (Join-Path $D "pedida"))) { exit 0 }

$pedida = ((Get-Content (Join-Path $D "pedida") -Raw) -replace '[^0-9.]', '')
$actual = ((Get-Content (Join-Path $R "VERSION") -Raw -ErrorAction SilentlyContinue) -replace '[^0-9.]', '')
Estado "Peticion recibida: actualizar de $actual a $pedida"
if (-not ((Test-Path $Clave) -and ((Get-Content $Clave -Raw) -match "ssh-"))) {
    Resultado $false "Esta instalacion no tiene la clave de publicacion de OCTOPUS (install\firma_publicacion.pub): por seguridad la actualizacion a distancia esta desactivada. Actualiza a mano con el instalador de la version nueva."
    exit 1
}
$url = Leer "OCTOPUS_URL_CODIGO"; if (-not $url) { $url = "https://codeload.github.com/josemurajo/OCTOPUS/tar.gz/refs/heads/publicado" }
$proto = Leer "OCTOPUS_PROTO_DESCARGA"   # solo para pruebas; por defecto solo HTTPS
$esquema = ([Uri]$url).Scheme
if ($esquema -ne "https" -and -not ($proto -and $proto.TrimStart('=') -eq $esquema)) {
    Resultado $false "La direccion de descarga no es HTTPS: no se descarga nada."
    exit 1
}
$tmp = Join-Path $env:TEMP ("octopus_act_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path "$tmp\x" | Out-Null
try {
    Estado "Descargando la version nueva desde GitHub..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    if ($esquema -eq "file") { Copy-Item ([Uri]$url).LocalPath "$tmp\codigo.tar.gz" }
    else { Invoke-WebRequest -Uri $url -OutFile "$tmp\codigo.tar.gz" -UseBasicParsing -TimeoutSec 600 -ErrorAction Stop }
    & tar.exe -xzf "$tmp\codigo.tar.gz" -C "$tmp\x"
    if ($LASTEXITCODE -ne 0) { Resultado $false "La descarga esta danada"; exit 1 }
    $nuevo = (Get-ChildItem "$tmp\x" -Directory | Select-Object -First 1).FullName
    Estado "Comprobando la firma de la version nueva..."
    $salida = (& $Py (Join-Path $R "lib\firma.py") verificar $Clave $nuevo 2>&1) -join " "
    if ($LASTEXITCODE -ne 0) {
        Resultado $false "No se instala nada: $($salida -replace '^NO: ', ''). Si no lo esperabas, avisa al soporte."
        exit 1
    }
    $vnueva = ((Get-Content (Join-Path $nuevo "VERSION") -Raw) -replace '[^0-9.]', '')
    & $Py (Join-Path $R "lib\firma.py") version-mayor $vnueva $actual
    if ($LASTEXITCODE -ne 0) { Resultado $false "La version publicada ($vnueva) no es mas nueva que la instalada ($actual): no hay nada que actualizar."; exit 0 }
    Estado "Firma correcta (version $vnueva). Instalando (unos minutos; el panel se reinicia)..."
    $log = Join-Path $R "datos\logs\actualizacion_$vnueva.log"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $nuevo "instalar_servidor_windows.ps1") -SinPreguntas -Destino $R *> $log
    if ($LASTEXITCODE -eq 0) {
        Resultado $true "Actualizado a la version $vnueva. Todo funciona. (Copia de la version anterior en $R.anterior)"
    } else {
        $ult = ((Get-Content $log -Tail 3 -ErrorAction SilentlyContinue) -join " ")
        Resultado $false "La instalacion de $vnueva dio problemas y se ha dejado todo como estaba: $($ult.Substring(0, [Math]::Min(300, $ult.Length)))"
        exit 1
    }
} catch {
    Resultado $false "No se pudo actualizar: $($_.Exception.Message). Se reintentara cuando lo vuelvas a pedir."
    exit 1
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
