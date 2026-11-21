from dl import fetch as snapshot_download

MODELS = [
    "intfloat/multilingual-e5-small",
    "BAAI/bge-m3",
    "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli",
    "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
]
for hf_id in MODELS:
    # tylko wagi potrzebne na CPU (pomijamy onnx/openvino itp.)
    snapshot_download(hf_id, ignore_patterns=["*.onnx", "onnx/*", "openvino/*", "*.msgpack",
                                              "*.h5", "*.ot", "colbert*", "sparse*", "imgs/*"])
