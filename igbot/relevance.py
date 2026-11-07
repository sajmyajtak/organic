"""Does a photo show what its label says? Zero-shot CLIP (ViT-B/32, ONNX, CPU).

Photo searches match words in titles, tags and categories, so "walnuts" finds a
cyclist at Walnut Beach and "maple leaf" a hockey arena. CLIP looks at the
picture itself and compares it with "a photo of walnuts" and with things a
sticker must never be (people, landscapes, buildings, artworks, text).

The model (Xenova/clip-vit-base-patch32, quantized, ~155 MB) is downloaded once
into build/models/clip. Rendering runs locally, so GitHub Actions never needs it;
if it can't be loaded the check is skipped (`match` returns None).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import requests
from PIL import Image

from .config import BUILD_DIR, env

MODEL_DIR = BUILD_DIR / "models" / "clip"
REPO = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/"
FILES = {"vision_model_quantized.onnx": "onnx/vision_model_quantized.onnx",
         "text_model_quantized.onnx": "onnx/text_model_quantized.onnx",
         "tokenizer.json": "tokenizer.json"}
SIZE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
SCALE = 100.0  # CLIP's logit scale

# What a cut-out sticker must not be. The object prompt competes with these.
NEGATIVES = ["a photo of a person", "a photo of a group of people", "a photo of a landscape",
             "a photo of a building", "a photo of a street", "a photo of a room",
             "a painting", "a drawing", "a page of text", "a screenshot"]


def _download(path: Path, url: str) -> None:
    tmp = path.with_suffix(path.suffix + ".part")
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)
    tmp.rename(path)


class Clip:
    def __init__(self, model_dir: Path = MODEL_DIR):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_dir.mkdir(parents=True, exist_ok=True)
        for name, remote in FILES.items():
            if not (model_dir / name).exists():
                print(f"  stahuji model CLIP: {name}")
                _download(model_dir / name, REPO + remote)
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        cpu = ["CPUExecutionProvider"]
        self.vision = ort.InferenceSession(str(model_dir / "vision_model_quantized.onnx"), opts, providers=cpu)
        self.textual = ort.InferenceSession(str(model_dir / "text_model_quantized.onnx"), opts, providers=cpu)
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._texts: dict[str, np.ndarray] = {}

    def text(self, prompt: str) -> np.ndarray:
        if prompt not in self._texts:
            ids = np.array([self.tokenizer.encode(prompt).ids[:77]], dtype=np.int64)
            emb = self.textual.run(None, {"input_ids": ids})[0][0]
            self._texts[prompt] = emb / np.linalg.norm(emb)
        return self._texts[prompt]

    def image(self, img: Image.Image) -> np.ndarray:
        if img.mode in ("RGBA", "LA"):  # a cut-out: judge it the way it will look, on paper
            bg = Image.new("RGB", img.size, "#E5D5BA")
            bg.paste(img, mask=img.getchannel("A"))
            img = bg
        img = img.convert("RGB")
        w, h = img.size
        k = SIZE / min(w, h)
        img = img.resize((max(SIZE, round(w * k)), max(SIZE, round(h * k))), Image.BICUBIC)
        left, top = (img.width - SIZE) // 2, (img.height - SIZE) // 2
        arr = np.asarray(img.crop((left, top, left + SIZE, top + SIZE)), dtype=np.float32) / 255.0
        arr = ((arr - MEAN) / STD).transpose(2, 0, 1)[None]
        emb = self.vision.run(None, {"pixel_values": arr.astype(np.float32)})[0][0]
        return emb / np.linalg.norm(emb)

    def match(self, img: Image.Image, what: str) -> float:
        """Probability (0-1) that `img` is a photo of `what` rather than a person, scene, artwork..."""
        prompts = [f"a photo of {what.lower()}"] + NEGATIVES
        emb = self.image(img)
        logits = SCALE * np.array([emb @ self.text(p) for p in prompts])
        p = np.exp(logits - logits.max())
        return float(p[0] / p.sum())


_clip: Clip | None = None
_failed = False


def match(img: Image.Image, what: str) -> float | None:
    """See Clip.match; None when the check is off (IGBOT_CLIP=0) or the model can't load."""
    global _clip, _failed
    if _failed or env("IGBOT_CLIP", "1") == "0":
        return None
    if _clip is None:
        try:
            _clip = Clip()
        except Exception as exc:  # no model = the old behaviour, not a broken render
            print(f"  kontrola fotek (CLIP) vypnutá: {exc}")
            _failed = True
            return None
    return _clip.match(img, what)
