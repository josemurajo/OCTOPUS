# OCTOPUS - (Re)instala OCTOPUS en el cerebro y despliega los agentes en los clientes Linux encendidos.
param([switch]$Reinstalar)
. "$PSScriptRoot\scripts\comun.ps1"
# v2: todo el servidor va en el contenedor "octopus". La instalacion es idempotente: reconstruye la imagen
# con el codigo actual y conserva datos y copias (volumenes).
$chk = Invoke-VM "cerebro" "test -d /vagrant_octopus/install && test -d /vagrant_host/scripts" -Quiet
$accion = if ($Reinstalar -or $chk.Code -ne 0) { "reload" } else { "provision" }
$rc = Invoke-Vagrant @($accion, "cerebro", "--provision-with", "sync,install")
if ($rc -eq 0) { Add-Result "PASS" "OCTOPUS instalado en cerebro" } else { Add-Result "FAIL" "OCTOPUS instalado en cerebro" "codigo $rc"; exit (Write-Report) }
$state = Get-VMState
$up = @("cliente1", "cliente2", "debian12", "rocky9") | Where-Object { $state[$_] -eq "running" }
if ($up.Count -gt 0) {
    Invoke-VM "cerebro" "bash /vagrant_host/scripts/pruebas_cerebro.sh limpiar" -Quiet | Out-Null   # equipos aislados de pruebas anteriores
    $r = Invoke-VM "cerebro" "docker exec octopus bash /app/ansible/deploy_vagrant.sh $($up -join ' ')"
    if ($r.Code -eq 0) { Add-Result "PASS" "agentes desplegados con Ansible" ($up -join ", ") } else { Add-Result "FAIL" "agentes desplegados con Ansible" "codigo $($r.Code)" }
} else { Add-Result "WARN" "no hay clientes Linux encendidos" "usa .\iniciar_vagrant.ps1" }
if ($state["win2022"] -eq "running") {
    $rc = Invoke-Vagrant @("provision", "win2022", "--provision-with", "agent")
    if ($rc -eq 0) { Add-Result "PASS" "agente Windows instalado" } else { Add-Result "FAIL" "agente Windows instalado" "codigo $rc" }
}
exit (Write-Report "INFORME DE DESPLIEGUE")
