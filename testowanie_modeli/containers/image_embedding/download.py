from huggingface_hub import snapshot_download

for m in ["laion/CLIP-ViT-B-32-laion2B-s34B-b79K", "facebook/dinov2-small"]:
    snapshot_download(m, allow_patterns=["*.json", "*.txt", "model.safetensors"])
