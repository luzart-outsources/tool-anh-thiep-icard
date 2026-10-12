# Bàn làm việc thiệp – khởi động trên Windows (gọi từ "MoTool-Windows.bat" trong repo git,
# hoặc "Mở Tool (Windows).bat" trong gói zip).
# Lần đầu: tải bộ chạy uv → Python 3.12 + thư viện vào %LOCALAPPDATA%\ThiepTool (không đụng hệ thống).
# Dữ liệu của khách: Documents\ThiepTool – nằm ngoài thư mục tool nên cập nhật bản mới không mất gì.
# File phải lưu UTF-8 CÓ BOM: PowerShell 5.1 (có sẵn trên Windows) thiếu BOM sẽ đọc sai tiếng Việt.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (Test-Path (Join-Path $Here '..\..\cardkit')) {          # repo git: <repo>\release\app\run.ps1
    $Root = (Resolve-Path (Join-Path $Here '..\..')).Path
} else {                                                     # gói zip: ThiepTool\app\run.ps1 (cardkit nằm cạnh)
    $Root = $Here
}
$Req = Join-Path $Here 'requirements-app.txt'
$RT = Join-Path $env:LOCALAPPDATA 'ThiepTool'
$Data = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'ThiepTool'
$UV = Join-Path $RT 'uv\uv.exe'
$Venv = Join-Path $RT 'venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $RT 'python'
$env:UV_CACHE_DIR = Join-Path $RT 'cache'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $RT 'browsers'
if ($env:THIEPTOOL_PRINT_PATHS) { Write-Output $Root; Write-Output $Req; exit 0 }   # dùng khi kiểm thử

function Fail($msg) {
    Write-Host ''
    Write-Host "  ✗ $msg" -ForegroundColor Red
    Write-Host ''
    Write-Host '  Chụp màn hình cửa sổ này gửi người bán tool để được hỗ trợ.'
    Read-Host '  Bấm Enter để đóng' | Out-Null
    exit 1
}

Write-Host ''
Write-Host '  ✦ BÀN LÀM VIỆC THIỆP'
Write-Host '  ────────────────────'

# Bản cài bằng git: tự lấy bản mới (không hỏi mật khẩu, lỗi mạng thì bỏ qua)
$Git = Get-Command git -ErrorAction SilentlyContinue
if ((Test-Path (Join-Path $Root '.git')) -and $Git) {
    Write-Host '  Đang kiểm tra bản mới…'
    $env:GIT_TERMINAL_PROMPT = '0'
    $env:GCM_INTERACTIVE = 'never'
    $old = (& git -C $Root rev-parse HEAD 2>$null)
    & git -C $Root -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20 pull --ff-only --quiet *> $null
    if ($LASTEXITCODE -eq 0) {
        if ((& git -C $Root rev-parse HEAD 2>$null) -ne $old) { Write-Host '  ✓ Đã cập nhật lên bản mới.' -ForegroundColor Green }
    } else {
        Write-Host '  (Chưa lấy được bản mới – vẫn mở bản đang có.)'
    }
}

try { New-Item -ItemType Directory -Force -Path $RT, $Data | Out-Null } catch { Fail "Không tạo được thư mục $RT" }

if (-not (Test-Path $UV)) {
    Write-Host '  Lần đầu mở trên máy này: đang tải bộ chạy (cần mạng, khoảng 3–5 phút)…'
    try {
        $env:UV_UNMANAGED_INSTALL = Join-Path $RT 'uv'
        Invoke-RestMethod 'https://astral.sh/uv/install.ps1' | Invoke-Expression | Out-Null
    } catch { Fail "Không tải được bộ chạy – kiểm tra mạng rồi mở lại. ($($_.Exception.Message))" }
    if (-not (Test-Path $UV)) { Fail 'Tải bộ chạy chưa xong – kiểm tra mạng rồi mở lại.' }
}

$hash = (Get-FileHash $Req -Algorithm MD5).Hash
$stamp = Join-Path $Venv ".ok-$hash"
if (-not (Test-Path $Py) -or -not (Test-Path $stamp)) {
    Write-Host '  Đang cài thư viện (chỉ lần đầu hoặc khi có bản mới)…'
    & $UV venv --quiet --allow-existing --python 3.12 $Venv
    if ($LASTEXITCODE -ne 0) { Fail 'Không cài được Python.' }
    & $UV pip install --quiet --python $Py -r $Req
    if ($LASTEXITCODE -ne 0) { Fail 'Không cài được thư viện – kiểm tra mạng rồi mở lại.' }
    Get-ChildItem -Path $Venv -Filter '.ok-*' -Force -ErrorAction SilentlyContinue | Remove-Item -Force
    New-Item -ItemType File -Force -Path $stamp | Out-Null
}

Set-Location $Root
& $Py -m cardkit.launch --data $Data @args
if ($LASTEXITCODE -ne 0) { Fail 'Tool dừng vì lỗi.' }
