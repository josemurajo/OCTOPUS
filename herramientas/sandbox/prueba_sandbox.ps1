# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jose Murillo Rajo - OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS - prueba completa DENTRO del Espacio aislado de Windows (Windows Sandbox).
#
# La lanza sola el archivo PROBAR_OCTOPUS.wsb. Dentro de ese Windows desechable instala el servidor de OCTOPUS y un
# equipo con su agente, hace una copia, estropea y recupera archivos, y abre el panel para que lo mires. Al cerrar
# la ventana del Espacio aislado, Windows lo borra TODO: en tu PC no queda nada.
#
# Funciona con el PowerShell que trae Windows (5.1). Las pruebas de GitHub la ejecutan igual en un Windows real,
# con OCTOPUS_ZIP_PRUEBA (el codigo ya descargado) y OCTOPUS_SIN_NAVEGADOR=1.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try { $Host.UI.RawUI.WindowTitle = "OCTOPUS - prueba en el Espacio aislado" } catch {}

$Base = if ($env:OCTOPUS_PRUEBA_DIR) { $env:OCTOPUS_PRUEBA_DIR } else { "C:\OCTOPUS-prueba" }
$R = "C:\ProgramData\OCTOPUS-Servidor"
$script:Fallos = @()
$script:Pasos = @()

function Titulo($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Paso($ok, $nombre, $detalle = "") {
    $script:Pasos += [pscustomobject]@{ ok = [bool]$ok; nombre = $nombre }
    if ($ok) { Write-Host "    [OK]    $nombre $detalle" -ForegroundColor Green }
    else { Write-Host "    [FALLO] $nombre $detalle" -ForegroundColor Red; $script:Fallos += $nombre }
}
# el panel usa un certificado propio de OCTOPUS: para comprobar que responde se acepta sin mas (solo en esta prueba)
Add-Type @"
using System.Net; using System.Security.Cryptography.X509Certificates;
public class OctopusConfiarPrueba : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint s, X509Certificate c, WebRequest r, int p) { return true; }
}
"@ -ErrorAction SilentlyContinue
[Net.ServicePointManager]::CertificatePolicy = New-Object OctopusConfiarPrueba
function Salud { try { return (Invoke-WebRequest "https://127.0.0.1:8080/healthz" -UseBasicParsing -TimeoutSec 5).Content } catch { return "" } }
function Esperar($seg) { $fin = (Get-Date).AddSeconds($seg); while ((Get-Date) -lt $fin) { if (Salud) { return $true }; Start-Sleep 3 }; return $false }

Write-Host ""
Write-Host "  OCTOPUS - prueba completa en un Windows desechable" -ForegroundColor White
Write-Host "  Todo lo que pase aqui se borra al cerrar la ventana del Espacio aislado." -ForegroundColor Gray
Write-Host "  Tarda unos 15 minutos. No hace falta que toques nada."

# 1. el codigo de OCTOPUS (lo ultimo de GitHub)
Titulo "Descargando OCTOPUS"
New-Item -ItemType Directory -Force -Path $Base | Out-Null
$zip = "$Base\octopus.zip"
if ($env:OCTOPUS_ZIP_PRUEBA) { Copy-Item $env:OCTOPUS_ZIP_PRUEBA $zip -Force }
else {
    try { Invoke-WebRequest "https://codeload.github.com/josemurajo/OCTOPUS/zip/refs/heads/main" -OutFile $zip -UseBasicParsing }
    catch { Paso $false "descargar OCTOPUS de GitHub" $_.Exception.Message }
}
Expand-Archive $zip -DestinationPath "$Base\x" -Force
$Repo = (Get-ChildItem "$Base\x" -Directory | Select-Object -First 1).FullName
Paso (Test-Path "$Repo\instalar_servidor_windows.ps1") "codigo descargado" "($(Get-Content "$Repo\VERSION" -ErrorAction SilentlyContinue))"

# 2. el servidor, como lo instalaria cualquiera (doble clic = este mismo instalador)
Titulo "Instalando el servidor (5 minutos)"
$t0 = Get-Date
& powershell -NoProfile -ExecutionPolicy Bypass -File "$Repo\instalar_servidor_windows.ps1" -SinPreguntas -IP 127.0.0.1 -Registro "$Base\instalacion.log" | Out-Host
Paso ($LASTEXITCODE -eq 0) "el instalador termina bien" ("{0:N0} s" -f ((Get-Date) - $t0).TotalSeconds)
Paso (Esperar 180) "el panel responde"

# 3. lo nuevo, en este Windows de verdad: modo discreto, modo casa y destinos de copia
$env:OCTOPUS_NATIVO = "1"; $env:OCTOPUS_DATA = "$R\datos"; $env:OCTOPUS_BOVEDA_DIR = "$R\boveda"; $env:OCTOPUS_BIN = "$R\bin"
$env:RESTIC_CACHE_DIR = "$R\datos\.cache\restic"; $env:PYTHONUTF8 = "1"; $env:PATH = "$R\bin;$env:PATH"
New-Item -ItemType Directory -Force -Path "$R\tests\ci" | Out-Null
foreach ($f in "prueba_agente.py", "prueba_casa.py", "prueba_discreto.py") { Copy-Item "$Repo\tests\ci\$f" "$R\tests\ci\" -Force }
$Py = "$R\python\python.exe"
function Lanzar($titulo, $argumentos) {
    Titulo $titulo
    $salida = & $Py @argumentos 2>&1
    foreach ($l in $salida) {
        $t = "$l"
        if ($t -match "^(PASS|FAIL) (.*)$") { Paso ($Matches[1] -eq "PASS") $Matches[2] }
        elseif ($t -match "^RESULT\|(PASS|FAIL)\|([^|]*)") { Paso ($Matches[1] -eq "PASS") $Matches[2] }
        elseif ($t -notmatch "^FALLOS:|^RESUMEN:") { Write-Host "    $t" -ForegroundColor DarkGray }
    }
}
Lanzar "Que no se note: mide este ordenador (procesador, grafica, bateria) y frena si se usa a fondo" @("$R\tests\ci\prueba_discreto.py")
$Datos = "C:\Users\prueba_casa\Documents"
New-Item -ItemType Directory -Force -Path $Datos | Out-Null
[IO.File]::WriteAllText("$Datos\documento.txt", "datos importantes")   # sin BOM: igual que lo comprueba la prueba
Lanzar "Modo casa: elegir casa, proteger este ordenador y hacer la primera copia (3 minutos)" @("$R\tests\ci\prueba_casa.py", "nativo")
$Equipo = (& $Py -c "import socket; print(socket.gethostname().split('.')[0])").Trim()
Lanzar "Destinos de copia: copiar directo a otra carpeta, ademas y en lugar del servidor (3 minutos)" @("$R\tests\ci\prueba_agente.py", "destino", $Equipo, $Datos, "C:\OCTOPUS-otro-destino")
$Clave = "ClaveDeCasa-2026!x"

# 4. resumen y el panel abierto para mirarlo
$bien = @($script:Pasos | Where-Object { $_.ok }).Count
Write-Host ""
if ($script:Fallos.Count -eq 0) {
    Write-Host "  TODO CORRECTO: $bien de $($script:Pasos.Count) pruebas bien." -ForegroundColor Green
} else {
    Write-Host "  Han fallado $($script:Fallos.Count) de $($script:Pasos.Count) pruebas:" -ForegroundColor Red
    $script:Fallos | ForEach-Object { Write-Host "   - $_" -ForegroundColor Red }
    Write-Host "  Haz una foto de esta ventana y pasasela a Claude." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  Ahora puedes mirar el panel. Se abre solo en el navegador: https://127.0.0.1:8080" -ForegroundColor White
Write-Host "  (avisara del certificado: 'Configuracion avanzada' -> 'Continuar')."
Write-Host "    Usuario: admin     Contrasena: $Clave   (solo existe en este Windows desechable)" -ForegroundColor Yellow
Write-Host "  Este ordenador ya esta protegido en modo casa. Su carpeta de prueba es '$Datos'."
Write-Host ""
Write-Host "  Cuando termines, CIERRA LA VENTANA DEL ESPACIO AISLADO: se borra todo y en tu PC no queda nada." -ForegroundColor Cyan
if (-not $env:OCTOPUS_SIN_NAVEGADOR) { Start-Process "https://127.0.0.1:8080" }
if ($env:OCTOPUS_SIN_NAVEGADOR) { if ($script:Fallos.Count) { exit 1 } else { exit 0 } }
