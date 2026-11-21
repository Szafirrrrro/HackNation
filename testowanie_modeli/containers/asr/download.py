from dl import fetch as snapshot_download

for m in ["Systran/faster-whisper-base", "Systran/faster-whisper-small"]:
    snapshot_download(m)
