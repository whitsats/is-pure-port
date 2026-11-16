# 《I"s Pure》方案 B 高清版实体机一键部署脚本
$ErrorActionPreference = "Stop"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "   《I's Pure》WebGAL 方案 B (高清原盘) 实体机部署" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../../..')).Path
$apkPath = Join-Path $projectRoot '成品/安卓移植/IS_Pure_Android_v9.apk'
$gameSourceDir = Join-Path $projectRoot '移植验证/WebGAL移植/新游戏打盘高清版/public/game'
$packageName = "dev.ispure.webgal.prototype"
$activityName = "com.openwebgal.demo.MainActivity"
$targetDir = "/sdcard/Android/data/$packageName/files/game"

# 1. 检查 APK 与资源源目录
if (-not (Test-Path $apkPath)) {
    Write-Error "未找到 APK 文件: $apkPath`n请先执行构建。"
    exit 1
}
if (-not (Test-Path $gameSourceDir)) {
    Write-Error "未找到资源目录: $gameSourceDir"
    exit 1
}

# 2. 检查 ADB 设备连接
Write-Host "`n[1/5] 检查 ADB 设备连接状态..." -ForegroundColor Yellow
$devicesOutput = adb devices | Where-Object { $_ -match "\S" } | Select-Object -Skip 1
$onlineDevices = $devicesOutput | Where-Object { $_ -match "\s+device$" }

if ($onlineDevices.Count -eq 0) {
    Write-Warning "未检测到已连接并授权的 Android 设备！"
    Write-Host "排查指引：" -ForegroundColor Gray
    Write-Host "  1. 手机通过 USB 连接电脑，并在手机上开启【开发者选项】->【USB 调试】。" -ForegroundColor Gray
    Write-Host "  2. 观察手机弹窗，勾选【始终允许来自此计算机的调试】并点击【允许】。" -ForegroundColor Gray
    Write-Host "  3. 若手机仅处于充电模式，请将 USB 连接方式切换为【传输文件 (MTP)】。" -ForegroundColor Gray
    Write-Host "`n当前设备状态："
    adb devices
    exit 1
}

$deviceId = ($onlineDevices[0] -split "\s+")[0]
Write-Host "已连接设备: $deviceId" -ForegroundColor Green

# 3. 检查设备存储空间
Write-Host "`n[2/5] 检查设备内部存储空间..." -ForegroundColor Yellow
$dfOutput = adb -s $deviceId shell df -h /sdcard | Out-String
Write-Host $dfOutput.Trim() -ForegroundColor Gray
Write-Host "提示：完整 6.83GB 高清资源包需要预留至少 8GB 可用空间。" -ForegroundColor Gray

# 4. 安装 APK 宿主
Write-Host "`n[3/5] 安装 APK..." -ForegroundColor Yellow
adb -s $deviceId install -r -d $apkPath
if ($LASTEXITCODE -ne 0) {
    Write-Error "APK 安装失败，请检查手机是否禁止安装未知应用或存储已满。"
    exit 1
}
Write-Host "APK 安装成功！" -ForegroundColor Green

# 5. 启动 App 初始化沙盒存储目录
Write-Host "`n[4/5] 初始化应用存储沙盒..." -ForegroundColor Yellow
adb -s $deviceId shell am start -n "$packageName/$activityName" | Out-Null
Start-Sleep -Seconds 2
adb -s $deviceId shell "mkdir -p $targetDir"

# 6. 推送 6.83GB 高清资源包
Write-Host "`n[5/5] 开始推送高清原盘素材与 12 卷漫画 (约 6.83 GiB)..." -ForegroundColor Yellow
Write-Host "推送目标: $targetDir" -ForegroundColor Cyan
Write-Host "文件较大，ADB 高速传输约需 2~4 分钟，请保持数据线连接稳定..." -ForegroundColor Gray

adb -s $deviceId push "$gameSourceDir\." "$targetDir/"
if ($LASTEXITCODE -ne 0) {
    Write-Error "资源推送过程中断，请重试！"
    exit 1
}

Write-Host "`n资源包推送完毕，正在重启游戏以挂载完整资产..." -ForegroundColor Yellow
adb -s $deviceId shell am force-stop $packageName
Start-Sleep -Seconds 1
adb -s $deviceId shell am start -n "$packageName/$activityName" | Out-Null

Write-Host "`n==================================================" -ForegroundColor Green
Write-Host "   部署完成！游戏已在手机端启动。" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host "体验核验重点：" -ForegroundColor Cyan
Write-Host "  1. 片头 OP 视频与主线语音即时播放。" -ForegroundColor Gray
Write-Host "  2. 点击「原著漫画」，屏幕自动旋转为【竖屏】，单页从左往右翻阅。" -ForegroundColor Gray
Write-Host "  3. 点击返回退出漫画，屏幕自动恢复为【横屏】。" -ForegroundColor Gray
