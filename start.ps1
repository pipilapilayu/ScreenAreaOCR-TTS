# Define the root directory to search for DLLs
$rootDir = $PSScriptRoot

# Add a directory to PATH
function AddToPath($dir) {
    $global:env:PATH = $dir + ";" + $global:env:PATH
}

# Find and add all directories containing DLL files to PATH
Get-ChildItem -Path $rootDir -Recurse -Directory | ForEach-Object {
    $dir = $_.FullName
    $dllFiles = Get-ChildItem -Path $dir -Filter "*.dll"
    if ($dllFiles.Count -gt 0) {
        Write-Output "Adding to PATH: $dir"
        AddToPath $dir
    }
}

# Start the application
$exePath = Join-Path -Path $rootDir -ChildPath "main.exe"
Write-Output "Current PATH: '$($global:env:PATH)'"

Start-Process PowerShell -ArgumentList "-NoProfile", "-Command", "`$env:PATH='$($global:env:PATH)'; & `"$exePath`"" -NoNewWindow
