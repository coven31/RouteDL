# RouteDL: восстановление окружения. Идемпотентно: качает только то, чего ещё нет в bin\
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = "C:\RouteDL"
$bin = "$root\bin"
$tmp = Join-Path $env:TEMP "routedl_setup"
New-Item -ItemType Directory -Force -Path $bin, $tmp | Out-Null

function Get-Zip($url, $name) {
    $zip = Join-Path $tmp "$name.zip"
    $dir = Join-Path $tmp $name
    Write-Host "скачиваю $name ..."
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $dir -Force
    return $dir
}
function Take($dir, $exe) {
    $f = Get-ChildItem -Path $dir -Recurse -Filter $exe | Select-Object -First 1
    if (-not $f) { throw "в архиве нет $exe" }
    Copy-Item $f.FullName "$bin\$exe" -Force
}
function Gh-Url($repo, $pattern) {
    $r = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest" -Headers @{ "User-Agent" = "RouteDL" }
    $a = $r.assets | Where-Object { $_.name -match $pattern } | Select-Object -First 1
    if (-not $a) { throw "в $repo нет файла по маске $pattern. Есть: $(($r.assets | ForEach-Object { $_.name }) -join ', ')" }
    return $a.browser_download_url
}

$steps = @(
    @{ n = "xray.exe";   f = { $d = Get-Zip (Gh-Url "XTLS/Xray-core" '^Xray-windows-64\.zip$') "xray"; Take $d "xray.exe" } },
    @{ n = "ciadpi.exe"; f = { $d = Get-Zip (Gh-Url "hufrea/byedpi" 'x86_64-w64.*\.zip$') "byedpi"; Take $d "ciadpi.exe" } },
    @{ n = "ffmpeg.exe"; f = { $d = Get-Zip "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" "ffmpeg"; Take $d "ffmpeg.exe"; Take $d "ffprobe.exe" } },
    @{ n = "deno.exe";   f = {
        $own = "$env:USERPROFILE\.deno\bin\deno.exe"
        if (Test-Path $own) { Copy-Item $own "$bin\deno.exe" -Force }
        else { $d = Get-Zip "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" "deno"; Take $d "deno.exe" }
    } }
)
foreach ($s in $steps) {
    if (Test-Path "$bin\$($s.n)") { continue }
    try { & $s.f } catch { Write-Host "ОШИБКА $($s.n): $($_.Exception.Message)" -ForegroundColor Red }
}

$ErrorActionPreference = "Continue"
Write-Host "`n== bin =="
foreach ($n in "xray.exe", "ciadpi.exe", "ffmpeg.exe", "ffprobe.exe", "deno.exe") {
    $p = "$bin\$n"
    if (Test-Path $p) { "{0,-12} OK  {1:N0} МБ" -f $n, ((Get-Item $p).Length / 1MB) }
    else { "{0,-12} ОТСУТСТВУЕТ" -f $n }
}
if (Test-Path "$bin\deno.exe") { & "$bin\deno.exe" --version | Select-Object -First 1 }

Write-Host "`n== Python =="
python --version
python -m pip install -q -r "$root\requirements.txt"
python -m yt_dlp --version
python -m gallery_dl --version

Write-Host "`n== Файлы и патчи в коде =="
$checks = @(
    @("routedl_cli.py", "def ladder"), @("routedl_cli.py", "count_info"), @("routedl_cli.py", "report_salt"),
    @("routedl_cli.py", "ba/b"), @("routedl_cli.py", "not a.info"),
    @("routedl_gui.py", "child_python"), @("routedl_gui.py", "draw_icon"), @("routedl_icon.py", "def draw_icon"),
    @("probe_nodes.py", "def parse_vless"), @("requirements.txt", "PySide6")
)
foreach ($c in $checks) {
    $p = "$root\$($c[0])"
    $ok = (Test-Path $p) -and (Select-String -Path $p -Pattern ([regex]::Escape($c[1])) -Quiet)
    "{0,-18} {1,-18} {2}" -f $c[0], $c[1], $(if ($ok) { "OK" } else { "НЕТ" })
}

Write-Host "`n== git =="
git -C $root log --oneline -3
git -C $root status --short
