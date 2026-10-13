# OCTOPUS - (pruebas de GitHub) instala el servidor NATIVO de Windows como lo haria un usuario y lo prueba entero:
# arranca, se vuelve a levantar solo si se cae, gestion con octopus.ps1, copia y restauracion de un agente real,
# reinstalar sin perder nada y actualizacion a distancia firmada (y que una manipulada NO se instala).
# Se ejecuta con pwsh desde la carpeta del repositorio, como administrador.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$Repo = (Get-Location).Path
$R = "C:\ProgramData\OCTOPUS-Servidor"
$script:Fallos = @()
function Resultado($ok, $nombre, $detalle = "") {
    if ($ok) { Write-Host "RESULT|PASS|$nombre|$detalle" -ForegroundColor Green }
    else { Write-Host "RESULT|FAIL|$nombre|$detalle" -ForegroundColor Red; $script:Fallos += $nombre }
}
function Salud { try { return (Invoke-WebRequest "https://127.0.0.1:8080/healthz" -SkipCertificateCheck -TimeoutSec 5).Content } catch { return "" } }
function Esperar($seg) { $fin = (Get-Date).AddSeconds($seg); while ((Get-Date) -lt $fin) { if (Salud) { return $true }; Start-Sleep -Seconds 3 }; return $false }
function Instalar { & powershell -NoProfile -ExecutionPolicy Bypass -File "$Repo\instalar_servidor_windows.ps1" -SinPreguntas -IP 127.0.0.1 -Registro "$env:RUNNER_TEMP\instalacion.log"; return $LASTEXITCODE }
function Entorno {
    $env:OCTOPUS_NATIVO = "1"; $env:OCTOPUS_DATA = "$R\datos"; $env:OCTOPUS_BOVEDA_DIR = "$R\boveda"; $env:OCTOPUS_BIN = "$R\bin"
    $env:RESTIC_CACHE_DIR = "$R\datos\.cache\restic"; $env:PYTHONUTF8 = "1"; $env:PATH = "$R\bin;$env:PATH"
}
function Equipos { Entorno; return (& "$R\python\python.exe" -c "import sqlite3;print(sqlite3.connect(r'$R\data\admin_panel.db').execute('select count(*) from systems').fetchone()[0])") }

# 1. instalar como un usuario (doble clic -> el .bat llama a este mismo instalador)
$t0 = Get-Date
$rc = Instalar
Resultado ($rc -eq 0) "el instalador nativo termina bien (sin WSL2 ni Docker)" ("{0:N0} s" -f ((Get-Date) - $t0).TotalSeconds)
$s = Salud
Resultado ([bool]$s) "el panel responde" $s
$t = Get-ScheduledTask -TaskName "OCTOPUS Servidor" -ErrorAction SilentlyContinue
$arranque = $t -and @($t.Triggers | Where-Object { $_.CimClass.CimClassName -eq "MSFT_TaskBootTrigger" }).Count -gt 0
Resultado ($t -and $t.Principal.UserId -eq "SYSTEM" -and $arranque) "arranca solo al encender Windows (tarea del sistema, sin iniciar sesion)"
Resultado ([bool](Get-ScheduledTask -TaskName "OCTOPUS Actualizador" -ErrorAction SilentlyContinue)) "actualizador automatico programado"
$procs = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "$R\*" })
$nombres = ($procs.Name | Sort-Object -Unique) -join ","
Resultado (($procs.Name -contains "python.exe") -and ($procs.Name -contains "rest-server.exe")) "funciona con su propio Python y rest-server" $nombres
$log = Get-Content "$R\datos\logs\servidor.log" -Raw -ErrorAction SilentlyContinue
Resultado ($log -match "cheroot en .* \(HTTPS") "panel con cheroot y HTTPS"
Resultado ([bool](Get-NetFirewallRule -DisplayName "OCTOPUS 8080" -ErrorAction SilentlyContinue)) "puertos abiertos en el Firewall de Windows"
Resultado (Test-Path "$R\data\CREDENCIALES_INICIALES.txt") "contrasena inicial creada"

# 2. si se cae, se levanta solo
$procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 5
$caido = -not (Salud)
Resultado ($caido -and (Esperar 240)) "si se para de golpe, vuelve a arrancar solo"

# 3. gestion
$e = (& powershell -NoProfile -ExecutionPolicy Bypass -File "$R\octopus.ps1" estado | Out-String)
Resultado ($e -match "Panel: \{") "octopus.ps1 estado" (($e -split "`n" | Select-Object -First 3) -join " / ")
& powershell -NoProfile -ExecutionPolicy Bypass -File "$R\octopus.ps1" reiniciar | Out-Null
Resultado (Esperar 120) "octopus.ps1 reiniciar"

# 4. un agente de verdad: alta, instalacion, copia, restaurar archivo y carpeta
New-Item -ItemType Directory -Force -Path "$R\tests\ci" | Out-Null
Copy-Item "$Repo\tests\ci\prueba_agente.py" "$R\tests\ci\" -Force
Entorno
& "$R\python\python.exe" "$R\tests\ci\prueba_agente.py" preparar windows ci-agente C:\octopus_ci "$env:RUNNER_TEMP\inst"
& powershell -NoProfile -ExecutionPolicy Bypass -File "$env:RUNNER_TEMP\inst\instalar_windows.ps1"
& "$R\python\python.exe" "$R\tests\ci\prueba_agente.py" probar ci-agente C:\octopus_ci
Resultado ($LASTEXITCODE -eq 0) "agente: copia y restauracion contra el servidor nativo"

# 5. volver a instalar (actualizar a mano) no pierde nada
$antes = Equipos
$rc = Instalar
Resultado ($rc -eq 0 -and (Salud)) "volver a instalar (actualizar) funciona"
Resultado ((Equipos) -eq $antes -and $antes -ge 1) "al reinstalar se conservan los equipos y los datos" "equipos: $antes -> $(Equipos)"
Resultado (Test-Path "$R.anterior\lib\servidor.py") "se guarda la version anterior por si hay que volver"

# 6. actualizacion a distancia firmada (desde un archivo local, con una clave de PRUEBA)
$claves = "$env:RUNNER_TEMP\claves"
$bash = "C:\Program Files\Git\bin\bash.exe"   # el de Git (el bash.exe de System32 seria WSL)
& $bash tests/ci/version_firmada.sh "$env:RUNNER_TEMP/buena.tar.gz" 9.9.9 $claves
& $bash tests/ci/version_firmada.sh "$env:RUNNER_TEMP/mala.tar.gz" 9.9.10 $claves manipular
Copy-Item "$claves\clave.pub" "$R\install\firma_publicacion.pub" -Force
function Pedir($archivo, $version) {
    $url = ([Uri]$archivo).AbsoluteUri
    $env_ = (Get-Content "$R\install\.env" | Where-Object { $_ -notmatch '^OCTOPUS_(URL_CODIGO|PROTO_DESCARGA)=' }) + "OCTOPUS_URL_CODIGO=$url" + "OCTOPUS_PROTO_DESCARGA==file"
    [IO.File]::WriteAllText("$R\install\.env", (($env_ -join "`n") + "`n"))
    New-Item -ItemType Directory -Force -Path "$R\datos\actualizacion" | Out-Null
    Remove-Item "$R\datos\actualizacion\resultado.json" -ErrorAction SilentlyContinue
    Set-Content "$R\datos\actualizacion\pedida" $version
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$R\actualizador.ps1"
    return (Get-Content "$R\datos\actualizacion\resultado.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json)
}
$r = Pedir "$env:RUNNER_TEMP\mala.tar.gz" "9.9.10"
Resultado ($r -and -not $r.ok -and ((Get-Content "$R\VERSION" -Raw).Trim() -ne "9.9.10")) "version manipulada: NO se instala" $r.detalle
$r = Pedir "$env:RUNNER_TEMP\buena.tar.gz" "9.9.9"
Resultado ($r -and $r.ok -and ((Get-Content "$R\VERSION" -Raw).Trim() -eq "9.9.9") -and (Salud)) "version firmada: se actualiza sola y sigue funcionando" $r.detalle
Resultado ((Equipos) -ge 1) "tras actualizar a distancia se conservan los equipos"

Write-Host ""
if ($script:Fallos.Count) { Write-Host "FALLOS: $($script:Fallos -join ', ')" -ForegroundColor Red; exit 1 }
Write-Host "TODO CORRECTO" -ForegroundColor Green
exit 0
