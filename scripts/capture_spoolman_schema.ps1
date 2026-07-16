$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$OutputPath = Join-Path $ProjectRoot "docs\spoolman-openapi.json"
$Candidates = @(
    "http://localhost:7912/openapi.json",
    "http://localhost:7912/api/v1/openapi.json"
)

foreach ($Url in $Candidates) {
    try {
        Write-Host "Trying $Url"
        Invoke-WebRequest -Uri $Url -OutFile $OutputPath -UseBasicParsing
        $Json = Get-Content $OutputPath -Raw | ConvertFrom-Json
        if ($null -eq $Json.openapi -and $null -eq $Json.swagger) {
            throw "The response was JSON but not an OpenAPI schema."
        }

        Write-Host ""
        Write-Host "Schema saved to:"
        Write-Host $OutputPath
        Write-Host ""
        Write-Host "API title: $($Json.info.title)"
        Write-Host "API version: $($Json.info.version)"
        exit 0
    }
    catch {
        Write-Host "Not available at $Url"
    }
}

throw "Could not download the Spoolman OpenAPI schema. Confirm Spoolman is running at http://localhost:7912."
