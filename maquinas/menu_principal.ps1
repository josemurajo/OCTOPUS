# OCTOPUS Zero-Touch - Menu del laboratorio Vagrant
Set-Location $PSScriptRoot
while ($true) {
    Write-Host ""
    Write-Host "=========== OCTOPUS Zero-Touch - Laboratorio v2 ========" -ForegroundColor Green
    Write-Host " 1) Ejecutar TODO (cerebro + cliente1 + cliente2 + pruebas)"
    Write-Host " 2) Ejecutar TODO con todas las maquinas (Debian, Rocky, Windows)"
    Write-Host " 3) Solo levantar maquinas"
    Write-Host " 4) (Re)instalar OCTOPUS y desplegar agentes"
    Write-Host " 5) Solo pruebas (con las maquinas ya encendidas)"
    Write-Host " 6) Reinstalar OCTOPUS en el cerebro desde la carpeta proyecto"
    Write-Host " 7) Capturar logs"
    Write-Host " 8) Estado de las maquinas"
    Write-Host " 9) Apagar todas las maquinas"
    Write-Host " 0) Salir"
    $op = Read-Host "Opcion"
    switch ($op) {
        "1" { & .\ejecutar_todo.ps1 }
        "2" { & .\ejecutar_todo.ps1 -Todo }
        "3" { & .\iniciar_vagrant.ps1 }
        "4" { & .\desplegar_zerotouch.ps1 }
        "5" { & .\ejecutar_todo.ps1 -SoloPruebas }
        "6" { & .\desplegar_zerotouch.ps1 -Reinstalar }
        "7" { & .\capturar_logs.ps1 }
        "8" { vagrant status }
        "9" { vagrant halt }
        "0" { return }
        default { Write-Host "Opcion no valida" -ForegroundColor Yellow }
    }
}
