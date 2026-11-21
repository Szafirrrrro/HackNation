"""Effort: wykrywanie obrazów generowanych przez AI (CLIP ViT-L/14 + ortogonalna dekompozycja SVD).

Używa tych samych funkcji co `python3 training/demo.py` (load_detector, infer_single_image),
więc wynik ekstrakcji = wynik komendy z README projektu Effort. Status `excluded`: ocena
„czy obraz jest fake” dla każdej reklamy, NIE dowód powiązania kampanii (decyzja zespołu
i użytkownika 2026-11-21: pochodzenie obrazu poza grupowaniem).
"""
import os
import sys
from pathlib import Path

from extractor import Extractor, Out, load_bgr

EFFORT = Path("/opt/effort/DeepfakeBench")
WEIGHTS_DIR = EFFORT / "training" / "weights"


class EffortAIGI(Extractor):
    name = "effort-clip-l14"
    use_case = "aigi_effort"
    family = "visual"
    modality = "image"
    primary_field = "ai.effort"
    stage = "excluded"
    decision = ("Wyłączone z grupowania (zgoda użytkownika 2026-11-21): ocena „czy to fake” per reklama; "
                "ten sam generator może służyć niezależnym kampaniom.")
    license = "CC BY-NC 4.0 (kod i wagi Effort); CLIP ViT-L/14 MIT"
    notes = ("CLIP-L/14 + Effort, checkpoint SD v1.4; zrzuty z ramką platformy i JPEG są poza "
             "rozkładem treningowym - fałszywe alarmy do zmierzenia")

    @property
    def weights(self) -> Path:
        return WEIGHTS_DIR / os.environ.get("EFFORT_WEIGHTS", "effort_clip_L14_trainOn_sdv14.pth")

    @property
    def version(self):
        w = self.weights
        size = w.stat().st_size if w.exists() else 0
        return f"effort@96f5dea/{w.name}:{size}"

    @property
    def params(self):
        return {"weights": self.weights.name, "landmark_model": None, "resolution": 224}

    def load(self, threads):
        import torch
        torch.set_num_threads(threads)
        if not self.weights.exists():
            raise FileNotFoundError(f"brak wag {self.weights.name} - wrzuć .pth do models/weights/effort/")
        os.chdir(EFFORT)  # ścieżka do CLIP w effort_detector.py jest względna
        sys.path.insert(0, str(EFFORT / "training"))
        import demo
        self.demo = demo
        model = demo.load_detector("training/config/detector/effort.yaml", str(self.weights))
        # demo.py ładuje wagi z strict=False - sprawdzamy, czy klucze faktycznie weszły
        ckpt = torch.load(str(self.weights), map_location="cpu")
        state = {k.replace("module.", ""): v for k, v in ckpt.get("state_dict", ckpt).items()}
        own = model.state_dict()
        matched = sum(1 for k, v in state.items() if k in own and own[k].shape == v.shape)
        if matched < 0.9 * len(state):
            raise RuntimeError(f"wagi pasują tylko w {matched}/{len(state)} kluczach - zły checkpoint?")
        self.matched = f"{matched}/{len(state)}"
        self.model = model

    def extract(self, item):
        cls, prob = self.demo.infer_single_image(load_bgr(item.path), None, None, self.model)
        return [Out("ai.effort", {"fake_prob": round(float(prob), 4), "label": int(cls),
                                  "label_meaning": "0=real, 1=fake", "weights_keys_matched": self.matched})]


EXTRACTORS = [EffortAIGI()]
