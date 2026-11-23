from __future__ import annotations

import re
from pathlib import Path

import numpy as np

_DENSITY_CACHE: dict[str, float] = {}


def _char_density(c: str) -> float:
    cached = _DENSITY_CACHE.get(c)
    if cached is not None:
        return cached
    try:
        from PIL import Image, ImageDraw, ImageFont

        im = Image.new("L", (12, 16), 0)
        d = ImageDraw.Draw(im)
        d.text((1, 1), c, font=ImageFont.load_default(), fill=255)
        cov = float(np.count_nonzero(np.asarray(im))) / (12.0 * 16.0)
    except Exception:
        cov = 0.05
    _DENSITY_CACHE[c] = cov
    return cov


def build_semantic_ramp(text: str, default_ramp: np.ndarray) -> np.ndarray:
    import unicodedata

    norm_text = unicodedata.normalize("NFKD", str(text))
    chars = [c for c in norm_text if 32 < ord(c) <= 126]
    if not chars:
        return default_ramp
    unique = list(dict.fromkeys(chars))
    sorted_chars = sorted(unique, key=lambda c: (_char_density(c), c))
    if len(sorted_chars) == 1:
        ramp_chars = [" ", sorted_chars[0]]
    elif len(sorted_chars) == 2:
        ramp_chars = [" ", sorted_chars[0], sorted_chars[1]]
    else:
        ramp_chars = [" "] + sorted_chars
    return np.array(ramp_chars, dtype="<U1")


class TextEngine:
    def __init__(self, source: str | Path | None = None) -> None:
        self._entries: list[tuple[float, float, str]] = []
        self._static_text: str | None = None
        if source is not None:
            source_str = str(source).strip()
            path = Path(source_str)
            if path.is_file():
                self.load_file(path)
            elif any(
                source_str.lower().endswith(ext)
                for ext in (".srt", ".lrc", ".txt", ".sub")
            ) or ("\\" in source_str or "/" in source_str):
                raise FileNotFoundError(f"text file not found: {source_str}")
            else:
                self._static_text = source_str

    def load_file(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"text file not found: {path}")
        content = path.read_text(encoding="utf-8", errors="replace")
        suffix = path.suffix.lower()
        if suffix == ".srt" or "-->" in content:
            self._parse_srt(content)
        elif suffix == ".lrc" or re.search(r"\[\d+:\d+", content):
            self._parse_lrc(content)
        else:
            self._static_text = content.strip()

    def _parse_lrc(self, text: str) -> None:
        pattern = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")
        entries: list[tuple[float, str]] = []
        for raw in text.splitlines():
            line = raw.strip()
            m = pattern.match(line)
            if m:
                mins, secs, txt = m.groups()
                t = int(mins) * 60.0 + float(secs)
                clean_txt = re.sub(r"<[^>]+>", "", txt)
                clean_txt = re.sub(r"\{[^}]+\}", "", clean_txt).strip()
                if clean_txt:
                    entries.append((t, clean_txt))
        entries.sort(key=lambda x: x[0])
        self._entries = []
        for i, (t, txt) in enumerate(entries):
            end_t = entries[i + 1][0] if i + 1 < len(entries) else t + 6.0
            self._entries.append((t, end_t, txt))

    def _parse_srt(self, text: str) -> None:
        pattern = re.compile(
            r"(\d+):(\d+):(\d+)[,\.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,\.](\d+)"
        )
        blocks = re.split(r"(?:\r?\n){2,}", text.strip())
        self._entries = []
        for b in blocks:
            lines = [l.strip() for l in b.splitlines() if l.strip()]
            if len(lines) >= 2:
                m = pattern.search(lines[1])
                if not m and len(lines) >= 3:
                    m = pattern.search(lines[0])
                    raw_sub = " ".join(lines[1:])
                elif m:
                    raw_sub = " ".join(lines[2:])
                else:
                    raw_sub = " ".join(lines[1:])
                if m:
                    h1, m1, s1, ms1, h2, m2, s2, ms2 = m.groups()
                    t1 = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000.0
                    t2 = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000.0
                    clean_sub = re.sub(r"<[^>]+>", "", raw_sub)
                    clean_sub = re.sub(r"\{[^}]+\}", "", clean_sub).strip()
                    if clean_sub:
                        self._entries.append((t1, t2, clean_sub))
        self._entries.sort(key=lambda x: x[0])

    def get_line(self, t: float) -> str | None:
        if self._static_text:
            return self._static_text
        if not self._entries:
            return None
        for start, end, txt in self._entries:
            if start <= t < end:
                return txt
        if t < self._entries[0][0]:
            return self._entries[0][2]
        if t >= self._entries[-1][1]:
            return self._entries[-1][2]
        last_txt = self._entries[0][2]
        for start, end, txt in self._entries:
            if t >= start:
                last_txt = txt
            else:
                break
        return last_txt

    def has_content(self) -> bool:
        return bool(self._static_text or self._entries)


LyricEngine = TextEngine
