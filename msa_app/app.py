import os
import json
import uuid
import time
import random
from pathlib import Path
from datetime import datetime

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
S3_BUCKET = os.environ.get("S3_BUCKET", "voicer-msa")
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
# (kept for registration + storage paths)
# ===============================

AVAILABLE_COUNTRIES = [
    "Egypt",
    "Saudi Arabia",
    "Morocco",
    "Yemen",
    "Jordan",
    "Palestine",
    "Algeria",
    "Sudan",
    "Tunisia",
    "Syria",
    "United Arab Emirates",
]

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
    "sy": "🇸🇾",  # fixed typo
    "tn": "🇹🇳",
    "ae": "🇦🇪",
    "ye": "🇾🇪",
}

RECORDING_TARGET_COUNT = 400

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
        "أخرى": "oth",
    },
    "Egypt": {
        "قاهرية": "ca",
        "إسكندرانية": "al",
        "صعيدية": "sa",
        "بورسعيدية": "si",
        "نوبية": "nb",
        "أخرى": "oth",
    },
    "Morocco": {
        "فاسية": "fe",
        "دار البيضاء": "ca",
        "مراكشية": "ma",
        "شمالية": "no",
        "شرقية": "shar",
        "أخرى": "oth",
    },
    "Iraq": {
        "بغدادية": "ba",
        "بصراوية": "bs",
        "موصلية": "mo",
        "كردية": "ku",
        "جنوبية": "so",
        "أخرى": "oth",
    },
    "Yemen": {
        "صنعانية": "sa",
        "عدنية": "ad",
        "حضرمية": "ha",
        "تهامية": "ti",
        "تعزية": "ta",
        "أخرى": "oth",
    },
    "Jordan": {
        "عمانية": "am",
        "شمالية": "no",
        "جنوبية": "so",
        "بدوية": "be",
        "أخرى": "oth",
    },
    "Lebanon": {
        "بيروتية": "be",
        "جبلية": "mo",
        "جنوبية": "so",
        "شمالية": "no",
        "أخرى": "oth",
    },
    "Syria": {
        "حلبية": "al",
        "حمصية": "ho",
        "شامية": "sh",
        "أخرى": "oth",
    },
    "Palestine": {
        "قدسية": "je",
        "غزاوية": "ga",
        "خليلية": "he",
        "شمالية": "no",
        "أخرى": "oth",
    },
    "United Arab Emirates": {
        "شرقية": "es",
        "شمالية": "no",
        "أبوظبي": "ad",
        "بدوية": "bd",
        "أخرى": "oth",
    },
    "Kuwait": {
        "كويتية": "ku",
        "بدوية": "be",
        "أخرى": "oth",
    },
    "Qatar": {
        "قطرية": "qa",
        "بدوية": "be",
        "أخرى": "oth",
    },
    "Bahrain": {
        "بحرينية": "ba",
        "مدنية": "ur",
        "أخرى": "oth",
    },
    "Oman": {
        "عمانية": "om",
        "ظفارية": "dh",
        "داخلية": "in",
        "أخرى": "oth",
    },
    "Algeria": {
        "شرقية": "al",
        "غربية": "co",
        "جنوبية": "or",
        "وسط": "ka",
        "أخرى": "oth",
    },
    "Tunisia": {
        "جنوبية": "tu",
        "صفاقسية": "sf",
        "ساحل شرقي": "so",
        "شمالية": "no",
        "وسطى": "me",
        "أخرى": "oth",
    },
    "Libya": {
        "طرابلسية": "tr",
        "بنغازية": "be",
        "فزانية": "fe",
        "أخرى": "oth",
    },
    "Sudan": {
        "خرطومية": "kh",
        "شمالية": "no",
        "دارفورية": "da",
        "أخرى": "oth",
    },
    "Somalia": {
        "صومالية": "so",
        "شمالية": "no",
        "جنوبية": "so",
        "أخرى": "oth",
    },
    "Mauritania": {
        "موريتانية": "mr",
        "حسانية": "ha",
        "أخرى": "oth",
    },
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
      يدرك المشارك أن المشاركة لا تتضمن أي مقابل مادي، والمساهمة هنا لدعم وتطوير البحث العلمي فقط.<br>
      بمجرد إنشاء حساب فأنت موافق علي جميع الشروط المذكورة أعلاه.
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


def get_country_code_from_dialect_code(dialect_code: str) -> str:
    return split_dialect_code(dialect_code)[0] or "unk"


# ===============================
# SENTENCES (GLOBAL FILE ONLY)
# Everyone reads from sentences_msa.json
# No dialect filtering, no fallback
# ===============================

SENTENCES_CACHE = {}  # [(id, text), ...]


def get_sentences_file_msa() -> Path:
    return BASE_DIR / "sentences_msa.json"


def load_sentences_msa(source):
    global SENTENCES_CACHE
    source = str(source).strip()

    if source in SENTENCES_CACHE:
        return SENTENCES_CACHE[source]
 
    path = get_sentences_file_msa()
    if not path.exists():
        path.write_text(json.dumps({"sentences": []}, ensure_ascii=False, indent=2), encoding="utf-8")

    data = json.loads(path.read_text(encoding="utf-8"))
    raw_sentences = data.get("sentences", [])

    SENTENCES_CACHE[source] = [
        (str(s.get("unique_id", "")).strip(), str(s.get("text", "")).strip())
        for s in raw_sentences
        if str(s.get("unique_id", "")).strip()
        and str(s.get("text", "")).strip()
        and str(s.get("source", "")).strip() == source
    ]
    return SENTENCES_CACHE[source]


def filter_sentences(st):
    completed_ids = st["completed_sentences"]
    completed_set = set(completed_ids or [])
    all_sentences = load_sentences_msa(st["source"])

    # Return same pool for everyone: only exclude completed.
    # We still return a 3rd value to keep your downstream code unchanged.
    return [(sid, text, None) for sid, text in all_sentences if sid not in completed_set]


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
            supabase.table("sessions_MSA").insert({
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
        return {"completed_sentences": [], "recorded_sentences": [], "total_recording_duration": 0.0}
    try:
        resp = supabase.table("sessions_MSA").select("*").eq("username", username).execute()
        if resp.data:
            row = resp.data[0]
            return {
                "completed_sentences": row.get("completed_sentences", []) or [],
                "recorded_sentences": row.get("recorded_sentences", []) or [],
                "total_recording_duration": float(row.get("total_recording_duration", 0.0) or 0.0),
            }
    except Exception as e:
        print("load_session error:", e)
    return {"completed_sentences": [], "recorded_sentences": [], "total_recording_duration": 0.0}


def save_session(username: str, completed_sentences, recorded_sentences, total_duration: float):
    if not supabase:
        return
    try:
        supabase.table("sessions_MSA").upsert({
            "username": username,
            "completed_sentences": completed_sentences,
            "recorded_sentences": recorded_sentences,
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


def save_recording_and_upload(
    username: str,
    active_dialect_code: str,
    user_dialect_code: str,
    sentence_id: str,
    sentence_text: str,
    audio_path: str,
):
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

def make_progress_bar(completed_count: float, target_count: float, bar_length: int = 24) -> str:
    if target_count <= 0:
        bar = "░" * bar_length
        return f"[{bar}] 0.0%"

    ratio = max(0.0, min(1.0, completed_count / target_count))
    filled = int(bar_length * ratio)
    bar = "█" * filled + "░" * (bar_length - filled)
    return f"[{bar}] {ratio * 100:.1f}%"


def compute_progress(completed_count: int):
    bar = make_progress_bar(completed_count, RECORDING_TARGET_COUNT)
    # mins = int(total_duration // 60)
    # secs = int(total_duration % 60)
    # target_mins = int(RECORDING_TARGET_SECONDS // 60)
    return f"{bar}\n{completed_count} sentences"


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

  .gradio-container,
  .gradio-container .main,
  .gradio-container .wrap,
  .gradio-container .contain{
    max-width: 100% !important;
    width: 100% !important;
  }

  .gradio-container .contain{
    padding-left: 12px !important;
    padding-right: 12px !important;
  }

  .gradio-container,
  .gradio-container .main,
  .gradio-container .wrap,
  .gradio-container .contain{
    overflow: visible !important;
  }

  .gradio-container *{
    min-width: 0;
  }

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

  .rtl .gr-accordion .label-wrap,
  .rtl .gr-accordion .label-wrap > div{
    direction: rtl !important;
    text-align: right !important;
    justify-content: space-between !important;
  }
  .rtl .gr-accordion .label-wrap svg{
    transform: scaleX(-1);
  }

  @media (max-width: 640px){
    .gradio-container .contain{
      padding-left: 8px !important;
      padding-right: 8px !important;
    }

    .app-shell{ padding: 8px; }

    .hero{
      padding: 14px;
      border-radius: 16px;
      backdrop-filter: none !important;
    }
    .hero h1{ font-size: 18px; }

    .card{
      padding: 12px;
      border-radius: 14px;
    }
    .card h3{ font-size: 15px; }
    .hint{ font-size: 11.5px; }

    .gradio-container .gr-row{
      flex-wrap: wrap !important;
      gap: 10px !important;
    }
    .gradio-container .gr-row > *{
      flex: 1 1 100% !important;
    }
  }

#sentence_box textarea,
#sentence_box input {
  direction: rtl;
  text-align: right;
}
</style>
"""


# ===============================
# PROFESSIONAL APP UI
# ===============================

def build_app():
    with gr.Blocks(title="Arabic Speech Recorder", css="") as demo:
        gr.HTML(APP_CSS)

        state = gr.State({
            "logged_in": False,
            "username": None,
            "user_dialect_code": None,
            "active_dialect_code": None,
            "dialect_code": None,  # backward compat
            "completed_sentences": [],
            "recorded_sentences": [],
            "total_duration": 0.0,
            "current_sentence_id": "",
            "current_sentence_text": "",
            "last_temp_audio_path": "",
            "source": "MSA",  # default to MSA for everyone
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
                login_email = gr.Textbox(label="الإيميل", placeholder="name@example.com")
                login_pw = gr.Textbox(label="كلمة السر", type="password", placeholder="••••••••")
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
            reg_name = gr.Textbox(label="الاسم (بالإنجليزية)", placeholder="e.g., Ahmed Ali")
            reg_email = gr.Textbox(label="الإيميل", placeholder="name@example.com")
            reg_pw = gr.Textbox(label="كلمة السر", type="password", placeholder="قم بحفظ كلمة السر هذه لتسجيل الدخول لاحقًا")
            reg_country = gr.Dropdown(choices=AVAILABLE_COUNTRIES, value="Saudi Arabia", label="الدولة")
            reg_dialect = gr.Dropdown(choices=get_dialects_for_country("Saudi Arabia"), value=None, label="اللهجة")
            reg_gender = gr.Dropdown(choices=GENDER, value=None, label="النوع")
            reg_age = gr.Dropdown(choices=AGES, value=None, label="الفئة العمرية")

            with gr.Accordion("إتفاقية التسجيل واستخدام البيانات", open=False):
                gr.Markdown(CONSENT_DETAILS)

            reg_btn = gr.Button("إنشاء الحساب", variant="primary")
            reg_msg = gr.HTML("")
            back_to_login_btn = gr.Button("الرجوع لتسجيل الدخول")
            gr.HTML('</div></div>')

        with gr.Column(visible=False) as main_view:
            gr.HTML('<div class="app-shell">')

            with gr.Row():
                info = gr.HTML("")
                logout_btn = gr.Button("تسجيل الخروج")

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
            
            choose_source = gr.Dropdown(choices=["MSA", "CA"], value="MSA", label="اختيار نوع الجملة")

            username_box = gr.Textbox(label="👤 اسم المستخدم", interactive=False, visible=False)
            sentence_box = gr.Textbox(label="✍️ الجملة", interactive=False, lines=3, elem_id="sentence_box")
            sentence_id_box = gr.Textbox(label="رمز الجملة", interactive=False, visible=False)

            audio_rec = gr.Audio(
                sources=["microphone"],
                type="filepath",
                label="🎙️ Record",
                format="wav",
            )
            temp_audio_path = gr.Textbox(label="Temp audio path", visible=False)

            with gr.Row():
                save_btn = gr.Button("حفظ", variant="primary", interactive=False)
            msg_box = gr.HTML("")
            gr.HTML('</div>')  # grid-2

            gr.HTML("</div>")  # app-shell

        # ---------- Navigation helpers ----------
        def show_register():
            return gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)

        def show_login():
            return gr.update(visible=True), gr.update(visible=False), gr.update(visible=False)

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
            return gr.update(interactive=False), ""

        audio_rec.start_recording(fn=on_start_recording, outputs=[save_btn, msg_box])

        def on_stop_recording(audio_path, st):
            if not audio_path:
                return st, "", gr.update(value=None), gr.update(interactive=True)

            st["last_temp_audio_path"] = audio_path
            time.sleep(0.2)
            return st, audio_path, gr.update(value=audio_path), gr.update(interactive=True)

        audio_rec.stop_recording(
            fn=on_stop_recording,
            inputs=[audio_rec, state],
            outputs=[state, temp_audio_path, audio_rec, save_btn],
        )

        audio_rec.clear(fn=lambda: gr.update(interactive=False), outputs=[save_btn])

        # ---------- Login ----------
        def _status(kind: str, text: str) -> str:
            cls = {"ok": "status-ok", "warn": "status-warn", "bad": "status-bad"}.get(kind, "status-warn")
            return f'<div class="{cls} rtl">{text}</div>'

        def next_sentence_for_state(st):
            # global pool, no dialect filtering
            available = filter_sentences(st)
            if not available:
                st["current_sentence_id"] = ""
                st["current_sentence_text"] = "No more sentences."
                # keep active dialect for storage paths (user dialect)
                st["active_dialect_code"] = st.get("user_dialect_code") or st.get("dialect_code")
            else:
                sid, text, _ = random.choice(available)
                st["current_sentence_id"] = sid
                st["current_sentence_text"] = text
                # keep active dialect for storage paths (user dialect)
                st["active_dialect_code"] = st.get("user_dialect_code") or st.get("dialect_code")

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
                    gr.update(visible=True),
                    gr.update(visible=False),
                    gr.update(visible=False),
                )

            username = result
            user = get_user_by_username(username)
            user_dialect_code = user.get("dialect_code", "sa-hj") if user else "sa-hj"

            sess = load_session(username)
            completed = sess["completed_sentences"]
            recorded = sess["recorded_sentences"]
            total_dur = sess["total_recording_duration"]

            available = filter_sentences(st)
            if not available:
                sentence_id = ""
                sentence_text = "No more sentences."
            else:
                sentence_id, sentence_text, _ = random.choice(available)

            st.update({
                "logged_in": True,
                "username": username,
                "user_dialect_code": user_dialect_code,
                "active_dialect_code": user_dialect_code,   # for storage paths only
                "dialect_code": user_dialect_code,          # backward compat
                "completed_sentences": completed,
                "recorded_sentences": recorded,
                "total_duration": total_dur,
                "current_sentence_id": sentence_id,
                "current_sentence_text": sentence_text,
            })

            country_code = get_country_code_from_dialect_code(user_dialect_code)
            flag = COUNTRY_EMOJIS.get(country_code, "")
            username_show = " ".join(username.split("_")[:-3]).title() or "User"
            info_text = f'<div class="chip rtl">👤 <b>{username_show}</b> &nbsp; {flag} {country_code.upper()}</div>'

            progress = compute_progress(len(completed))

            return (
                st,
                _status("ok", "✅ تم تسجيل الدخول بنجاح"),
                info_text,
                username,
                progress,
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
                sentence_box,
                sentence_id_box,
                login_view,
                register_view,
                main_view,
            ],
        )

        def disable_save():
            return gr.update(interactive=False)
        
        def handle_change_source(st):
            next_sentence_for_state(st)
            progress = compute_progress(len(st["completed_sentences"]))
            return (
                st,
                st["current_sentence_text"],
                st["current_sentence_id"],
                progress,
            )

        def handle_save(audio_path, edited_sentence, temp_path, st):
            if not st.get("logged_in"):
                progress = compute_progress(len(st["completed_sentences"]))
                return (
                    st,
                    _status("warn", "الرجاء تسجيل الدخول أولاً."),
                    st["current_sentence_text"],
                    st["current_sentence_id"],
                    progress,
                    gr.update(value=None),
                )

            if not audio_path and not temp_path:
                progress = compute_progress(len(st["completed_sentences"]))
                return (
                    st,
                    _status("warn", "⚠️ سجّل الصوت أولاً."),
                    st["current_sentence_text"],
                    st["current_sentence_id"],
                    progress,
                    gr.update(value=None),
                )

            sentence_text = (edited_sentence or st["current_sentence_text"]).strip()
            if not sentence_text:
                progress = compute_progress(len(st["completed_sentences"]))
                return (
                    st,
                    _status("warn", "⚠️ نص الجملة فارغ."),
                    st["current_sentence_text"],
                    st["current_sentence_id"],
                    progress,
                    gr.update(value=None),
                )

            sid = st["current_sentence_id"]
            if not sid:
                progress = compute_progress(len(st["completed_sentences"]))
                return (
                    st,
                    _status("warn", "⚠️ لا توجد جملة نشطة الآن."),
                    st["current_sentence_text"],
                    st["current_sentence_id"],
                    progress,
                    gr.update(value=None),
                )

            tmp_path = audio_path or temp_path
            ok, msg, _dur = validate_audio(tmp_path)
            if not ok:
                progress = compute_progress(len(st["completed_sentences"]))
                return (
                    st,
                    _status("bad", f"❌ مشكلة في الصوت: {msg}"),
                    st["current_sentence_text"],
                    st["current_sentence_id"],
                    progress,
                    gr.update(value=None),
                )

            # Keep dialect only for folder structure / metadata filename logic
            active_dialect = st.get("active_dialect_code") or st.get("dialect_code") or "unk-gen"
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
            if sid not in st["recorded_sentences"]:
                st["recorded_sentences"].append(sid)

            save_session(st["username"], st["completed_sentences"], st["recorded_sentences"], st["total_duration"])

            next_sentence_for_state(st)
            progress = compute_progress(len(st["completed_sentences"]))

            return (
                st,
                _status("ok", "✅ تم الحفظ بنجاح — ممتاز!"),
                st["current_sentence_text"],
                st["current_sentence_id"],
                progress,
                gr.update(value=None),
            )

        save_btn.click(
            disable_save, inputs=[], outputs=[save_btn]
        ).then(
            handle_save,
            inputs=[audio_rec, sentence_box, temp_audio_path, state],
            outputs=[state, msg_box, sentence_box, sentence_id_box, progress_box, audio_rec],
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
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(visible=False),
            )

        logout_btn.click(
            do_logout,
            inputs=[state],
            outputs=[state, info, username_box, progress_box, msg_box, login_view, register_view, main_view],
        )
        
        def on_source_change(new_source, st):
            st["source"] = new_source
            return st
        choose_source.change(on_source_change, 
                             inputs=[choose_source, state], outputs=[state]).then(
                                 handle_change_source,
                                    inputs=state,
                                    outputs=[state, sentence_box, sentence_id_box, progress_box],
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