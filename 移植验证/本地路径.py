"""Paths to inputs kept outside the public repository."""

from os import environ
from pathlib import Path

PORT_ROOT = Path(__file__).resolve().parents[1]
ZH_ROOT = Path(environ.get("IS_PURE_ZH_ROOT", str(PORT_ROOT.parent / "is-pure-zh")))

_local_iso = PORT_ROOT / "素材/PS2原盘/game-original.iso"
_shared_iso = ZH_ROOT / "素材/PS2原盘/game-original.iso"
ORIGINAL_ISO = Path(environ.get("IS_PURE_ORIGINAL_ISO", str(_local_iso if _local_iso.is_file() else _shared_iso)))

V74_RELEASE = Path(environ.get(
    "IS_PURE_V74_RELEASE",
    str(ZH_ROOT / "字体研究/_release-v7.4/I-s-Pure-最终汉化结果-20261113-v7.4"),
))
