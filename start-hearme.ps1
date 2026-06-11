$ErrorActionPreference = "Stop"

$sdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$adb = Join-Path $sdk "platform-tools\adb.exe"
$emulator = Join-Path $sdk "emulator\emulator.exe"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Wait-ForBoot([string]$serial) {
    $deadline = (Get-Date).AddMinutes(4)
    do {
        Start-Sleep -Seconds 3
        $booted = ""
        $connected = (& $adb devices) -match "^$serial\s+device$"
        if ($connected) {
            $booted = (& $adb -s $serial shell getprop sys.boot_completed 2>$null)
        }
    } while ($booted -ne "1" -and (Get-Date) -lt $deadline)

    if ($booted -ne "1") {
        throw "$serial did not finish booting."
    }
}

$devices = & $adb devices
if ($devices -notmatch "emulator-5554\s+device") {
    Start-Process -FilePath $emulator -ArgumentList @(
        "-avd", "Pixel_4",
        "-allow-host-audio",
        "-no-snapshot-load",
        "-no-snapshot-save"
    )
}

if ($devices -notmatch "emulator-5556\s+device") {
    Start-Process -FilePath $emulator -ArgumentList @("-avd", "Wear_OS_Small_Round")
}

Wait-ForBoot "emulator-5554"
Wait-ForBoot "emulator-5556"

& $adb -s emulator-5554 emu avd hostmicon | Out-Null
& $adb -s emulator-5554 forward tcp:5601 tcp:5601 | Out-Null

$mobileApk = Join-Path $root "mobile\build\outputs\apk\debug\mobile-debug.apk"
$wearApk = Join-Path $root "wear\build\outputs\apk\debug\wear-debug.apk"

if (Test-Path $mobileApk) {
    & $adb -s emulator-5554 install -r $mobileApk | Out-Null
}
if (Test-Path $wearApk) {
    & $adb -s emulator-5556 install -r $wearApk | Out-Null
}

& $adb -s emulator-5554 shell pm grant com.smartbabycry.app android.permission.RECORD_AUDIO
& $adb -s emulator-5554 shell am start -n com.smartbabycry.app/.MainActivity | Out-Null
& $adb -s emulator-5556 shell am start -n com.smartbabycry.app/.WearMainActivity | Out-Null

Write-Host "HearMe phone and watch are ready. Host microphone input is enabled."
