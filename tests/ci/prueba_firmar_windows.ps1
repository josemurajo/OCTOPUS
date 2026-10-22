# OCTOPUS - (pruebas de GitHub, Windows) prueba herramientas/FIRMAR_VERSION.bat como lo usara Jose, con una clave de
# PRUEBA y un "GitHub" simulado (un servidor web local): firma, la firma vale, no firma con otra clave, y avisa si ya
# estaba firmada o si no hay version preparada.
$ErrorActionPreference = "Continue"
$Repo = (Get-Location).Path
$T = Join-Path $env:RUNNER_TEMP "firmar"
$script:Fallos = @()
function Resultado($ok, $nombre, $detalle = "") {
    if ($ok) { Write-Host "RESULT|PASS|$nombre|$detalle" -ForegroundColor Green }
    else { Write-Host "RESULT|FAIL|$nombre|$detalle" -ForegroundColor Red; $script:Fallos += $nombre }
}
$sk = "C:\Program Files\Git\usr\bin\ssh-keygen.exe"
New-Item -ItemType Directory -Force -Path "$T\web\install", "$T\escritorio" | Out-Null
# claves de prueba sin frase de paso (con pwsh 7.3+ un "" llega a ssh-keygen como argumento vacio)
& $sk -q -t ed25519 -N "" -C prueba -f "$T\clave" | Out-Null
& $sk -q -t ed25519 -N "" -C otra -f "$T\otra" | Out-Null
Resultado ((Test-Path "$T\clave") -and (Test-Path "$T\otra")) "claves de prueba creadas"
"9.9.9" | Set-Content "$T\web\VERSION"
"0123abcd  lib/servidor.py" | Set-Content "$T\web\MANIFIESTO"
Copy-Item "$T\clave.pub" "$T\web\install\firma_publicacion.pub"

$web = Start-Process python -ArgumentList "-m", "http.server", "8765", "--bind", "127.0.0.1" -WorkingDirectory "$T\web" -PassThru -WindowStyle Hidden
Start-Sleep 3
$env:OCTOPUS_URL_BASE = "http://127.0.0.1:8765"; $env:OCTOPUS_DESTINO_FIRMA = "$T\escritorio"; $env:OCTOPUS_SIN_PAUSA = "1"
function Firmar($clave) { $env:OCTOPUS_CLAVE_PUBLICAR = $clave; $o = (cmd /c "`"$Repo\herramientas\FIRMAR_VERSION.bat`"" 2>&1 | Out-String); return @($LASTEXITCODE, $o) }

# 1. con la clave buena
$rc, $o = Firmar "$T\clave"
Write-Host $o
$sig = "$T\escritorio\MANIFIESTO.sig"
Resultado ($rc -eq 0 -and (Test-Path $sig)) "firma la version preparada y deja MANIFIESTO.sig"
Resultado ($o -match "COPIADA") "dice que la firma queda copiada para pegarla en el chat"
"octopus namespaces=`"octopus-version`" $((Get-Content "$T\clave.pub" -Raw).Trim())" | Set-Content "$T\firmantes" -Encoding ascii
cmd /c "`"$sk`" -Y verify -f `"$T\firmantes`" -I octopus -n octopus-version -s `"$sig`" < `"$T\web\MANIFIESTO`"" | Out-Null
Resultado ($LASTEXITCODE -eq 0) "la firma vale para el MANIFIESTO publicado (como lo comprueba un servidor)"

# 2. con otra clave: no firma
Remove-Item $sig -ErrorAction SilentlyContinue
$rc, $o = Firmar "$T\otra"
Resultado ($rc -ne 0 -and -not (Test-Path $sig) -and $o -match "NO es la tuya") "con otra clave NO firma y lo explica"

# 3. ya firmada
Copy-Item "$T\web\MANIFIESTO" "$T\web\MANIFIESTO.sig"
$rc, $o = Firmar "$T\clave"
Resultado ($rc -eq 0 -and $o -match "ya esta firmada") "si ya esta firmada, lo dice y no hace nada"
Remove-Item "$T\web\MANIFIESTO.sig"

# 4. sin version preparada
Remove-Item "$T\web\MANIFIESTO"
$rc, $o = Firmar "$T\clave"
Resultado ($rc -ne 0 -and $o -match "no hay ninguna version preparada") "sin version preparada, lo dice"

Stop-Process -Id $web.Id -Force -ErrorAction SilentlyContinue
if ($script:Fallos.Count) { Write-Host "FALLOS: $($script:Fallos -join ', ')" -ForegroundColor Red; exit 1 }
Write-Host "TODO CORRECTO" -ForegroundColor Green
exit 0
