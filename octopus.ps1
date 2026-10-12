# OCTOPUS Zero-Touch - gestion del servidor en Windows (lo mismo que octopus.sh en Linux y Mac)
#   powershell -ExecutionPolicy Bypass -File octopus.ps1 <orden>
param([string]$Orden = "ayuda", [string]$Arg = "")
$ErrorActionPreference = "Continue"
$Raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$dc = @("compose", "--env-file", (Join-Path $Raiz "install\.env"), "-f", (Join-Path $Raiz "install\docker-compose.yml"))
foreach ($d in @("$env:ProgramFiles\Rancher Desktop", "$env:LOCALAPPDATA\Programs\Rancher Desktop")) {
    $bin = Join-Path $d "resources\resources\win32\bin"
    if (Test-Path $bin) { $env:Path = "$bin;$env:Path" }
}

switch ($Orden) {
    "estado" {
        & docker ps --filter "name=^octopus" --format "table {{.Names}}`t{{.Status}}`t{{.Ports}}"
        & docker exec octopus python /app/lib/equipos_cli.py lista
        & docker exec octopus curl -fsk https://127.0.0.1:8080/healthz; Write-Host ""
    }
    "logs"          { & docker logs --tail 100 -f octopus }
    "credenciales"  { & docker exec octopus cat /data/panel/CREDENCIALES_INICIALES.txt }
    "kit"           { & docker exec octopus python /app/lib/mantenimiento.py kit }
    "mantenimiento" { $t = if ($Arg) { $Arg } else { "todo" }; & docker exec octopus python /app/lib/mantenimiento.py $t }
    "ajustes" {
        $tmp = [IO.Path]::GetTempFileName()
        & docker cp octopus:/data/.env $tmp
        if ($LASTEXITCODE -ne 0) { Remove-Item $tmp; break }
        $antes = Get-FileHash $tmp
        Start-Process notepad.exe -ArgumentList $tmp -Wait
        if ((Get-FileHash $tmp).Hash -ne $antes.Hash) {
            # el archivo vive en Linux: sin finales de linea de Windows
            $txt = [IO.File]::ReadAllText($tmp) -replace "`r`n", "`n"
            [IO.File]::WriteAllText($tmp, $txt, (New-Object Text.UTF8Encoding($false)))
            & docker cp $tmp octopus:/data/.env
            & docker exec octopus chmod 600 /data/.env
            & docker restart octopus | Out-Null
            Write-Host "Ajustes guardados. OCTOPUS se ha reiniciado."
        } else { Write-Host "Sin cambios." }
        Remove-Item $tmp -Force
    }
    "recuperar-servidor" {
        if (-not $Arg) { Write-Host "Uso: octopus.ps1 recuperar-servidor <carpeta octopus-backups del disco antiguo | almacen externo>"; exit 2 }
        $repo = $Arg
        if (Test-Path $Arg -PathType Container) {
            $n = (& docker exec octopus sh -c "ls /boveda/octopus-backups/snapshots 2>/dev/null | wc -l").Trim()
            if ($n -ne "0") { Write-Host "Este servidor ya tiene copias en su almacen: no se sobrescriben. Usa un servidor recien instalado."; exit 1 }
            Write-Host "Copiando el almacen (puede tardar)..."
            & docker exec octopus rm -rf /boveda/octopus-backups
            & docker cp $Arg octopus:/boveda/octopus-backups
            $cuar = Join-Path (Split-Path $Arg -Parent) "octopus-cuarentena"
            if (Test-Path $cuar) { & docker exec octopus rm -rf /boveda/octopus-cuarentena; & docker cp $cuar octopus:/boveda/octopus-cuarentena }
            & docker exec octopus chown -R root:root /boveda
            $repo = "/boveda/octopus-backups"
        }
        & docker exec -it octopus python /app/lib/recuperar_servidor.py $repo
        if ($LASTEXITCODE -eq 0) { & docker restart octopus | Out-Null; Write-Host "OCTOPUS reiniciado con la configuracion recuperada." }
    }
    "actualizar" { & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Raiz "instalar_servidor_windows.ps1") }
    "volver" {
        & docker image inspect octopus-servidor:anterior *> $null
        if ($LASTEXITCODE -ne 0) { Write-Host "No hay version anterior guardada"; exit 1 }
        $f = Join-Path $Raiz "install\.env"
        $txt = (Get-Content $f) -replace "^OCTOPUS_VERSION=.*", "OCTOPUS_VERSION=anterior"
        [IO.File]::WriteAllText($f, (($txt -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
        & docker @dc up -d --no-build octopus
        Write-Host "Vuelto a la version anterior. Para volver a la nueva: octopus.ps1 actualizar"
    }
    "parar"     { & docker @dc stop }
    "arrancar"  { & docker @dc up -d --no-build octopus }
    "reiniciar" { & docker restart octopus }
    "consola"   { & docker exec -it octopus bash }
    default {
        Write-Host @"
Uso: powershell -ExecutionPolicy Bypass -File octopus.ps1 <orden>
  estado          como esta todo (contenedor, equipos conectados, almacen)
  logs            registro en directo del servidor
  credenciales    contrasena inicial del panel
  kit             kit de recuperacion (claves de las copias) - guardalo fuera del servidor
  mantenimiento   limpieza, verificacion y copia del servidor ahora (normalmente cada noche)
  ajustes         cambia los ajustes del servidor (almacen externo...) en el Bloc de notas y reinicia
  recuperar-servidor <almacen>   monta este servidor con la configuracion del que se perdio
  actualizar      instala la version de esta carpeta (conserva datos y copias)
  volver          vuelve a la version anterior si la actualizacion da problemas
  parar | arrancar | reiniciar | consola
"@
    }
}
