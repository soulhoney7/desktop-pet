# 데스크탑펫 하나를 켜서 가만히 둔 채 CPU/메모리 재기
param([string]$exe, [string]$label, [string]$out)
Get-Process DesktopPet -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2
Remove-Item "$env:APPDATA\DesktopPet\running.lock" -ErrorAction SilentlyContinue
$null = Start-Process $exe -PassThru
Start-Sleep 25                                   # 켜지고 펫이 자리 잡을 때까지
$cores = [Environment]::ProcessorCount
$samples = @()
$c1 = (Get-Process DesktopPet | Measure-Object CPU -Sum).Sum
for ($i = 0; $i -lt 6; $i++) {
  Start-Sleep 10
  $c2 = (Get-Process DesktopPet | Measure-Object CPU -Sum).Sum
  $samples += ($c2 - $c1) / 10 * 100 / $cores   # 컴퓨터 전체 CPU 대비 %
  $c1 = $c2
}
$mem = (Get-Process DesktopPet | Measure-Object WorkingSet64 -Sum).Sum / 1MB
$avg = ($samples | Measure-Object -Average).Average
$line = "{0}: CPU 평균 {1:N2}% (10초 단위: {2}) / 메모리 {3:N0}MB / 코어 {4}개" -f $label, $avg, (($samples | ForEach-Object { "{0:N2}" -f $_ }) -join ", "), $mem, $cores
$line | Tee-Object -FilePath $out -Append
Get-Process DesktopPet -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 3
