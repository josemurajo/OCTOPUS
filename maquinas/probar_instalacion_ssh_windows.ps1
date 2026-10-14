<#
OCTOPUS - Prueba de la INSTALACION A DISTANCIA en un Windows por SSH (lo que hace el boton «Buscar equipos en la red»).

  Servidor:  win11srv (servidor nativo de Windows, el de PROBAR_SERVIDOR_WINDOWS.bat; si no esta instalado, se instala)
  Equipo:    win2022  (Windows Server 2022 con el «Servidor OpenSSH» activado; se activa aqui si no lo esta)

  1. Apaga las demas maquinas y levanta las dos.
  2. Activa el Servidor OpenSSH en win2022 (la caracteristica opcional de Windows) y abre el puerto 22.
  3. Desde el servidor, con el mismo codigo que el panel: alta del equipo, instalacion por SSH (usuario vagrant de la
     maquina de pruebas), y comprueba que se conecta y responde. Tambien que una contrasena mala se explica bien.
Informe en reportes\informe_<fecha>.txt
#>
. "$PSScriptRoot\scripts\comun.ps1"
$SRV = "win11srv"; $SRV_IP = "192.168.10.70"; $EQ = "win2022"; $EQ_IP = "192.168.10.40"
$R = "C:\ProgramData\OCTOPUS-Servidor"
Write-Log "=== OCTOPUS - instalacion a distancia por SSH en Windows ($SRV -> $EQ) ===" "Green"

Write-Log "Apagando las demas maquinas para dejar memoria libre..." "Yellow"
Invoke-Vagrant @("halt", "cerebro", "cliente1", "cliente2", "debian12", "rocky9") | Out-Null
foreach ($m in @($SRV, $EQ)) {
    # --no-provision: win2022 tiene un aprovisionamiento antiguo que espera al cerebro; aqui no hace falta
    $rc = Invoke-VagrantLimite @("up", $m, "--no-provision") 120
    if ($rc -ne 0) { Add-Result "FAIL" "vagrant up $m" "codigo $rc (ver log)"; exit (Write-Report) }
    Add-Result "PASS" "vagrant up $m"
}

# 1. Servidor en win11srv (si no responde, se instala igual que en PROBAR_SERVIDOR_WINDOWS)
$hay = (Invoke-WinVM $SRV "if (Test-Path '$R\python\python.exe') { 'INSTALADO' }").Output -join " "
if ($hay -notmatch "INSTALADO") {
    Write-Log "Instalando el servidor nativo en $SRV..." "Cyan"
    $i = Invoke-WinVM $SRV "Remove-Item 'C:\OctopusServidor' -Recurse -Force -ErrorAction SilentlyContinue; robocopy C:\OCTOPUS C:\OctopusServidor /MIR /XD __pycache__ .git data datos /XF .env /NFL /NDL /NJH /NJS | Out-Null; & powershell -NoProfile -ExecutionPolicy Bypass -File C:\OctopusServidor\instalar_servidor_windows.ps1 -SinPreguntas -IP $SRV_IP; `"CODIGO=`$LASTEXITCODE`""
    if (($i.Output -join " ") -notmatch "CODIGO=0") { Add-Result "FAIL" "servidor en $SRV" (($i.Output | Select-Object -Last 6) -join " | "); exit (Write-Report) }
}
Add-Result "PASS" "servidor OCTOPUS en $SRV"

# 2. Servidor OpenSSH en win2022 (caracteristica opcional de Windows; la primera vez la descarga de Windows Update)
Write-Log "Activando el Servidor OpenSSH en $EQ (la primera vez puede tardar unos minutos)..." "Cyan"
$ssh = Invoke-WinVM $EQ @"
`$c = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
if (`$c.State -ne 'Installed') { Add-WindowsCapability -Online -Name `$c.Name | Out-Null }
Set-Service sshd -StartupType Automatic; Start-Service sshd
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow -Profile Any | Out-Null }
else { Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -Profile Any -Enabled True }
"SSHD=" + (Get-Service sshd).Status
"@
if (($ssh.Output -join " ") -match "SSHD=Running") { Add-Result "PASS" "${EQ}: Servidor OpenSSH activado" }
else { Add-Result "FAIL" "${EQ}: Servidor OpenSSH" (($ssh.Output | Select-Object -Last 4) -join " | "); exit (Write-Report) }

# 3. Instalar a distancia desde el servidor (mismo codigo que el panel)
Write-Log "Instalando OCTOPUS en $EQ desde el servidor, por SSH..." "Cyan"
$entorno = @"
`$env:OCTOPUS_NATIVO='1'; `$env:OCTOPUS_DATA='$R\datos'; `$env:OCTOPUS_BOVEDA_DIR='$R\boveda'; `$env:OCTOPUS_BIN='$R\bin'
`$env:RESTIC_CACHE_DIR='$R\datos\.cache\restic'; `$env:PYTHONUTF8='1'; `$env:PATH='$R\bin;' + `$env:PATH
foreach (`$l in (Get-Content '$R\install\.env' -ErrorAction SilentlyContinue)) { if (`$l -match '^\s*([A-Z_][A-Z0-9_]*)=(.*)$' -and `$Matches[2].Trim()) { Set-Item "env:`$(`$Matches[1])" `$Matches[2].Trim().Trim('"') } }
New-Item -ItemType Directory -Force '$R\tests\ci' | Out-Null; Copy-Item C:\OCTOPUS\tests\ci\prueba_remota.py '$R\tests\ci\' -Force
Set-Location '$R'

"@
# la maquina de pruebas usa la cuenta estandar de las cajas de Vagrant (vagrant/vagrant); nunca una contrasena real
$g = Invoke-WinVM $SRV ($entorno + "`n`$env:OCTOPUS_PRUEBA_PASSWORD='vagrant'; & '$R\python\python.exe' '$R\tests\ci\prueba_remota.py' $EQ_IP windows vagrant win2022-ssh 2>&1 | ForEach-Object { `"`$_`" }")
foreach ($l in @($g.Output | Where-Object { "$_" -like "RESULT|*" })) {
    $c = "$l" -split "\|", 4
    Add-Result $c[1] "$($EQ) por SSH: $($c[2])" $c[3]
}
if (-not @($g.Output | Where-Object { "$_" -like "RESULT|*" }).Count) { Add-Result "FAIL" "$EQ por SSH" (($g.Output | Select-Object -Last 6) -join " | ") }

# 4. Contrasena mala: tiene que explicarlo claro (y no bloquear nada)
$m = Invoke-WinVM $SRV ($entorno + "`n& '$R\python\python.exe' -c `"import sys; sys.path.insert(0, 'lib'); import instalacion_remota as i; print('MSG=' + i.instalar_windows('x', '$EQ_IP', 'vagrant', 'mala-a-proposito', b'', lambda t: None, lambda: False)[1])`"")
$msg = (@($m.Output | Where-Object { "$_" -like "MSG=*" }) -join " ")
if ($msg -match "incorrectos") { Add-Result "PASS" "contrasena mala: lo explica claro" $msg } else { Add-Result "FAIL" "contrasena mala: lo explica claro" (($m.Output | Select-Object -Last 4) -join " | ") }

exit (Write-Report "PRUEBA DE INSTALACION A DISTANCIA POR SSH EN WINDOWS")
