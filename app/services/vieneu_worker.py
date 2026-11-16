"""Standalone VieNeu TTS worker.

MoneyPrinterTurbo runs this file with the Python interpreter of a separate
environment where the ``vieneu`` package is installed (for example a
text-to-video project venv). It must only use the standard library plus
``vieneu`` so it works in that other environment.

Input: one JSON object on stdin, ``{"text": ..., "voice": ..., "output": ...}``.
Output: a WAV file at ``output``; exit code 0 on success.
"""

import json
import os
import sys


def main() -> int:
    raw = sys.stdin.buffer.read().decode("utf-8")
    request = json.loads(raw)
    text = str(request.get("text") or "").strip()
    voice = str(request.get("voice") or "").strip() or None
    output = str(request.get("output") or "").strip()
    if not text or not output:
        print("vieneu worker: text and output are required", file=sys.stderr)
        return 2

    import vieneu  # imported late so a bad request fails fast

    tts = vieneu.Vieneu()
    audio = tts.infer(text, voice=voice) if voice else tts.infer(text)
    tts.save(audio, output)
    if not os.path.exists(output) or os.path.getsize(output) == 0:
        print("vieneu worker: no audio was written", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
