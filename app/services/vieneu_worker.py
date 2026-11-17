"""Standalone VieNeu TTS worker.

MoneyPrinterTurbo runs this file with the Python interpreter of a separate
environment where the ``vieneu`` package is installed (for example a
text-to-video project venv). It must only use the standard library plus
``vieneu`` so it works in that other environment.

One-shot mode (default):
    stdin: one JSON object ``{"text": ..., "voice": ..., "output": ...}``.
    Writes a WAV file at ``output``; exit code 0 on success.

Server mode (``--serve``):
    Loads the model once, then reads one JSON request per line from stdin and
    answers each with one JSON line ``{"ok": true}`` or
    ``{"ok": false, "error": "..."}``. Loading the model is the slow part of
    VieNeu on CPU, so keeping it in memory makes every later voiceover and
    voice preview much faster. The process ends when stdin closes.
"""

import json
import os
import sys


def _synthesize(tts, request) -> str:
    """Return an error message, or "" on success."""
    text = str(request.get("text") or "").strip()
    voice = str(request.get("voice") or "").strip() or None
    output = str(request.get("output") or "").strip()
    if not text or not output:
        return "text and output are required"
    audio = tts.infer(text, voice=voice) if voice else tts.infer(text)
    tts.save(audio, output)
    if not os.path.exists(output) or os.path.getsize(output) == 0:
        return "no audio was written"
    return ""


def _serve() -> int:
    # The protocol owns the real stdout. Libraries (and their C extensions)
    # sometimes print progress there, which would corrupt the replies, so
    # file descriptor 1 is pointed at stderr for everything else.
    replies = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    def reply(**payload):
        replies.write(json.dumps(payload, ensure_ascii=False) + "\n")
        replies.flush()

    try:
        import vieneu

        tts = vieneu.Vieneu()
    except Exception as exc:  # report the load failure, then stop
        reply(ok=False, ready=False, error=f"{type(exc).__name__}: {exc}")
        return 4
    reply(ok=True, ready=True)

    for line in sys.stdin.buffer:
        line = line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            error = _synthesize(tts, json.loads(line))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        if error:
            reply(ok=False, error=error)
        else:
            reply(ok=True)
    return 0


def main() -> int:
    if "--serve" in sys.argv[1:]:
        return _serve()

    raw = sys.stdin.buffer.read().decode("utf-8")
    request = json.loads(raw)
    if not str(request.get("text") or "").strip() or not str(
        request.get("output") or ""
    ).strip():
        print("vieneu worker: text and output are required", file=sys.stderr)
        return 2

    import vieneu  # imported late so a bad request fails fast

    error = _synthesize(vieneu.Vieneu(), request)
    if error:
        print(f"vieneu worker: {error}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
