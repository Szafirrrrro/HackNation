"""Twarze: detekcja + embedding tożsamości (porównanie z bazą znanych osób, cosine)."""
import cv2
import numpy as np

from extractor import Extractor, Out, l2, load_bgr


class OpenCVFace(Extractor):
    stage = "on_demand"
    decision = ("Model twarzy (benchmark 2026-11-22), poza profilem domyślnym: test powiązań wymaga "
                "uprawnionej bazy referencyjnej i różnych kampanii z tą samą osobą.")
    name = "opencv-yunet-sface"
    use_case = "face"
    family = "visual"
    modality = "image"
    primary_field = "face.count"
    version = f"opencv-{cv2.__version__}/yunet-2023mar+sface-2021dec"
    license = "YuNet MIT, SFace Apache-2.0"
    params = {"score_threshold": 0.8, "nms_threshold": 0.3}
    notes = "lekka alternatywa: detekcja + embedding 128d"

    def load(self, threads):
        cv2.setNumThreads(threads)
        self.det = cv2.FaceDetectorYN.create(
            "/models/opencv/face_detection_yunet_2023mar.onnx", "", (320, 320), 0.8, 0.3, 5000)
        self.rec = cv2.FaceRecognizerSF.create(
            "/models/opencv/face_recognition_sface_2021dec.onnx", "")

    def extract(self, item):
        img = load_bgr(item.path)
        h, w = img.shape[:2]
        self.det.setInputSize((w, h))
        _, faces = self.det.detect(img)
        faces = faces if faces is not None else []
        outs = [Out("face.count", len(faces))]
        for i, f in enumerate(faces):
            emb = self.rec.feature(self.rec.alignCrop(img, f))
            x, y, bw, bh = (int(v) for v in f[:4])
            outs.append(Out("face.embedding", {
                "vector": l2(np.asarray(emb)), "face_index": i,
                "bbox_xyxy": [x, y, x + bw, y + bh], "det_score": round(float(f[-1]), 4)}))
        return outs


EXTRACTORS = [OpenCVFace()]
