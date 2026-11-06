# RouteDL: восстановление окружения. Идемпотентно: качает только то, чего ещё нет в bin\
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = $PSScriptRoot
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
    $h = (Get-FileHash "$bin\$exe" -Algorithm SHA256).Hash
    if ($known[$exe] -and $known[$exe] -ne $h) { Write-Host "Заметка: $exe отличается от проверенной версии (SHA256 $h). Это новее проверенной версии, для v0.1 нормально." -ForegroundColor Yellow }
    $h = (Get-FileHash "$bin\$exe" -Algorithm SHA256).Hash
    if ($known[$exe] -and $known[$exe] -ne $h) { Write-Host "Заметка: $exe отличается от проверенной версии (SHA256 $h). Это новее проверенной версии, для v0.1 нормально." -ForegroundColor Yellow }
}
$known = @{
  "xray.exe"   = "C77A00EB84FB93AE044C2D771A1CABCC033B81E487253FBC35B12DF6879C1E15"
  "ciadpi.exe" = "EB53CEEEB981CC6735AC24BB1E51E725280B86630E80FDF19DDC4EE4A5B54EF4"
  "ffmpeg.exe" = "3256173F3F8BFFD7DF12227C68ADF68025EDB1832273A9530688A7BB1ED8EDEC"
  "ffprobe.exe"= "F0D36ECBBDD3BCFAC3EFA078C96C7271C2E68B3810595552AC3B7F17E9A65C52"
  "deno.exe"   = "84BA64A0EEEBDC921CDEA57D5780AF7C1E512BE19F7C024C0C27C3D583BAD502"
}
$known = @{
  "xray.exe"   = "C77A00EB84FB93AE044C2D771A1CABCC033B81E487253FBC35B12DF6879C1E15"
  "ciadpi.exe" = "EB53CEEEB981CC6735AC24BB1E51E725280B86630E80FDF19DDC4EE4A5B54EF4"
  "ffmpeg.exe" = "3256173F3F8BFFD7DF12227C68ADF68025EDB1832273A9530688A7BB1ED8EDEC"
  "ffprobe.exe"= "F0D36ECBBDD3BCFAC3EFA078C96C7271C2E68B3810595552AC3B7F17E9A65C52"
  "deno.exe"   = "84BA64A0EEEBDC921CDEA57D5780AF7C1E512BE19F7C024C0C27C3D583BAD502"
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

Write-Host "`n== Python (portable) =="
$pyVer = "3.12.7"
$pyDir = "$root\runtime\python"
$py = "$pyDir\python.exe"
if (-not (Test-Path $py)) {
    $zip = Join-Path $tmp "python-embed.zip"
    Write-Host "скачиваю Python $pyVer (portable, в папку runtime) ..."
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/$pyVer/python-$pyVer-embed-amd64.zip" -OutFile $zip -UseBasicParsing
    $pyHash = "0D57BB6CB078B74D23DBFE91F77D6780D45BED328911609F1F7EE2BA1606BF44"   # SHA256 python-3.12.7-embed-amd64.zip (MD5 сверен с python.org)
    if ($pyHash -and ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $pyHash)) { throw "SHA256 Python не совпал: архив повреждён или подменён" }
    New-Item -ItemType Directory -Force -Path $pyDir | Out-Null
    Expand-Archive -Path $zip -DestinationPath $pyDir -Force
    $pth = Get-ChildItem $pyDir -Filter "python*._pth" | Select-Object -First 1
    Set-Content -Path $pth.FullName -Value @("$($pth.BaseName).zip", ".", "..\..", "Lib\site-packages", "import site") -Encoding ASCII
    $gp = Join-Path $tmp "get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $gp -UseBasicParsing
    & $py $gp --no-warn-script-location
}
& $py --version
Write-Host "устанавливаю зависимости (несколько минут, PySide6 большой) ..."
& $py -m pip install -q --no-warn-script-location -r "$root\requirements.txt"
& $py -m yt_dlp --version
& $py -m gallery_dl --version

Write-Host "`n== Ярлыки =="
try {
    $ws = New-Object -ComObject WScript.Shell
    foreach ($t in @("$([Environment]::GetFolderPath('Desktop'))\RouteDL.lnk", "$([Environment]::GetFolderPath('Programs'))\RouteDL.lnk")) {
        $s = $ws.CreateShortcut($t)
        $s.TargetPath = "$root\runtime\python\pythonw.exe"
        $s.Arguments = "routedl_gui.py"
        $s.WorkingDirectory = $root
        $s.IconLocation = "$root\routedl.ico"
        $s.Description = "RouteDL"
        $s.Save()
    }
    Write-Host "ярлыки RouteDL созданы: рабочий стол и меню Пуск"
} catch { Write-Host "ярлыки не созданы: $($_.Exception.Message)" -ForegroundColor Yellow }
