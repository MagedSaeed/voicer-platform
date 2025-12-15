# app.py  (youtube-transcript-api == 1.2.3)
import os
import re
import zipfile
import tempfile
from urllib.parse import urlparse, parse_qs

import gradio as gr
from importlib.metadata import version as dist_version

from youtube_transcript_api import YouTubeTranscriptApi


# ------------------ URL helpers ------------------

def extract_video_id(url: str) -> str | None:
    url = (url or "").strip()
    if not url:
        return None

    m = re.search(r"(?:youtu\.be/)([A-Za-z0-9_-]{6,})", url)
    if m:
        return m.group(1)

    try:
        u = urlparse(url)
        if "youtube.com" in (u.netloc or ""):
            qs = parse_qs(u.query)
            if "v" in qs and qs["v"]:
                return qs["v"][0]

        for pat in (r"(?:/shorts/)([A-Za-z0-9_-]{6,})", r"(?:/embed/)([A-Za-z0-9_-]{6,})"):
            m = re.search(pat, u.path or "")
            if m:
                return m.group(1)
    except Exception:
        pass

    m = re.search(r"([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def safe_filename(s: str, max_len: int = 120) -> str:
    s = (s or "").strip()
    s = re.sub(r"https?://", "", s)
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:max_len] or "video").rstrip("_")


def runtime_info() -> str:
    import youtube_transcript_api as yta
    return f"youtube-transcript-api={dist_version('youtube-transcript-api')} | file={yta.__file__}"


# ------------------ Transcript helpers ------------------

def _arabic_priority_codes() -> list[str]:
    # Try Arabic + common region variants. fetch() prefers manual over auto automatically.
    return [
        "ar", "ar-SA", "ar-EG", "ar-AE", "ar-IQ", "ar-JO", "ar-KW", "ar-LB",
        "ar-LY", "ar-MA", "ar-OM", "ar-QA", "ar-SD", "ar-SY", "ar-TN", "ar-YE", "ar-001"
    ]


def fetched_transcript_to_text(fetched_transcript) -> str:
    # fetched_transcript is iterable over FetchedTranscriptSnippet objects
    # Each snippet has .text, .start, .duration (per docs)
    return "\n".join(snippet.text for snippet in fetched_transcript)


def fetch_arabic_text(video_id: str) -> tuple[str, dict]:
    """
    Using docs API:
      1) ytt_api.fetch(video_id, languages=[arabic codes...]) (manual preferred automatically)
      2) fallback: list(video_id) + translate('ar') if possible
    """
    ytt_api = YouTubeTranscriptApi()

    # 1) Direct Arabic (manual preferred automatically)
    try:
        ft = ytt_api.fetch(video_id, languages=_arabic_priority_codes())
        return fetched_transcript_to_text(ft), {
            "language_code": getattr(ft, "language_code", "ar"),
            "is_generated": getattr(ft, "is_generated", None),
            "method": "fetch(ar*)",
        }
    except Exception:
        pass

    # 2) Translate from an available transcript
    tl = ytt_api.list(video_id)

    translatable_manual = [t for t in tl if (not t.is_generated) and t.is_translatable]
    translatable_auto = [t for t in tl if t.is_generated and t.is_translatable]
    candidates = translatable_manual or translatable_auto

    if candidates:
        src = candidates[0]
        ar_t = src.translate("ar")
        ft = ar_t.fetch()
        return fetched_transcript_to_text(ft), {
            "language_code": "ar",
            "is_generated": None,
            "method": f"translate(from={src.language_code}, generated={src.is_generated})",
        }

    raise RuntimeError("No Arabic transcript track and no translatable transcript found.")


# ------------------ Cleaning: one sentence per line ------------------

def captions_to_ar_sentences(raw_text: str) -> list[str]:
    text = raw_text or ""

    # Remove timestamps / ranges
    text = re.sub(r"\[?\(?\d{1,2}:\d{2}(?::\d{2})?\)?\]?", " ", text)
    text = re.sub(r"\d{1,2}:\d{2}\s*-->\s*\d{1,2}:\d{2}", " ", text)

    # Remove common artifacts
    text = re.sub(
        r"\s*\(?(?:applause|music|laughter|cheering|inaudible|تصفيق|موسيقى|ضحك)\)?\s*",
        " ",
        text,
        flags=re.I,
    )

    # Normalize whitespace
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    # Sentence split on Arabic/Latin punctuation
    text = re.sub(r"([\.!\?…؟؛])\s+", r"\1<SPLIT>", text)
    parts = [p.strip() for p in text.split("<SPLIT>") if p.strip()]

    out = []
    for s in parts:
        s = re.sub(r"\s+", " ", s).strip()
        s = re.sub(r"\s+([،,\.!\?…؟؛:;])", r"\1", s)
        if s:
            out.append(s)

    return out


# ------------------ Build ZIP ------------------

def build_zip_arabic(urls_text: str, include_header: bool) -> tuple[str | None, str]:
    urls = [u.strip() for u in (urls_text or "").splitlines() if u.strip()]
    if not urls:
        return None, "Paste at least one YouTube URL (one per line)."

    tmpdir = tempfile.mkdtemp(prefix="yt_captions_ar_")
    zip_path = os.path.join(tmpdir, "captions_sentences_ar.zip")

    ok, bad = [], []

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, url in enumerate(urls, start=1):
            vid = extract_video_id(url)
            if not vid:
                bad.append(f"{idx}. Could not extract video id: {url}")
                continue

            try:
                raw_text, meta = fetch_arabic_text(vid)
                sentences = captions_to_ar_sentences(raw_text)

                if not sentences:
                    bad.append(f"{idx}. Arabic output empty after cleaning: {url}")
                    continue

                fname = f"{safe_filename(url)}__{vid}__ar.txt"

                lines = []
                if include_header:
                    lines += [
                        f"URL: {url}",
                        f"VideoID: {vid}",
                        f"ArabicCode: {meta.get('language_code')}",
                        f"Generated: {meta.get('is_generated')}",
                        f"Method: {meta.get('method')}",
                        "",
                    ]
                lines += sentences

                zf.writestr(fname, "\n".join(lines) + "\n")
                ok.append(f"{idx}. ✅ {vid} — {len(sentences)} lines ({meta.get('method')})")

            except Exception as e:
                bad.append(f"{idx}. Error for {url}: {type(e).__name__}: {e}")

    log = ["Runtime:", runtime_info(), ""]
    if ok:
        log += ["Downloaded (Arabic output):", *ok]
    if bad:
        log += ["", "Problems:", *bad]

    return zip_path, "\n".join(log).strip()


# ------------------ UI ------------------

with gr.Blocks(title="YouTube Arabic Captions → Sentences", theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        """
        # YouTube Arabic Captions → One Sentence Per Line
        Uses v1.2.x API (`fetch`, `list`, `translate`) and handles snippet objects correctly (`snippet.text`).
        """
    )

    urls_in = gr.Textbox(
        label="YouTube URLs (one per line)",
        placeholder="https://www.youtube.com/watch?v=...\nhttps://youtu.be/...\n...",
        lines=8,
    )
    include_header_in = gr.Checkbox(
        label="Include metadata header in each file",
        value=False,
    )

    run_btn = gr.Button("Download Arabic Captions", variant="primary")

    out_file = gr.File(label="captions_sentences_ar.zip")
    out_log = gr.Textbox(label="Log", lines=12)

    run_btn.click(
        fn=build_zip_arabic,
        inputs=[urls_in, include_header_in],
        outputs=[out_file, out_log],
    )

if __name__ == "__main__":
    demo.launch()
