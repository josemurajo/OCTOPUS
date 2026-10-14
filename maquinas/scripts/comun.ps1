# OCTOPUS - funciones comunes para los scripts del laboratorio Vagrant (PowerShell 5.1+)
# Se carga con:  . "$PSScriptRoot\scripts\comun.ps1"

$ErrorActionPreference = "Continue"
$Global:LabDir = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Global:LabDir "Vagrantfile"))) { $Global:LabDir = $PSScriptRoot }
$Global:ReportDir = Join-Path $Global:LabDir "reportes"
New-Item -ItemType Directory -Force -Path $Global:ReportDir | Out-Null
$Global:Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Global:LogFile = Join-Path $Global:ReportDir "ejecucion_$($Global:Stamp).log"
$Global:Results = New-Object System.Collections.ArrayList
$Global:IPs = @{ cerebro = "192.168.10.10"; cliente1 = "192.168.10.20"; cliente2 = "192.168.20.20";
                 rocky9 = "192.168.10.50"; debian12 = "192.168.10.60"; win2022 = "192.168.10.40" }
Set-Location $Global:LabDir

function Write-Log {
    param([string]$Text, [string]$Color = "Gray")
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Text
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $Global:LogFile -Value $line
}

function Add-Result {
    param([string]$Estado, [string]$Nombre, [string]$Detalle = "")
    [void]$Global:Results.Add([pscustomobject]@{ Estado = $Estado; Prueba = $Nombre; Detalle = $Detalle })
    $color = switch ($Estado) { "PASS" { "Green" } "FAIL" { "Red" } default { "Yellow" } }
    Write-Log ("{0,-4}  {1}  {2}" -f $Estado, $Nombre, $Detalle) $color
}

# Ejecuta vagrant mostrando la salida en pantalla y guardandola en el log. Devuelve el codigo de salida.
function Invoke-Vagrant {
    param([string[]]$VagrantArgs)
    Write-Log ("> vagrant " + ($VagrantArgs -join " ")) "Cyan"
    & vagrant @VagrantArgs 2>&1 | ForEach-Object { $s = "$_"; Write-Host $s; Add-Content -Path $Global:LogFile -Value $s }
    return $LASTEXITCODE
}

# Lee lo nuevo de un archivo que otro programa esta escribiendo; lo muestra y lo guarda en el log.
function Show-NuevoTexto {
    param([string]$Ruta, [long]$Desde)
    if (-not (Test-Path $Ruta)) { return $Desde }
    try {
        $fs = [IO.File]::Open($Ruta, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        try {
            if ($fs.Length -le $Desde) { return $Desde }
            [void]$fs.Seek($Desde, [IO.SeekOrigin]::Begin)
            $sr = New-Object IO.StreamReader($fs)
            $texto = $sr.ReadToEnd()
            $nuevo = $fs.Position
            foreach ($l in ($texto -split "`r?`n")) {
                if ($l -ne "") { Write-Host $l; Add-Content -Path $Global:LogFile -Value $l }
            }
            return $nuevo
        } finally { $fs.Close() }
    } catch { return $Desde }
}

# Como Invoke-Vagrant pero con tiempo maximo: si vagrant se queda parado (p. ej. cerebro colgado en
# "Configuring and enabling network interfaces..."), lo corta y devuelve 124.
function Invoke-VagrantLimite {
    param([string[]]$VagrantArgs, [int]$Minutos = 15)
    Write-Log ("> vagrant " + ($VagrantArgs -join " ") + "   (maximo $Minutos min)") "Cyan"
    $out = [IO.Path]::GetTempFileName()
    $err = [IO.Path]::GetTempFileName()
    try {
        $p = Start-Process -FilePath "vagrant" -ArgumentList $VagrantArgs -NoNewWindow -PassThru `
                           -RedirectStandardOutput $out -RedirectStandardError $err
        $null = $p.Handle   # sin esto, ExitCode puede salir vacio al terminar
        $limite = (Get-Date).AddMinutes($Minutos)
        $posOut = 0; $posErr = 0
        while (-not $p.HasExited) {
            Start-Sleep -Seconds 2
            $posOut = Show-NuevoTexto $out $posOut
            $posErr = Show-NuevoTexto $err $posErr
            if ((Get-Date) -gt $limite) {
                & taskkill /T /F /PID $p.Id 2>&1 | Out-Null
                Write-Log "vagrant lleva mas de $Minutos minutos sin terminar: se corta" "Yellow"
                return 124
            }
        }
        $p.WaitForExit()
        $posOut = Show-NuevoTexto $out $posOut
        $posErr = Show-NuevoTexto $err $posErr
        return $p.ExitCode
    } finally {
        Remove-Item $out, $err -Force -ErrorAction SilentlyContinue
    }
}

# Ejecuta un script bash como root dentro de una VM Linux. El script viaja en base64 para que
# PowerShell no rompa las comillas (era el fallo de los scripts antiguos). Devuelve objeto {Code, Output}.
function Invoke-VM {
    param([string]$VM, [string]$Bash, [switch]$Quiet)
    $clean = $Bash -replace "`r", ""
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($clean))
    $cmd = "echo $b64 | base64 -d | sudo bash"
    $out = & vagrant ssh $VM -c $cmd 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    Add-Content -Path $Global:LogFile -Value ("--- [{0}] codigo={1}" -f $VM, $code)
    if ($out) { Add-Content -Path $Global:LogFile -Value $out }
    if (-not $Quiet -and $out) { $out | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray } }
    return [pscustomobject]@{ Code = $code; Output = @($out) }
}

# Ejecuta PowerShell dentro de la VM Windows por WinRM (tambien codificado para evitar problemas de comillas)
function Invoke-WinVM {
    param([string]$VM, [string]$PS)
    $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($PS))
    $out = & vagrant winrm $VM -c "powershell -NoProfile -EncodedCommand $enc" 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    Add-Content -Path $Global:LogFile -Value ("--- [{0}] codigo={1}" -f $VM, $code)
    if ($out) { Add-Content -Path $Global:LogFile -Value $out }
    return [pscustomobject]@{ Code = $code; Output = @($out) }
}

# Estado de las maquinas segun vagrant (machine-readable, sin depender del idioma)
function Get-VMState {
    $states = @{}
    $lines = & vagrant status --machine-readable 2>$null
    foreach ($l in $lines) {
        $p = "$l".Split(",")
        if ($p.Count -ge 4 -and $p[2] -eq "state") { $states[$p[1]] = $p[3] }
    }
    return $states
}

function Test-Prerequisites {
    $ok = $true
    $v = (& vagrant --version 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $v) { Add-Result "FAIL" "Vagrant instalado" "no se encuentra 'vagrant' en el PATH"; $ok = $false }
    else { Add-Result "PASS" "Vagrant instalado" "$v" }

    $vbm = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
    if (-not (Test-Path $vbm)) { $c = Get-Command VBoxManage -ErrorAction SilentlyContinue; if ($c) { $vbm = $c.Source } }
    if (Test-Path $vbm) { Add-Result "PASS" "VirtualBox instalado" ((& $vbm --version) -join "") }
    else { Add-Result "FAIL" "VirtualBox instalado" "no se encuentra VBoxManage.exe"; $ok = $false }

    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
        $state = if ($freeGB -ge 6) { "PASS" } else { "WARN" }
        Add-Result $state "RAM libre en el host" "$freeGB GB (minimo recomendado 6 GB para cerebro+2 clientes)"
    } catch { }
    return $ok
}

function Write-Report {
    param([string]$Titulo = "INFORME DE PRUEBAS OCTOPUS ZERO-TOUCH")
    $file = Join-Path $Global:ReportDir "informe_$($Global:Stamp).txt"
    $pass = @($Global:Results | Where-Object { $_.Estado -eq "PASS" }).Count
    $fail = @($Global:Results | Where-Object { $_.Estado -eq "FAIL" }).Count
    $warn = @($Global:Results | Where-Object { $_.Estado -eq "WARN" }).Count
    $lines = @()
    $lines += "=" * 90
    $lines += "  $Titulo"
    $lines += "  Fecha: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')     Host: $env:COMPUTERNAME"
    $lines += "=" * 90
    foreach ($r in $Global:Results) { $lines += ("{0,-5} {1,-50} {2}" -f $r.Estado, $r.Prueba, $r.Detalle) }
    $lines += "-" * 90
    $global = if ($fail -eq 0) { "TODO CORRECTO" } else { "HAY FALLOS - revisa el log: $($Global:LogFile)" }
    $lines += "  RESUMEN: $pass correctas, $fail fallidas, $warn avisos  ->  $global"
    $lines += "=" * 90
    $lines | Set-Content -Path $file -Encoding UTF8
    Write-Host ""
    $lines | ForEach-Object {
        $c = if ($_ -like "FAIL*") { "Red" } elseif ($_ -like "PASS*") { "Green" } elseif ($_ -like "WARN*") { "Yellow" } else { "White" }
        Write-Host $_ -ForegroundColor $c
    }
    Write-Host ""
    Write-Host "Informe guardado en: $file" -ForegroundColor Cyan
    return $fail
}
