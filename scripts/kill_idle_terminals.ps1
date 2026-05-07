param([switch]$Force,[switch]$DryRun)
$currentPid=0+$PID; $minAge=30; $cpuMs=800
$activeKids=@("python","py","git","node","npm","pwsh","curl","wget","ssh","docker")
Write-Host ""
Write-Host "== Kill Idle Terminals ==" -ForegroundColor Cyan
if($DryRun){Write-Host "  [DRY RUN]" -ForegroundColor Yellow}
$allPs=Get-Process -Name powershell -EA SilentlyContinue
Write-Host "Procesos powershell: $($allPs.Count) | PID protegido: $currentPid"
$snap=@{}
foreach($p in $allPs){if($p.Id -ne $currentPid){try{$snap[$p.Id]=$p.CPU}catch{$snap[$p.Id]=0}}}
Start-Sleep -Milliseconds $cpuMs
$kill=[System.Collections.Generic.List[object]]::new()
$keep=[System.Collections.Generic.List[object]]::new()
foreach($p in $allPs){
  if($p.Id -eq $currentPid){$keep.Add([pscustomobject]@{P=$p;R="este proceso"});continue}
  $r=$null
  try{$kids=Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.Id)" -EA Stop|Where-Object{$activeKids -contains $_.Name.ToLower().Replace(".exe","")};if($kids){$r="hijos: "+(($kids|Select-Object -Exp Name)-join",")}}catch{}
  if(-not $r){try{$d=[math]::Round($p.CPU-$snap[$p.Id],3);if($d -gt 0.05){$r="CPU+${d}s"}}catch{}}
  if(-not $r){try{$a=((Get-Date)-$p.StartTime).TotalSeconds;if($a -lt $minAge){$r="reciente($([int]$a)s)"}}catch{}}
  if($r){$keep.Add([pscustomobject]@{P=$p;R=$r})}else{$kill.Add($p)}
}
Write-Host ""
Write-Host "CONSERVAR ($($keep.Count)):" -ForegroundColor Green
foreach($e in $keep){$age=try{[math]::Round(((Get-Date)-$e.P.StartTime).TotalMinutes,1)}catch{"?"};Write-Host "  [KEEP] PID $($e.P.Id) | ${age}min | $($e.R)" -ForegroundColor Green}
Write-Host ""
Write-Host "ELIMINAR ($($kill.Count) idle):" -ForegroundColor $(if($kill.Count -eq 0){"Green"}else{"Yellow"})
foreach($p in $kill){$age=try{[math]::Round(((Get-Date)-$p.StartTime).TotalMinutes,1)}catch{"?"};$cpu=try{[math]::Round($p.CPU,3)}catch{"?"};Write-Host "  [KILL] PID $($p.Id) | ${age}min | CPU=${cpu}s" -ForegroundColor Yellow}
if($kill.Count -eq 0){Write-Host "  Nada idle."-ForegroundColor Green;exit 0}
Write-Host ""
$go=$Force -or $DryRun
if(-not $go){$ans=Read-Host "Eliminar $($kill.Count) idle? [S/n]";$go=($ans -eq "" -or $ans -match "^[sS]")}
if($DryRun){Write-Host "[DRY RUN] Habria eliminado $($kill.Count) procesos."-ForegroundColor Cyan}
elseif($go){$n=0;foreach($p in $kill){try{Stop-Process -Id $p.Id -Force -EA Stop;$n++}catch{}};Write-Host "Listo: $n eliminadas."-ForegroundColor Cyan}
else{Write-Host "Cancelado."-ForegroundColor DarkGray}
Write-Host ""
