# OCTOPUS - Limpieza de maquinas virtuales que sobran (VirtualBox + Vagrant)
#
# NUNCA borra las maquinas que usan los laboratorios (v1: Desktop\vagrant, v2: esta carpeta).
# Marca como SOBRA las copias viejas que Vagrant fue dejando y las borra de golpe si dices que si.
# Cualquier otra maquina se pregunta una a una (por defecto NO se borra).
$ErrorActionPreference = "Continue"

function Titulo($t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor Cyan }

$vbm = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
if (-not (Test-Path $vbm)) { $c = Get-Command VBoxManage -ErrorAction SilentlyContinue; if ($c) { $vbm = $c.Source } }
if (-not (Test-Path $vbm)) { Write-Host "No encuentro VirtualBox (VBoxManage.exe)." -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- maquinas que usan los laboratorios
$labs = @((Join-Path $env:USERPROFILE "Desktop\vagrant"), $PSScriptRoot)
$enUso = @{}
foreach ($lab in $labs) {
    $dir = Join-Path $lab ".vagrant\machines"
    if (-not (Test-Path $dir)) { continue }
    Get-ChildItem -Path $dir -Recurse -Filter "id" -ErrorAction SilentlyContinue | ForEach-Object {
        $id = (Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue)
        if ($id) { $enUso[$id.Trim().ToLower()] = (Split-Path $lab -Leaf) + " / " + $_.Directory.Parent.Name }
    }
}

# ---------------------------------------------------------------- todas las maquinas de VirtualBox
$encendidas = @{}
& $vbm list runningvms 2>$null | ForEach-Object { if ("$_" -match '\{([0-9a-fA-F-]+)\}') { $encendidas[$Matches[1].ToLower()] = $true } }

$lista = @()
& $vbm list vms 2>$null | ForEach-Object {
    if ("$_" -match '^"(.*)"\s+\{([0-9a-fA-F-]+)\}') {
        $nombre = $Matches[1]; $uuid = $Matches[2].ToLower()
        $carpeta = $null; $mb = 0
        $info = & $vbm showvminfo $uuid --machinereadable 2>$null
        foreach ($l in $info) { if ("$l" -match '^CfgFile="(.*)"$') { $carpeta = Split-Path ($Matches[1] -replace '\\\\', '\') -Parent } }
        if ($carpeta -and (Test-Path $carpeta)) {
            $mb = [math]::Round(((Get-ChildItem $carpeta -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum) / 1MB)
        }
        if ($enUso.ContainsKey($uuid)) { $tipo = "EN USO"; $nota = "laboratorio " + $enUso[$uuid] }
        elseif ($nombre -eq "<inaccessible>") { $tipo = "SOBRA"; $nota = "rota (VirtualBox no la encuentra)" }
        elseif ($nombre -match '^ZT2?-') { $tipo = "OTRA"; $nota = "es de OCTOPUS pero ningun laboratorio la usa ahora: se pregunta" }
        elseif ($nombre -match '_\d{10,}_\d+$' -or $nombre -match '_default_\d+') { $tipo = "SOBRA"; $nota = "copia vieja creada por Vagrant" }
        else { $tipo = "OTRA"; $nota = "no parece de OCTOPUS: se pregunta" }
        $lista += [pscustomobject]@{ Tipo = $tipo; Nombre = $nombre; MB = $mb; Encendida = [bool]$encendidas[$uuid]; Uuid = $uuid; Nota = $nota }
    }
}

if ($lista.Count -eq 0) { Write-Host "VirtualBox no tiene ninguna maquina." -ForegroundColor Green }

Titulo "Maquinas encontradas: $($lista.Count)"
foreach ($m in ($lista | Sort-Object Tipo, Nombre)) {
    $color = switch ($m.Tipo) { "EN USO" { "Green" } "SOBRA" { "Yellow" } default { "Gray" } }
    $enc = if ($m.Encendida) { " (encendida)" } else { "" }
    Write-Host ("  {0,-7} {1,-45} {2,7} MB{3}   {4}" -f $m.Tipo, $m.Nombre, $m.MB, $enc, $m.Nota) -ForegroundColor $color
}

function Borrar($m) {
    if ($m.Encendida) { & $vbm controlvm $m.Uuid poweroff 2>$null | Out-Null; Start-Sleep -Seconds 4 }
    & $vbm unregistervm $m.Uuid --delete 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { & $vbm unregistervm $m.Uuid 2>$null | Out-Null }
    $ok = -not ((& $vbm list vms 2>$null) -match [regex]::Escape($m.Uuid))
    if ($ok) { Write-Host "    borrada: $($m.Nombre)" -ForegroundColor Green; return $m.MB }
    Write-Host "    NO se pudo borrar: $($m.Nombre) (cierra VirtualBox y vuelve a probar)" -ForegroundColor Red
    return 0
}

$liberado = 0
$sobran = @($lista | Where-Object { $_.Tipo -eq "SOBRA" })
if ($sobran.Count -gt 0) {
    $total = ($sobran | Measure-Object MB -Sum).Sum
    Titulo "Sobran $($sobran.Count) maquinas ($total MB)"
    $r = Read-Host "Borrarlas todas? (S/N)"
    if ($r -match '^[sS]') { foreach ($m in $sobran) { $liberado += Borrar $m } }
    else { Write-Host "  No se borra ninguna." }
}

$otras = @($lista | Where-Object { $_.Tipo -eq "OTRA" })
if ($otras.Count -gt 0) {
    Titulo "Otras maquinas. Se pregunta una a una; por defecto NO se borran"
    foreach ($m in $otras) {
        $r = Read-Host ("  Borrar '{0}' ({1} MB)? (s/N)" -f $m.Nombre, $m.MB)
        if ($r -match '^[sS]') { $liberado += Borrar $m }
    }
}

Titulo "Limpieza de Vagrant"
& vagrant global-status --prune 2>$null | Out-Null
Write-Host "  Lista de maquinas de Vagrant actualizada (se quitan las que ya no existen)."
$r = Read-Host "Borrar tambien las versiones viejas de las imagenes descargadas (boxes) que no se usan? (S/N)"
if ($r -match '^[sS]') { & vagrant box prune --force 2>&1 | ForEach-Object { Write-Host "  $_" } }

Titulo "Terminado"
Write-Host "  Espacio liberado en maquinas: $liberado MB" -ForegroundColor Green
Write-Host "  Las maquinas EN USO de los laboratorios no se han tocado."
