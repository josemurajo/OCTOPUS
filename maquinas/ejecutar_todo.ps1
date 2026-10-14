<#
OCTOPUS Zero-Touch - Ejecucion completa y REAL del laboratorio

  .\ejecutar_todo.ps1                      cerebro + cliente1 (Ubuntu) + cliente2 (Rocky 9)
  .\ejecutar_todo.ps1 -Todo                ademas debian12, rocky9 y win2022 (necesita ~12 GB de RAM libres)
  .\ejecutar_todo.ps1 -Maquinas cliente1,debian12,win2022
  .\ejecutar_todo.ps1 -Limpio              destruye las VMs y empieza de cero
  .\ejecutar_todo.ps1 -SoloPruebas         no levanta ni instala nada, solo ejecuta las pruebas

Cada comprobacion se verifica de verdad (codigo de salida y contenido); el informe final
indica PASS / FAIL / WARN por prueba y se guarda en .\reportes\
#>
param(
    [string[]]$Maquinas = @("cliente1", "cliente2"),
    [switch]$Todo,
    [switch]$Limpio,
    [switch]$SoloPruebas,
    [switch]$CopiaCompleta,
    [switch]$Apagar
)

. "$PSScriptRoot\scripts\comun.ps1"
if ($Todo) { $Maquinas = @("cliente1", "cliente2", "debian12", "rocky9", "win2022") }
$Maquinas = @($Maquinas | ForEach-Object { $_ -split "," } | Where-Object { $_ } | ForEach-Object { $_.Trim().ToLower() })
$Linux = @($Maquinas | Where-Object { $_ -ne "win2022" })
$ConWindows = $Maquinas -contains "win2022"

Write-Log "=== OCTOPUS Zero-Touch - prueba completa ($($Maquinas -join ', ')) ===" "Green"

# ---------------------------------------------------------------- 0. Requisitos
if (-not (Test-Prerequisites)) {
    Write-Report "INFORME OCTOPUS - FALTAN REQUISITOS" | Out-Null
    exit 1
}

if (-not $SoloPruebas) {
    # ------------------------------------------------------------ 1. Limpieza opcional
    if ($Limpio) {
        Write-Log "Destruyendo VMs anteriores (-Limpio)..." "Yellow"
        Invoke-Vagrant @("destroy", "-f") | Out-Null
        Remove-Item -Recurse -Force (Join-Path $Global:LabDir ".runtime") -ErrorAction SilentlyContinue
    }

    # ------------------------------------------------------------ 2. Cerebro
    # La maquina de prueba del servidor en Windows 11 ocupa 6 GB: si esta encendida, se apaga para dejar memoria
    $previo = Get-VMState
    if ($previo["win11srv"] -eq "running") {
        Write-Log "Apagando win11srv (prueba del servidor en Windows) para dejar memoria libre..." "Yellow"
        Invoke-Vagrant @("halt", "win11srv") | Out-Null
    }
    if ($previo["win2022"] -eq "running" -and -not $ConWindows) {
        Write-Log "Apagando win2022 (no se usa en esta prueba) para dejar memoria libre..." "Yellow"
        Invoke-Vagrant @("halt", "win2022") | Out-Null
    }
    $rc = Invoke-VagrantLimite @("up", "cerebro") 15
    if ($rc -ne 0) {
        # A veces cerebro se queda colgado de una ejecucion anterior (encendido pero sin responder por SSH:
        # "timeout during server version negotiating") o parado al configurar la red. Se apaga a la fuerza
        # y se vuelve a arrancar una vez.
        Write-Log "cerebro no responde: apagandolo a la fuerza y arrancandolo otra vez..." "Yellow"
        Invoke-Vagrant @("halt", "-f", "cerebro") | Out-Null
        Start-Sleep -Seconds 5
        $rc = Invoke-VagrantLimite @("up", "cerebro") 15
    }
    if ($rc -ne 0) {
        Add-Result "FAIL" "vagrant up cerebro" "codigo $rc (ver log). Prueba APAGAR_MAQUINAS.bat y vuelve a lanzar"
        exit (Write-Report)
    }
    Add-Result "PASS" "vagrant up cerebro" "192.168.10.10"

    # Siempre se (re)aplica la instalacion: es idempotente y asi el cerebro tiene la ultima version del proyecto.
    # Si las carpetas compartidas no estan montadas (VM creada con un Vagrantfile antiguo) se hace reload.
    $mnt = Invoke-VM "cerebro" "test -d /vagrant_octopus/install && test -d /vagrant_host/scripts" -Quiet
    $accion = if ($mnt.Code -ne 0) { "reload" } else { "provision" }
    Write-Log "Instalando/actualizando OCTOPUS en el cerebro (la primera vez tarda 10-15 min)..." "Yellow"
    $rc = Invoke-Vagrant @($accion, "cerebro", "--provision-with", "sync,install")
    if ($rc -ne 0) {
        Add-Result "FAIL" "instalacion OCTOPUS en cerebro" "codigo $rc (ver log)"
        exit (Write-Report)
    }
    Add-Result "PASS" "instalacion OCTOPUS en cerebro" "contenedor octopus: panel, almacen, API y mantenimiento"

    # ------------------------------------------------------------ 3. Clientes Linux
    foreach ($m in $Linux) {
        $rc = Invoke-Vagrant @("up", $m)
        if ($rc -eq 0) { Add-Result "PASS" "vagrant up $m" $Global:IPs[$m] }
        else { Add-Result "FAIL" "vagrant up $m" "codigo $rc (ver log)" }
    }
    $state = Get-VMState
    $LinuxUp = @($Linux | Where-Object { $state[$_] -eq "running" })

    # ------------------------------------------------------------ 4. Despliegue zero-touch (Ansible desde el cerebro)
    if ($LinuxUp.Count -gt 0) {
        Write-Log "Desplegando agentes con Ansible desde el cerebro en: $($LinuxUp -join ', ')" "Cyan"
        # equipos que quedaron aislados en una prueba anterior: se liberan antes de desplegar
        Invoke-VM "cerebro" "sed 's/\r$//' /vagrant_host/scripts/pruebas_cerebro.sh | bash -s -- limpiar" -Quiet | Out-Null
        # v2: Ansible se ejecuta DENTRO del contenedor del servidor (tiene la clave SSH y la base de datos)
        # cliente1 NO se despliega con Ansible: las pruebas lo instalan desde el panel con su contrasena
        $Ansible = @($LinuxUp | Where-Object { $_ -ne "cliente1" })
        if ($Ansible.Count -gt 0) {
            $r = Invoke-VM "cerebro" "docker exec octopus bash /app/ansible/deploy_vagrant.sh $($Ansible -join ' ')"
            if ($r.Code -eq 0) { Add-Result "PASS" "despliegue Ansible de agentes Linux" ($Ansible -join ", ") }
            else { Add-Result "FAIL" "despliegue Ansible de agentes Linux" "codigo $($r.Code) (ver log)" }
        }
    }

    # ------------------------------------------------------------ 5. Windows
    if ($ConWindows) {
        # El cerebro prepara el instalador del panel para win2022 (alta + clave propia + carpetas)
        $r = Invoke-VM "cerebro" "sed 's/\r$//' /vagrant_host/scripts/pruebas_cerebro.sh | bash -s -- instalador win2022 windows" -Quiet
        if ($r.Code -eq 0) { Add-Result "PASS" "win2022: instalador del panel generado" (($r.Output | Select-Object -Last 1) -join "") }
        else { Add-Result "FAIL" "win2022: instalador del panel generado" (($r.Output -join " ") -replace "\s+", " ") }
        Write-Log "Levantando Windows Server 2022 (la primera vez descarga ~6 GB)..." "Yellow"
        $rc = Invoke-Vagrant @("up", "win2022", "--no-provision")
        if ($rc -eq 0) { Add-Result "PASS" "vagrant up win2022" "192.168.10.40" }
        else { Add-Result "FAIL" "vagrant up win2022" "codigo $rc (ver log)" }
        $rc = Invoke-Vagrant @("provision", "win2022", "--provision-with", "agent")
        if ($rc -eq 0) { Add-Result "PASS" "win2022: agente instalado con el instalador del panel (INSTALAR)" }
        else { Add-Result "FAIL" "win2022: agente instalado con el instalador del panel (INSTALAR)" "codigo $rc (ver log)" }
    }
}

# ---------------------------------------------------------------- 6. Pruebas reales
$state = Get-VMState
if ($state["cerebro"] -ne "running") {
    Add-Result "FAIL" "cerebro en ejecucion" "estado: $($state['cerebro'])"
    exit (Write-Report)
}
$LinuxUp = @($Linux | Where-Object { $state[$_] -eq "running" })
foreach ($m in $Linux) { if ($state[$m] -ne "running") { Add-Result "FAIL" "$m en ejecucion" "estado: $($state[$m])" } }

Write-Log "Ejecutando bateria de pruebas desde el cerebro..." "Cyan"
$r = Invoke-VM "cerebro" "sed 's/\r$//' /vagrant_host/scripts/pruebas_cerebro.sh | bash -s -- todo $($LinuxUp -join ' ')" -Quiet
$found = 0
foreach ($line in $r.Output) {
    if ($line -match '^RESULT\|(PASS|FAIL|WARN)\|([^|]*)\|(.*)$') {
        Add-Result $Matches[1] $Matches[2] $Matches[3]
        $found++
    }
}
if ($found -eq 0) { Add-Result "FAIL" "bateria de pruebas" "no se obtuvieron resultados (codigo $($r.Code)); ver log" }

# Windows: rotura y restauracion con el agente de Windows
if ($ConWindows -and $state["win2022"] -eq "running") {
    $ip = $Global:IPs["win2022"]
    $cx = Invoke-VM "cerebro" "bash /vagrant_host/scripts/pruebas_cerebro.sh conectado win2022 60" -Quiet
    if ($cx.Code -eq 0) { Add-Result "PASS" "win2022: agente conectado al servidor (HTTPS saliente)" }
    else { Add-Result "FAIL" "win2022: agente conectado al servidor (HTTPS saliente)" (($cx.Output -join " ") -replace "\s+", " ") }
    $h = Invoke-VM "cerebro" "bash /vagrant_host/scripts/pruebas_cerebro.sh health $ip" -Quiet
    if (($h.Output -join "") -match '"status": "ok"') { Add-Result "PASS" "win2022: agente responde" }
    else { Add-Result "FAIL" "win2022: agente responde" (($h.Output -join " ") -replace "\s+", " ") }

    $b = Invoke-VM "cerebro" "bash /vagrant_host/scripts/pruebas_cerebro.sh backup $ip" -Quiet
    if (-not (($b.Output -join "") -match '"status": "success"')) {
        # el instalador lanza la primera copia al terminar: si coinciden, se espera y se repite
        Write-Log "win2022: la copia coincidio con la primera copia del instalador; reintento en 90 s" "Yellow"
        Start-Sleep -Seconds 90
        $b = Invoke-VM "cerebro" "bash /vagrant_host/scripts/pruebas_cerebro.sh backup $ip" -Quiet
    }
    if (($b.Output -join "") -match '"status": "success"') { Add-Result "PASS" "win2022: backup al cerebro" }
    else { Add-Result "FAIL" "win2022: backup al cerebro" ((($b.Output -join " ") -replace "\s+", " ").Substring(0, [Math]::Min(200, ($b.Output -join " ").Length))) }

    $file = "C:\OctopusTest\critico\config.txt"
    Invoke-WinVM "win2022" "Set-Content -Path '$file' -Value 'ARCHIVO ESTROPEADO POR LA PRUEBA'" | Out-Null
    $c = Invoke-WinVM "win2022" "Get-Content -Path '$file'"
    if (($c.Output -join "") -match "ESTROPEADO") { Add-Result "PASS" "win2022: archivo estropeado a proposito ($file)" } else { Add-Result "FAIL" "win2022: archivo estropeado a proposito" ($c.Output -join " ") }

    $rs = Invoke-VM "cerebro" "bash /vagrant_host/scripts/pruebas_cerebro.sh restaurar $ip 'C:\OctopusTest\critico\config.txt'" -Quiet
    $c = Invoke-WinVM "win2022" "Get-Content -Path '$file'"
    if ((($c.Output -join "") -match "config original") -and (($rs.Output -join "") -match '"status": "success"')) {
        Add-Result "PASS" "win2022: archivo restaurado" "contenido='config original'"
    } else {
        Add-Result "FAIL" "win2022: archivo restaurado" ("respuesta=" + (($rs.Output -join " ") -replace "\s+", " ") + " contenido=" + ($c.Output -join " "))
    }
}

# Copia completa del equipo Windows (todo el disco C: con instantanea VSS): solo con -CopiaCompleta (tarda)
if ($CopiaCompleta -and $ConWindows -and $state["win2022"] -eq "running") {
    Write-Log "win2022: copia completa de todo el disco C: (la primera puede tardar 10-60 min)..." "Yellow"
    $cc = Invoke-VM "cerebro" "sed 's/\r$//' /vagrant_host/scripts/pruebas_cerebro.sh | bash -s -- completa win2022" -Quiet
    $n = 0
    foreach ($line in $cc.Output) {
        if ($line -match '^RESULT\|(PASS|FAIL|WARN)\|([^|]*)\|(.*)$') { Add-Result $Matches[1] ("win2022: " + $Matches[2]) $Matches[3]; $n++ }
    }
    if ($n -eq 0) { Add-Result "FAIL" "win2022: copia completa" "sin resultados (codigo $($cc.Code)); ver log" }
    $hf = Invoke-WinVM "win2022" "(Get-ChildItem 'C:\Windows\System32\drivers\etc' -Filter 'hosts.restaurado-*').Count; (Get-Item 'C:\Windows\System32\drivers\etc\hosts').Length"
    Write-Log ("win2022: copias de hosts recuperadas al lado / tamano del original: " + ($hf.Output -join " ")) "Gray"
}

# Copia de credenciales para el usuario
$cred = Join-Path $Global:LabDir ".runtime\CREDENCIALES_INICIALES.txt"
if (Test-Path $cred) { Write-Log "Credenciales del panel: $cred" "Cyan" }
Write-Log "Panel web: https://192.168.10.10:8080" "Cyan"

if ($Apagar) { Invoke-Vagrant @("halt") | Out-Null }
$fails = Write-Report
exit $fails
