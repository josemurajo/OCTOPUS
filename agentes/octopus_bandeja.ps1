# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jose Murillo Rajo - OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS - icono junto al reloj de Windows: "OCTOPUS te protege".
#
# Para que la persona se SIENTA protegida sin que le moleste: un pulpo pequeno junto al reloj, en verde si todo va
# bien y en naranja si hay algo que mirar. Al pasar el raton dice cuando fue la ultima copia. Solo avisa con un
# globo si algo va mal, y como mucho una vez cada 12 horas (Windows ademas lo calla en pantalla completa / juegos).
# Doble clic: abre el panel. Lo arranca Windows al iniciar sesion (tarea "OCTOPUS Icono"); se puede ocultar.
#
# Lee el estado que deja el agente en C:\ProgramData\Octopus-estado\estado.json (sin claves: lo puede leer todo
# el mundo). Con -Prueba solo calcula el texto y lo escribe (lo usan las pruebas de GitHub).
param([switch]$Prueba, [string]$Estado = "$env:ProgramData\Octopus-estado\estado.json")
$ErrorActionPreference = "SilentlyContinue"

function Leer {
    try { return Get-Content $Estado -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}
function Hace($iso) {
    try {
        $t = [DateTime]::Parse($iso).ToLocalTime()
        $m = [int]((Get-Date) - $t).TotalMinutes
        if ($m -lt 2) { return "hace un momento" }
        if ($m -lt 60) { return "hace $m min" }
        if ($m -lt 48 * 60) { return "hace $([int]($m / 60)) h" }
        return "hace $([int]($m / 1440)) dias"
    } catch { return "" }
}
function Texto($e) {
    if (-not $e) { return @{ ok = $true; texto = "OCTOPUS: preparando la proteccion de este ordenador" } }
    $cuando = if ($e.ultima_copia) { "Ultima copia " + (Hace $e.ultima_copia) } else { "Aun sin copias" }
    if ($e.ok) { return @{ ok = $true; texto = "OCTOPUS te protege. $cuando." } }
    return @{ ok = $false; texto = "OCTOPUS: $($e.texto)" }
}

if ($Prueba) { $r = Texto (Leer); Write-Output ("{0}|{1}" -f $(if ($r.ok) { "OK" } else { "AVISO" }), $r.texto); exit 0 }

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
# un solo icono por sesion
$mutex = New-Object System.Threading.Mutex($false, "Local\OctopusIcono")
if (-not $mutex.WaitOne(0)) { exit 0 }

function Icono($verde) {
    $bmp = New-Object System.Drawing.Bitmap 32, 32
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = "AntiAlias"
    $color = if ($verde) { [System.Drawing.Color]::FromArgb(23, 92, 140) } else { [System.Drawing.Color]::FromArgb(214, 120, 0) }
    $pincel = New-Object System.Drawing.SolidBrush $color
    $g.FillEllipse($pincel, 6, 2, 20, 18)
    foreach ($x in 7, 12, 17, 22) { $g.FillRectangle($pincel, $x, 16, 3, 13) }
    $blanco = [System.Drawing.Brushes]::White
    $g.FillEllipse($blanco, 11, 8, 4, 4); $g.FillEllipse($blanco, 17, 8, 4, 4)
    $g.Dispose()
    return [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
}
$iconoOk = Icono $true
$iconoAviso = Icono $false

$ni = New-Object System.Windows.Forms.NotifyIcon
$ni.Icon = $iconoOk
$ni.Text = "OCTOPUS te protege"
$ni.Visible = $true
function AbrirPanel { $e = Leer; if ($e -and $e.panel) { Start-Process $e.panel } }
$menu = New-Object System.Windows.Forms.ContextMenuStrip
[void]$menu.Items.Add("Abrir OCTOPUS", $null, { AbrirPanel })
[void]$menu.Items.Add("Ocultar este icono", $null, { $ni.Visible = $false; [System.Windows.Forms.Application]::Exit() })
$ni.ContextMenuStrip = $menu
$ni.add_DoubleClick({ AbrirPanel })

$script:ultimoGlobo = [DateTime]::MinValue
$script:estabaBien = $true
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 60000
$timer.add_Tick({
    $r = Texto (Leer)
    $t = $r.texto
    $ni.Text = if ($t.Length -gt 63) { $t.Substring(0, 63) } else { $t }   # Windows corta a 63 letras
    $ni.Icon = if ($r.ok) { $iconoOk } else { $iconoAviso }
    if (-not $r.ok -and ($script:estabaBien -or ((Get-Date) - $script:ultimoGlobo).TotalHours -ge 12)) {
        $ni.ShowBalloonTip(10000, "OCTOPUS", $t, [System.Windows.Forms.ToolTipIcon]::Warning)
        $script:ultimoGlobo = Get-Date
    }
    $script:estabaBien = $r.ok
})
$timer.Start()
$timer.GetType().GetMethod("OnTick", [Reflection.BindingFlags]"NonPublic,Instance").Invoke($timer, @([EventArgs]::Empty))
[System.Windows.Forms.Application]::Run()
$ni.Visible = $false
