$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$voiceName = 'Microsoft Irina Desktop'
$synth = $null

function Write-ProtocolLine($value) {
    [Console]::Out.WriteLine(($value | ConvertTo-Json -Compress -Depth 4))
    [Console]::Out.Flush()
}

try {
    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $voice = @($synth.GetInstalledVoices() | Where-Object {
        $_.Enabled -and $_.VoiceInfo.Name -eq $voiceName -and $_.VoiceInfo.Culture.Name -eq 'ru-RU'
    }) | Select-Object -First 1
    if ($null -eq $voice) { throw 'required_voice_unavailable' }
    $synth.SelectVoice($voiceName)
    Write-ProtocolLine @{type='ready'; voice=$voiceName; culture='ru-RU'}

    while ($null -ne ($line = [Console]::In.ReadLine())) {
        $requestId = $null
        try {
            $request = ConvertFrom-Json -InputObject $line -ErrorAction Stop
            $requestId = [string]$request.id
            $text = [string]$request.text
            $output = [string]$request.output_path
            # E76: optional SSML of the same text (the worker never builds markup itself: it only speaks what the manager sent)
            $ssml = if ($null -ne $request.ssml) { [string]$request.ssml } else { '' }
            if ([string]::IsNullOrWhiteSpace($requestId) -or [string]::IsNullOrWhiteSpace($text) -or $text.Length -gt 5000) {
                throw 'bad_request'
            }
            if ([string]::IsNullOrWhiteSpace($output) -or -not [IO.Path]::IsPathRooted($output) -or [IO.Path]::GetExtension($output) -ne '.wav') {
                throw 'bad_output_path'
            }
            $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
                24000,
                [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
                [System.Speech.AudioFormat.AudioChannel]::Mono
            )
            if ($ssml -ne '' -and (-not $ssml.StartsWith('<speak') -or $ssml.Length -gt 40000)) { throw 'bad_request' }
            $synth.SetOutputToWaveFile($output, $format)
            $markup = $false
            if ($ssml -ne '') {
                try { $synth.SpeakSsml($ssml); $markup = $true }
                catch {
                    # The voice refused the markup: say the same text plain, the cue must not be lost for an intonation.
                    $synth.SetOutputToNull()
                    $synth.SetOutputToWaveFile($output, $format)
                    $synth.Speak($text)
                }
            } else {
                $synth.Speak($text)
            }
            $synth.SetOutputToNull()
            Write-ProtocolLine @{type='result'; id=$requestId; ok=$true; voice=$voiceName; culture='ru-RU'; ssml=$markup}
        } catch {
            try { $synth.SetOutputToNull() } catch { }
            $code = if ($_.Exception.Message -match 'bad_request|bad_output_path') { $_.Exception.Message } else { 'synthesis_failed' }
            Write-ProtocolLine @{type='result'; id=$requestId; ok=$false; error=$code; voice=$voiceName; culture='ru-RU'}
        }
    }
} finally {
    if ($null -ne $synth) { $synth.Dispose() }
}
