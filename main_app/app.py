# Arabic Speech Dataset Recorder (Professional UI + Lifetime Country Leaderboard)
# ---------------------------------------------------------------------------
# What changed vs your original:
# ✅ Professional layout (cards, spacing, typography, consistent RTL handling)
# ✅ Clean status alerts + less “boring” UI
# ✅ Lifetime anonymous leaderboard per COUNTRY (Arabic aliases + emojis)
# ✅ Highlights current user row + rank number on the LEFT
# ✅ Leaderboard is inside a collapsed Accordion (does NOT disrupt recording workflow)
#
# Notes:
# - Logic (auth/sentences/storage) is kept very close to your original for safety.
# - You MUST run the SQL setup for leaderboard tables in Supabase (provided at bottom).
#
# ---------------------------------------------------------------------------

import os
import json
import uuid
import time
import random
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import boto3
import gradio as gr
import soundfile as sf
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client, Client

# ===============================
# CONFIG & GLOBALS
# ===============================

load_dotenv()
BASE_DIR = Path(__file__).parent if "__file__" in globals() else Path(".").resolve()
DATA_DIR = Path.home() / ".tts_dataset_creator"
USERS_ROOT = DATA_DIR / "users"

DATA_DIR.mkdir(parents=True, exist_ok=True)
USERS_ROOT.mkdir(parents=True, exist_ok=True)

AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY", "")
AWS_SECRET_KEY = os.environ.get("AWS_SECRET_KEY", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "voicer-storage")
AWS_REGION = os.environ.get("AWS_REGION", "me-south-1")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ Supabase env vars not set")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


def _create_s3_client():
    aws_access_key = os.environ.get("AWS_ACCESS_KEY", "")
    aws_secret_key = os.environ.get("AWS_SECRET_KEY", "")
    if not aws_access_key or not aws_secret_key:
        print("Using IAM role or instance profile for S3")
        return boto3.client("s3", region_name=AWS_REGION)
    print("Using explicit access keys for S3")
    return boto3.client(
        "s3",
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=AWS_REGION,
    )


S3_CLIENT = _create_s3_client()

# ===============================
# COUNTRIES & DIALECTS
# ===============================

AVAILABLE_COUNTRIES = ["Egypt", "Saudi Arabia", "Morocco"]

COUNTRY_EMOJIS = {
    "dz": "🇩🇿",
    "bh": "🇧🇭",
    "eg": "🇪🇬",
    "iq": "🇮🇶",
    "jo": "🇯🇴",
    "kw": "🇰🇼",
    "lb": "🇱🇧",
    "ly": "🇱🇾",
    "mr": "🇲🇷",
    "ma": "🇲🇦",
    "om": "🇴🇲",
    "ps": "🇵🇸",
    "qa": "🇶🇦",
    "sa": "🇸🇦",
    "so": "🇸🇴",
    "sd": "🇸🇩",
    "sy": "🇱🇾",  # (kept from your code, though it's a typo)
    "tn": "🇹🇳",
    "ae": "🇦🇪",
    "ye": "🇾🇪",
}

RECORDING_TARGET_MINUTES = 30
RECORDING_TARGET_SECONDS = RECORDING_TARGET_MINUTES * 60

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
    "Yemen": "ye"
}

COUNTRY_DIALECTS = {
    "Saudi Arabia": {
        "حجازية": "hj",
        "حجازية بدوية": "hj-bd",
        "جنوبية": "jn",
        "تهامية": "th",
        "نجدية": "nj",
        "نجدية بدوية": "nj-bd",
        "قصيمية": "qm",
        "الشمال": "sh",
        "حساوية": "hs",
        "قطيفية": "qt",
        "سيهاتية": "sy",
        "أخرى": "oth"
    },
    "Egypt": {
        "قاهرية": "ca",
        "إسكندرانية": "al",
        "صعيدية": "sa",
        "بورسعيدية": "si",
        "نوبية": "nb",
        "أخرى": "oth"
    },
    "Morocco": {
        "فاسية": "fe",
        "دار البيضاء": "ca",
        "مراكشية": "ma",
        "شمالية": "no",
        "شرقية": "shar",
        "أخرى": "oth"
    },
    "Iraq": {
        "بغدادية": "ba",
        "بصراوية": "bs",
        "موصلية": "mo",
        "كردية": "ku",
        "جنوبية": "so",
        "أخرى": "oth"
    },
    "Yemen": {
        "صنعانية": "sa",
        "عدنية": "ad",
        "حضرمية": "ha",
        "تهامية": "ti",
        "أخرى": "oth"
    },
    "Jordan": {
        "عمانية": "am",
        "شمالية": "no",
        "جنوبية": "so",
        "بدوية": "be",
        "أخرى": "oth"
    },
    "Lebanon": {
        "بيروتية": "be",
        "جبلية": "mo",
        "جنوبية": "so",
        "شمالية": "no",
        "أخرى": "oth"
    },
    "Syria": {
        "دمشقية": "da",
        "حلبية": "al",
        "حمصية": "ho",
        "ساحلية": "co",
        "أخرى": "oth"
    },
    "Palestine": {
        "قدسية": "je",
        "غزاوية": "ga",
        "خليلية": "he",
        "شمالية": "no",
        "أخرى": "oth"
    },
    "United Arab Emirates": {
        "إماراتية": "em",
        "دبية": "du",
        "أبوظبية": "ad",
        "شارقية": "shr",
        "أخرى": "oth"
    },
    "Kuwait": {
        "كويتية": "ku",
        "بدوية": "be",
        "أخرى": "oth"
    },
    "Qatar": {
        "قطرية": "qa",
        "بدوية": "be",
        "أخرى": "oth"
    },
    "Bahrain": {
        "بحرينية": "ba",
        "مدنية": "ur",
        "أخرى": "oth"
    },
    "Oman": {
        "عمانية": "om",
        "ظفارية": "dh",
        "داخلية": "in",
        "أخرى": "oth"
    },
    "Algeria": {
        "جزائرية": "al",
        "قسنطينية": "co",
        "وهرانية": "or",
        "قبائلية": "ka",
        "أخرى": "oth"
    },
    "Tunisia": {
        "تونسية": "tu",
        "صفاقسية": "sf",
        "سوسية": "so",
        "أخرى": "oth"
    },
    "Libya": {
        "طرابلسية": "tr",
        "بنغازية": "be",
        "فزانية": "fe",
        "أخرى": "oth"
    },
    "Sudan": {
        "خرطومية": "kh",
        "شمالية": "no",
        "دارفورية": "da",
        "أخرى": "oth"
    },
    "Somalia": {
        "صومالية": "so",
        "شمالية": "no",
        "جنوبية": "so",
        "أخرى": "oth"
    },
    "Mauritania": {
        "موريتانية": "mr",
        "حسانية": "ha",
        "أخرى": "oth"
    }
}

RECORDING_INSTRUCTIONS = """
<div dir="rtl" style="text-align: right">

### 🎙️ تعليمات التسجيل

1. **البيئة** 🌿  
   سجّل في مكان هادئ قدر الإمكان، وحاول تتجنّب الضوضاء أو أي أصوات في الخلفية.

2. **الميكروفون** 🎧  
   يفضّل استخدام مايك سماعة أو مايك خارجي، لأنه غالبًا أوضح بكثير من مايك اللابتوب.  
   في حال استخدام الجوال 📱، تأكّد من جودة التسجيل قبل المتابعة.

3. **طريقة التحدث** 🗣️  
   اقرأ الجملة بصوت واضح وطبيعي وبلهجتك.  
   لا تغيّر أو تستبدل أي كلمة أبدًا، إلا في اختلافات النطق الطبيعية مثل:  
   *"ثلاثة"* و*"تلاتة"* — وهذا عادي 👍  
   إذا ما حاب تسجّل جملة معيّنة أو واجهتك صعوبة في نطقها، اضغط **Skip** ⏭️.

4. **التعديل** ✏️  
   تقدر تعدّل الجملة قبل ما تبدأ التسجيل.

5. **الحفظ** 💾  
   بعد ما تسجّل، اضغط **Save & Next** عشان تحفظ تسجيلك.  
   لإعادة التسجيل، احذف التسجيل الحالي من واجهة الصوت باستخدام (✕) ❌،  
   أو اضغط **Skip** للانتقال للجملة اللي بعدها.

6. **المدة** ⏱️  
   حاول تسجّل عدد كافي من الجمل — كل تسجيل يفرق معنا ⭐  
   نفضّل يكون مجموع تسجيلاتك **على الأقل 30 دقيقة**، ونقدّر وقتك وجهدك كثير ✨

---

📧 **لأي مشكلة أو استفسار:**  
a.a.elghawas@gmail.com
</div>
"""

CONSENT_DETAILS = """
<section dir="rtl" lang="ar" style="text-align: right">
  <h1>الموافقة على جمع واستخدام البيانات</h1>
  <p>
    هذه الاتفاقية بين <strong>المشارك </strong> وفريق البحث من 
    <strong>جامعة الملك فهد للبترول والمعادن</strong> و<strong>جامعة طيبة</strong> 
    (والتي سنشير إليها فيما يلي بـ "الجامعتين").  
    الهدف من الاتفاقية هو جمع واستخدام وتوزيع تسجيلات صوتية لدعم أبحاث كشف الأصوات المزيفة (Deepfake) وغيرها من الأبحاث غير التجارية.
  </p>
  <ol>
    <li>
      <strong>هدف جمع البيانات:</strong><br>
      يقوم الفريق بجمع تسجيلات صوتية لإنشاء مجموعة بيانات (Dataset) خاصة بالكشف عن الأصوات المصنعة بالذكاء الاصطناعي 
      باستخدام تقنيات تحويل النص إلى صوت (TTS) أو تقليد الأصوات (Voice Conversion) وطرق أخرى.  
      ستُستخدم هذه البيانات في أبحاث علمية وأكاديمية لتطوير طرق أفضل لاكتشاف الأصوات المزيفة وغيرها من الأبحاث غير التجارية.
    </li>
    <li>
      <strong>طبيعة البيانات التي سيتم جمعها:</strong><br>
      يوافق المشارك على تقديم:  
      <ul>
        <li>تسجيلات صوتية بصوته الطبيعي أو من خلال نصوص/جمل يطلب منه قراءتها.</li>
        <li>بيانات اختيارية مثل: النوع (ذكر/أنثى)، الفئة العمرية، اللهجة، وغيرها.</li>
        <li>موافقة على إمكانية تعديل صوته أو تغييره باستخدام أساليب صناعية.</li>
      </ul>
    </li>
    <li>
      <strong>الحقوق الممنوحة:</strong><br>
      يمنح المشارك الفريق الحق الكامل (بدون مقابل مالي أو قيود) في:  
      <ul>
        <li>تسجيل ومعالجة واستخدام الصوت الطبيعي والنسخ المصنعة منه.</li>
        <li>توزيع مجموعة البيانات (الطبيعية والمصنعة) للباحثين في المجتمع العلمي لأغراض بحثية غير تجارية فقط.</li>
        <li>نشر عينات صوتية على منصات مهنية أو أكاديمية مثل LinkedIn، X/Twitter، YouTube لتعزيز الوعي بأبحاث الديب فيك أو للإعلان عن توفر البيانات.</li>
      </ul>
    </li>
    <li>
      <strong>إتاحة البيانات:</strong><br>
      سيتم نشر المجموعة الصوتية (الطبيعية والمصنعة) بترخيص مفتوح 
      <em>(Creative Commons Attribution 4.0)</em> 
      مما يسمح لأي باحث باستخدامها ومشاركتها لأغراض أكاديمية غير تجارية.
    </li>
    <li>
      <strong>الخصوصية والسرية:</strong><br>
      <ul>
        <li>لن يتم نشر اسم المشارك أو أي بيانات شخصية مباشرة إلا بموافقته المكتوبة.</li>
        <li>سيكون للمشارك معرف (ID) مجهول داخل مجموعة البيانات.</li>
      </ul>
    </li>
    <li>
      <strong>المشاركة والانضمام:</strong><br>
      <ul>
        <li>المشاركة اختيارية 100٪.</li>
        <li>للمشارك الحق في الانسحاب أو طلب حذف تسجيلاته قبل نشر مجموعة البيانات للعامة.</li>
        <li>بعد النشر العام، سحب البيانات لن يكون ممكنًا بسبب طريقة توزيعها.</li>
      </ul>
    </li>
    <li>
      <strong>التعويض:</strong><br>
      يدرك المشارك أن المشاركة لا تتضمن أي مقابل مادي، والمساهمة هنا لدعم وتطوير البحث العلمي فقط.
    </li>
  </ol>
</section>
"""

AGES = ["4–9", "10–14", "15–19", "20–24", "25–34", "35–44", "45–54", "55–64", "65–74", "75–84", "85+"]

GENDER = ["ذكر", "أنثى"]


def get_dialects_for_country(country: str):
    dialects = list(COUNTRY_DIALECTS.get(country, {}).keys())
    return dialects if dialects else ["أخرى"]


def split_dialect_code(dialect_code: str):
    dialect_code = (dialect_code or "").strip().lower() or "unk-gen"
    parts = dialect_code.split("-", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], "gen"


def get_fallback_dialect_code(user_dialect_code: str) -> str:
    country_code, _ = split_dialect_code(user_dialect_code)
    return f"{country_code}-oth"


def get_country_code_from_dialect_code(dialect_code: str) -> str:
    return split_dialect_code(dialect_code)[0] or "unk"


# ===============================
# SENTENCES (per-country, cached)
# ===============================

SENTENCES_CACHE = {}  # {country_code: [(id, text, [dialects]), ...]}


def get_sentences_file_for_country(country_code: str) -> Path:
    return BASE_DIR / f"sentences_{country_code}.json"


def load_sentences_for_country(country_code: str):
    if country_code in SENTENCES_CACHE:
        return SENTENCES_CACHE[country_code]

    path = get_sentences_file_for_country(country_code)
    if not path.exists():
        path.write_text(json.dumps({"sentences": []}, ensure_ascii=False, indent=2), encoding="utf-8")

    data = json.loads(path.read_text(encoding="utf-8"))
    raw_sentences = data.get("sentences", [])

    SENTENCES_CACHE[country_code] = [(s["unique_id"], s["text"], s.get("dialect", [])) for s in raw_sentences]
    return SENTENCES_CACHE[country_code]


def filter_sentences(dialect_code: str, completed_ids, allow_fallback: bool = True):
    completed_set = set(completed_ids or [])
    dialect_code = (dialect_code or "").strip().lower() or "unk-gen"
    country_code, _ = split_dialect_code(dialect_code)
    all_sentences = load_sentences_for_country(country_code)

    def _pick(dcode: str):
        return [(sid, text, dcode) for sid, text, dialects in all_sentences if sid not in completed_set and dcode in (dialects or [])]

    primary = _pick(dialect_code)
    if primary:
        return primary

    if allow_fallback:
        return _pick(get_fallback_dialect_code(dialect_code))

    return []


# ===============================
# AUTH / SUPABASE
# ===============================

def get_user_by_email(email: str):
    if not supabase:
        return None
    try:
        resp = supabase.table("users").select("*").eq("email", email.lower()).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        print("get_user_by_email error:", e)
        return None


def get_user_by_username(username: str):
    if not supabase:
        return None
    try:
        resp = supabase.table("users").select("*").eq("username", username).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        print("get_user_by_username error:", e)
        return None


def create_user(name: str, email: str, password: str, country: str, dialect_label: str, gender: str, age: str):
    if not supabase:
        return False, "Supabase not configured"

    email = email.lower()
    if get_user_by_email(email):
        return False, "Email already registered"

    base = name.strip().replace(" ", "_").lower() or "user"
    country_code = COUNTRY_CODES.get(country, "unk")
    dialect_map = COUNTRY_DIALECTS.get(country, {})
    dialect_code_raw = dialect_map.get(dialect_label, "oth")
    dialect_code = f"{country_code}-{dialect_code_raw}"

    username = f"{base}_{uuid.uuid4().hex[:7]}_{dialect_code}_{'m' if gender == 'ذكر' else 'f'}"

    hashed_pw = generate_password_hash(password)
    payload = {
        "username": username,
        "name": name,
        "email": email,
        "password": hashed_pw,
        "country": country,
        "dialect_code": dialect_code,
        "gender": gender,
        "age": age,
        "created_at": datetime.utcnow().isoformat(),
    }

    try:
        resp = supabase.table("users").insert(payload).execute()
        if resp.data:
            supabase.table("sessions").insert({
                "username": username,
                "completed_sentences": [],
                "total_recording_duration": 0.0,
                "updated_at": datetime.utcnow().isoformat(),
            }).execute()
            return True, username
        return False, "Failed to insert user"
    except Exception as e:
        print("create_user error:", e)
        return False, f"Registration failed: {e}"


def authenticate(email: str, password: str):
    if not supabase:
        return False, "Supabase not configured"

    user = get_user_by_email(email)
    if not user or not check_password_hash(user.get("password", ""), password):
        return False, "Invalid email or password"
    return True, user["username"]


def load_session(username: str):
    if not supabase:
        return {"completed_sentences": [], "total_recording_duration": 0.0}
    try:
        resp = supabase.table("sessions").select("*").eq("username", username).execute()
        if resp.data:
            row = resp.data[0]
            return {
                "completed_sentences": row.get("completed_sentences", []) or [],
                "total_recording_duration": float(row.get("total_recording_duration", 0.0) or 0.0),
            }
    except Exception as e:
        print("load_session error:", e)
    return {"completed_sentences": [], "total_recording_duration": 0.0}


def save_session(username: str, completed_sentences, total_duration: float):
    if not supabase:
        return
    try:
        supabase.table("sessions").upsert({
            "username": username,
            "completed_sentences": completed_sentences,
            "total_recording_duration": total_duration,
            "updated_at": datetime.utcnow().isoformat(),
        }).execute()
    except Exception as e:
        print("save_session error:", e)


# ===============================
# STORAGE / AUDIO
# ===============================

def ensure_user_dirs(username: str, dialect_code: str):
    country_code, dialect = split_dialect_code(dialect_code)
    user_dir = USERS_ROOT / country_code / dialect / username
    (user_dir / "wavs").mkdir(parents=True, exist_ok=True)
    (user_dir / "txt").mkdir(parents=True, exist_ok=True)
    return user_dir


def validate_audio(audio_path: str):
    try:
        with sf.SoundFile(audio_path) as f:
            duration = len(f) / f.samplerate
            if f.samplerate < 16000:
                return False, f"Sample rate too low: {f.samplerate} Hz", duration
            if duration < 1.0:
                return False, "Recording too short", duration
            return True, "OK", duration
    except Exception as e:
        return False, f"Audio error: {e}", None


def upload_file_to_s3(local_path: Path, s3_key: str):
    if not S3_CLIENT or not S3_BUCKET:
        print("S3 not configured, skipping upload:", s3_key)
        return False
    try:
        S3_CLIENT.upload_file(str(local_path), S3_BUCKET, s3_key)
        return True
    except Exception as e:
        print("upload_file_to_s3 error:", e)
        return False


def download_s3_text_if_exists(s3_key: str) -> str | None:
    if not S3_CLIENT or not S3_BUCKET:
        return None
    try:
        obj = S3_CLIENT.get_object(Bucket=S3_BUCKET, Key=s3_key)
        return obj["Body"].read().decode("utf-8", errors="replace")
    except Exception:
        return None


def append_row_to_s3_metadata(s3_key: str, row_line: str):
    header = "audio_file|text\n"
    existing = download_s3_text_if_exists(s3_key)

    row_line = (row_line or "").strip()
    if not row_line:
        return

    if not existing or not existing.strip():
        merged = header + row_line + "\n"
    else:
        lines = existing.splitlines()
        has_header = len(lines) > 0 and lines[0].strip() == header.strip()
        rows = lines[1:] if has_header else lines

        existing_set = {r.strip() for r in rows if r.strip()}
        if row_line not in existing_set:
            merged_rows = [r.strip() for r in rows if r.strip()] + [row_line]
            merged = header + "\n".join(merged_rows) + "\n"
        else:
            merged = existing if existing.endswith("\n") else existing + "\n"

    tmp_path = Path("/tmp") / f"metadata_{uuid.uuid4().hex}.csv"
    tmp_path.write_text(merged, encoding="utf-8")
    upload_file_to_s3(tmp_path, s3_key)
    try:
        tmp_path.unlink()
    except Exception:
        pass


def save_recording_and_upload(username: str, active_dialect_code: str, user_dialect_code: str,
                              sentence_id: str, sentence_text: str, audio_path: str):
    user_dir = ensure_user_dirs(username, active_dialect_code)
    wav_dir = user_dir / "wavs"

    country_code, active_dialect = split_dialect_code(active_dialect_code)
    _, user_dialect = split_dialect_code(user_dialect_code)

    meta_filename = "metadata.csv" if active_dialect == user_dialect else f"metadata_{active_dialect}.csv"
    meta_file = user_dir / meta_filename

    filename = f"{username}_{sentence_id}.wav"
    dest = wav_dir / filename
    Path(audio_path).replace(dest)

    try:
        with sf.SoundFile(dest) as f:
            duration = len(f) / f.samplerate
    except Exception:
        duration = 0.0

    row_line = f"{filename}|{sentence_text.strip()}"

    meta_file.parent.mkdir(parents=True, exist_ok=True)
    needs_header = (not meta_file.exists()) or (meta_file.stat().st_size == 0)
    with meta_file.open("a", encoding="utf-8") as f:
        if needs_header:
            f.write("audio_file|text\n")
        f.write(row_line + "\n")

    base_prefix = f"{country_code}/{username}"
    upload_file_to_s3(dest, f"{base_prefix}/wavs/{filename}")

    s3_meta_key = f"{base_prefix}/{meta_filename}"
    append_row_to_s3_metadata(s3_meta_key, row_line)

    return duration


# ===============================
# PROGRESS UI
# ===============================

def make_progress_bar(current_seconds: float, target_seconds: float, bar_length: int = 24) -> str:
    if target_seconds <= 0:
        bar = "░" * bar_length
        return f"[{bar}] 0.0%"

    ratio = max(0.0, min(1.0, current_seconds / target_seconds))
    filled = int(bar_length * ratio)
    bar = "█" * filled + "░" * (bar_length - filled)
    return f"[{bar}] {ratio * 100:.1f}%"


def compute_progress(completed_count: int, total_duration: float):
    bar = make_progress_bar(total_duration, RECORDING_TARGET_SECONDS)
    mins = int(total_duration // 60)
    secs = int(total_duration % 60)
    target_mins = int(RECORDING_TARGET_SECONDS // 60)
    return f"{bar}\n{mins}m {secs:02d}s / {target_mins}m target • {completed_count} sentences"


# ===============================
# LEADERBOARD (LIFETIME, PER-COUNTRY, ANON, ARABIC ALIASES)
# ===============================

LEADERBOARD_ENABLED = True
LEADERBOARD_TOP_N = 8
LEADERBOARD_MIN_SECONDS_TO_SHOW = 60  # 1 minute minimum to appear

AR_ADJECTIVES = [
    "صامت", "هادئ", "واضح", "عميق", "نقي", "ثابت", "سريع", "ذكي",
    "رنان", "دافئ", "قوي", "خفيف", "موزون", "سلس", "مشرق", "راقي",
    "متقن", "ثري", "مرن", "نادر"
]
AR_NOUNS = [
    "الصوت", "الصدى", "النبرة", "الموجة", "الوتر", "الإيقاع",
    "الهمس", "الرنين", "المدى", "النبض", "اللحن", "الأثر", "الانسجام"
]
AR_EMOJIS = ["🎙️", "🦅", "🐪", "🦉", "🎧", "🌙", "✨", "🛡️", "🌵", "⭐"]


def _stable_int_hash(s: str, mod: int) -> int:
    if mod <= 0:
        return 0
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return int(h[:12], 16) % mod


def build_arabic_alias(seed: str) -> tuple[str, str]:
    emoji = AR_EMOJIS[_stable_int_hash(seed + "|emo", len(AR_EMOJIS))]
    noun = AR_NOUNS[_stable_int_hash(seed + "|noun", len(AR_NOUNS))]
    adj = AR_ADJECTIVES[_stable_int_hash(seed + "|adj", len(AR_ADJECTIVES))]
    num = _stable_int_hash(seed + "|num", 90) + 10
    return emoji, f"{noun}-{adj}-{num}"


def get_or_create_lifetime_alias_country(username: str, country_code: str) -> dict | None:
    if not supabase or not LEADERBOARD_ENABLED:
        return None
    country_code = (country_code or "unk").lower()

    try:
        resp = (
            supabase.table("leaderboard_aliases_country_lifetime")
            .select("*")
            .eq("username", username)
            .eq("country_code", country_code)
            .execute()
        )
        if resp.data:
            return resp.data[0]

        seed = f"{username}|{country_code}|lifetime_leaderboard_ar"
        emoji, alias = build_arabic_alias(seed)

        ins = (
            supabase.table("leaderboard_aliases_country_lifetime")
            .insert({
                "username": username,
                "country_code": country_code,
                "emoji": emoji,
                "alias": alias,
                "created_at": datetime.utcnow().isoformat(),
            })
            .execute()
        )
        return ins.data[0] if ins.data else {"username": username, "country_code": country_code, "emoji": emoji, "alias": alias}
    except Exception as e:
        print("get_or_create_lifetime_alias_country error:", e)
        return None


def upsert_lifetime_leaderboard_entry_country(username: str, user_dialect_code: str):
    if not supabase or not LEADERBOARD_ENABLED:
        return

    try:
        country_code = get_country_code_from_dialect_code(user_dialect_code)
        alias_row = get_or_create_lifetime_alias_country(username, country_code)
        if not alias_row:
            return

        sess = load_session(username)
        total_seconds = float(sess.get("total_recording_duration", 0.0) or 0.0)
        if total_seconds < LEADERBOARD_MIN_SECONDS_TO_SHOW:
            return

        payload = {
            "country_code": country_code,
            "username": username,
            "emoji": alias_row.get("emoji", "🎙️"),
            "alias": alias_row.get("alias", "الصوت-النقي-10"),
            "time_seconds": total_seconds,
            "sentences": int(len(sess.get("completed_sentences", []) or [])),
            "updated_at": datetime.utcnow().isoformat(),
        }

        supabase.table("leaderboard_lifetime_country").upsert(
            payload, on_conflict="country_code,username"
        ).execute()

    except Exception as e:
        print("upsert_lifetime_leaderboard_entry_country error:", e)


def _fmt_mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m = seconds // 60
    s = seconds % 60
    return f"{m}m {s:02d}s"


def fetch_top_lifetime_country(country_code: str, limit: int = 8) -> list[dict]:
    if not supabase or not LEADERBOARD_ENABLED:
        return []
    country_code = (country_code or "unk").lower()
    try:
        resp = (
            supabase.table("leaderboard_lifetime_country")
            .select("username,emoji,alias,time_seconds,sentences")
            .eq("country_code", country_code)
            .order("time_seconds", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print("fetch_top_lifetime_country error:", e)
        return []


def fetch_user_row_country(country_code: str, username: str) -> dict | None:
    if not supabase:
        return None
    try:
        resp = (
            supabase.table("leaderboard_lifetime_country")
            .select("username,emoji,alias,time_seconds,sentences")
            .eq("country_code", country_code)
            .eq("username", username)
            .limit(1)
            .execute()
        )
        return (resp.data or [None])[0]
    except Exception as e:
        print("fetch_user_row_country error:", e)
        return None


def get_user_rank_country(country_code: str, username: str) -> int | None:
    if not supabase:
        return None
    try:
        me = (
            supabase.table("leaderboard_lifetime_country")
            .select("time_seconds")
            .eq("country_code", country_code)
            .eq("username", username)
            .limit(1)
            .execute()
        ).data
        if not me:
            return None

        my_seconds = float(me[0].get("time_seconds", 0) or 0)

        higher = (
            supabase.table("leaderboard_lifetime_country")
            .select("id", count="exact")
            .eq("country_code", country_code)
            .gt("time_seconds", my_seconds)
            .execute()
        )
        higher_count = int(getattr(higher, "count", None) or 0)
        return higher_count + 1
    except Exception as e:
        print("get_user_rank_country error:", e)
        return None

APP_CSS = """
<style>
  :root{
    --card-bg: rgba(255,255,255,0.78);
    --card-border: rgba(15,23,42,0.12);
    --muted: rgba(15,23,42,0.72);
    --muted2: rgba(15,23,42,0.56);
    --accent: rgba(15,23,42,0.06);

    --shadow-sm: 0 1px 2px rgba(2,6,23,0.06);
    --shadow-md: 0 8px 24px rgba(2,6,23,0.10);
    --shadow-lg: 0 14px 44px rgba(2,6,23,0.14);
  }

  /* Dark mode friendliness */
  @media (prefers-color-scheme: dark){
    :root{
      --card-bg: rgba(255,255,255,0.04);
      --card-border: rgba(255,255,255,0.10);
      --muted: rgba(255,255,255,0.72);
      --muted2: rgba(255,255,255,0.55);
      --accent: rgba(255,255,255,0.10);

      --shadow-sm: 0 1px 2px rgba(0,0,0,0.22);
      --shadow-md: 0 10px 30px rgba(0,0,0,0.28);
      --shadow-lg: 0 18px 60px rgba(0,0,0,0.34);
    }
  }

  /* ============================
     Gradio layout fixes (mobile)
     ============================ */

  /* Stop "centered narrow app" on phones */
  .gradio-container,
  .gradio-container .main,
  .gradio-container .wrap,
  .gradio-container .contain{
    max-width: 100% !important;
    width: 100% !important;
  }

  /* Use screen width */
  .gradio-container .contain{
    padding-left: 12px !important;
    padding-right: 12px !important;
  }

  /* Prevent dropdown/autofill/popovers being clipped by overflow hidden/auto */
  .gradio-container,
  .gradio-container .main,
  .gradio-container .wrap,
  .gradio-container .contain{
    overflow: visible !important;
  }

  /* Ensure Gradio children can shrink instead of "vertical letters" */
  .gradio-container *{
    min-width: 0;
  }

  /* Your app wrapper */
  .app-shell{
    max-width: 980px;
    margin: 0 auto;
    padding: 10px;
  }

  .hero{
    border: 1px solid var(--card-border);
    border-radius: 18px;
    padding: 18px 18px;
    background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(255,255,255,0.70));
    box-shadow: var(--shadow-md);
    backdrop-filter: blur(10px);
  }
  @media (prefers-color-scheme: dark){
    .hero{
      background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
      box-shadow: var(--shadow-sm);
    }
  }

  .hero h1{ margin: 0; font-size: 22px; font-weight: 900; }
  .hero p{ margin: 8px 0 0 0; color: var(--muted); line-height: 1.6; }

  .grid-2{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
  }
  @media (max-width: 920px){
    .grid-2{ grid-template-columns: 1fr; }
  }

  .card{
    border: 1px solid var(--card-border);
    border-radius: 16px;
    background: var(--card-bg);
    padding: 14px;
    box-shadow: var(--shadow-sm);
  }
  .card h3{
    margin: 0 0 10px 0;
    font-size: 16px;
    font-weight: 900;
  }

  .hint{
    color: var(--muted2);
    font-size: 12px;
    margin-top: 8px;
    line-height: 1.5;
  }

  .status-ok, .status-warn, .status-bad{
    border-radius: 14px;
    padding: 10px 12px;
    box-shadow: var(--shadow-sm);
  }
  .status-ok{
    border: 1px solid rgba(16,185,129,0.30);
    background: rgba(16,185,129,0.10);
  }
  .status-warn{
    border: 1px solid rgba(245,158,11,0.30);
    background: rgba(245,158,11,0.10);
  }
  .status-bad{
    border: 1px solid rgba(239,68,68,0.30);
    background: rgba(239,68,68,0.10);
  }

  .topbar{
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .chip{
    display:inline-flex;
    align-items:center;
    gap: 8px;
    padding: 7px 11px;
    border-radius: 999px;
    border: 1px solid var(--card-border);
    background: rgba(255,255,255,0.70);
    box-shadow: var(--shadow-sm);
    color: rgba(15,23,42,0.88);
    font-size: 12px;
    font-weight: 800;
  }
  @media (prefers-color-scheme: dark){
    .chip{
      background: rgba(255,255,255,0.05);
      color: rgba(255,255,255,0.88);
    }
  }

  .mono{
    font-variant-numeric: tabular-nums;
    white-space: pre-line;
  }
  .rtl{ direction: rtl; text-align: right; }

  /* RTL accordion header alignment + arrow direction */
  .rtl .gr-accordion .label-wrap,
  .rtl .gr-accordion .label-wrap > div{
    direction: rtl !important;
    text-align: right !important;
    justify-content: space-between !important;
  }
  .rtl .gr-accordion .label-wrap svg{
    transform: scaleX(-1);
  }

  /* ============================
     Mobile tightening
     ============================ */
  @media (max-width: 640px){
    .gradio-container .contain{
      padding-left: 8px !important;
      padding-right: 8px !important;
    }

    .app-shell{ padding: 8px; }

    .hero{
      padding: 14px;
      border-radius: 16px;
      backdrop-filter: none !important; /* avoids stacking bugs on some mobile browsers */
    }
    .hero h1{ font-size: 18px; }

    .card{
      padding: 12px;
      border-radius: 14px;
    }
    .card h3{ font-size: 15px; }
    .hint{ font-size: 11.5px; }

    /* Force rows to stack instead of squeezing */
    .gradio-container .gr-row{
      flex-wrap: wrap !important;
      gap: 10px !important;
    }
    .gradio-container .gr-row > *{
      flex: 1 1 100% !important;
    }

    /* Make buttons & controls easier to tap */
    .gradio-container button,
    .gradio-container .gr-button{
      width: 100% !important;
    }

    .gradio-container input,
    .gradio-container textarea,
    .gradio-container select{
      font-size: 14px !important;
    }
  }
</style>
"""


LEADERBOARD_CSS = """
<style>
  .lb-wrap{
    border: 1px solid rgba(15,23,42,0.12);
    border-radius: 14px;
    padding: 14px;
    background: rgba(255,255,255,0.72);
    box-shadow: 0 10px 28px rgba(2,6,23,0.10);
  }
  @media (prefers-color-scheme: dark){
    .lb-wrap{
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(255,255,255,0.03);
      box-shadow: 0 10px 30px rgba(0,0,0,0.30);
    }
  }

  .lb-header{
    display:flex;
    align-items:flex-start;
    justify-content:space-between;
    margin-bottom: 10px;
    gap: 10px;
    flex-wrap: wrap;
  }
  .lb-title{
    font-size: 16px;
    font-weight: 900;
  }
  .lb-sub{
    font-size: 12px;
    opacity: 0.75;
    white-space: nowrap;
  }

  .lb-colhdr{
    display:grid;
    grid-template-columns: 44px 1fr 110px 110px;
    gap: 10px;
    padding: 8px 10px;
    font-size: 12px;
    opacity: 0.70;
    border-radius: 10px;
    background: rgba(15,23,42,0.04);
    margin-bottom: 6px;
  }
  @media (prefers-color-scheme: dark){
    .lb-colhdr{ background: rgba(255,255,255,0.05); }
  }

  .lb-row{
    display:grid;
    grid-template-columns: 44px 1fr 110px 110px;
    gap: 10px;
    padding: 10px 10px;
    align-items:center;
    border-top: 1px solid rgba(15,23,42,0.08);
    border-radius: 10px;
  }
  @media (prefers-color-scheme: dark){
    .lb-row{ border-top: 1px solid rgba(255,255,255,0.08); }
  }

  .lb-row:first-child{ border-top:none; }

  .lb-rank{
    width: 34px;
    height: 34px;
    border-radius: 10px;
    display:flex;
    align-items:center;
    justify-content:center;
    font-weight: 900;
    background: rgba(15,23,42,0.06);
  }
  @media (prefers-color-scheme: dark){
    .lb-rank{ background: rgba(255,255,255,0.06); }
  }

  .lb-name{
    display:flex;
    align-items:center;
    gap: 8px;
    font-weight: 900;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0 !important;
  }

  .lb-meta{
    text-align:right;
    font-variant-numeric: tabular-nums;
    opacity: 0.95;
    font-weight: 800;
    white-space: nowrap;
  }

  .lb-highlight{
    background: rgba(15,23,42,0.04);
    border: 1px solid rgba(15,23,42,0.10);
  }
  @media (prefers-color-scheme: dark){
    .lb-highlight{
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.12);
    }
  }

  .lb-badge{
    padding: 2px 8px;
    border-radius: 999px;
    background: rgba(15,23,42,0.08);
    font-weight: 900;
    font-size: 12px;
    white-space: nowrap;
  }
  @media (prefers-color-scheme: dark){
    .lb-badge{ background: rgba(255,255,255,0.08); }
  }

  .lb-you{
    font-size: 12px;
    opacity: 0.85;
    margin-top: 10px;
    display:flex;
    justify-content:space-between;
    gap: 10px;
    flex-wrap: wrap;
  }

  /* ============================
     Mobile leaderboard: stacked rows
     ============================ */
  @media (max-width: 640px){
    .lb-sub{ white-space: normal !important; }
    .lb-colhdr{ display:none !important; }

    .lb-row{
      grid-template-columns: 44px 1fr;
      grid-template-rows: auto auto;
      row-gap: 6px;
    }

    /* rank stays left, name top-right */
    .lb-rank{ grid-row: 1 / span 2; }

    /* Put time+sentences on row 2 */
    .lb-row .lb-meta:nth-of-type(1){
      grid-column: 2;
      grid-row: 2;
      justify-self: start;
      opacity: 0.90;
    }
    .lb-row .lb-meta:nth-of-type(2){
      grid-column: 2;
      grid-row: 2;
      justify-self: end;
      opacity: 0.90;
    }
  }
</style>
"""


def render_leaderboard_html_country(country_code: str, current_username: str | None) -> str:
    country_code = (country_code or "unk").lower()
    flag = COUNTRY_EMOJIS.get(country_code, "🏳️")
    top = fetch_top_lifetime_country(country_code, limit=LEADERBOARD_TOP_N)

    title = f"🏆 لوحة الشرف — {flag} {country_code.upper()} <span class='lb-sub'>(مدى الحياة)</span>"

    html = [LEADERBOARD_CSS, "<div class='lb-wrap rtl'>"]
    html.append(
        "<div class='lb-header'>"
        f"<div class='lb-title'>{title}</div>"
        "<div class='lb-sub'>🔒 مجهولة بالكامل</div>"
        "</div>"
    )
    html.append(
        "<div class='lb-colhdr'>"
        "<div>#</div><div>المشارك</div>"
        "<div style='text-align:right;'>الوقت</div>"
        "<div style='text-align:right;'>الجمل</div>"
        "</div>"
    )

    if not top:
        html.append(
            "<div class='lb-row'>"
            "<div class='lb-rank'>—</div>"
            "<div class='lb-name'>لا يوجد بيانات كافية بعد… كن أول بطل 🎙️✨</div>"
            "<div class='lb-meta'></div><div class='lb-meta'></div>"
            "</div>"
        )
    else:
        for idx, r in enumerate(top, start=1):
            is_me = (current_username is not None) and (r.get("username") == current_username)
            row_cls = "lb-row lb-highlight" if is_me else "lb-row"
            emoji = r.get("emoji", "🎙️")
            alias = r.get("alias", "الصوت-النقي-10")
            t = _fmt_mmss(r.get("time_seconds", 0))
            s = int(r.get("sentences", 0) or 0)
            html.append(
                f"<div class='{row_cls}'>"
                f"<div class='lb-rank'>{idx}</div>"
                f"<div class='lb-name'>{emoji} <span title='{alias}'>{alias}</span>"
                f"{' <span class=\"lb-badge\">أنت</span>' if is_me else ''}"
                f"</div>"
                f"<div class='lb-meta'>{t}</div>"
                f"<div class='lb-meta'>{s}</div>"
                f"</div>"
            )

    if current_username:
        my_rank = get_user_rank_country(country_code, current_username)
        my_row = fetch_user_row_country(country_code, current_username)
        if my_rank and my_row:
            my_t = _fmt_mmss(my_row.get("time_seconds", 0))
            my_s = int(my_row.get("sentences", 0) or 0)
            my_alias = my_row.get("alias", "—")
            my_emo = my_row.get("emoji", "🎙️")
            html.append(
                "<div class='lb-you'>"
                f"<div>🔎 ترتيبك الحالي: <b>#{my_rank}</b> — {my_emo} <b>{my_alias}</b></div>"
                f"<div><span class='lb-badge'>{my_t}</span> <span class='lb-badge'>📝 {my_s}</span></div>"
                "</div>"
            )

    html.append("</div>")
    return "".join(html)


# ===============================
# PROFESSIONAL APP UI
# ===============================

def build_app():
    with gr.Blocks(title="Arabic Speech Recorder", css="") as demo:
        # Inject CSS once
        gr.HTML(APP_CSS)

        state = gr.State({
            "logged_in": False,
            "username": None,
            "user_dialect_code": None,
            "active_dialect_code": None,
            "dialect_code": None,  # backward compat
            "completed_sentences": [],
            "total_duration": 0.0,
            "current_sentence_id": "",
            "current_sentence_text": "",
            "last_temp_audio_path": "",
        })

        gr.HTML("""
        <div class="app-shell">
          <div class="hero rtl">
            <h1>🗣️ مسجّل مجموعة البيانات الصوتية العربية</h1>
            <p>
              منصة لجمع تسجيلات من اللهجات العربية لدعم أبحاث كشف الأصوات المزيفة وتقنيات الذكاء الاصطناعي الصوتية.
            </p>
          </div>
        </div>
        """)

        # Views
        with gr.Column(visible=True) as login_view:
            gr.HTML('<div class="app-shell"><div class="grid-2">')

            with gr.Column():
                gr.HTML('<div class="card rtl"><h3>تسجيل الدخول</h3>')
                login_email = gr.Textbox(label="Email", placeholder="name@example.com")
                login_pw = gr.Textbox(label="Password", type="password", placeholder="••••••••")
                login_btn = gr.Button("تسجيل الدخول", variant="primary")
                login_msg = gr.HTML("")
                goto_register_btn = gr.Button("إنشاء حساب جديد")
                gr.HTML('</div>')

            with gr.Column():
                gr.HTML('<div class="card rtl"><h3>عن التسجيل</h3>')
                gr.Markdown("""
- 🎯 هدفنا: **30 دقيقة** تقريبًا لكل مشارك  
- ✅ التسجيلات الجيدة ترفع جودة البحث  
- 🔒 بياناتك: **مجهولة** داخل مجموعة البيانات  
""")
                gr.HTML('<div class="hint">نصيحة: جرّب تسجيل 1–2 جملة ثم استمع لها قبل الإكمال.</div>')
                gr.HTML('</div>')

            gr.HTML('</div></div>')

        with gr.Column(visible=False) as register_view:
            gr.HTML('<div class="app-shell"><div class="card rtl"><h3>إنشاء حساب جديد</h3>')
            reg_name = gr.Textbox(label="Name (Latin)", placeholder="e.g., Ahmed Ali")
            reg_email = gr.Textbox(label="Email", placeholder="name@example.com")
            reg_pw = gr.Textbox(label="Password", type="password", placeholder="Create a password")
            reg_country = gr.Dropdown(choices=AVAILABLE_COUNTRIES, value="Saudi Arabia", label="Country")
            reg_dialect = gr.Dropdown(choices=get_dialects_for_country("Saudi Arabia"), value=None, label="Dialect")
            reg_gender = gr.Dropdown(choices=GENDER, value=None, label="Gender")
            reg_age = gr.Dropdown(choices=AGES, value=None, label="Age Group")

            with gr.Accordion("إتفاقية التسجيل واستخدام البيانات", open=False):
                gr.Markdown(CONSENT_DETAILS)

            reg_btn = gr.Button("إنشاء الحساب", variant="primary")
            reg_msg = gr.HTML("")
            back_to_login_btn = gr.Button("الرجوع لتسجيل الدخول")
            gr.HTML('</div></div>')

        with gr.Column(visible=False) as main_view:
            gr.HTML('<div class="app-shell">')

            # Topbar
            with gr.Row():
                info = gr.HTML("")
                logout_btn = gr.Button("تسجيل الخروج")

            # Stats card
            gr.HTML('<div class="grid-2">')
            with gr.Column():
                gr.HTML('<div class="card rtl"><h3>تعليمات سريعة</h3>')
                with gr.Accordion("تعليمات مهمة للتسجيل", open=False):
                    gr.Markdown(RECORDING_INSTRUCTIONS)
                gr.HTML('</div>')

            with gr.Column():
                gr.HTML('<div class="card rtl"><h3>حالة المشاركة</h3>')
                progress_box = gr.Textbox(label="📊 الإنجاز", interactive=False, elem_classes=["mono"])
                gr.HTML('<div class="hint">الإنجاز يعتمد على <b>مدة التسجيل</b> وليس عدد الجمل فقط.</div>')
                gr.HTML('</div>')
                # Leaderboard (collapsed, non-disruptive)
                with gr.Accordion("🏆 لوحة الشرف (مجهولة) — بلدك", open=False):
                    with gr.Row():
                        lb_refresh_btn = gr.Button("🔄 تحديث", size="sm")
                        lb_hint = gr.HTML('<div style="opacity:0.65;font-size:12px;direction:rtl;text-align:right;">'
                                        'لن يؤثر على التسجيل — مجرد تحديث للعرض</div>')
                    leaderboard_html = gr.HTML("")
            gr.HTML('</div>')  # grid


            # Recording card
            gr.HTML('<div class="card rtl"><h3>التسجيل</h3>')
            username_box = gr.Textbox(label="👤 Username", interactive=False, visible=False)
            sentence_box = gr.Textbox(label="✍️ الجملة (يمكنك تعديلها)", interactive=True, lines=3)
            sentence_id_box = gr.Textbox(label="Sentence ID", interactive=False, visible=False)

            audio_rec = gr.Audio(
                sources=["microphone"],
                type="filepath",
                label="🎙️ Record",
                format="wav",
            )
            temp_audio_path = gr.Textbox(label="Temp audio path", visible=False)

            with gr.Row():
                save_btn = gr.Button("Save & Next", variant="primary", interactive=False)
                skip_btn = gr.Button("Skip", variant="secondary")
            msg_box = gr.HTML("")
            gr.HTML('</div>')  # card

            gr.HTML("</div>")  # app-shell
            
        def refresh_leaderboard(st):
            """
            Re-render leaderboard for current user's country.
            Optionally upserts ONLY this user's latest totals (fast + accurate).
            """
            if not st.get("logged_in") or not st.get("username"):
                return ""

            username = st["username"]
            user_dialect = st.get("user_dialect_code") or st.get("dialect_code") or "unk-gen"
            country_code = get_country_code_from_dialect_code(user_dialect)

            # Optional but recommended: update ONLY current user row so their numbers are accurate
            # (this is NOT "update on each save"; it's only when user clicks refresh)
            upsert_lifetime_leaderboard_entry_country(username, user_dialect)

            return render_leaderboard_html_country(country_code, username)

        # ---------- Navigation helpers ----------
        def show_register():
            return gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)

        def show_login():
            return gr.update(visible=True), gr.update(visible=False), gr.update(visible=False)

        def show_main()
            return gr.update(visible=False), gr.update(visible=False), gr.update(visible=True)

        goto_register_btn.click(show_register, inputs=[], outputs=[login_view, register_view, main_view])
        back_to_login_btn.click(show_login, inputs=[], outputs=[login_view, register_view, main_view])

        # ---------- Register callbacks ----------
        def update_dialects(country):
            dialects = get_dialects_for_country(country)
            return gr.update(choices=dialects, value=None)

        reg_country.change(update_dialects, inputs=reg_country, outputs=reg_dialect)

        def do_register(name, email, pw, country, dialect_label, gender, age, st):
            if not all([name, email, pw, country, dialect_label, gender, age]):
                return st, '<div class="status-warn rtl">❌ الرجاء تعبئة جميع الحقول</div>', *show_register()

            ok, result = create_user(name, email, pw, country, dialect_label, gender, age)
            if not ok:
                return st, f'<div class="status-bad rtl">❌ {result}</div>', *show_register()

            return st, '<div class="status-ok rtl">✅ تم إنشاء الحساب. يمكنك تسجيل الدخول الآن.</div>', *show_login()

        reg_btn.click(
            do_register,
            inputs=[reg_name, reg_email, reg_pw, reg_country, reg_dialect, reg_gender, reg_age, state],
            outputs=[state, reg_msg, login_view, register_view, main_view],
        )

        # ---------- Audio recording interactions ----------
        def on_start_recording():
            # Disable Save/Skip while recording (clean UX)
            return gr.update(interactive=False), gr.update(interactive=False), ""

        audio_rec.start_recording(fn=on_start_recording, outputs=[save_btn, skip_btn, msg_box])

        def on_stop_recording(audio_path, st):
            if not audio_path:
                return st, "", gr.update(value=None), gr.update(interactive=True), gr.update(interactive=True)

            st["last_temp_audio_path"] = audio_path
            time.sleep(0.2)
            return st, audio_path, gr.update(value=audio_path), gr.update(interactive=True), gr.update(interactive=True)

        audio_rec.stop_recording(
            fn=on_stop_recording,
            inputs=[audio_rec, state],
            outputs=[state, temp_audio_path, audio_rec, save_btn, skip_btn],
        )

        audio_rec.clear(fn=lambda: gr.update(interactive=False), outputs=[save_btn])

        # ---------- Login ----------
        def _status(kind: str, text: str) -> str:
            cls = {"ok": "status-ok", "warn": "status-warn", "bad": "status-bad"}.get(kind, "status-warn")
            return f'<div class="{cls} rtl">{text}</div>'

        def next_sentence_for_state(st):
            user_dialect = st.get("user_dialect_code") or st.get("dialect_code")
            available = filter_sentences(user_dialect, st["completed_sentences"], allow_fallback=True)
            if not available:
                st["current_sentence_id"] = ""
                st["current_sentence_text"] = "No more sentences."
                st["active_dialect_code"] = user_dialect
            else:
                sid, text, used_dialect = random.choice(available)
                st["current_sentence_id"] = sid
                st["current_sentence_text"] = text
                st["active_dialect_code"] = used_dialect

        def do_login(email, pw, st):
            ok, result = authenticate(email, pw)
            if not ok:
                return (
                    st,
                    _status("bad", f"❌ {result}"),
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    gr.update(visible=True),
                    gr.update(visible=False),
                    gr.update(visible=False),
                )

            username = result
            user = get_user_by_username(username)
            user_dialect_code = user.get("dialect_code", "sa-hj") if user else "sa-hj"

            sess = load_session(username)
            completed = sess["completed_sentences"]
            total_dur = sess["total_recording_duration"]

            available = filter_sentences(user_dialect_code, completed, allow_fallback=True)
            if not available:
                sentence_id = ""
                sentence_text = "No more sentences for your dialect (including general)."
                active_dialect_code = user_dialect_code
            else:
                sentence_id, sentence_text, active_dialect_code = random.choice(available)

            st.update({
                "logged_in": True,
                "username": username,
                "user_dialect_code": user_dialect_code,
                "active_dialect_code": active_dialect_code,
                "dialect_code": user_dialect_code,
                "completed_sentences": completed,
                "total_duration": total_dur,
                "current_sentence_id": sentence_id,
                "current_sentence_text": sentence_text,
            })

            country_code = get_country_code_from_dialect_code(user_dialect_code)
            flag = COUNTRY_EMOJIS.get(country_code, "")
            username_show = " ".join(username.split("_")[:-3]).title() or "User"
            info_text = f'<div class="chip rtl">👤 <b>{username_show}</b> &nbsp; {flag} {country_code.upper()}</div>'

            progress = compute_progress(len(completed), total_dur)

            # ✅ leaderboard update & render (non-disruptive: only on login)
            upsert_lifetime_leaderboard_entry_country(username, user_dialect_code)
            lb_html = render_leaderboard_html_country(country_code, username)

            return (
                st,
                _status("ok", "✅ تم تسجيل الدخول بنجاح"),
                info_text,
                username,
                progress,
                lb_html,
                sentence_text,
                sentence_id,
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=True),
            )

        login_btn.click(
            do_login,
            inputs=[login_email, login_pw, state],
            outputs=[
                state,
                login_msg,
                info,
                username_box,
                progress_box,
                leaderboard_html,
                sentence_box,
                sentence_id_box,
                login_view,
                register_view,
                main_view,
            ],
        )

        # ---------- Save / Skip ----------
        def disable_skip():
            return gr.update(interactive=False)

        def disable_save():
            return gr.update(interactive=False)

        def handle_save(audio_path, edited_sentence, temp_path, st):
            if not st.get("logged_in"):
                progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
                return st, _status("warn", "الرجاء تسجيل الدخول أولاً."), st["current_sentence_text"], st["current_sentence_id"], progress, "", gr.update(value=None), gr.update(interactive=True)

            if not audio_path and not temp_path:
                progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
                return st, _status("warn", "⚠️ سجّل الصوت أولاً."), st["current_sentence_text"], st["current_sentence_id"], progress, "", gr.update(value=None), gr.update(interactive=True)

            sentence_text = (edited_sentence or st["current_sentence_text"]).strip()
            if not sentence_text:
                progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
                return st, _status("warn", "⚠️ نص الجملة فارغ."), st["current_sentence_text"], st["current_sentence_id"], progress, "", gr.update(value=None), gr.update(interactive=True)

            sid = st["current_sentence_id"]
            if not sid:
                progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
                return st, _status("warn", "⚠️ لا توجد جملة نشطة الآن."), st["current_sentence_text"], st["current_sentence_id"], progress, "", gr.update(value=None), gr.update(interactive=True)

            tmp_path = audio_path or temp_path
            ok, msg, _dur = validate_audio(tmp_path)
            if not ok:
                progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
                return st, _status("bad", f"❌ مشكلة في الصوت: {msg}"), st["current_sentence_text"], st["current_sentence_id"], progress, "", gr.update(value=None), gr.update(interactive=True)

            active_dialect = st.get("active_dialect_code") or st.get("dialect_code")
            user_dialect = st.get("user_dialect_code") or st.get("dialect_code") or "unk-gen"

            duration = save_recording_and_upload(
                st["username"],
                active_dialect,
                user_dialect,
                sid,
                sentence_text,
                tmp_path,
            )

            st["total_duration"] += duration
            if sid not in st["completed_sentences"]:
                st["completed_sentences"].append(sid)

            save_session(st["username"], st["completed_sentences"], st["total_duration"])

            next_sentence_for_state(st)
            progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])

            return (
                st,
                _status("ok", "✅ تم الحفظ بنجاح — ممتاز!"),
                st["current_sentence_text"],
                st["current_sentence_id"],
                progress,
                gr.update(value=None),
                gr.update(interactive=True),
            )

        def handle_skip(st):
            if not st.get("logged_in"):
                progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
                return st, _status("warn", "الرجاء تسجيل الدخول أولاً."), st["current_sentence_text"], st["current_sentence_id"], progress, gr.update(value=None), gr.update(interactive=True)

            sid = st["current_sentence_id"]
            if sid and sid not in st["completed_sentences"]:
                st["completed_sentences"].append(sid)
                save_session(st["username"], st["completed_sentences"], st["total_duration"])

            next_sentence_for_state(st)
            progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])

            return st, _status("warn", "⏭️ تم التخطي."), st["current_sentence_text"], st["current_sentence_id"], progress, gr.update(value=None), gr.update(interactive=True)

        save_btn.click(
            disable_skip, inputs=[], outputs=[skip_btn]
        ).then(
            handle_save,
            inputs=[audio_rec, sentence_box, temp_audio_path, state],
            outputs=[state, msg_box, sentence_box, sentence_id_box, progress_box, audio_rec, skip_btn],
        )

        skip_btn.click(
            disable_save, inputs=[], outputs=[save_btn]
        ).then(
            handle_skip,
            inputs=[state],
            outputs=[state, msg_box, sentence_box, sentence_id_box, progress_box, audio_rec, save_btn],
        )

        # ---------- Logout ----------
        def do_logout(st):
            st.update({
                "logged_in": False,
                "username": None,
                "user_dialect_code": None,
                "active_dialect_code": None,
                "dialect_code": None,
                "completed_sentences": [],
                "total_duration": 0.0,
                "current_sentence_id": "",
                "current_sentence_text": "",
                "last_temp_audio_path": "",
            })
            return (
                st,
                "",
                "",
                "",
                _status("ok", "تم تسجيل الخروج."),
                "",
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(visible=False),
            )

        logout_btn.click(
            do_logout,
            inputs=[state],
            outputs=[state, info, username_box, progress_box, msg_box, leaderboard_html, login_view, register_view, main_view],
        )
        lb_refresh_btn.click(
            refresh_leaderboard,
            inputs=[state],
            outputs=[leaderboard_html],
        )

    return demo


# ===============================
# ENTRYPOINT
# ===============================

if __name__ == "__main__":
    port = int(os.environ.get("GRADIO_SERVER_PORT", 7860))
    app = build_app()
    app.queue()
    app.launch(server_name="0.0.0.0", server_port=port, debug=False)

# ===============================
# SUPABASE SQL SETUP (RUN ONCE)
# ===============================
"""
-- 1) Lifetime alias per country (anonymous identity)
create table if not exists public.leaderboard_aliases_country_lifetime (
  id bigserial primary key,
  country_code text not null,
  username text not null,
  emoji text not null,
  alias text not null,
  created_at timestamptz default now(),
  unique (country_code, username)
);

create index if not exists leaderboard_aliases_country_lifetime_country_idx
on public.leaderboard_aliases_country_lifetime (country_code);

-- 2) Lifetime leaderboard per country (aggregated)
create table if not exists public.leaderboard_lifetime_country (
  id bigserial primary key,
  country_code text not null,
  username text not null,
  emoji text not null,
  alias text not null,
  time_seconds double precision not null default 0,
  sentences integer not null default 0,
  updated_at timestamptz default now(),
  unique (country_code, username)
);

create index if not exists leaderboard_lifetime_country_rank_idx
on public.leaderboard_lifetime_country (country_code, time_seconds desc);
"""
