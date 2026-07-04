param(
  [Parameter(Mandatory = $true)]
  [string]$Root,
  [int]$Port = 8010
)

$resolvedRoot = [System.IO.Path]::GetFullPath($Root)
$address = [System.Net.IPAddress]::Parse("127.0.0.1")
$server = [System.Net.Sockets.TcpListener]::new($address, $Port)
$server.Start()

$contentTypes = @{
  ".html" = "text/html; charset=utf-8"
  ".css" = "text/css; charset=utf-8"
  ".js" = "application/javascript; charset=utf-8"
  ".json" = "application/json; charset=utf-8"
  ".md" = "text/markdown; charset=utf-8"
  ".png" = "image/png"
  ".jpg" = "image/jpeg"
  ".jpeg" = "image/jpeg"
  ".svg" = "image/svg+xml"
  ".ico" = "image/x-icon"
}

function Send-Response {
  param(
    [System.Net.Sockets.NetworkStream]$Stream,
    [int]$StatusCode,
    [string]$StatusText,
    [byte[]]$Body,
    [string]$ContentType = "text/plain; charset=utf-8"
  )

  $header = "HTTP/1.1 $StatusCode $StatusText`r`nContent-Type: $ContentType`r`nContent-Length: $($Body.Length)`r`nConnection: close`r`n`r`n"
  $headerBytes = [System.Text.Encoding]::ASCII.GetBytes($header)
  $Stream.Write($headerBytes, 0, $headerBytes.Length)
  if ($Body.Length -gt 0) {
    $Stream.Write($Body, 0, $Body.Length)
  }
}

while ($true) {
  $client = $server.AcceptTcpClient()
  try {
    $stream = $client.GetStream()
    $buffer = New-Object byte[] 8192
    $read = $stream.Read($buffer, 0, $buffer.Length)
    if ($read -le 0) {
      $client.Close()
      continue
    }

    $request = [System.Text.Encoding]::ASCII.GetString($buffer, 0, $read)
    $firstLine = ($request -split "`r?`n")[0]
    $parts = $firstLine -split " "
    if ($parts.Length -lt 2 -or $parts[0] -ne "GET") {
      Send-Response $stream 405 "Method Not Allowed" ([System.Text.Encoding]::UTF8.GetBytes("Method Not Allowed"))
      $client.Close()
      continue
    }

    $requestPath = ($parts[1] -split "\?")[0].TrimStart("/")
    $requestPath = [System.Uri]::UnescapeDataString($requestPath)
    if ([string]::IsNullOrWhiteSpace($requestPath)) {
      $requestPath = "index.html"
    }

    $filePath = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($resolvedRoot, $requestPath))
    if (-not $filePath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
      Send-Response $stream 403 "Forbidden" ([System.Text.Encoding]::UTF8.GetBytes("Forbidden"))
      $client.Close()
      continue
    }

    if ([System.IO.Directory]::Exists($filePath)) {
      $filePath = [System.IO.Path]::Combine($filePath, "index.html")
    }

    if (-not [System.IO.File]::Exists($filePath)) {
      Send-Response $stream 404 "Not Found" ([System.Text.Encoding]::UTF8.GetBytes("Not Found"))
      $client.Close()
      continue
    }

    $extension = [System.IO.Path]::GetExtension($filePath).ToLowerInvariant()
    $contentType = if ($contentTypes.ContainsKey($extension)) { $contentTypes[$extension] } else { "application/octet-stream" }
    $bytes = [System.IO.File]::ReadAllBytes($filePath)
    Send-Response $stream 200 "OK" $bytes $contentType
    $client.Close()
  } catch {
    try {
      $body = [System.Text.Encoding]::UTF8.GetBytes("Internal Server Error")
      Send-Response $stream 500 "Internal Server Error" $body
    } catch {}
    $client.Close()
  }
}
