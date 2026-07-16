$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$OutputPath = Join-Path $ProjectRoot "docs\spoolman-openapi.json"
$Url = "http://localhost:7912/api/v1/openapi.json"

Write-Host "Downloading Spoolman REST API schema from:"
Write-Host $Url

try {
    $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing
    $Json = $Response.Content | ConvertFrom-Json
}
catch {
    throw "Could not download or parse the Spoolman REST API schema from $Url. Confirm Spoolman is running at http://localhost:7912. $($_.Exception.Message)"
}

if ($null -eq $Json.openapi -and $null -eq $Json.swagger) {
    throw "The response from $Url was JSON, but it was not an OpenAPI document."
}

if ($null -eq $Json.info -or $null -eq $Json.info.title -or $Json.info.title -notlike "*Spoolman REST API*") {
    throw "Wrong Spoolman schema returned from $Url. Expected title containing 'Spoolman REST API', got '$($Json.info.title)'."
}

if ($null -eq $Json.paths) {
    throw "The Spoolman REST API schema from $Url did not contain a paths object."
}

$PathCount = @($Json.paths.PSObject.Properties).Count
if ($PathCount -eq 0) {
    throw "The Spoolman REST API schema from $Url did not contain any paths."
}

Set-Content -LiteralPath $OutputPath -Value $Response.Content -NoNewline

Write-Host ""
Write-Host "Schema saved to:"
Write-Host $OutputPath
Write-Host ""
Write-Host "API title: $($Json.info.title)"
Write-Host "API version: $($Json.info.version)"
Write-Host "Path count: $PathCount"
