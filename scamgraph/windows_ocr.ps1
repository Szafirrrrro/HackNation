param([Parameter(Mandatory=$true)][string]$ImagePath)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$taskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation' + [char]96 + '1'
} | Select-Object -First 1
function Get-Result($operation, $type) {
    $task = $taskMethod.MakeGenericMethod($type).Invoke($null, @($operation))
    $task.Wait()
    $task.Result
}
$file = Get-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream = Get-Result ($file.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType,Windows.Storage.Streams,ContentType=WindowsRuntime])
$decoder = Get-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Get-Result ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$result = Get-Result ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime])
$lines = foreach ($line in $result.Lines) {
    $rects = $line.Words | ForEach-Object { $_.BoundingRect }
    $left = ($rects.X | Measure-Object -Minimum).Minimum
    $top = ($rects.Y | Measure-Object -Minimum).Minimum
    $right = ($rects | ForEach-Object { $_.X + $_.Width } | Measure-Object -Maximum).Maximum
    $bottom = ($rects | ForEach-Object { $_.Y + $_.Height } | Measure-Object -Maximum).Maximum
    @{text=$line.Text; bbox=@($left,$top,$right,$bottom)}
}
@{language=$engine.RecognizerLanguage.LanguageTag; lines=@($lines)} | ConvertTo-Json -Depth 5 -Compress
