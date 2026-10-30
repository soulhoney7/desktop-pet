# 메모장 창을 화면 가운데쯤으로 옮김 (펫이 올라설 자리 확보)
param([int]$x = 330, [int]$y = 300, [int]$w = 520, [int]$h = 300)
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W { [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int hh, bool r); }
"@
$p = Get-Process notepad | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
[W]::MoveWindow($p.MainWindowHandle, $x, $y, $w, $h, $true) | Out-Null
