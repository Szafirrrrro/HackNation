"""Analiza twarzy: detekcja + embedding tożsamości (+ wiek/płeć w InsightFace).

Embedding twarzy -> porównanie z bazą referencyjną znanych osób (cosine).
"""
import cv2
import numpy as np

from bench import IMG_EXT, ModelSpec, files, run_suite, short_label


def inputs():
    return files("faces", IMG_EXT) or files("images", IMG_EXT)


# ---- InsightFace buffalo_l (RetinaFace-10GF + ArcFace R100 + genderage) ----
def load_insight(threads):
    import onnxruntime as ort
    from insightface.app import FaceAnalysis
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    app = FaceAnalysis(name="buffalo_l", root="/models/insightface",
                       providers=["CPUExecutionProvider"])
    # FaceAnalysis nie przyjmuje SessionOptions -> podmieniamy sesje
    for m in app.models.values():
        m.session = ort.InferenceSession(m.session._model_path, so,
                                         providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    return app


def infer_insight(app, path):
    img = cv2.imread(path)
    faces = app.get(img)
    return [{"bbox": [int(v) for v in f.bbox], "score": round(float(f.det_score), 3),
             "age": int(f.age), "sex": f.sex, "emb_dim": int(f.normed_embedding.shape[0])}
            for f in faces]


# ---- OpenCV YuNet (detekcja) + SFace (embedding) ----
def load_cv(threads):
    cv2.setNumThreads(threads)
    det = cv2.FaceDetectorYN.create(
        "/models/opencv/face_detection_yunet_2023mar.onnx", "", (320, 320), 0.8, 0.3, 5000)
    rec = cv2.FaceRecognizerSF.create(
        "/models/opencv/face_recognition_sface_2021dec.onnx", "")
    return det, rec


def infer_cv(m, path):
    det, rec = m
    img = cv2.imread(path)
    h, w = img.shape[:2]
    det.setInputSize((w, h))
    _, faces = det.detect(img)
    out = []
    for f in (faces if faces is not None else []):
        crop = rec.alignCrop(img, f)
        emb = rec.feature(crop)
        out.append({"bbox": [int(v) for v in f[:4]], "score": round(float(f[-1]), 3),
                    "emb_dim": int(np.asarray(emb).size)})
    return out


run_suite("face", [
    ModelSpec("insightface/buffalo_l", "face",
              "kod MIT; wagi modeli tylko do użytku niekomercyjnego/badawczego",
              load_insight, infer_insight, inputs,
              notes="RetinaFace + ArcFace(512d) + wiek/płeć", item_label=short_label),
    ModelSpec("opencv/yunet+sface", "face",
              "YuNet MIT, SFace Apache-2.0",
              load_cv, infer_cv, inputs,
              notes="lekka alternatywa: detekcja + embedding 128d", item_label=short_label),
])
