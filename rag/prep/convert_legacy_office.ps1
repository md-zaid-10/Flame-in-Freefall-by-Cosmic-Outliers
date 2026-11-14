# Convert legacy MS Office binaries (.doc / .ppt) in the PSI corpus to .docx / .pptx
# so that python-docx / python-pptx can read them.
#
# Needs Microsoft Word and PowerPoint installed (COM automation). Originals are kept.
# Converted files land next to them with the modern extension.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\convert_legacy_office.ps1

$ErrorActionPreference = "Stop"
$root = Join-Path (Split-Path -Parent $PSScriptRoot) "data\psi"

if (-not (Test-Path $root)) { throw "Corpus directory not found: $root" }

$docs = @(Get-ChildItem -Path $root -Recurse -Filter *.doc  -File | Where-Object { $_.Extension -eq ".doc" })
$ppts = @(Get-ChildItem -Path $root -Recurse -Filter *.ppt  -File | Where-Object { $_.Extension -eq ".ppt" })

Write-Host "Found $($docs.Count) .doc and $($ppts.Count) .ppt files"

$ok = 0; $failed = 0; $skipped = 0
$results = @()

# ---- Word: .doc -> .docx (wdFormatDocumentDefault = 16) ----
if ($docs.Count -gt 0) {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    foreach ($f in $docs) {
        $dest = [IO.Path]::ChangeExtension($f.FullName, ".docx")
        if (Test-Path $dest) {
            Write-Host "  SKIP  $($f.Name) (already converted)"; $skipped++; continue
        }
        try {
            $d = $word.Documents.Open($f.FullName, $false, $true)   # ConfirmConversions, ReadOnly
            $d.SaveAs2($dest, 16)
            $d.Close(0)
            $size = (Get-Item $dest).Length
            Write-Host ("  OK    {0,-58} -> {1:N0} bytes" -f $f.Name, $size)
            $results += [pscustomobject]@{ source = $f.Name; dest = (Split-Path $dest -Leaf); bytes = $size; status = "ok" }
            $ok++
        } catch {
            Write-Host "  FAIL  $($f.Name) -> $($_.Exception.Message)"
            $results += [pscustomobject]@{ source = $f.Name; dest = ""; bytes = 0; status = "fail" }
            $failed++
        }
    }
    $word.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
}

# ---- PowerPoint: .ppt -> .pptx (ppSaveAsOpenXMLPresentation = 24) ----
if ($ppts.Count -gt 0) {
    $pp = New-Object -ComObject PowerPoint.Application
    foreach ($f in $ppts) {
        $dest = [IO.Path]::ChangeExtension($f.FullName, ".pptx")
        if (Test-Path $dest) {
            Write-Host "  SKIP  $($f.Name) (already converted)"; $skipped++; continue
        }
        try {
            $p = $pp.Presentations.Open($f.FullName, $true, $false, $false)  # ReadOnly, Untitled, WithWindow
            $p.SaveAs($dest, 24)
            $p.Close()
            $size = (Get-Item $dest).Length
            Write-Host ("  OK    {0,-58} -> {1:N0} bytes" -f $f.Name, $size)
            $results += [pscustomobject]@{ source = $f.Name; dest = (Split-Path $dest -Leaf); bytes = $size; status = "ok" }
            $ok++
        } catch {
            Write-Host "  FAIL  $($f.Name) -> $($_.Exception.Message)"
            $results += [pscustomobject]@{ source = $f.Name; dest = ""; bytes = 0; status = "fail" }
            $failed++
        }
    }
    $pp.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($pp)
}

[GC]::Collect()
$log = Join-Path (Split-Path -Parent $PSScriptRoot) "data\legacy_conversion.json"
$results | ConvertTo-Json -Depth 3 | Out-File -FilePath $log -Encoding utf8

Write-Host ""
Write-Host "DONE  converted=$ok  failed=$failed  skipped=$skipped"
Write-Host "log: $log"
