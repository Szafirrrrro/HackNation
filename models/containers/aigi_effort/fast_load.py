"""Szybkie ładowanie detektora Effort: te same wagi i ten sam wynik co demo.load_detector.

Oryginalny loader wczytuje cały CLIP-L/14, liczy 96 rozkładów SVD macierzy 1024x1024, a potem
i tak nadpisuje wszystko checkpointem (ponad 2 minuty na 8 rdzeniach). Checkpoint zawiera komplet
parametrów wieży wizyjnej i głowicy, więc tutaj:
  1. budujemy pustą wieżę wizyjną z samej konfiguracji (bez wczytywania wag CLIP i bez SVD),
  2. dla każdej warstwy uwagi składamy wagę tak, jak robi to SVDResidualLinear.forward:
     weight_main + U_residual @ diag(S_residual) @ V_residual, raz przy ładowaniu zamiast przy
     każdym obrazie,
  3. wczytujemy stan i sprawdzamy, że żaden parametr nie został pominięty ani nadmiarowy.
Gdy checkpoint ma inny układ kluczy, load_fast zgłasza FastLoadError, a wywołujący wraca do
oryginalnego demo.load_detector.

    python /app/uc/fast_load.py <argumenty demo.py>     # demo.py z szybkim loaderem (effort.sh)
"""
import sys
from pathlib import Path

CLIP_DIR = Path("/opt/effort/models--openai--clip-vit-large-patch14")
RESIDUAL = ("S_residual", "U_residual", "V_residual")
UNUSED = ("S_r", "U_r", "V_r")   # część główna rozkładu; potrzebna tylko w funkcji straty przy treningu
BUFFERS = ("position_ids",)      # bufor wyliczany z konfiguracji, nie parametr


class FastLoadError(RuntimeError):
    pass


def merged_state(state: dict) -> dict:
    """Stan Effort (weight_main + składniki resztowe) -> stan zwykłych warstw nn.Linear."""
    import torch
    out = {}
    for key, value in state.items():
        prefix, _, leaf = key.rpartition(".")
        if leaf in RESIDUAL or leaf in UNUSED:
            continue
        if leaf == "weight_main":
            parts = [state.get(f"{prefix}.{name}") for name in RESIDUAL]
            if all(p is not None for p in parts):
                s, u, v = parts
                value = value + u @ torch.diag(s) @ v
            elif any(p is not None for p in parts):
                raise FastLoadError(f"niepełne składniki resztowe: {prefix}")
            key = f"{prefix}.weight"
        out[key] = value
    return out


def load_fast(detector_cfg: str, weights: str):
    import torch
    import yaml
    from transformers import CLIPVisionConfig, CLIPVisionModel
    from transformers.modeling_utils import no_init_weights

    from detectors import DETECTOR

    with open(detector_cfg, "r") as f:
        cfg = yaml.safe_load(f)
    if cfg["model_name"] != "effort":
        raise FastLoadError(f"nieobsługiwany detektor: {cfg['model_name']}")
    try:
        ckpt = torch.load(weights, map_location="cpu", mmap=True, weights_only=True)
    except Exception:  # starszy format pliku lub obiekty spoza listy bezpiecznych typów
        ckpt = torch.load(weights, map_location="cpu")
    raw = ckpt.get("state_dict", ckpt)
    state = merged_state({k.replace("module.", ""): v for k, v in raw.items()})

    model_cls = DETECTOR[cfg["model_name"]]
    original = model_cls.build_backbone
    try:  # wieża wizyjna z konfiguracji; losowa inicjalizacja jest zbędna, bo stan nadpisuje wszystko
        with no_init_weights():
            vision = CLIPVisionModel(CLIPVisionConfig.from_pretrained(str(CLIP_DIR))).vision_model
        model_cls.build_backbone = lambda self, config: vision
        model = model_cls(cfg)
    finally:
        model_cls.build_backbone = original

    result = model.load_state_dict(state, strict=False)
    missing = [k for k in result.missing_keys if k.rpartition(".")[2] not in BUFFERS]
    if missing or result.unexpected_keys:
        raise FastLoadError(f"checkpoint nie pasuje do modelu: brak {missing[:3]}, "
                            f"nadmiar {list(result.unexpected_keys)[:3]}")
    model.eval()
    model.checkpoint_keys = len(raw)   # wszystkie klucze checkpointu zostały użyte
    return model


def main():
    """demo.py z repozytorium Effort, z podmienionym loaderem; wyjście i argumenty bez zmian."""
    training = Path("/opt/effort/DeepfakeBench/training")
    sys.path.insert(0, str(training))
    import demo

    slow = demo.load_detector

    def load(detector_cfg, weights):
        try:
            model = load_fast(detector_cfg, weights)
        except Exception as e:  # noqa: BLE001 - każdy błąd szybkiej ścieżki -> oryginalny loader
            print(f"[!] szybkie ładowanie niedostępne ({e}); używam oryginalnego", file=sys.stderr)
            return slow(detector_cfg, weights)
        print("[✓] Detector loaded.")
        return model

    demo.load_detector = load
    demo.main()


if __name__ == "__main__":
    main()
