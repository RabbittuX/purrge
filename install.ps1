# Purrge Windows 安装脚本：
#   [Net.ServicePointManager]::SecurityProtocol = 'Tls12'; irm https://raw.githubusercontent.com/RabbittuX/purrge/master/install.ps1 | iex
#   或者 git clone 后运行：pwsh -File install.ps1（PowerShell 7；旧版 Windows PowerShell 读本地文件可能乱码，请用上面的 irm 方式）
# 环境变量：PURRGE_BRANCH 下载指定分支（测试用），PURRGE_YES=1 全部默认同意，PURRGE_SRC 使用本地代码目录（PowerShell 模块用）
# 可选参数（本地运行时）：--engine claude|codex|workbuddy|deepseek|pi  --threshold 15  --yes
$ErrorActionPreference = "Stop"
# 老版本 Windows / Windows Server 的 PowerShell 5.1 默认不用 TLS 1.2，连 GitHub、python.org 会报"基础连接已经关闭"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}
$yes = ($args -contains "--yes") -or [bool]$env:PURRGE_YES
$branch = if ($env:PURRGE_BRANCH) { $env:PURRGE_BRANCH } else { "refs/heads/master" }
function Test-Py($c) {
  # 应用商店的"假 python"（WindowsApps 里的跳转链接）运行会失败，这里一并排除
  if (-not $c) { return $false }
  try { & $c -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}
function Find-Py {
  foreach ($c in @("python", "py")) { if ((Get-Command $c -ErrorAction SilentlyContinue) -and (Test-Py $c)) { return $c } }
  $local = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
  if ($local -and (Test-Py $local.FullName)) { return $local.FullName }
  return $null
}
function Get-File($url, $out) {
  # 优先用系统自带的 curl.exe：有进度条，比 Invoke-WebRequest 快；网络时好时坏时自动重试
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  for ($i = 1; $i -le 3; $i++) {
    $ok = $false
    if ($curl) {
      $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"   # curl 的进度条写在 stderr，不能当成错误
      & $curl.Source -L --fail --progress-bar -o $out $url
      $ok = ($LASTEXITCODE -eq 0); $ErrorActionPreference = $old
    } else {
      try { Invoke-WebRequest $url -OutFile $out -UseBasicParsing; $ok = $true } catch { $ok = $false }
    }
    if ($ok -and (Test-Path $out)) { return $true }
    if ($i -lt 3) { Write-Host "下载没成功，3 秒后重试（第 $i 次）…"; Start-Sleep 3 }
  }
  return $false
}
function Update-PathEnv {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
}

$py = if ($env:PURRGE_FORCE_NO_PY) { $null } else { Find-Py }   # CI 自检用：模拟没有 Python
if (-not $py) {
  Write-Host "没有检测到 Python 3.8 以上，Purrge 需要它才能运行。"
  $ans = if ($yes) { "y" } else { Read-Host "现在自动安装 Python 官方版本吗？（只装给当前用户，不需要管理员权限）[Y/n]" }
  if ($ans -and $ans.Trim().ToLower() -notin @("y", "yes", "是", "好")) {
    Write-Host "已取消。可以从 https://www.python.org 手动安装（勾选 Add python.exe to PATH），然后重新运行这条命令。"
    return   # 不用 exit：irm | iex 方式下 exit 会直接关掉用户的 PowerShell 窗口
  }
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "正在用 winget 安装 Python（下面会显示下载进度；超过 10 分钟没有变化可以按 Ctrl+C 后重新运行）…"
    # 不接管道直接输出到窗口：进度条才显示得出来；winget 输出的是 UTF-8，临时把窗口编码切成 UTF-8，避免中文乱码
    $oldEnc = $null
    try { $oldEnc = [Console]::OutputEncoding; [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    $ErrorActionPreference = $old
    if ($oldEnc) { try { [Console]::OutputEncoding = $oldEnc } catch {} }
    Update-PathEnv
    $py = Find-Py
  }
  if (-not $py) {
    $ver = "3.12.10"
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "amd64" }
    $exe = Join-Path $env:TEMP "python-$ver-$arch.exe"
    Write-Host "正在从 python.org 下载 Python $ver…"
    if (-not (Get-File "https://www.python.org/ftp/python/$ver/python-$ver-$arch.exe" $exe)) {
      Write-Host "下载失败。请检查网络后重新运行这条命令，或从 https://www.python.org 手动安装。"
      return   # 不用 exit：irm | iex 方式下 exit 会直接关掉用户的 PowerShell 窗口
    }
    $sig = Get-AuthenticodeSignature $exe       # 只运行 Python 软件基金会签名的官方安装包
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Python Software Foundation") {
      Remove-Item $exe -ErrorAction SilentlyContinue
      Write-Host "安装包签名校验没通过，已放弃安装。请从 https://www.python.org 手动安装。"
      return   # 不用 exit：irm | iex 方式下 exit 会直接关掉用户的 PowerShell 窗口
    }
    $p = Start-Process $exe -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0 Include_test=0" -PassThru
    $t0 = Get-Date
    while (-not $p.HasExited) {                 # 静默安装没有界面：每 2 秒刷新一次用时，让人知道还在进行
      Write-Host -NoNewline ("`r正在安装 Python（约 1～2 分钟）… 已用 {0} 秒" -f [int]((Get-Date) - $t0).TotalSeconds)
      Start-Sleep 2
    }
    Write-Host ""
    Remove-Item $exe -ErrorAction SilentlyContinue
    Update-PathEnv
    $py = Find-Py
  }
  if (-not $py) {
    Write-Host "Python 自动安装没有成功。请从 https://www.python.org 手动安装（勾选 Add python.exe to PATH），然后重新运行这条命令。"
    return   # 不用 exit：irm | iex 方式下 exit 会直接关掉用户的 PowerShell 窗口
  }
  Write-Host "✓ Python 已就绪：$(& $py --version 2>&1)"
}
$src = if ($env:PURRGE_SRC) { $env:PURRGE_SRC } elseif ($PSScriptRoot) { $PSScriptRoot } else { "" }   # PURRGE_SRC：PowerShell 模块自带完整代码，不用再下载
if (-not $src -or -not (Test-Path (Join-Path $src "runtime\lib\dg.py"))) {
  $tmp = Join-Path $env:TEMP ("purrge-" + [guid]::NewGuid())
  New-Item -ItemType Directory -Path $tmp | Out-Null
  Write-Host "正在下载 Purrge…"
  if (-not (Get-File "https://codeload.github.com/RabbittuX/purrge/zip/$branch" (Join-Path $tmp "purrge.zip"))) {
    Write-Host "下载 Purrge 失败。请检查网络后重新运行这条命令。"
    return   # 不用 exit：irm | iex 方式下 exit 会直接关掉用户的 PowerShell 窗口
  }
  Expand-Archive (Join-Path $tmp "purrge.zip") -DestinationPath $tmp
  $src = (Get-ChildItem $tmp -Directory | Where-Object Name -like "purrge-*" | Select-Object -First 1).FullName
}
if ($env:PURRGE_PS1_CHECK_ONLY) { & $py (Join-Path $src "runtime\lib\dg.py") version; return }   # CI 自检用
& $py (Join-Path $src "runtime\lib\dg.py") install @args
