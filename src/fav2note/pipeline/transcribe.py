"""语音转写：ffmpeg 抽音轨 + faster-whisper。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..config import Config
from ..models import Media, Transcript


def extract_audio(config: Config, video: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [config.ffmpeg, "-v", "error", "-y", "-i", str(video), "-vn",
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)],
        check=True,
        timeout=900,
    )
    return dest


def parse_srt(text: str) -> list[tuple[int, str]]:
    """SRT -> [(秒, 台词)]"""
    segments: list[tuple[int, str]] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        stamp = next((line for line in lines if "-->" in line), "")
        match = re.search(r"(\d+):(\d+):(\d+)", stamp)
        if not match:
            continue
        seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
        text_line = lines[-1]
        if "-->" not in text_line:
            segments.append((seconds, text_line))
    return segments


def load_wav(path: Path, rate: int = 16000):
    """直接读 16k 单声道 16bit WAV，避免 PyAV 版本差异。"""
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as handle:
        if (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) != (rate, 1, 2):
            raise ValueError("需要 16kHz / 单声道 / 16bit 的 WAV")
        raw = handle.readframes(handle.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


class Transcriber:
    """按需加载模型，避免只跑图文时也占显存。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:  # pragma: no cover
            raise SystemExit("需要 faster-whisper：pip install 'fav2note[asr]'") from error

        device = self.config.asr_device
        compute = self.config.asr_compute
        if device == "auto":
            device, compute = "cuda", "float16"
        try:
            self._model = WhisperModel(self.config.asr_model, device=device, compute_type=compute)
        except Exception:  # noqa: BLE001  GPU 不可用时退回 CPU
            self._model = WhisperModel(self.config.asr_model, device="cpu", compute_type="int8")
        return self._model

    def run(self, media: Media) -> Transcript:
        if not media.has_video:
            return Transcript(text="", segments=[])

        wav = media.workdir / f"{media.item.item_id}.wav"
        extract_audio(self.config, media.video, wav)

        model = self._load()
        audio = load_wav(wav)
        try:
            result, _info = model.transcribe(
                audio, language="zh", beam_size=5, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            segments = list(result)
        except Exception as error:  # noqa: BLE001  GPU 缺库时退回 CPU 再跑一次
            print(f"    [i] GPU 转写失败（{error}），改用 CPU 重试")
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.config.asr_model, device="cpu", compute_type="int8")
            result, _info = self._model.transcribe(
                audio, language="zh", beam_size=5, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            segments = list(result)

        rows: list[tuple[int, str]] = []
        srt_lines: list[str] = []
        for index, seg in enumerate(segments, start=1):
            text = seg.text.strip()
            if not text:
                continue
            start = int(seg.start)
            rows.append((start, text))
            srt_lines.append(
                f"{index}\n{_fmt(seg.start)} --> {_fmt(seg.end)}\n{text}\n"
            )

        srt_path = media.workdir / f"{media.item.item_id}.srt"
        srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
        return Transcript(text="\n".join(t for _, t in rows), srt_path=srt_path, segments=rows)


def _fmt(seconds: float) -> str:
    total = int(seconds * 1000)
    hours, rest = divmod(total, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def timed_text(segments: list[tuple[int, str]]) -> str:
    """给 LLM 的带时间码逐字稿。"""
    return "\n".join(f"[{int(s) // 60:02d}:{int(s) % 60:02d}] {text}" for s, text in segments)
