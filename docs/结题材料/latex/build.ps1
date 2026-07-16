param(
    [ValidateSet('all','requirements','design','manual','test','summary','final')]
    [string]$Target = 'all'
)

$ErrorActionPreference = 'Stop'
$LatexRoot = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $LatexRoot '..\..\..')).Path
$GeneratedDir = Join-Path $LatexRoot 'generated'
$AssetsDir = Join-Path $LatexRoot 'assets'
$BuildDir = Join-Path $LatexRoot 'build'
$OutputDir = Join-Path $RepoRoot 'output\pdf'
$PublicationDir = Join-Path $OutputDir 'latex-final'
$Filter = Join-Path $LatexRoot 'filters\localize-images.lua'

foreach ($dir in @($GeneratedDir, $AssetsDir, $BuildDir, $OutputDir, $PublicationDir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

$documents = [ordered]@{
    requirements = @{
        source = 'docs\结题材料\17-需求分析报告V2.0.md'
        body = 'requirements-body.tex'
        wrapper = 'requirements-report.tex'
        output = 'STrans-需求分析报告V2.0.pdf'
    }
    design = @{
        source = 'docs\结题材料\18-系统设计方案V2.0.md'
        body = 'system-design-body.tex'
        wrapper = 'system-design-report.tex'
        output = 'STrans-系统设计方案V2.0.pdf'
    }
    manual = @{
        source = 'docs\结题材料\15-软件使用说明书.md'
        body = 'software-manual-body.tex'
        wrapper = 'software-manual.tex'
        output = 'STrans-软件使用说明书.pdf'
    }
    test = @{
        source = 'docs\结题材料\06-系统测试报告.md'
        body = 'system-test-body.tex'
        wrapper = 'system-test-report.tex'
        output = 'STrans-系统测试报告.pdf'
    }
    summary = @{
        source = 'docs\结题材料\16-项目总结报告.md'
        body = 'project-summary-body.tex'
        wrapper = 'project-summary.tex'
        output = 'STrans-项目总结报告.pdf'
    }
}

if ($Target -in @('all','final')) {
    $conversionKeys = @($documents.Keys)
} else {
    $conversionKeys = @($Target)
}

$assetOrigins = @{}
foreach ($key in $conversionKeys) {
    $doc = $documents[$key]
    $source = Join-Path $RepoRoot $doc.source
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Markdown source missing: $source"
    }

    $content = Get-Content -LiteralPath $source -Raw -Encoding UTF8
    $matches = [regex]::Matches($content, '!\[[^\]]*\]\((?<path>[^\s\)]+)')
    foreach ($match in $matches) {
        $relative = $match.Groups['path'].Value
        if ($relative -match '^https?://') { continue }
        $resolved = [IO.Path]::GetFullPath((Join-Path (Split-Path $source -Parent) ($relative -replace '/', '\')))
        if (-not (Test-Path -LiteralPath $resolved)) {
            throw "Referenced image missing: $resolved (from $source)"
        }
        $name = Split-Path $resolved -Leaf
        if ($assetOrigins.ContainsKey($name) -and $assetOrigins[$name] -ne $resolved) {
            throw "Asset filename collision: $name"
        }
        $assetOrigins[$name] = $resolved
        Copy-Item -LiteralPath $resolved -Destination (Join-Path $AssetsDir $name) -Force
    }

    $bodyPath = Join-Path $GeneratedDir $doc.body
    $env:STRANS_DOC_PREFIX = $key
    & pandoc $source `
        '--from=markdown-implicit_figures+pipe_tables+fenced_code_blocks+raw_tex' `
        '--to=latex' `
        '--top-level-division=chapter' `
        '--syntax-highlighting=none' `
        '--wrap=none' `
        "--lua-filter=$Filter" `
        "--output=$bodyPath"
    if ($LASTEXITCODE -ne 0) {
        throw "Pandoc conversion failed for $source"
    }
}
Remove-Item Env:STRANS_DOC_PREFIX -ErrorAction SilentlyContinue

if ($Target -eq 'all') {
    $compileKeys = @($documents.Keys) + @('final')
} elseif ($Target -eq 'final') {
    $compileKeys = @('final')
} else {
    $compileKeys = @($Target)
}

Push-Location $LatexRoot
try {
    foreach ($key in $compileKeys) {
        if ($key -eq 'final') {
            $wrapper = 'final-report.tex'
            $outputName = 'STrans-结题综合报告.pdf'
        } else {
            $wrapper = $documents[$key].wrapper
            $outputName = $documents[$key].output
        }
        if (-not (Test-Path -LiteralPath $wrapper)) {
            throw "LaTeX wrapper missing: $wrapper"
        }

        if ($key -eq 'final') {
            # Some PDF viewers keep the previous comprehensive report open. Build
            # through a unique staging job so an open final-report.pdf cannot block
            # XeTeX's XDV-to-PDF conversion.
            $stamp = Get-Date -Format 'yyyyMMddHHmmssfff'
            $jobName = "final-report-$stamp"
            foreach ($pass in 1..2) {
                & xelatex '-no-pdf' '-interaction=nonstopmode' '-halt-on-error' '-file-line-error' "-jobname=$jobName" "-output-directory=$BuildDir" $wrapper
                if ($LASTEXITCODE -ne 0) {
                    throw "XeLaTeX pass $pass failed: $wrapper"
                }
            }
            $xdv = Join-Path $BuildDir "$jobName.xdv"
            $compiled = Join-Path $BuildDir "$jobName.pdf"
            & xdvipdfmx '-E' '-o' $compiled $xdv
            if ($LASTEXITCODE -ne 0) {
                throw "XDV to PDF conversion failed: $wrapper"
            }
            Copy-Item -LiteralPath (Join-Path $BuildDir "$jobName.log") -Destination (Join-Path $BuildDir 'final-report.log') -Force
        } else {
            & latexmk '-xelatex' '-interaction=nonstopmode' '-halt-on-error' '-file-line-error' "-outdir=$BuildDir" $wrapper
            if ($LASTEXITCODE -ne 0) {
                throw "LaTeX compilation failed: $wrapper"
            }
            $compiled = Join-Path $BuildDir (([IO.Path]::GetFileNameWithoutExtension($wrapper)) + '.pdf')
        }

        if (-not (Test-Path -LiteralPath $compiled)) {
            throw "Compiled PDF missing: $compiled"
        }
        # latex-final is the authoritative publication directory. The top-level
        # copy is retained for compatibility, but a PDF viewer may lock it.
        Copy-Item -LiteralPath $compiled -Destination (Join-Path $PublicationDir $outputName) -Force
        try {
            Copy-Item -LiteralPath $compiled -Destination (Join-Path $OutputDir $outputName) -Force -ErrorAction Stop
        }
        catch [System.IO.IOException] {
            Write-Warning "Top-level compatibility PDF is open; authoritative copy was written to latex-final: $outputName"
        }
    }
}
finally {
    Pop-Location
}

Get-ChildItem -LiteralPath $PublicationDir -Filter 'STrans-*.pdf' |
    Sort-Object Name |
    Select-Object Name, Length, LastWriteTime
