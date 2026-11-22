from dl import fetch as snapshot_download

for m in ["google/owlv2-base-patch16-ensemble"]:
    snapshot_download(m, allow_patterns=["*.json", "*.txt", "model.safetensors"])
