Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class WinEnum {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder sb, int max);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder sb, int max);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  public static string List(uint[] pids) {
    StringBuilder outp = new StringBuilder();
    EnumWindows((h, l) => {
      uint pid;
      GetWindowThreadProcessId(h, out pid);
      foreach (uint target in pids) {
        if (pid == target && IsWindowVisible(h)) {
          StringBuilder cn = new StringBuilder(256);
          GetClassName(h, cn, 256);
          StringBuilder tt = new StringBuilder(256);
          GetWindowText(h, tt, 256);
          RECT r;
          GetWindowRect(h, out r);
          outp.AppendLine(string.Format("HWND=0x{0:X} CLASS={1} TITLE={2} RECT=({3},{4})-({5},{6}) W={7} H={8}",
            h.ToInt64(), cn.ToString(), tt.ToString(), r.Left, r.Top, r.Right, r.Bottom, r.Right - r.Left, r.Bottom - r.Top));
        }
      }
      return true;
    }, IntPtr.Zero);
    return outp.ToString();
  }
}
"@

$procs = Get-Process | Where-Object { $_.ProcessName -match '^(Weixin|WeChat)$' }
if (-not $procs) { Write-Output "NO_WECHAT_PROCESS"; exit }
foreach ($p in $procs) {
  Write-Output ("PROCESS: $($p.ProcessName) PID=$($p.Id) PATH=$($p.Path)")
  $ids = [uint32[]]@([uint32]$p.Id)
  [WinEnum]::List($ids) | ForEach-Object { if ($_.Trim()) { Write-Output $_ } }
}
