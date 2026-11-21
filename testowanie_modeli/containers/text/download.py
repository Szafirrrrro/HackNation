import sys

sys.path.insert(0, "/app/uc")
from huggingface_hub import snapshot_download

from models import EMBED, ZEROSHOT

for hf_id, *_ in EMBED + ZEROSHOT:
    # tylko wagi safetensors/pytorch potrzebne na CPU (pomijamy onnx/openvino itp.)
    snapshot_download(hf_id, ignore_patterns=["*.onnx", "onnx/*", "openvino/*", "*.msgpack",
                                              "*.h5", "*.ot", "colbert*", "sparse*", "imgs/*"])
