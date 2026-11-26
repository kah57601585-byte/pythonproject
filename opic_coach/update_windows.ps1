# OPIc Coach 업데이트: GitHub에서 최신 코드를 받아 설치합니다.
# update_windows.bat 이 이 파일을 실행해요. (PowerShell은 파일 전체를 먼저 읽으므로 업데이트 중 덮어써도 안전해요.)
$ErrorActionPreference = "Stop"
$Branch = "ccr-bbb459a1-ex8kfh"
$Repo = "kah57601585-byte/pythonproject"
$AppDir = $PSScriptRoot
$RepoRoot = Split-Path $AppDir -Parent

function Step($msg) { Write-Host ""; Write-Host "▶ $msg" -ForegroundColor Cyan }

try {
    Write-Host "==== OPIc Coach 업데이트 ====" -ForegroundColor Green
    Write-Host "폴더: $AppDir"

    Step "실행 중인 예전 서버 종료"
    $conns = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
    if ($conns.Count -eq 0) { Write-Host "실행 중인 서버 없음" }
    foreach ($c in $conns) {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "예전 서버를 종료했어요 (PID $($c.OwningProcess))"
    }

    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git -and (Test-Path (Join-Path $RepoRoot ".git"))) {
        Step "git으로 최신 코드 받기 (브랜치 $Branch)"
        git -C $RepoRoot fetch origin $Branch
        if ($LASTEXITCODE -ne 0) { throw "git fetch에 실패했어요. 인터넷 연결을 확인해 주세요." }
        git -C $RepoRoot checkout $Branch
        if ($LASTEXITCODE -ne 0) { throw "브랜치를 바꾸지 못했어요. 직접 수정한 파일이 있으면 'git stash' 후 다시 실행해 주세요." }
        git -C $RepoRoot pull --ff-only origin $Branch
        if ($LASTEXITCODE -ne 0) { throw "git pull에 실패했어요. 직접 수정한 파일이 있으면 'git stash' 후 다시 실행해 주세요." }
    } else {
        Step "GitHub에서 최신 코드 ZIP 받기 (브랜치 $Branch)"
        $tmp = Join-Path $env:TEMP ("opic_update_" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $tmp | Out-Null
        $zip = Join-Path $tmp "src.zip"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $src = Get-ChildItem -Path $tmp -Directory |
            Where-Object { Test-Path (Join-Path $_.FullName "opic_coach\server.py") } | Select-Object -First 1
        if (-not $src) { throw "받은 파일에서 opic_coach 폴더를 찾지 못했어요." }
        # .env(API 키)와 .venv(설치된 패키지)는 그대로 두고 나머지만 덮어써요.
        robocopy (Join-Path $src.FullName "opic_coach") $AppDir /E /XD .venv __pycache__ .pytest_cache /XF .env .env.txt env.txt /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "파일 복사에 실패했어요 (robocopy 코드 $LASTEXITCODE)." }
        Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }

    Step "필요한 패키지 설치"
    $venvPy = Join-Path $AppDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        if (Get-Command py -ErrorAction SilentlyContinue) { py -m venv (Join-Path $AppDir ".venv") }
        else { python -m venv (Join-Path $AppDir ".venv") }
        if (-not (Test-Path $venvPy)) { throw "가상환경을 만들지 못했어요. Python이 설치되어 있는지 확인해 주세요." }
    }
    & $venvPy -m pip install --disable-pip-version-check -q -r (Join-Path $AppDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "패키지 설치에 실패했어요." }

    Step "설치된 버전"
    Push-Location $AppDir
    & $venvPy -c "import version; print('OPIc Coach 버전:', version.APP_VERSION)"
    Pop-Location

    if (-not (Test-Path (Join-Path $AppDir ".env")) -and -not (Test-Path (Join-Path $AppDir ".env.txt"))) {
        Copy-Item (Join-Path $AppDir ".env.example") (Join-Path $AppDir ".env")
        Write-Host ""
        Write-Host "※ .env 파일을 새로 만들었어요. 메모장으로 열어 OPENAI_API_KEY 를 넣어 주세요." -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "업데이트 완료!" -ForegroundColor Green
    exit 0
} catch {
    Write-Host ""
    Write-Host "업데이트 실패: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
