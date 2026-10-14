# OCTOPUS - Recoge logs reales del cerebro y de los clientes en .\reportes\logs_<fecha>.txt
. "$PSScriptRoot\scripts\comun.ps1"
$out = Join-Path $Global:ReportDir "logs_$($Global:Stamp).txt"
$state = Get-VMState
"=== vagrant status ===" | Set-Content $out
& vagrant status 2>&1 | ForEach-Object { "$_" } | Add-Content $out
if ($state["cerebro"] -eq "running") {
    $r = Invoke-VM "cerebro" @'
echo "=== contenedores ==="; docker ps -a
echo "=== estado OCTOPUS ==="; bash /opt/zerotouch/octopus.sh estado 2>&1
echo "=== registro del servidor ==="; docker logs --tail 150 octopus 2>&1
echo "=== mantenimiento ==="; docker exec octopus tail -n 40 /data/logs/mantenimiento.log 2>/dev/null
echo "=== red ==="; ip -br addr; ip route
'@ -Quiet
    "`n######## CEREBRO ########" | Add-Content $out; $r.Output | Add-Content $out
}
foreach ($m in @("cliente1", "cliente2", "debian12", "rocky9")) {
    if ($state[$m] -ne "running") { continue }
    $r = Invoke-VM $m @'
echo "=== agente ==="; systemctl --no-pager status octopus-agent | head -20
echo "=== log agente ==="; tail -n 60 /var/log/octopus/agent.log 2>/dev/null
echo "=== config (sin secretos) ==="; python3 -c "import json;d=json.load(open('/etc/octopus/config.json'));[d.pop(k,None) for k in ('minio_secret_key','password_restic','agent_token')];print(json.dumps(d,indent=1))" 2>/dev/null
echo "=== red ==="; ip -br addr
'@ -Quiet
    "`n######## $m ########" | Add-Content $out; $r.Output | Add-Content $out
}
Write-Log "Logs guardados en $out" "Green"
