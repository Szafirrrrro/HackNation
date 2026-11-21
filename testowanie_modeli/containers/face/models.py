"""Twarze: detekcja + embedding tożsamości (porównanie z bazą znanych osób, cosine)."""
import cv2
import numpy as np

from extractor import Extractor, Out, l2, load_bgr


class InsightFace(Extractor):
    name = "insightface-buffalo_l"
    use_case = "face"
    family = "visual"
    modality = "image"
    primary_field = "face.count"
    version = "insightface-0.7.3/buffalo_l"
    license = "kod MIT; wagi buffalo_l tylko do użytku niekomercyjnego/badawczego"
    notes = "RetinaFace-10GF + ArcFace R50 WebFace600K (512d) + wiek/płeć"

    def load(self, threads):
        import onnxruntime as ort
        from insightface.app import FaceAnalysis
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        app = FaceAnalysis(name="buffalo_l", root="/models/insightface",
                           providers=["CPUExecutionProvider"])
        for m in app.models.values():  # FaceAnalysis nie przyjmuje SessionOptions
            m.session = ort.InferenceSession(m.session._model_path, so,
                                             providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(640, 640))
        self.app = app

    def extract(self, item):
        faces = self.app.get(load_bgr(item.path))
        outs = [Out("face.count", len(faces))]
        for i, f in enumerate(faces):
            outs.append(Out("face.embedding", {
                "vector": l2(f.normed_embedding), "face_index": i,
                "bbox_xyxy": [int(v) for v in f.bbox], "det_score": round(float(f.det_score), 4),
                "age": int(f.age), "sex": f.sex}))
        return outs


class OpenCVFace(Extractor):
    name = "opencv-yunet-sface"
    use_case = "face"
    family = "visual"
    modality = "image"
    primary_field = "face.count"
    version = f"opencv-{cv2.__version__}/yunet-2023mar+sface-2021dec"
    license = "YuNet MIT, SFace Apache-2.0"
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


EXTRACTORS = [InsightFace(), OpenCVFace()]
