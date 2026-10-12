# llama-launcher installer for Windows (Windows PowerShell 5.1 or newer).
#
#   irm https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.ps1 | iex
#
# What it does, and nothing else:
#   1. installs uv with Astral's official installer, if uv is not on PATH
#   2. finds the latest llama-launcher release on GitHub
#   3. installs it with `uv tool install` (uv fetches a suitable Python itself)
#
# No administrator rights. Run it again to update. Remove with:
#   uv tool uninstall llama-launcher
# Your config file is not touched by installing, updating or removing.
#
# Set $env:LLAMA_LAUNCHER_SOURCE to a path or URL to install that instead of
# the latest release - which is how this script is tested.
#
# Everything runs inside one script block. A download that is cut off part-way
# is a parse error that runs nothing, and no variable or preference set here
# outlives the script. Two things do persist, for this window only: TLS 1.2 is
# added to the protocols .NET may use, and uv's folder is added to PATH if uv
# had to be installed.

& {
    $ErrorActionPreference = 'Stop'
    $repo = 'gabrieljakob/llama-server-launcher'
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    # One request with redirects NOT followed, so every hop can be checked and
    # a redirect to plain HTTP is refused.
    function Open-Https([string]$url) {
        if (-not $url.StartsWith('https://')) { throw "refusing a non-HTTPS URL: $url" }
        $request = [Net.HttpWebRequest]::Create($url)
        $request.AllowAutoRedirect = $false
        $request.UserAgent = 'llama-launcher-install'
        return $request.GetResponse()
    }

    # Where $url redirects to, or '' if it does not redirect.
    function Get-RedirectTarget([string]$url) {
        $response = Open-Https $url
        try {
            $code = [int]$response.StatusCode
            if ($code -ge 300 -and $code -lt 400) { return [string]$response.Headers['Location'] }
            return ''
        } finally { $response.Close() }
    }

    # The body at $url, following redirects by hand.
    function Get-HttpsText([string]$url) {
        for ($hop = 0; $hop -lt 6; $hop++) {
            $response = Open-Https $url
            try {
                $code = [int]$response.StatusCode
                if ($code -ge 300 -and $code -lt 400) {
                    $url = [string]$response.Headers['Location']
                    continue
                }
                $reader = New-Object IO.StreamReader($response.GetResponseStream())
                return $reader.ReadToEnd()
            } finally { $response.Close() }
        }
        throw "too many redirects fetching $url"
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "uv not found - installing it with Astral's installer"
        # Run from a file in a child PowerShell: Astral's script ends in `exit`
        # on failure, and here that would close the window this is typed in.
        $installer = Join-Path ([IO.Path]::GetTempPath()) ('uv-install-' + [Guid]::NewGuid().ToString('N') + '.ps1')
        Set-Content -Path $installer -Value (Get-HttpsText 'https://astral.sh/uv/install.ps1') -Encoding UTF8
        try {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer
            if ($LASTEXITCODE -ne 0) { throw "uv's installer failed (exit $LASTEXITCODE)" }
        } finally {
            Remove-Item -Path $installer -ErrorAction SilentlyContinue
        }
        $env:Path = "$HOME\.local\bin;$env:Path"
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
            throw 'uv was installed but is not on PATH yet; open a new terminal and run this again'
        }
    }

    $source = $env:LLAMA_LAUNCHER_SOURCE
    if ($source) {
        Write-Host "installing llama-launcher from $source"
    } else {
        # .../releases/latest redirects to .../releases/tag/<tag>. With no
        # release it redirects to .../releases, and a repository that cannot
        # be seen is a 404, which GetResponse raises.
        $location = ''
        try { $location = Get-RedirectTarget "https://github.com/$repo/releases/latest" } catch { $location = '' }
        if ($location -notmatch '/releases/tag/([^/?#]+)$') {
            throw "no published release of $repo was found"
        }
        $tag = $Matches[1]
        $source = "llama-launcher @ https://github.com/$repo/archive/refs/tags/$tag.zip"
        Write-Host "installing llama-launcher $tag"
    }

    # --force so that running this again is how you update.
    & uv tool install --force --python '>=3.12' $source
    if ($LASTEXITCODE -ne 0) { throw "uv tool install failed (exit $LASTEXITCODE)" }

    $bin = (& uv tool dir --bin | Select-Object -First 1)
    if ($LASTEXITCODE -ne 0 -or -not $bin) { throw "could not find uv's tool folder" }
    $installed = & (Join-Path $bin 'llama-launcher.exe') --version
    if ($LASTEXITCODE -ne 0) { throw "llama-launcher was installed but does not run (exit $LASTEXITCODE)" }
    Write-Host ''
    Write-Host "installed: $installed"
    if (Get-Command llama-launcher -ErrorAction SilentlyContinue) {
        Write-Host 'run it with:  llama-launcher'
    } else {
        Write-Host 'llama-launcher is not on PATH in this window yet.'
        Write-Host 'run:  uv tool update-shell   then open a new terminal and run:  llama-launcher'
    }
}
