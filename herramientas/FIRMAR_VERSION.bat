@echo off
rem OCTOPUS Zero-Touch - FIRMAR UNA VERSION (solo Jose, en su PC). Guardalo en el escritorio.
rem Doble clic cuando Claude avise de que hay una version preparada. Pide tu frase de paso, firma, y deja la firma
rem copiada: la pegas en el chat de Claude (Ctrl+V). La clave privada nunca sale de tu PC.
title OCTOPUS - firmar version
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText('%~f0'); $i=$s.LastIndexOf('#'+'PS1'); iex $s.Substring($i)"
set RC=%ERRORLEVEL%
if not defined OCTOPUS_SIN_PAUSA pause
exit /b %RC%
#PS1
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
function Mal($t) { Write-Host ""; Write-Host "  NO SE HA FIRMADO: $t" -ForegroundColor Red; exit 1 }

$base = if ($env:OCTOPUS_URL_BASE) { $env:OCTOPUS_URL_BASE } else { "https://raw.githubusercontent.com/josemurajo/OCTOPUS/main" }
$clave = if ($env:OCTOPUS_CLAVE_PUBLICAR) { $env:OCTOPUS_CLAVE_PUBLICAR } else { "$env:USERPROFILE\.ssh\octopus_publicar" }
$destino = if ($env:OCTOPUS_DESTINO_FIRMA) { $env:OCTOPUS_DESTINO_FIRMA } else { [Environment]::GetFolderPath("Desktop") }

Write-Host ""
Write-Host "  OCTOPUS - firmar la version preparada" -ForegroundColor White
if (-not (Test-Path $clave)) { Mal "no encuentro tu clave de publicacion en $clave" }
$sk = @("$env:ProgramFiles\Git\usr\bin\ssh-keygen.exe", "${env:ProgramFiles(x86)}\Git\usr\bin\ssh-keygen.exe",
        "$env:LOCALAPPDATA\Programs\Git\usr\bin\ssh-keygen.exe") | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $sk) { $c = Get-Command ssh-keygen -ErrorAction SilentlyContinue; if ($c) { $sk = $c.Source } }
if (-not $sk) { Mal "falta ssh-keygen: instala Git for Windows (gratis, git-scm.com)" }

$tmp = Join-Path $env:TEMP ("octopus_firma_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
$t = [DateTime]::Now.Ticks
function Bajar($ruta, $archivo) { Invoke-WebRequest "$base/$($ruta)?t=$t" -OutFile (Join-Path $tmp $archivo) -UseBasicParsing }
try { Bajar "MANIFIESTO" "MANIFIESTO" } catch { Mal "no hay ninguna version preparada para firmar. Espera a que Claude te avise." }
try { Bajar "VERSION" "VERSION"; Bajar "install/firma_publicacion.pub" "proyecto.pub" } catch { Mal "no se puede descargar de GitHub (hay Internet?)" }
$ya = $true; try { Bajar "MANIFIESTO.sig" "ya.sig" } catch { $ya = $false }
$version = (Get-Content (Join-Path $tmp "VERSION") -Raw).Trim()
if ($ya) { Write-Host ""; Write-Host "  La version $version ya esta firmada. No hay que hacer nada." -ForegroundColor Green; exit 0 }

$mia = ((Get-Content "$clave.pub" -Raw).Trim() -split "\s+")[1]
$suya = ((Get-Content (Join-Path $tmp "proyecto.pub") -Raw).Trim() -split "\s+")[1]
if ($mia -ne $suya) { Mal "la clave publica del proyecto NO es la tuya. No firmes y avisa a Claude." }

Write-Host ""
Write-Host "  Vas a firmar la version $version." -ForegroundColor Cyan
Write-Host "  Escribe la frase de paso de tu clave (no se ve mientras escribes) y pulsa Enter."
$m = Join-Path $tmp "MANIFIESTO"
$ErrorActionPreference = "Continue"
& $sk -Y sign -f $clave -n octopus-version $m
$sig = "$m.sig"
if (-not (Test-Path $sig)) { Mal "no se ha creado la firma (la frase de paso estaba bien?). Vuelve a intentarlo." }

# comprobar la firma igual que lo haran los servidores
$firmantes = Join-Path $tmp "firmantes"
[IO.File]::WriteAllText($firmantes, "octopus namespaces=`"octopus-version`" " + (Get-Content "$clave.pub" -Raw).Trim() + "`n")
cmd /c "`"$sk`" -Y verify -f `"$firmantes`" -I octopus -n octopus-version -s `"$sig`" < `"$m`"" | Out-Null
if ($LASTEXITCODE -ne 0) { Mal "la firma no se ha podido comprobar. Avisa a Claude." }

$texto = [IO.File]::ReadAllText($sig)
Copy-Item $sig (Join-Path $destino "MANIFIESTO.sig") -Force
try { Set-Clipboard -Value $texto } catch { }
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "  LISTO: version $version firmada." -ForegroundColor Green
Write-Host "  La firma esta COPIADA. Ve al chat de Claude, pega (Ctrl+V) y envia." -ForegroundColor Yellow
Write-Host "  (Tambien la tienes en el escritorio: MANIFIESTO.sig. No es secreta.)"
exit 0
