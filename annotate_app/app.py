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
from werkzeug.security import generate_password_hash, check_password_hash

# =========================================================
# ENV / CONFIG
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"  # one folder up (as you requested)
load_dotenv(ENV_PATH)

AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY", "")
AWS_SECRET_KEY = os.environ.get("AWS_SECRET_KEY", "")
AWS_REGION = os.environ.get("AWS_REGION", "me-south-1")
S3_BUCKET = os.environ.get("S3_BUCKET", "voicer-storage")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_KEY")
    or os.environ.get("SUPABASE_ANON_KEY")
    or ""
)

COUNTRY_CODES = {
    "Algeria": "dz",
    "Egypt": "eg",
    "Jordan": "jo",
    "Morocco": "ma",
    "Palestine": "ps",
    "Saudi Arabia": "sa",
    "Sudan": "sd",
    "Syria": "sy",
    "Tunisia": "tn",
    "United Arab Emirates": "ae",
    "Yemen": "ye",
}

# Bucket layout (your structure):
#   {country_code}/{username}/wavs/*.wav
#   {country_code}/{username}/metadata.csv
#   {country_code}/{username}/metadata_oth.csv (optional)
WAVS_FOLDER = "wavs"
METADATA_CSV_NAME = "metadata.csv"
METADATA_OTH_CSV_NAME = "metadata_oth.csv"

# Annotation selection behavior
RANDOM_TRIES = int(os.environ.get("RANDOM_TRIES", "150"))  # random candidates per pick
SUPABASE_IN_CHUNK = int(os.environ.get("SUPABASE_IN_CHUNK", "100"))  # keep small to avoid PostgREST issues

# Rejection reasons (2 levels)
REASON_SEP = " | "
REJECT_REASONS = [
    "غير واضح",
    "نص غير مطابق",
    "سكوت طويل",
    "لهجة مختلفة",
    "Other",
]
REJECT_SUBREASONS = {
    "غير واضح": ["أصوات في الخلفية", "أكثر من متحدث", "صدي صوت", "صوت منخفض"],
    "نص غير مطابق": ["غير مطابق تماما", "مطابق جزئيا", "اختلاف بسيط (مثلا في نطق كلمة أو اثنين)"],
}

# Only these mains will show sub-reason components (the ones in the dict)
SUB_MAIN_REASONS = list(REJECT_SUBREASONS.keys())  # e.g. ["غير واضح", "نص غير مطابق"]

# =========================================================
# CLIENTS
# =========================================================
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
supabase: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None


def ensure_supabase() -> Client:
    if not supabase:
        raise RuntimeError("Supabase is not configured.")
    return supabase


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
        missing.append("SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY / SUPABASE_ANON_KEY)")

    if missing:
        return (
            "⚠️ **Configuration is missing.**\n\n"
            f"Missing env vars: `{', '.join(missing)}`\n\n"
            f"Local: ensure `{ENV_PATH}` exists and contains the required keys.\n"
            "HF Spaces: set them under **Space → Settings → Secrets**.\n"
        )
    return None


# =========================================================
# UTIL / SAFE STRING
# =========================================================
def _to_str(v: Any) -> str:
    """Defensive conversion to string; handles list values too."""
    if v is None:
        return ""
    if isinstance(v, list):
        return " ".join(str(x) for x in v if x is not None).strip()
    return str(v).strip()


def sanitize_id(s: str) -> str:
    """Stable-ish sample id string (no control chars)."""
    if not s:
        return ""
    return "".join(ch for ch in s if ch >= " " and ch not in "\x7f").strip()


# =========================================================
# AUTH (annotators table, like admins)
# =========================================================
def get_annotator_by_email(email: str) -> Optional[dict]:
    sb = ensure_supabase()
    try:
        resp = sb.table("annotators").select("*").eq("email", (email or "").lower()).limit(1).execute()
        data = resp.data or []
        return data[0] if data else None
    except Exception as e:
        print("get_annotator_by_email error:", e)
        return None


def create_annotator(name: str, email: str, password: str) -> Tuple[bool, str]:
    """
    Signup -> approved=false. You approve manually in Supabase.
    Table: public.annotators(name,email,password,approved,created_at)
    """
    sb = ensure_supabase()
    name = (name or "").strip()
    email = (email or "").strip().lower()
    password = password or ""

    if not (name and email and password):
        return False, "Please fill all fields."

    existing = get_annotator_by_email(email)
    if existing:
        return False, "Email already registered."

    payload = {
        "name": name,
        "email": email,
        "password": generate_password_hash(password),
        "approved": False,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    try:
        resp = sb.table("annotators").insert(payload).execute()
        if resp.data:
            return True, "Registered successfully. Waiting for approval."
        return False, "Failed to create annotator."
    except Exception as e:
        print("create_annotator error:", e)
        return False, f"Signup failed. Raw: {e}"


def authenticate_annotator(email: str, password: str) -> Tuple[bool, str, Optional[dict]]:
    sb = ensure_supabase()
    email = (email or "").strip().lower()
    password = password or ""

    if not (email and password):
        return False, "Please enter email and password.", None

    user = get_annotator_by_email(email)
    if not user:
        return False, "Invalid email or password.", None

    if not check_password_hash(user.get("password", ""), password):
        return False, "Invalid email or password.", None

    if not user.get("approved", False):
        return False, "Your account is not approved yet.", None

    return True, "OK", user


# =========================================================
# S3 HELPERS
# =========================================================
def s3_get_bytes(key: str) -> bytes:
    obj = S3_CLIENT.get_object(Bucket=S3_BUCKET, Key=key)
    return obj["Body"].read()


def s3_key_exists(key: str) -> bool:
    try:
        S3_CLIENT.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except Exception:
        return False


def list_user_folders(country_code: str) -> List[str]:
    """
    Returns folder prefixes like: "sa/username/"
    """
    prefixes: List[str] = []
    token = None
    prefix = f"{country_code}/"

    while True:
        kwargs = {"Bucket": S3_BUCKET, "Prefix": prefix, "Delimiter": "/", "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token

        resp = S3_CLIENT.list_objects_v2(**kwargs)
        for cp in (resp.get("CommonPrefixes") or []):
            p = cp.get("Prefix")
            if p and p != prefix:
                prefixes.append(p)

        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break

    return sorted(prefixes)


def load_audio_from_s3(key: str) -> Optional[Tuple[int, np.ndarray]]:
    try:
        data = s3_get_bytes(key)
        audio, sr = sf.read(io.BytesIO(data))
        return (sr, audio)
    except Exception as e:
        print("load_audio_from_s3 error:", key, e)
        return None


# =========================================================
# METADATA
# =========================================================
def parse_metadata_csv_bytes(b: bytes) -> List[Dict[str, str]]:
    """
    Robust CSV parsing. Supports comma or pipe separators.
    """
    text = b.decode("utf-8", errors="replace")
    delimiter = "|" if text.count("|") > text.count(",") else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows: List[Dict[str, str]] = []
    for row in reader:
        clean = {_to_str(k): _to_str(v) for k, v in (row or {}).items()}
        clean = {k: v for k, v in clean.items() if k}
        rows.append(clean)
    return rows


def extract_audio_and_text(row: Dict[str, str]) -> Optional[Tuple[str, str]]:
    audio_keys = ["audio_file", "audio", "file", "filename", "wav", "path"]
    text_keys = ["text", "sentence", "transcript", "prompt"]

    audio = ""
    for k in audio_keys:
        if k in row and row[k]:
            audio = row[k]
            break

    text = ""
    for k in text_keys:
        if k in row and row[k]:
            text = row[k]
            break

    if not audio:
        return None
    return audio, text


def load_user_metadata(user_folder: str) -> List[Dict[str, str]]:
    """
    user_folder like: "sa/userA/"
    key: "sa/userA/metadata.csv"
    optional: "sa/userA/metadata_oth.csv"
    """
    rows: List[Dict[str, str]] = []

    key_main = f"{user_folder}{METADATA_CSV_NAME}"
    b_main = s3_get_bytes(key_main)
    rows.extend(parse_metadata_csv_bytes(b_main))

    key_oth = f"{user_folder}{METADATA_OTH_CSV_NAME}"
    if s3_key_exists(key_oth):
        try:
            b_oth = s3_get_bytes(key_oth)
            rows.extend(parse_metadata_csv_bytes(b_oth))
        except Exception as e:
            print("Skipping metadata_oth.csv for", user_folder, "error:", e)

    return rows


def resolve_audio_key(user_folder: str, audio_file: str) -> str:
    """
    audio_file might be 'x.wav' or 'wavs/x.wav' etc.
    We try reasonable candidates and return first existing.
    """
    af = (audio_file or "").lstrip("/")
    candidates = [
        f"{user_folder}{WAVS_FOLDER}/{af}",
        f"{user_folder}{af}",
        f"{user_folder}{WAVS_FOLDER}/{Path(af).name}",
    ]
    for k in candidates:
        if s3_key_exists(k):
            return k
    return candidates[0]


# =========================================================
# DATA MODEL
# =========================================================
@dataclass
class Sample:
    country_name: str
    country_code: str
    user_folder: str
    audio_file: str
    text: str


def make_sample_id(s: Sample) -> str:
    raw = f"{s.country_code}|{s.user_folder}|{(s.audio_file or '').lstrip('/')}"
    return sanitize_id(raw)


# =========================================================
# SUPABASE (annotations)
# =========================================================
def fetch_annotated_ids(sample_ids: List[str]) -> Set[str]:
    """
    Query Supabase for already annotated sample_ids.
    Uses chunked .in_ to avoid PostgREST 400 errors.
    """
    sb = ensure_supabase()
    cleaned: List[str] = []
    seen: Set[str] = set()

    for x in sample_ids:
        x = sanitize_id(x)
        if not x or x in seen:
            continue
        seen.add(x)
        cleaned.append(x)

    out: Set[str] = set()
    if not cleaned:
        return out

    for i in range(0, len(cleaned), SUPABASE_IN_CHUNK):
        chunk = cleaned[i : i + SUPABASE_IN_CHUNK]
        if not chunk:
            continue
        resp = sb.table("annotations").select("sample_id").in_("sample_id", chunk).execute()
        rows = resp.data or []
        for r in rows:
            sid = r.get("sample_id")
            if sid:
                out.add(sid)
    return out


def save_annotation(
    annotator_email: str,
    annotator_name: str,
    sample: Sample,
    s3_audio_key: str,
    decision: str,
    reject_reason_combined: Optional[str],
    comment: Optional[str],
):
    """
    Table expected:
      public.annotations(
        sample_id, country_code, country_name,
        user_folder, audio_file, s3_audio_key, text_sample,
        annotator_email, annotator_name,
        decision, reject_reason, comment, created_at
      )
    """
    sb = ensure_supabase()
    payload = {
        "sample_id": make_sample_id(sample),
        "country_code": sample.country_code,
        "country_name": sample.country_name,
        "audio_file": sample.audio_file,
        "s3_audio_key": s3_audio_key,
        "text_sample": sample.text or "",
        "annotator_email": annotator_email,
        "annotator_name": annotator_name,
        "decision": decision,
        "reject_reason": reject_reason_combined if decision == "reject" else None,
        "comment": (comment or "").strip() if decision == "reject" else None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    sb.table("annotations").insert(payload).execute()


# =========================================================
# SAMPLE LOADING / PICKING
# =========================================================
def build_country_samples(country_name: str, country_code: str) -> List[Sample]:
    """
    Loads all users under {country_code}/ and merges their metadata.csv (+ metadata_oth.csv).
    Returns a flat list of samples.
    """
    samples: List[Sample] = []
    folders = list_user_folders(country_code)

    for user_folder in folders:
        try:
            rows = load_user_metadata(user_folder)
        except Exception as e:
            print("Skipping folder (no metadata.csv?):", user_folder, e)
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
                )
            )

    return samples


def pick_random_unannotated_index(samples: List[Sample]) -> Optional[int]:
    """
    Randomly choose from samples that are not annotated in Supabase.
    Strategy:
      - sample K random indices
      - ask Supabase which sample_ids are already annotated (chunked)
      - pick random among remaining
    """
    n = len(samples)
    if n == 0:
        return None

    k = min(RANDOM_TRIES, n)
    idxs = random.sample(range(n), k)
    sids = [make_sample_id(samples[i]) for i in idxs]

    annotated = fetch_annotated_ids(sids)
    available = [i for i, sid in zip(idxs, sids) if sid not in annotated]
    if not available:
        return None
    return random.choice(available)


def build_reject_reasons_multi(selected_mains: List[str], sub_map: Dict[str, Optional[str]]) -> str:
    """
    Build one string containing multiple mains. Only mains in SUB_MAIN_REASONS use their sub reason.
    Example:
      "غير واضح | أصوات في الخلفية ; سكوت طويل ; نص غير مطابق | مطابق جزئيا"
    """
    selected_mains = selected_mains or []
    parts: List[str] = []
    for m in selected_mains:
        m = (m or "").strip()
        if not m:
            continue
        if m in sub_map and sub_map.get(m):
            parts.append(f"{m}{REASON_SEP}{(sub_map.get(m) or '').strip()}")
        else:
            parts.append(m)
    return " ; ".join(parts)


# =========================================================
# GRADIO STATE + CALLBACKS
# =========================================================
def empty_state() -> dict:
    return {
        "logged_in": False,
        "annotator_email": None,
        "annotator_name": None,
        "country_name": None,
        "country_code": None,
        "samples": [],
        "current_index": None,
        "error": None,
    }


def handle_signup(name, email, pw):
    err = config_error_message()
    if err:
        return "❌ " + err
    ok, msg = create_annotator(name, email, pw)
    return ("✅ " if ok else "❌ ") + msg


def handle_login(email, pw, st):
    err = config_error_message()
    if err:
        st = empty_state()
        st["error"] = err
        return st, "❌ " + err, gr.update(visible=True), gr.update(visible=False), ""

    ok, msg, user = authenticate_annotator(email, pw)
    if not ok:
        return st, f"❌ {msg}", gr.update(visible=True), gr.update(visible=False), ""

    st["logged_in"] = True
    st["annotator_email"] = user.get("email")
    st["annotator_name"] = user.get("name")

    header_text = f"### Logged in as **{st['annotator_name']}**"
    return st, "", gr.update(visible=False), gr.update(visible=True), header_text


def handle_logout(st):
    st = empty_state()
    return st, gr.update(visible=True), gr.update(visible=False), ""


# --- Decision change: show/hide reject UI + reset sub widgets
def on_decision_change(dec: str):
    if dec != "reject":
        # hide everything + clear
        return (
            gr.update(visible=False, value=[]),      # reject_main (checkboxes)
            gr.update(visible=False, value=None),    # sub for "غير واضح"
            gr.update(visible=False, value=None),    # sub for "نص غير مطابق"
            gr.update(visible=False, value=""),      # comment
        )

    # show reject_main and comment; subs appear only if their main selected
    return (
        gr.update(visible=True, value=[]),          # reject_main
        gr.update(visible=False, value=None),       # sub1 hidden until selected
        gr.update(visible=False, value=None),       # sub2 hidden until selected
        gr.update(visible=True, value=""),          # comment
    )


def on_main_reasons_change(selected, decision, sub_state):
    if decision != "reject":
        return (
            gr.update(visible=False, value=None),
            gr.update(visible=False, value=None),
        )

    selected = selected or []
    sub_state = sub_state or {}

    # غير واضح
    if "غير واضح" in selected:
        sub1 = gr.update(
            visible=True,
            choices=REJECT_SUBREASONS["غير واضح"],
            value=sub_state.get("غير واضح") or REJECT_SUBREASONS["غير واضح"][0],
        )
    else:
        sub1 = gr.update(visible=False)

    # نص غير مطابق
    if "نص غير مطابق" in selected:
        sub2 = gr.update(
            visible=True,
            choices=REJECT_SUBREASONS["نص غير مطابق"],
            value=sub_state.get("نص غير مطابق") or REJECT_SUBREASONS["نص غير مطابق"][0],
        )
    else:
        sub2 = gr.update(visible=False)

    return sub1, sub2


def ui_load_current(st: dict):
    """
    Load a random unannotated sample and return UI updates.
    """
    if not st or not st.get("logged_in"):
        return (
            st,
            gr.update(value="⚠️ Please login first.", visible=True),
            gr.update(value="", visible=True),
            None,
            gr.update(value="accept"),
            gr.update(visible=False, value=[]),        # reject_main
            gr.update(visible=False, value=None),      # sub1
            gr.update(visible=False, value=None),      # sub2
            gr.update(visible=False, value=""),        # comment
            gr.update(value=""),
        )

    samples: List[Sample] = st.get("samples") or []
    if not samples:
        cn = st.get("country_name") or ""
        return (
            st,
            gr.update(value=f"⚠️ No samples loaded for **{cn}**.", visible=True),
            gr.update(value="", visible=True),
            None,
            gr.update(value="accept"),
            gr.update(visible=False, value=[]),
            gr.update(visible=False, value=None),
            gr.update(visible=False, value=None),
            gr.update(visible=False, value=""),
            gr.update(value=""),
        )

    idx = pick_random_unannotated_index(samples)
    if idx is None:
        cn = st.get("country_name") or ""
        return (
            st,
            gr.update(value=f"✅ No more unannotated samples found for **{cn}**.", visible=True),
            gr.update(value="", visible=True),
            None,
            gr.update(value="accept"),
            gr.update(visible=False, value=[]),
            gr.update(visible=False, value=None),
            gr.update(visible=False, value=None),
            gr.update(visible=False, value=""),
            gr.update(value=""),
        )

    st["current_index"] = idx
    s = samples[idx]
    audio_key = resolve_audio_key(s.user_folder, s.audio_file)
    audio = load_audio_from_s3(audio_key)

    header = f"**{s.country_name}** — random unannotated sample"
    return (
        st,
        gr.update(value=header, visible=True),
        gr.update(value=(s.text or "(no text found)"), visible=True),
        audio,
        gr.update(value="accept"),
        gr.update(visible=False, value=[]),     # reject_main hidden by default
        gr.update(visible=False, value=None),   # sub1
        gr.update(visible=False, value=None),   # sub2
        gr.update(visible=False, value=""),     # comment
        gr.update(value=""),
    )


def on_country_change(st: dict, country_name: str):
    """
    Build samples list for the selected country, then load a sample.
    """
    if not st or not st.get("logged_in"):
        return (
            st,
            gr.update(value="⚠️ Please login first.", visible=True),
            gr.update(value="", visible=True),
            None,
            gr.update(value="accept"),
            gr.update(visible=False, value=[]),
            gr.update(visible=False, value=None),
            gr.update(visible=False, value=None),
            gr.update(visible=False, value=""),
            gr.update(value=""),
        )

    country_code = COUNTRY_CODES[country_name]
    st["country_name"] = country_name
    st["country_code"] = country_code

    try:
        st["samples"] = build_country_samples(country_name, country_code)
    except Exception as e:
        st["samples"] = []
        st["current_index"] = None
        return (
            st,
            gr.update(value=f"❌ Failed loading samples: `{e}`", visible=True),
            gr.update(value="", visible=True),
            None,
            gr.update(value="accept"),
            gr.update(visible=False, value=[]),
            gr.update(visible=False, value=None),
            gr.update(visible=False, value=None),
            gr.update(visible=False, value=""),
            gr.update(value=""),
        )

    return ui_load_current(st)

def on_sub_reason_change(value, main_reason, sub_state):
    sub_state = dict(sub_state or {})
    sub_state[main_reason] = value
    return sub_state

def submit_and_next(st, decision, reject_mains, sub_state, comment):
    """
    Save current annotation to Supabase and load next random unannotated sample.
    Uses sub_state (cached radio selections) as the source of truth.
    """
    if not st or not st.get("logged_in"):
        return ui_load_current(st)

    samples: List[Sample] = st.get("samples") or []
    idx = st.get("current_index")
    if idx is None or idx < 0 or idx >= len(samples):
        return ui_load_current(st)

    s = samples[idx]
    audio_key = resolve_audio_key(s.user_folder, s.audio_file)

    # Normalize
    reject_mains = reject_mains or []
    sub_state = sub_state or {}

    try:
        if decision == "reject":
            reason_combined = build_reject_reasons_multi(reject_mains, sub_state)
            comment_clean = (comment or "").strip() or None
        else:
            reason_combined = None
            comment_clean = None

        save_annotation(
            annotator_email=st["annotator_email"],
            annotator_name=st["annotator_name"],
            sample=s,
            s3_audio_key=audio_key,
            decision=decision,
            reject_reason_combined=reason_combined,
            comment=comment_clean,
        )

    except Exception as e:
        # Pull the last remembered sub selections for UI restore
        sub_unclear = sub_state.get("غير واضح")
        sub_text_mismatch = sub_state.get("نص غير مطابق")

        return (
            st,
            gr.update(value="❌ Failed to save annotation.", visible=True),
            gr.update(value=(s.text or "(no text found)"), visible=True),
            load_audio_from_s3(audio_key),
            gr.update(value=decision),
            gr.update(visible=(decision == "reject"), value=reject_mains),  # reject_main

            # Sub radios: visible only if their main is selected; value restored from sub_state
            gr.update(
                visible=(decision == "reject" and ("غير واضح" in reject_mains) and bool(REJECT_SUBREASONS.get("غير واضح"))),
                choices=REJECT_SUBREASONS.get("غير واضح", []),
                value=sub_unclear,
            ),
            gr.update(
                visible=(decision == "reject" and ("نص غير مطابق" in reject_mains) and bool(REJECT_SUBREASONS.get("نص غير مطابق"))),
                choices=REJECT_SUBREASONS.get("نص غير مطابق", []),
                value=sub_text_mismatch,
            ),

            gr.update(visible=(decision == "reject"), value=comment),
            gr.update(value=f"❌ `{e}`"),
        )

    return ui_load_current(st)


# =========================================================
# UI
# =========================================================
def build_app():
    with gr.Blocks(title="Arabic Speech Annotation Tool") as demo:
        st = gr.State(empty_state())
        sub_state = gr.State({
            "غير واضح": None,
            "نص غير مطابق": None,
        })

        gr.HTML(
            """
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
"""
        )

        gr.Markdown("# ✅ Annotation Tool")

        # ---------- AUTH VIEW ----------
        with gr.Row(visible=True) as auth_view:
            with gr.Column(scale=1):
                gr.Markdown("## Login")
                login_email = gr.Textbox(label="Email")
                login_pw = gr.Textbox(label="Password", type="password")
                login_btn = gr.Button("Login", variant="primary")
                login_msg = gr.Markdown("")

            with gr.Column(scale=1):
                gr.Markdown("## Sign up")
                su_name = gr.Textbox(label="Name")
                su_email = gr.Textbox(label="Email")
                su_pw = gr.Textbox(label="Password", type="password")
                su_btn = gr.Button("Sign up")
                su_msg = gr.Markdown("")

        # ---------- MAIN VIEW ----------
        with gr.Column(visible=False) as main_view:
            header_md = gr.Markdown("")
            logout_btn = gr.Button("Logout")

            country_dropdown = gr.Dropdown(
                choices=list(COUNTRY_CODES.keys()),
                value="" if "Saudi Arabia" in COUNTRY_CODES else list(COUNTRY_CODES.keys())[0],
                label="Country",
            )

            header = gr.Markdown("")
            text_box = gr.Textbox(label="Text Sample", interactive=False, lines=4, max_lines=10)

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

            # Main reject reasons: MULTI-SELECT
            reject_main = gr.CheckboxGroup(
                choices=REJECT_REASONS,
                value=[],
                label="أسباب الرفض (يمكن اختيار أكثر من سبب)",
                visible=False,
            )

            # Only two sub-reason radios (for dict keys), stacked
            reject_sub_unclear = gr.Radio(
                choices=REJECT_SUBREASONS.get("غير واضح", []),
                value=None,
                label="تفاصيل سبب الرفض: غير واضح",
                visible=False,
            )

            reject_sub_text = gr.Radio(
                choices=REJECT_SUBREASONS.get("نص غير مطابق", []),
                value=None,
                label="تفاصيل سبب الرفض: نص غير مطابق",
                visible=False,
            )

            comment = gr.Textbox(
                label="ملاحظة (اختياري)",
                placeholder="اكتب تعليق إضافي إذا احتجت…",
                visible=False,
                lines=2,
                max_lines=4,
            )

            msg = gr.Markdown("")

            with gr.Row():
                next_btn = gr.Button("Submit & Next", variant="primary", elem_id="next_btn")
                reload_btn = gr.Button("Reload current")

        # --- AUTH callbacks
        su_btn.click(fn=handle_signup, inputs=[su_name, su_email, su_pw], outputs=[su_msg])

        login_btn.click(
            fn=handle_login,
            inputs=[login_email, login_pw, st],
            outputs=[st, login_msg, auth_view, main_view, header_md],
        )

        logout_btn.click(
            fn=handle_logout,
            inputs=[st],
            outputs=[st, auth_view, main_view, header_md],
        )

        # --- Decision / reject UI
        decision.change(
            fn=on_decision_change,
            inputs=[decision],
            outputs=[reject_main, reject_sub_unclear, reject_sub_text, comment],
        )

        reject_main.change(
            fn=on_main_reasons_change,
            inputs=[reject_main, decision, sub_state],
            outputs=[reject_sub_unclear, reject_sub_text],
        )
        reject_sub_unclear.change(
            fn=on_sub_reason_change,
            inputs=[reject_sub_unclear, gr.State("غير واضح"), sub_state],
            outputs=[sub_state],
        )

        reject_sub_text.change(
            fn=on_sub_reason_change,
            inputs=[reject_sub_text, gr.State("نص غير مطابق"), sub_state],
            outputs=[sub_state],
        )
        # --- Country change -> load samples -> load a random sample
        country_dropdown.change(
            fn=on_country_change,
            inputs=[st, country_dropdown],
            outputs=[st, header, text_box, audio, decision, reject_main, reject_sub_unclear, reject_sub_text, comment, msg],
        )

        # --- Reload
        reload_btn.click(
            fn=ui_load_current,
            inputs=[st],
            outputs=[st, header, text_box, audio, decision, reject_main, reject_sub_unclear, reject_sub_text, comment, msg],
        )

        # --- Submit & Next
        next_btn.click(
            fn=submit_and_next,
            inputs=[st, decision, reject_main, sub_state, comment],
            outputs=[st, header, text_box, audio, decision, reject_main, reject_sub_unclear, reject_sub_text, comment, msg],
        )

    return demo


if __name__ == "__main__":
    app = build_app()
    app.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", "7860")), debug=False)
