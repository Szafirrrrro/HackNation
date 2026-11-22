import os
import urllib.request

os.makedirs("/models/opencv", exist_ok=True)
for url in [
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
]:
    dst = "/models/opencv/" + url.rsplit("/", 1)[1]
    urllib.request.urlretrieve(url, dst)
    assert os.path.getsize(dst) > 100_000, f"{dst} wygląda na wskaźnik LFS"
