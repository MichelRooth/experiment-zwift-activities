param(
    [Parameter(Mandatory=$true)][string]$InputFile,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
[System.Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::InvariantCulture
$bytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $InputFile))
if ($bytes.Length -lt 14 -or [Text.Encoding]::ASCII.GetString($bytes, 8, 4) -ne '.FIT') {
    throw 'Input is not a valid FIT file.'
}

$headerSize = [int]$bytes[0]
$dataEnd = $headerSize + [int][BitConverter]::ToUInt32($bytes, 4)
$offset = $headerSize
$definitions = @{}
$records = [Collections.Generic.List[object]]::new()
$sessions = [Collections.Generic.List[object]]::new()
$fileIds = [Collections.Generic.List[object]]::new()
$lastTimestamp = 0L
$epoch = [DateTimeOffset]::new(1989, 12, 31, 0, 0, 0, [TimeSpan]::Zero)

function Get-FitValue([byte[]]$b, [int]$at, [int]$size, [byte]$baseType, [bool]$little) {
    $type = $baseType -band 0x1F
    if ($size -eq 1) {
        $v = [int]$b[$at]
        if ($type -eq 1 -and $v -ge 128) { $v -= 256 }
        if ($type -eq 1 -and $v -eq 127) { return $null }
        if (($type -eq 0 -or $type -eq 2 -or $type -eq 10) -and $v -eq 255) { return $null }
        return $v
    }
    if ($size -eq 2) {
        $v = [int][BitConverter]::ToUInt16($b, $at)
        if (-not $little) { $v = [int]($b[$at] * 256 + $b[$at+1]) }
        if ($type -eq 3) { if ($v -ge 32768) { $v -= 65536 }; if ($v -eq 32767) { return $null } }
        elseif ($v -eq 65535) { return $null }
        return $v
    }
    if ($size -eq 4) {
        if ($little) { $u = [uint64][BitConverter]::ToUInt32($b, $at) }
        else { $u = [uint64]$b[$at] * 16777216 + [uint64]$b[$at+1] * 65536 + [uint64]$b[$at+2] * 256 + $b[$at+3] }
        if ($type -eq 5) { $v = [int64]$u; if ($v -ge 2147483648) { $v -= 4294967296 }; if ($v -eq 2147483647) { return $null }; return $v }
        if ($u -eq 4294967295) { return $null }
        return $u
    }
    if ($size -eq 8) {
        $v = [BitConverter]::ToUInt64($b, $at)
        if ($v -eq [uint64]::MaxValue) { return $null }
        return $v
    }
    return ,([byte[]]$b[$at..($at+$size-1)])
}

while ($offset -lt $dataEnd) {
    $h = [int]$bytes[$offset]; $offset++
    $compressed = (($h -band 0x80) -ne 0)
    $isDefinition = (($h -band 0x40) -ne 0)
    $local = if ($compressed) { ($h -shr 5) -band 0x03 } else { $h -band 0x0F }
    if ($isDefinition) {
        $offset++ # reserved
        $architecture = [int]$bytes[$offset]; $offset++
        $little = ($architecture -eq 0)
        if ($little) { $global = [int][BitConverter]::ToUInt16($bytes, $offset) }
        else { $global = [int]($bytes[$offset] * 256 + $bytes[$offset+1]) }
        $offset += 2
        $n = [int]$bytes[$offset]; $offset++
        $fields = [Collections.Generic.List[object]]::new()
        for ($i=0; $i -lt $n; $i++) { $fields.Add(@{ num=[int]$bytes[$offset]; size=[int]$bytes[$offset+1]; type=[byte]$bytes[$offset+2] }); $offset += 3 }
        $devFields = @()
        if (($h -band 0x20) -ne 0) {
            $dn = [int]$bytes[$offset]; $offset++
            for ($i=0; $i -lt $dn; $i++) { $devFields += ,@{ num=[int]$bytes[$offset]; size=[int]$bytes[$offset+1]; index=[int]$bytes[$offset+2] }; $offset += 3 }
        }
        $definitions[$local] = @{ global=$global; little=$little; fields=$fields; dev=$devFields }
        continue
    }
    if (-not $definitions.ContainsKey($local)) { throw "FIT data message references undefined local message $local." }
    $def = $definitions[$local]
    $row = [ordered]@{ _global=$def.global }
    $timestampFromHeader = $null
    foreach ($field in $def.fields) {
        if ($compressed -and $field.num -eq 253) { $timestampFromHeader = (($h -band 0x1F) -bor ($lastTimestamp -band 0xFFFFFFE0)); if ($timestampFromHeader -lt $lastTimestamp) { $timestampFromHeader += 0x20 } }
        $value = Get-FitValue $bytes $offset $field.size $field.type $def.little
        $row[[string]$field.num] = $value
        $offset += $field.size
    }
    foreach ($field in $def.dev) { $offset += $field.size }
    if ($timestampFromHeader -ne $null -and -not $row.Contains('253')) { $row['253'] = $timestampFromHeader }
    if ($row.Contains('253') -and $null -ne $row['253']) { $lastTimestamp = [long]$row['253'] }
    if ($def.global -eq 20) { $records.Add($row) }
    elseif ($def.global -eq 18) { $sessions.Add($row) }
    elseif ($def.global -eq 0) { $fileIds.Add($row) }
}

function Convert-FitTime($v) { if ($null -eq $v) { return $null }; return $epoch.AddSeconds([double]$v).ToString('o') }
function CsvValue($v) { if ($null -eq $v) { return '' }; return $v }

$recordRows = foreach ($r in $records) {
    $ts = if ($r.Contains('253')) { Convert-FitTime $r['253'] } else { $null }
    [pscustomobject][ordered]@{
        activity_file = [IO.Path]::GetFileName($InputFile)
        timestamp_utc = $ts
        latitude_deg = if ($null -ne $r['0']) { [math]::Round(([double]$r['0'] * 180 / 2147483648), 6) } else { '' }
        longitude_deg = if ($null -ne $r['1']) { [math]::Round(([double]$r['1'] * 180 / 2147483648), 6) } else { '' }
        altitude_m = if ($null -ne $r['2']) { [math]::Round(([double]$r['2'] / 5) - 500, 2) } else { '' }
        heart_rate_bpm = if ($r['3'] -gt 0) { $r['3'] } else { '' }
        cadence_rpm = CsvValue $r['4']
        distance_m = if ($null -ne $r['5']) { [math]::Round(([double]$r['5'] / 100), 2) } else { '' }
        speed_m_s = if ($null -ne $r['6']) { [math]::Round(([double]$r['6'] / 1000), 3) } else { '' }
        power_w = CsvValue $r['7']
        temperature_c = CsvValue $r['13']
        raw_timestamp_s = CsvValue $r['253']
    }
}

$session = if ($sessions.Count) { $sessions[$sessions.Count-1] } else { @{} }
$fileId = if ($fileIds.Count) { $fileIds[0] } else { @{} }
$name = [IO.Path]::GetFileName($InputFile)
$dateFromName = $null
if ($name -match '^(\d{4}-\d{2}-\d{2})') { $dateFromName = $Matches[1] }
$start = if ($session.Contains('2')) { Convert-FitTime $session['2'] } elseif ($records.Count -and $records[0].Contains('253')) { Convert-FitTime $records[0]['253'] } else { $null }
$powers = @($records | Where-Object { $null -ne $_['7'] } | ForEach-Object { [double]$_['7'] })
$powerMean = if ($powers.Count) { [math]::Round(($powers | Measure-Object -Average).Average, 2) } else { $null }
$hrs = @($records | Where-Object { $null -ne $_['3'] } | ForEach-Object { [double]$_['3'] })
$hrMean = if ($session.Contains('16') -and $session['16'] -gt 0) { [int]$session['16'] } elseif ($hrs.Count) { [math]::Round(($hrs | Measure-Object -Average).Average, 2) } else { $null }
$hrs = @($hrs | Where-Object { $_ -gt 0 })
if (($null -eq $hrMean -or $hrMean -eq 0) -and $hrs.Count) { $hrMean = [math]::Round(($hrs | Measure-Object -Average).Average, 2) }
if ($hrMean -eq 0) { $hrMean = $null }
$avgPower = if ($session.Contains('20') -and $null -ne $session['20']) { [int]$session['20'] } else { $powerMean }
$avgHr = $hrMean
$distance = if ($session.Contains('9') -and $null -ne $session['9']) { [math]::Round(([double]$session['9'] / 100), 2) } elseif ($records.Count -and $null -ne $records[$records.Count-1]['5']) { [math]::Round(([double]$records[$records.Count-1]['5'] / 100), 2) } else { $null }
$duration = if ($session.Contains('8') -and $null -ne $session['8']) { [math]::Round(([double]$session['8'] / 1000), 1) } elseif ($records.Count -gt 1) { [double]$records[$records.Count-1]['253'] - [double]$records[0]['253'] } else { $null }

$windows = [ordered]@{ 15=15; 30=30; 60=60; 120=120; 300=300; 600=600; 1200=1200; 1800=1800; 3600=3600 }
$maxes = [ordered]@{}
$timedPower = @($records | Where-Object { $null -ne $_['253'] -and $null -ne $_['7'] } | ForEach-Object { [pscustomobject]@{ T=[double]$_['253']; P=[double]$_['7'] } } | Sort-Object T)
$prefixPower = [double[]]::new($timedPower.Count + 1)
for ($i=0; $i -lt $timedPower.Count; $i++) { $prefixPower[$i+1] = $prefixPower[$i] + $timedPower[$i].P }
foreach ($sec in $windows.Keys) {
    $best = $null
    if ($timedPower.Count -ge [int]$sec) {
        $left = 0
        for ($i=0; $i -lt $timedPower.Count; $i++) {
            $startT = $timedPower[$i].T - [int]$sec + 1
            while ($left -lt $i -and $timedPower[$left].T -lt $startT) { $left++ }
            $count = $i - $left + 1
            if ($count -ge ([int]$sec * 0.9) -and ($timedPower[$i].T - $timedPower[$left].T) -ge ([int]$sec - 2)) {
                $mean = ($prefixPower[$i+1] - $prefixPower[$left]) / $count
                if ($null -eq $best -or $mean -gt $best) { $best = $mean }
            }
        }
    }
    $maxes["max_avg_power_${sec}s_w"] = if ($null -eq $best) { '' } else { [math]::Round($best, 2) }
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$metadata = [ordered]@{
    activity_file=$name; date_from_filename=$dateFromName; start_time_utc=$start
    sport=if ($session.Contains('5')) { $session['5'] } else { '' }
    sub_sport=if ($session.Contains('6')) { $session['6'] } else { '' }
    duration_s=$duration; distance_m=$distance; avg_power_w=$avgPower; avg_heart_rate_bpm=$avgHr
    max_heart_rate_bpm=if ($session.Contains('17') -and $session['17'] -gt 0) { $session['17'] } else { '' }
    total_ascent_m=if ($session.Contains('22')) { $session['22'] } else { '' }
    total_descent_m=if ($session.Contains('23')) { $session['23'] } else { '' }
    record_count=$records.Count
    manufacturer=if ($fileId.Contains('1')) { $fileId['1'] } else { '' }
    product_id=if ($fileId.Contains('2')) { $fileId['2'] } else { '' }
    normalized_power_w=if ($session.Contains('34')) { $session['34'] } else { '' }
    training_stress_score=if ($session.Contains('35')) { $session['35'] } else { '' }
}
foreach ($key in $maxes.Keys) { $metadata[$key] = $maxes[$key] }
$metadataRow = [pscustomobject]$metadata
$metadataRow | Export-Csv -LiteralPath (Join-Path $OutputDirectory 'activity_metadata.csv') -NoTypeInformation -Encoding utf8
$recordRows | Export-Csv -LiteralPath (Join-Path $OutputDirectory 'workout_records.csv') -NoTypeInformation -Encoding utf8
Write-Output "Wrote metadata and $($records.Count) workout records to $OutputDirectory"
