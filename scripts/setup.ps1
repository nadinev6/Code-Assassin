param(
    [string]$ProjectName = "qwen2.5-coder:3b",
    [string]$Voice = "en_GB-alan-medium"
)

Write-Host "=== Code Assassin Setup ===" -ForegroundColor Cyan

# Check uv
Write-Host "Checking uv..."
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is not installed. Please install uv first: https://github.com/astral-sh/uv"
    exit 1
}
Write-Host "uv found." -ForegroundColor Green

# Check ollama
Write-Host "Checking ollama..."
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Warning "ollama is not installed. Please install ollama: https://ollama.com/"
} else {
    Write-Host "ollama found." -ForegroundColor Green
}

# Sync dependencies
Write-Host "Syncing dependencies..."
& uv sync

# Pull model
Write-Host "Pulling model $ProjectName..."
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    & ollama pull $ProjectName
} else {
    Write-Warning "Skipping model pull (ollama not found)"
}

# Download voice
Write-Host "Downloading voice $Voice..."
& uv run assassin voices download $Voice

# Run doctor
Write-Host "Running health checks..."
& uv run assassin doctor

Write-Host "Setup complete!" -ForegroundColor Cyan