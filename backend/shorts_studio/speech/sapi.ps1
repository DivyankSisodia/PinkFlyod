# Windows system voice (SAPI, offline): speak a text file into a WAV and print each word's start time as JSON.
param(
    [Parameter(Mandatory = $true)][string]$TextFile,
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Voice = "",
    [int]$Rate = 0,
    [switch]$ListVoices
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($ListVoices) {
    $list = $s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object {
        @{ name = $_.VoiceInfo.Name; culture = $_.VoiceInfo.Culture.Name; gender = [string]$_.VoiceInfo.Gender }
    }
    $s.Dispose()
    ConvertTo-Json -InputObject @($list) -Compress
    exit 0
}
if ($Voice) { $s.SelectVoice($Voice) }
$s.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
$text = [IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8)
$events = New-Object System.Collections.ArrayList
$s.add_SpeakProgress({ param($sender, $e)
    [void]$events.Add(@{ pos = $e.CharacterPosition; len = $e.CharacterCount; ms = $e.AudioPosition.TotalMilliseconds; text = $e.Text })
})
# SpeakProgress.AudioPosition is computed as if the audio were 16 kHz, whatever the output format (measured: at
# 22050 Hz every time is 22050/16000 too late). Writing 16 kHz makes the reported word times match the audio.
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($Out, $fmt)
$s.Speak($text)
$s.SetOutputToNull()
$voiceName = $s.Voice.Name
$s.Dispose()
ConvertTo-Json -InputObject @{ voice = $voiceName; words = @($events) } -Compress -Depth 4
