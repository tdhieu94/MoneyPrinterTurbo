"""VieNeu 本地 TTS 集成：用假的 vieneu 包验证子进程、编码和字幕，不需要真实模型。"""

import sys
import textwrap

import pytest

from app.config import config
from app.services import voice

FAKE_VIENEU = textwrap.dedent(
    '''
    import json, math, os, struct, wave

    class Vieneu:
        def __init__(self):
            loads = os.environ.get("FAKE_VIENEU_LOADS")
            if loads:
                with open(loads, "a", encoding="utf-8") as f:
                    f.write("load\\n")
            print("loading model... (noise on stdout)")

        def infer(self, text, voice=None):
            log = os.environ.get("FAKE_VIENEU_LOG")
            if log:
                with open(log, "w", encoding="utf-8") as f:
                    json.dump({"text": text, "voice": voice}, f, ensure_ascii=False)
            if text == "fail please":
                raise RuntimeError("model exploded")
            return [int(8000 * math.sin(i / 10)) for i in range(24000 * 2)]

        def save(self, audio, path):
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(b"".join(struct.pack("<h", s) for s in audio))
    '''
)


@pytest.fixture
def fake_vieneu(tmp_path, monkeypatch):
    package_dir = tmp_path / "fakepkg"
    package_dir.mkdir()
    (package_dir / "vieneu.py").write_text(FAKE_VIENEU, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(package_dir))
    log = tmp_path / "request.json"
    monkeypatch.setenv("FAKE_VIENEU_LOG", str(log))
    settings = {"python_path": sys.executable, "timeout_seconds": 120}
    monkeypatch.setattr(config, "vieneu", settings)
    voice._vieneu_server.stop()
    yield settings, log
    voice._vieneu_server.stop()


def test_voice_list_and_routing():
    voices = voice.get_vieneu_voices()
    assert "vieneu:Ngọc Lan-Female" in voices
    assert len(voices) == 10
    assert voice.is_vieneu_voice("vieneu:Ngọc Lan-Female")
    assert not voice.is_azure_v1_voice("vieneu:Ngọc Lan-Female")


def test_synthesizes_mp3_with_sentence_subtitles(fake_vieneu, tmp_path):
    _, log = fake_vieneu
    output = tmp_path / "audio.mp3"
    text = "Xin chào các bạn. Hôm nay mình giới thiệu sản phẩm này."
    sub_maker = voice.tts(text, "vieneu:Ngọc Lan-Female", 1.0, str(output))
    assert sub_maker is not None
    assert output.exists() and output.stat().st_size > 0
    assert 1.5 < voice.get_audio_duration(str(output)) < 2.5
    assert len(sub_maker.subs) == 2
    import json

    request = json.loads(log.read_text(encoding="utf-8"))
    assert request == {"text": text, "voice": "Ngọc Lan"}


def test_worker_failure_returns_none(fake_vieneu, tmp_path):
    output = tmp_path / "audio.mp3"
    assert voice.vieneu_tts("fail please", "Ngọc Lan", str(output)) is None
    assert not output.exists()


def test_missing_python_path(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "vieneu", {"python_path": ""})
    assert voice.vieneu_tts("Xin chào", "Ngọc Lan", str(tmp_path / "a.mp3")) is None
    monkeypatch.setattr(config, "vieneu", {"python_path": str(tmp_path / "nope.exe")})
    assert voice.vieneu_tts("Xin chào", "Ngọc Lan", str(tmp_path / "a.mp3")) is None


def test_model_is_loaded_once_for_several_voiceovers(fake_vieneu, tmp_path, monkeypatch):
    loads = tmp_path / "loads.txt"
    monkeypatch.setenv("FAKE_VIENEU_LOADS", str(loads))
    for index in range(3):
        output = tmp_path / f"audio-{index}.mp3"
        assert voice.vieneu_tts("Xin chào các bạn.", "Ngọc Lan", str(output))
        assert output.exists()
    assert loads.read_text(encoding="utf-8").count("load") == 1
    # A failed sentence must not kill the loaded model for the next one.
    assert voice.vieneu_tts("fail please", "Ngọc Lan", str(tmp_path / "x.mp3")) is None
    assert voice.vieneu_tts("Lần nữa.", "Ngọc Lan", str(tmp_path / "y.mp3"))
    assert loads.read_text(encoding="utf-8").count("load") == 1


def test_one_shot_mode_when_keep_loaded_is_off(fake_vieneu, tmp_path, monkeypatch):
    settings, _ = fake_vieneu
    settings["keep_loaded"] = False
    loads = tmp_path / "loads.txt"
    monkeypatch.setenv("FAKE_VIENEU_LOADS", str(loads))
    for index in range(2):
        assert voice.vieneu_tts("Xin chào.", "Ngọc Lan", str(tmp_path / f"{index}.mp3"))
    assert loads.read_text(encoding="utf-8").count("load") == 2
