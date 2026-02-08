import os
import io
import csv
import time
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, Set

import boto3
import gradio as gr
import numpy as np
import soundfile as sf
from dotenv import load_dotenv
from supabase import create_client, Client

# =========================
# CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR.parent / ".env"
load_dotenv(ENV_PATH)

AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY", "")
AWS_SECRET_KEY = os.environ.get("AWS_SECRET_KEY", "")
AWS_REGION = os.environ.get("AWS_REGION", "me-south-1")
S3_BUCKET = os.environ.get("S3_BUCKET", "voicer-storage")

SUPABASE_URL = os.environ.get("SUPABASE_URL_2", "")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_KEY_2")
    or os.environ.get("SUPABASE_ANON_KEY")
    or ""
)

COUNTRY_CODES = {
    "Algeria": "dz",
    "Bahrain": "bh",
    "Egypt": "eg",
    "Iraq": "iq",
    "Jordan": "jo",
    "Kuwait": "kw",
    "Lebanon": "lb",
    "Libya": "ly",
    "Mauritania": "mr",
    "Morocco": "ma",
    "Oman": "om",
    "Palestine": "ps",
    "Qatar": "qa",
    "Saudi Arabia": "sa",
    "Somalia": "so",
    "Sudan": "sd",
    "Syria": "sy",
    "Tunisia": "tn",
    "United Arab Emirates": "ae",
    "Yemen": "ye",
}

WAVS_FOLDER = "wavs"
METADATA_CSV_NAME = "metadata.csv"
METADATA_OTH_CSV_NAME = "metadata_oth.csv"

REJECT_REASONS = [
    "Noisy",
    "Wrong text",
    "Silence",
    "Clipped / Cut",
    "Distortion",
    "Wrong speaker",
    "Other",
]

# S3 listing safety
MAX_KEYS_LIST = int(os.environ.get("MAX_KEYS_LIST", "200000"))

# Random "next" sampling size
RANDOM_TRIES = int(os.environ.get("RANDOM_TRIES", "150"))
SUPABASE_IN_CHUNK = int(os.environ.get("SUPABASE_IN_CHUNK", "100"))


# =========================
# CLIENTS
# =========================
def _create_s3_client():
    if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
        return boto3.client("s3", region_name=AWS_REGION)
    return boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION,
    )


S3_CLIENT = _create_s3_client()
supabase: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


# =========================
# DATA STRUCTURES
# =========================
@dataclass
class Sample:
    country_name: str
    country_code: str
    user_folder: str  # internal only
    audio_file: str
    text: str
    row: Dict[str, Any]


# =========================
# VALIDATION / SANITIZATION
# =========================
def config_error_message() -> Optional[str]:
    missing = []
    if not S3_BUCKET:
        missing.append("S3_BUCKET")
    if not AWS_REGION:
        missing.append("AWS_REGION")
    if not AWS_ACCESS_KEY:
        missing.append("AWS_ACCESS_KEY")
    if not AWS_SECRET_KEY:
        missing.append("AWS_SECRET_KEY")
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY)")

    if missing:
        return (
            "⚠️ **Configuration is missing.**\n\n"
            f"Missing env vars: `{', '.join(missing)}`\n\n"
            f"Local: ensure `{ENV_PATH}` contains them.\n"
            "HF Spaces: set them under **Space → Settings → Secrets**.\n"
        )
    return None


def sanitize_id(s: str) -> str:
    """
    Remove control chars that can break PostgREST / HTTP encoding.
    """
    if not s:
        return ""
    return "".join(ch for ch in s if ch >= " " and ch not in "\x7f").strip()


def _to_str(v) -> str:
    """
    Robust conversion for CSV values; sometimes DictReader values become lists
    if a row has extra columns.
    """
    if v is None:
        return ""
    if isinstance(v, list):
        return " ".join(str(x) for x in v if x is not None).strip()
    return str(v).strip()


# =========================
# S3 HELPERS
# =========================
def s3_get_bytes(key: str) -> bytes:
    obj = S3_CLIENT.get_object(Bucket=S3_BUCKET, Key=key)
    return obj["Body"].read()


def s3_key_exists(key: str) -> bool:
    try:
        S3_CLIENT.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except Exception:
        return False


def list_s3_common_prefixes(prefix: str, delimiter: str = "/") -> List[str]:
    """
    List "folders" under a prefix using Delimiter.
    Example: prefix="sa/" returns ["sa/userA/", "sa/userB/", ...]
    """
    prefixes = []
    token = None
    listed = 0

    while True:
        kwargs = {
            "Bucket": S3_BUCKET,
            "Prefix": prefix,
            "Delimiter": delimiter,
            "MaxKeys": 1000,
        }
        if token:
            kwargs["ContinuationToken"] = token

        resp = S3_CLIENT.list_objects_v2(**kwargs)

        for p in resp.get("CommonPrefixes", []) or []:
            cp = p.get("Prefix")
            if cp:
                prefixes.append(cp)
            listed += 1
            if listed >= MAX_KEYS_LIST:
                break

        if listed >= MAX_KEYS_LIST:
            break

        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break

    return prefixes


def load_audio_from_s3(key: str) -> Optional[Tuple[int, np.ndarray]]:
    try:
        data = s3_get_bytes(key)
        audio, sr = sf.read(io.BytesIO(data))
        return (sr, audio)
    except Exception as e:
        print("load_audio_from_s3 error:", key, e)
        return None


# =========================
# METADATA CSV PARSING
# =========================
def parse_metadata_csv_bytes(b: bytes) -> List[Dict[str, str]]:
    text = b.decode("utf-8", errors="replace")

    delimiter = ","
    if text.count("|") > text.count(","):
        delimiter = "|"

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = []
    for row in reader:
        clean = {_to_str(k): _to_str(v) for k, v in row.items()}
        clean = {k: v for k, v in clean.items() if k}  # drop empty keys
        rows.append(clean)
    return rows


def extract_audio_and_text(row: Dict[str, str]) -> Optional[Tuple[str, str]]:
    audio_candidates = ["audio_file", "audio", "file", "filename", "wav", "path"]
    text_candidates = ["text", "sentence", "transcript", "prompt"]

    audio = ""
    for k in audio_candidates:
        if k in row and row[k]:
            audio = row[k]
            break

    text = ""
    for k in text_candidates:
        if k in row and row[k]:
            text = row[k]
            break

    if not audio:
        return None
    return audio, text


def load_user_metadata(user_folder: str) -> List[Dict[str, str]]:
    """
    Loads:
      - {user_folder}/metadata.csv (required)
      - {user_folder}/metadata_oth.csv (optional)
    Returns combined rows.
    """
    rows: List[Dict[str, str]] = []

    key_main = f"{user_folder}{METADATA_CSV_NAME}"
    b_main = s3_get_bytes(key_main)
    rows.extend(parse_metadata_csv_bytes(b_main))

    key_oth = f"{user_folder}{METADATA_OTH_CSV_NAME}"
    try:
        if s3_key_exists(key_oth):
            b_oth = s3_get_bytes(key_oth)
            rows.extend(parse_metadata_csv_bytes(b_oth))
    except Exception as e:
        print("Skipping metadata_oth.csv for", user_folder, "error:", e)

    return rows


def resolve_audio_key(country_code: str, user_folder: str, audio_file: str) -> str:
    audio_file = (audio_file or "").lstrip("/")

    candidates = [
        f"{user_folder}{WAVS_FOLDER}/{audio_file}",
        f"{user_folder}{audio_file}",  # if metadata already includes wavs/...
        f"{country_code}/{audio_file}",  # fallback
    ]
    for k in candidates:
        if s3_key_exists(k):
            return k
    return candidates[0]


# =========================
# BUILD SAMPLES
# =========================
def build_country_samples(country_name: str, country_code: str) -> List[Sample]:
    country_prefix = f"{country_code}/"
    user_prefixes = sorted(list_s3_common_prefixes(country_prefix))

    samples: List[Sample] = []
    for user_folder in user_prefixes:
        try:
            rows = load_user_metadata(user_folder)
        except Exception as e:
            print("Skipping folder (metadata read/parse issue):", user_folder, e)
            continue

        for row in rows:
            parsed = extract_audio_and_text(row)
            if not parsed:
                continue
            audio_file, text = parsed
            samples.append(
                Sample(
                    country_name=country_name,
                    country_code=country_code,
                    user_folder=user_folder,
                    audio_file=audio_file,
                    text=text,
                    row=row,
                )
            )
    return samples


def sample_id_from(s: Sample) -> str:
    raw = f"{s.country_code}|{s.user_folder}|{(s.audio_file or '').lstrip('/')}"
    return sanitize_id(raw)


# =========================
# SUPABASE HELPERS
# =========================
def ensure_supabase() -> Client:
    if not supabase:
        raise RuntimeError("Supabase is not configured.")
    return supabase

def register_annotator(name: str) -> Tuple[bool, str]:
    """
    Get-or-create:
      - If name exists -> OK (returning user)
      - If not -> insert -> OK (new user)
    """
    sb = ensure_supabase()
    name = (name or "").strip()
    if not name:
        return False, "❌ Please enter a name."
    if len(name) < 3:
        return False, "❌ Name is too short (min 3 chars)."
    if len(name) > 40:
        return False, "❌ Name is too long (max 40 chars)."

    # 1) Check if it exists
    try:
        resp = sb.table("annotators").select("name").eq("name", name).limit(1).execute()
        data = resp.data or []
        if data:
            return True, f"✅ Welcome back: **{name}**"
    except Exception as e:
        return False, f"❌ Failed to check name: `{e}`"

    # 2) If not exists, create it
    try:
        sb.table("annotators").insert({"name": name}).execute()
        return True, f"✅ Name reserved: **{name}**"
    except Exception:
        # Race case: someone created same name between check & insert
        return True, f"✅ Welcome back: **{name}**"


def fetch_annotated_ids(sample_ids: List[str], chunk_size: int = SUPABASE_IN_CHUNK) -> Set[str]:
    """
    Chunked .in_() to avoid PostgREST 'JSON could not be generated' / request size limits.
    Also sanitizes + de-dups.
    """
    sb = ensure_supabase()
    out: Set[str] = set()

    cleaned: List[str] = []
    seen: Set[str] = set()
    for x in sample_ids:
        x = sanitize_id(x)
        if not x or x in seen:
            continue
        seen.add(x)
        cleaned.append(x)

    for i in range(0, len(cleaned), chunk_size):
        chunk = cleaned[i : i + chunk_size]
        if not chunk:
            continue
        resp = sb.table("annotations").select("sample_id").in_("sample_id", chunk).execute()
        rows = resp.data or []
        out.update(r["sample_id"] for r in rows if "sample_id" in r)

    return out


def save_annotation(
    annotator_name: str,
    s: Sample,
    decision: str,
    reject_reason: str,
    comment: str,
    s3_audio_key: str,
):
    sb = ensure_supabase()
    payload = {
        "sample_id": sample_id_from(s),
        "country_code": s.country_code,
        "country_name": s.country_name,
        "s3_audio_key": s3_audio_key,
        "audio_file": s.audio_file,
        "text_sample": s.text,
        "annotator_name": annotator_name,
        "decision": decision,
        "reject_reason": reject_reason if decision == "reject" else None,
        "comment": (comment or "").strip() if decision == "reject" else None,
    }
    sb.table("annotations").insert(payload).execute()


# =========================
# RANDOM NEXT SAMPLE
# =========================
def pick_random_unannotated_index(samples: List[Sample]) -> Optional[int]:
    n = len(samples)
    if n == 0:
        return None

    k = min(RANDOM_TRIES, n)
    idxs = random.sample(range(n), k)

    sids = [sample_id_from(samples[i]) for i in idxs]
    annotated = fetch_annotated_ids(sids)

    available = [i for i, sid in zip(idxs, sids) if sid not in annotated]
    if not available:
        return None
    return random.choice(available)


# =========================
# UI CALLBACKS
# =========================
def on_start_name(state: dict, name: str):
    state = state or {}

    err = config_error_message()
    if err:
        state["error"] = err
        return state, err, gr.update(interactive=False), gr.update(interactive=False)

    ok, msg = register_annotator(name)
    if not ok:
        state["annotator_name"] = None
        return state, msg, gr.update(interactive=False), gr.update(interactive=False)

    state["annotator_name"] = name.strip()
    return state, msg, gr.update(interactive=True), gr.update(interactive=True)


def on_country_change(state: dict, country_name: str):
    state = state or {}
    err = config_error_message()
    if err:
        state["error"] = err
        return ui_load_current(state)

    if not state.get("annotator_name"):
        return (state, "⚠️ Enter a unique name first.", "", None, "accept", gr.update(visible=False), gr.update(visible=False), "")

    country_code = COUNTRY_CODES[country_name]
    samples = build_country_samples(country_name, country_code)

    state["country_name"] = country_name
    state["country_code"] = country_code
    state["samples"] = samples
    state["current_index"] = None

    return ui_load_current(state)


def ui_load_current(state: dict):
    # Outputs: state, header, text, audio, decision, reject_reason, comment, msg
    if not state:
        return (state, "⚠️ Not initialized yet.", "", None, "accept", gr.update(visible=False), gr.update(visible=False), "")

    if state.get("error"):
        return (state, state["error"], "", None, "accept", gr.update(visible=False), gr.update(visible=False), "")

    if not state.get("annotator_name"):
        return (state, "⚠️ Enter a unique name first.", "", None, "accept", gr.update(visible=False), gr.update(visible=False), "")

    samples: List[Sample] = state.get("samples") or []
    country_name = state.get("country_name", "")

    if not samples:
        return (state, f"⚠️ No samples found for **{country_name}**.", "", None, "accept", gr.update(visible=False), gr.update(visible=False), "")

    idx = pick_random_unannotated_index(samples)
    if idx is None:
        return (state, f"✅ No more unannotated samples found for **{country_name}**.", "", None, "accept", gr.update(visible=False), gr.update(visible=False), "")

    state["current_index"] = idx
    s = samples[idx]

    audio_key = resolve_audio_key(s.country_code, s.user_folder, s.audio_file)
    audio = load_audio_from_s3(audio_key)

    header = f"**{country_name}** — Random unannotated sample"
    return (
        state,
        header,
        s.text or "(no text found)",
        audio,
        "accept",
        gr.update(visible=False, value=REJECT_REASONS[0]),
        gr.update(visible=False, value=""),
        "",
    )


def on_toggle(decision: str):
    show = (decision == "reject")
    return gr.update(visible=show), gr.update(visible=show)


def submit_and_next(state: dict, decision: str, reject_reason: str, comment: str):
    if not state:
        return ui_load_current(state)

    if state.get("error"):
        return ui_load_current(state)

    annotator_name = state.get("annotator_name")
    if not annotator_name:
        return (state, "⚠️ Enter a unique name first.", "", None, "accept", gr.update(visible=False), gr.update(visible=False), "")

    samples: List[Sample] = state.get("samples") or []
    idx = state.get("current_index")
    if idx is None or idx < 0 or idx >= len(samples):
        return ui_load_current(state)

    s = samples[idx]
    audio_key = resolve_audio_key(s.country_code, s.user_folder, s.audio_file)

    try:
        save_annotation(
            annotator_name=annotator_name,
            s=s,
            decision=decision,
            reject_reason=(reject_reason or "").strip(),
            comment=(comment or "").strip(),
            s3_audio_key=audio_key,
        )
    except Exception as e:
        msg = f"❌ Failed to save annotation: `{e}`"
        return (
            state,
            state.get("country_name", ""),
            s.text or "(no text found)",
            load_audio_from_s3(audio_key),
            decision,
            gr.update(visible=(decision == "reject")),
            gr.update(visible=(decision == "reject")),
            msg,
        )

    return ui_load_current(state)


# =========================
# UI
# =========================
with gr.Blocks(title="Annotation Tool") as demo:
    gr.HTML("""
<script>
(function(){
  function enhanceAudio(){
    const a = document.querySelector('#player audio');
    if(!a) return;
    try{
      a.setAttribute('controlsList', 'nodownload noplaybackrate');
      a.setAttribute('disablePictureInPicture', 'true');
      a.play().catch(()=>{});
    }catch(e){}
  }
  const obs = new MutationObserver(()=> enhanceAudio());
  obs.observe(document.body, {childList:true, subtree:true});
  setTimeout(enhanceAudio, 600);

  // Hotkeys: A=accept, R=reject, N=next
  document.addEventListener('keydown', function(e){
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
    if (e.key === 'a' || e.key === 'A') {
      const el = document.querySelector('input[type="radio"][value="accept"]');
      if(el) el.click();
    }
    if (e.key === 'r' || e.key === 'R') {
      const el = document.querySelector('input[type="radio"][value="reject"]');
      if(el) el.click();
    }
    if (e.key === 'n' || e.key === 'N') {
      const btn = document.querySelector('#next_btn button');
      if(btn) btn.click();
    }
  });
})();
</script>
""")

    state = gr.State({})

    gr.Markdown("## Simple Annotation Tool")

    with gr.Row():
        annotator_name = gr.Textbox(
            label="Annotator Name (must be unique)",
            placeholder="e.g., sara, ali_1, qa_team_ahmed",
        )
        start_btn = gr.Button("Start", variant="primary")

    start_msg = gr.Markdown("")

    with gr.Row():
        country_dropdown = gr.Dropdown(
            choices=list(COUNTRY_CODES.keys()),
            value="Saudi Arabia" if "Saudi Arabia" in COUNTRY_CODES else list(COUNTRY_CODES.keys())[0],
            label="Country",
            interactive=False,
        )
        load_btn = gr.Button("Load / Next sample", interactive=False)

    header = gr.Markdown("")
    text = gr.Textbox(label="Text Sample", interactive=False, lines=4, max_lines=10)

    audio = gr.Audio(
        label="Audio Sample",
        interactive=False,
        type="numpy",
        elem_id="player",
        show_download_button=False,
        autoplay=True,
    )

    decision = gr.Radio(
        choices=[("Accept ✅", "accept"), ("Reject ❌", "reject")],
        value="accept",
        label="Decision",
    )

    reject_reason = gr.Radio(
        choices=REJECT_REASONS,
        value=REJECT_REASONS[0],
        label="Reject reason",
        visible=False,
    )

    comment = gr.Textbox(
        label="Optional comment",
        placeholder="Add details if needed…",
        visible=False,
        lines=2,
        max_lines=4,
    )

    msg = gr.Markdown("")
    next_btn = gr.Button("Submit & Next", variant="primary", elem_id="next_btn")

    decision.change(fn=on_toggle, inputs=[decision], outputs=[reject_reason, comment])

    start_btn.click(
        fn=on_start_name,
        inputs=[state, annotator_name],
        outputs=[state, start_msg, country_dropdown, load_btn],
    )

    load_btn.click(
        fn=on_country_change,
        inputs=[state, country_dropdown],
        outputs=[state, header, text, audio, decision, reject_reason, comment, msg],
    )

    country_dropdown.change(
        fn=on_country_change,
        inputs=[state, country_dropdown],
        outputs=[state, header, text, audio, decision, reject_reason, comment, msg],
    )

    next_btn.click(
        fn=submit_and_next,
        inputs=[state, decision, reject_reason, comment],
        outputs=[state, header, text, audio, decision, reject_reason, comment, msg],
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", "7860")))
