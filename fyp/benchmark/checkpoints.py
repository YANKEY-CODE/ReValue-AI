"""Verified checkpoint metadata and restricted Houdan loading for local experiments."""

from hashlib import sha256
from importlib import import_module
from io import BytesIO

BUNDLED_SHA = "b26c49987eb44ab60ba0368420b5aa6fa89462b72212d5a83773aabc9a1d543f"
HOUDAN_SHA = "c2c32004a2bbfae390fe439e01a1bdd00fed4ad21270b9cf2caedd5f0e0bf26c"
HOUDAN_BYTES = 19_156_634
HOUDAN_NAMES = {0: "scratch", 1: "bump", 2: "paint", 3: "crack"}
HOUDAN_URL = "https://github.com/houdan-hub/phone-defect-detection/releases/download/v1.0.0/best.pt"


def verify_houdan_bytes(data):
    if len(data) != HOUDAN_BYTES or sha256(data).hexdigest() != HOUDAN_SHA:
        raise ValueError("Houdan checkpoint does not match the approved v1.0.0 release SHA-256.")


def load_houdan(weights, YOLO, torch):
    # Check the exact bytes passed to PyTorch, including for cached or manually supplied files.
    with weights.open("rb") as stream:
        data = stream.read(HOUDAN_BYTES + 1)
    verify_houdan_bytes(data)
    allowed = {
        "torch.nn.modules.linear": ("Identity",),
        "torch.nn.modules.pooling": ("MaxPool2d",),
        "torch.nn.modules.conv": ("Conv2d",),
        "torch.nn.modules.upsampling": ("Upsample",),
        "torch.nn.modules.batchnorm": ("BatchNorm2d",),
        "torch.nn.modules.activation": ("SiLU",),
        "torch.nn.modules.container": ("Sequential", "ModuleList"),
        "ultralytics.nn.tasks": ("DetectionModel",),
        "ultralytics.nn.modules.block": ("DFL", "Attention", "SPPF", "Bottleneck", "PSABlock", "C2PSA", "C3k2", "C3k"),
        "ultralytics.nn.modules.conv": ("Concat", "DWConv", "Conv"),
        "ultralytics.nn.modules.head": ("Detect",),
    }
    approved = [getattr(import_module(module), name) for module, names in allowed.items() for name in names]
    with torch.serialization.safe_globals([*approved, set]):
        checkpoint = torch.load(BytesIO(data), weights_only=True, map_location="cpu")
    wrapper = YOLO("yolo11s.yaml", task="detect", verbose=False)
    wrapper.model = (checkpoint.get("ema") or checkpoint["model"]).float().eval()
    if wrapper.names != HOUDAN_NAMES or wrapper.model.yaml.get("scale") != "s":
        raise ValueError("Houdan's architecture or classes differ from the verified checkpoint.")
    return wrapper
