from huggingface_hub import snapshot_download

snapshot_download("Ateeqq/ai-vs-human-image-detector",
                  ignore_patterns=["*.onnx", "*.msgpack", "*.h5", "*.bin"])
