# OCTOPUS - Levanta e instala el laboratorio (cerebro + clientes) SIN ejecutar las pruebas.
#   .\iniciar_vagrant.ps1                 cerebro + cliente1 + cliente2
#   .\iniciar_vagrant.ps1 -Todo           todas las maquinas
param([switch]$Todo, [string[]]$Maquinas = @("cliente1", "cliente2"))
. "$PSScriptRoot\scripts\comun.ps1"
if ($Todo) { $Maquinas = @("cliente1", "cliente2", "debian12", "rocky9", "win2022") }
if (-not (Test-Prerequisites)) { exit 1 }
foreach ($m in @("cerebro") + $Maquinas) {
    $rc = Invoke-Vagrant @("up", $m)
    if ($rc -eq 0) { Add-Result "PASS" "vagrant up $m" } else { Add-Result "FAIL" "vagrant up $m" "codigo $rc" }
}
Invoke-Vagrant @("status") | Out-Null
Write-Log "Siguiente paso: .\desplegar_zerotouch.ps1  (o todo de golpe: .\ejecutar_todo.ps1)" "Cyan"
exit (Write-Report "INFORME DE ARRANQUE DEL LABORATORIO")
