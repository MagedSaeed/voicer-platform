import os
import json
import uuid
from pathlib import Path
from datetime import datetime
import random
from dotenv import load_dotenv
import boto3
import gradio as gr
import soundfile as sf
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
print(SUPABASE_KEY)
print(SUPABASE_URL)

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
AVAILABLE_COUNTRIES = [
    "Egypt", "Saudi Arabia", "Morocco"
]

COUNTRIES = [
    "Algeria", "Bahrain", "Egypt", "Iraq", "Jordan", "Kuwait", "Lebanon",
    "Libya", "Mauritania", "Morocco", "Oman", "Palestine", "Qatar",
    "Saudi Arabia", "Somalia", "Sudan", "Syria", "Tunisia",
    "United Arab Emirates", "Yemen"
]

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

### تعليمات التسجيل
1. **البيئة**: سجّل في مكان هادئ قد ما تقدر، وحاول ما يكون فيه ضوضاء أو أصوات في الخلفية.  
2. **الميكروفون**: يفضّل تستخدم مايك سماعة أو مايك خارجي، لأنه غالبًا بيكون أوضح بكثير من مايك اللابتوب. في حالة استخدام الجوال يمكن فقط التأكد من جودة التسجيل قبل الإكمال.  
3. **طريقة التحدث**: اقرأ الجملة بصوت واضح وطبيعي، وبلهجتك. لا تغيّر أو تستبدل أي كلمة أبدًا، إلا لو كان فيه اختلاف بالنطق مثل: "ثلاثة" و"تلاتة" — هذا عادي. إذا حسّيت إنك ما تبغى تسجل جملة معينة أو ما عرفت تنطقها، عادي اضغط "Skip".  
4. **التعديل**: تقدر تعدل الجملة قبل لا تسجل إذا ودك.  
5. **الحفظ**: بعد ما تسجل، اضغط "Save & Next" عشان تحفظ تسجيلك. إذا ودك تعيد، استخدم "Discard"، أو اضغط "Skip" عشان تروح للجملة اللي بعدها.  
6. **المدة**: حاول تسجل عدد كافي من الجمل، كل تسجيل يساعدنا أكثر! حاول يكون مجموع تسجيلاتك على الأقل 30 دقيقة، ونقدّر وقتك وجهدك   

إذا عندك أي مشكلة أو استفسار، تواصل معي على الإيميل:  
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


AGES = [
    "4–9",   # baby
    "10–14", # child
    "15–19", # teen
    "20–24", # young adult
    "25–34", # adult
    "35–44", # mid-age adult
    "45–54", # older adult
    "55–64", # senior
    "65–74", # elderly
    "75–84", # aged
    "85+"    # very aged
]

GENDER = [
    "ذكر",
    "أنثى"
]


def get_dialects_for_country(country: str):
    dialects = list(COUNTRY_DIALECTS.get(country, {}).keys())
    if not dialects:
        return ["أخرى"]
    return dialects


def split_dialect_code(dialect_code: str):
    dialect_code = (dialect_code or "").strip().lower() or "unk-gen"
    parts = dialect_code.split("-", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], "gen"

# ===============================
# SENTENCES (per-country, cached)
# ===============================

SENTENCES_CACHE = {}  # {country_code: [(id, text, [dialects]), ...]}


def get_sentences_file_for_country(country_code: str) -> Path:
    """
    Return the path to the sentences file for a given country code,
    e.g. 'eg' -> BASE_DIR / 'sentences_eg.json'.
    """
    return BASE_DIR / f"sentences_{country_code}.json"


def load_sentences_for_country(country_code: str):
    """
    Load and cache all sentences for a given country code.

    Expected JSON structure:
    {
      "sentences": [
        {
          "unique_id": "105130",
          "text": "...",
          "dialect": ["eg-ca", "eg-al", ...]
        },
        ...
      ]
    }
    """
    if country_code in SENTENCES_CACHE:
        return SENTENCES_CACHE[country_code]

    path = get_sentences_file_for_country(country_code)

    # If missing, initialise an empty file (or you can raise an error if you prefer)
    if not path.exists():
        path.write_text(
            json.dumps({"sentences": []}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    raw_sentences = data.get("sentences", [])

    SENTENCES_CACHE[country_code] = [
        (s["unique_id"], s["text"], s.get("dialect", []))
        for s in raw_sentences
    ]
    return SENTENCES_CACHE[country_code]



def filter_sentences(dialect_code: str, completed_ids):
    """
    Return all (sentence_id, text) pairs for a given dialect_code,
    excluding any sentence IDs in completed_ids.

    - dialect_code looks like 'sa-hj', 'eg-ca', etc.
    - We infer the country_code ('sa', 'eg', ...) from dialect_code,
      then load the corresponding sentences_{country_code}.json.
    """
    completed_set = set(completed_ids or [])

    country_code, _ = split_dialect_code(dialect_code)
    all_sentences = load_sentences_for_country(country_code)

    return [
        (sid, text)
        for sid, text, dialects in all_sentences
        if sid not in completed_set and dialect_code in dialects
    ]

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


def create_password_reset_token(email: str):
    if not supabase:
        return False, "Supabase not configured"

    user = get_user_by_email(email)
    if not user:
        return False, "Email not found"

    token = uuid.uuid4().hex
    payload = {
        "email": email.lower(),
        "token": token,
        "created_at": datetime.utcnow().isoformat(),
    }
    try:
        supabase.table("password_resets").insert(payload).execute()
        return True, token
    except Exception as e:
        # nice clean message instead of raw dict
        print("create_password_reset_token error:", e)
        return False, "Password reset is not configured on the server (missing password_resets table)."


def reset_password_with_token(token: str, new_password: str):
    if not supabase:
        return False, "Supabase not configured"
    try:
        resp = supabase.table("password_resets").select("*").eq("token", token).execute()
        rows = resp.data or []
        if not rows:
            return False, "Invalid or expired token"

        row = rows[0]
        email = row["email"]
        user = get_user_by_email(email)
        if not user:
            return False, "User not found"

        hashed_pw = generate_password_hash(new_password)
        supabase.table("users").update({"password": hashed_pw}).eq("email", email).execute()
        supabase.table("password_resets").delete().eq("token", token).execute()
        return True, "Password updated successfully"
    except Exception as e:
        print("reset_password_with_token error:", e)
        return False, "Password reset is not fully configured on the server."


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


def save_recording_and_upload(username: str, dialect_code: str, sentence_id: str, sentence_text: str, audio_path: str):
    """
    Local:
      ~/.tts_dataset_creator/users/{country}/{dialect}/{username}/wavs/{country}_{dialect}_{username}_{sentence}.wav

    S3 (country-level folder only):
      {country_code}/{username}/wavs/{country}_{dialect}_{username}_{sentence}.wav
      {country_code}/{username}/metadata.csv
    """
    user_dir = ensure_user_dirs(username, dialect_code)
    wav_dir = user_dir / "wavs"
    meta_file = user_dir / "metadata.csv"

    if not meta_file.exists():
        meta_file.write_text("audio_file|text\n", encoding="utf-8")

    country_code, dialect = split_dialect_code(dialect_code)
    filename = f"{username}_{sentence_id}.wav"
    dest = wav_dir / filename

    Path(audio_path).replace(dest)

    try:
        with sf.SoundFile(dest) as f:
            duration = len(f) / f.samplerate
    except Exception:
        duration = 0.0

    with meta_file.open("a", encoding="utf-8") as f:
        f.write(f"{filename}|{sentence_text.strip()}\n")

    base_prefix = f"{country_code}/{username}"
    upload_file_to_s3(dest, f"{base_prefix}/wavs/{filename}")
    upload_file_to_s3(meta_file, f"{base_prefix}/metadata.csv")

    return duration


def compute_progress(completed_count: int, total_duration: float):
    mins = int(total_duration // 60)
    secs = int(total_duration % 60)
    return f"{completed_count} sentences, {mins}m {secs}s recorded"


# ===============================
# GRADIO APP (3 PAGES)
# ===============================

def build_app():
    with gr.Blocks(title="TTS Dataset Recorder") as demo:
        state = gr.State({
            "logged_in": False,
            "username": None,
            "dialect_code": None,
            "completed_sentences": [],
            "total_duration": 0.0,
            "current_sentence_id": "",
            "current_sentence_text": "",
        })

        gr.Markdown("## Arabic TTS Dataset Recorder")

        # ---------- LOGIN PAGE ----------
        with gr.Column(visible=True) as login_view:
            gr.Markdown("### Login")
            login_email = gr.Textbox(label="Email")
            login_pw = gr.Textbox(label="Password", type="password")
            login_btn = gr.Button("Login")
            login_msg = gr.Markdown("")
            goto_register_btn = gr.Button("Create new account")
            with gr.Accordion("Forgot password?", open=False, visible=False):
                fp_email = gr.Textbox(label="Email")
                fp_btn = gr.Button("Create reset token")
                fp_output = gr.Markdown("")
                rp_token = gr.Textbox(label="Reset token")
                rp_new_pw = gr.Textbox(label="New password", type="password")
                rp_btn = gr.Button("Reset password")
                rp_output = gr.Markdown("")

        # ---------- REGISTER PAGE ----------
        with gr.Column(visible=False) as register_view:
            gr.Markdown("### Register")
            reg_name = gr.Textbox(label="Name (Latin)")
            reg_email = gr.Textbox(label="Email")
            reg_pw = gr.Textbox(label="Password", type="password")
            reg_country = gr.Dropdown(choices=AVAILABLE_COUNTRIES, value="Saudi Arabia", label="Country")
            default_dialects = get_dialects_for_country("Saudi Arabia")
            reg_dialect = gr.Dropdown(
                choices=default_dialects,
                value=None,   # user must choose
                label="Dialect"
            )
            reg_gender = gr.Dropdown(
                choices=GENDER,
                value=None,   # user must choose
                label="Gender"
            )
            reg_age = gr.Dropdown(
                choices=AGES,
                value=None,   # user must choose
                label="Age Group"
            )
            with gr.Accordion("إتفاقية التسجيل بالموقع واستخدام البيانات", open=True, visible=True):
                inst_output = gr.Markdown(CONSENT_DETAILS)
            reg_btn = gr.Button("Register", variant="primary")
            reg_msg = gr.Markdown("")
            back_to_login_btn = gr.Button("Back to login")

        # ---------- MAIN PAGE ----------
        with gr.Column(visible=False) as main_view:
            info = gr.Markdown("")
            logout_btn = gr.Button("Logout")
            with gr.Accordion("تعليمات مهمة للتسجيل", open=True, visible=True):
                rec_inst_output = gr.Markdown(RECORDING_INSTRUCTIONS)
            username_box = gr.Textbox(label="Username", interactive=False)
            progress_box = gr.Textbox(label="Progress", interactive=False)
            sentence_box = gr.Textbox(label="Sentence", interactive=True, lines=3)
            sentence_id_box = gr.Textbox(label="Sentence ID", interactive=False, visible=False)
            audio_rec = gr.Audio(sources=["microphone"], type="filepath", label="Record")
            save_btn = gr.Button("Save & Next", variant="primary")
            skip_btn = gr.Button("Skip")
            msg_box = gr.Markdown("")

        # ---------- Navigation helpers ----------

        def show_register():
            return (
                gr.update(visible=False),
                gr.update(visible=True),
                gr.update(visible=False),
            )

        def show_login():
            return (
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(visible=False),
            )

        def show_main():
            return (
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=True),
            )

        goto_register_btn.click(
            show_register,
            inputs=[],
            outputs=[login_view, register_view, main_view],
        )

        back_to_login_btn.click(
            show_login,
            inputs=[],
            outputs=[login_view, register_view, main_view],
        )

        # ---------- Register callbacks ----------

        def update_dialects(country):
            dialects = get_dialects_for_country(country)
            # IMPORTANT FIX: don't try to set a default value; let user choose
            return gr.update(choices=dialects, value=None)

        reg_country.change(
            update_dialects,
            inputs=reg_country,
            outputs=reg_dialect
        )

        def do_register(name, email, pw, country, dialect_label, gender, age, st):
            if not all([name, email, pw, country, dialect_label, gender, age]):
                return (
                    st,
                    "❌ Please fill all fields",
                    gr.update(visible=False),
                    gr.update(visible=True),
                    gr.update(visible=False),
                )

            ok, result = create_user(name, email, pw, country, dialect_label, gender, age)
            if not ok:
                return (
                    st,
                    f"❌ {result}",
                    gr.update(visible=False),
                    gr.update(visible=True),
                    gr.update(visible=False),
                )

            return (
                st,
                "✅ Registered successfully. You can now login.",
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(visible=False),
            )

        reg_btn.click(
            do_register,
            inputs=[reg_name, reg_email, reg_pw, reg_country, reg_dialect, reg_gender, reg_age, state],
            outputs=[state, reg_msg, login_view, register_view, main_view],
        )

        # ---------- Login + password reset ----------

        def do_login(email, pw, st):
            ok, result = authenticate(email, pw)
            if not ok:
                return (
                    st,
                    f"❌ {result}",
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
            dialect_code = user.get("dialect_code", "sa-hj") if user else "sa-hj"

            sess = load_session(username)
            completed = sess["completed_sentences"]
            total_dur = sess["total_recording_duration"]

            available = filter_sentences(dialect_code, completed)
            if not available:
                sentence_id = ""
                sentence_text = "No more sentences for your dialect."
            else:
                sentence_id, sentence_text = random.choice(available)

            st.update({
                "logged_in": True,
                "username": username,
                "dialect_code": dialect_code,
                "completed_sentences": completed,
                "total_duration": total_dur,
                "current_sentence_id": sentence_id,
                "current_sentence_text": sentence_text,
            })

            progress = compute_progress(len(completed), total_dur)
            info_text = f"Logged in as **{username}** (dialect: `{dialect_code}`)."

            return (
                st,
                "",
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

        def do_forget_password(email):
            if not email:
                return "Please enter your email."
            ok, msg = create_password_reset_token(email)
            if not ok:
                return f"❌ {msg}"
            return f"✅ Reset token (dev mode): `{msg}`"

        fp_btn.click(do_forget_password, inputs=[fp_email], outputs=[fp_output])

        def do_reset_password(token, new_pw):
            if not token or not new_pw:
                return "Please provide token and new password."
            ok, msg = reset_password_with_token(token, new_pw)
            return ("✅ " if ok else "❌ ") + msg

        rp_btn.click(do_reset_password, inputs=[rp_token, rp_new_pw], outputs=[rp_output])

        # ---------- Main page logic ----------

        def next_sentence_for_state(st):
            available = filter_sentences(st["dialect_code"], st["completed_sentences"])
            if not available:
                st["current_sentence_id"] = ""
                st["current_sentence_text"] = "No more sentences."
            else:
                sid, text = random.choice(available)
                st["current_sentence_id"] = sid
                st["current_sentence_text"] = text

        def handle_save(audio_path, edited_sentence, st):
            if not st.get("logged_in"):
                progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
                return st, "Please login first.", st["current_sentence_text"], st["current_sentence_id"], progress, None

            if not audio_path:
                progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
                return st, "⚠️ Record audio first.", st["current_sentence_text"], st["current_sentence_id"], progress, None

            sentence_text = (edited_sentence or st["current_sentence_text"]).strip()
            if not sentence_text:
                progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
                return st, "⚠️ Sentence text is empty.", st["current_sentence_text"], st["current_sentence_id"], progress, None

            sid = st["current_sentence_id"]
            if not sid:
                progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
                return st, "⚠️ No active sentence.", st["current_sentence_text"], st["current_sentence_id"], progress, None

            ok, msg, _dur = validate_audio(audio_path)
            if not ok:
                progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
                return st, f"❌ Audio error: {msg}", st["current_sentence_text"], st["current_sentence_id"], progress, None

            duration = save_recording_and_upload(
                st["username"],
                st["dialect_code"],
                sid,
                sentence_text,
                audio_path,
            )
            st["total_duration"] += duration
            if sid not in st["completed_sentences"]:
                st["completed_sentences"].append(sid)

            save_session(st["username"], st["completed_sentences"], st["total_duration"])

            next_sentence_for_state(st)
            progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
            return st, "✅ Saved", st["current_sentence_text"], st["current_sentence_id"], progress, None

        save_btn.click(
            handle_save,
            inputs=[audio_rec, sentence_box, state],
            outputs=[state, msg_box, sentence_box, sentence_id_box, progress_box, audio_rec],
        )

        def handle_skip(st):
            if not st.get("logged_in"):
                progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
                return st, "Please login first.", st["current_sentence_text"], st["current_sentence_id"], progress, None

            sid = st["current_sentence_id"]
            if sid and sid not in st["completed_sentences"]:
                st["completed_sentences"].append(sid)
                save_session(st["username"], st["completed_sentences"], st["total_duration"])

            next_sentence_for_state(st)
            progress = compute_progress(len(st["completed_sentences"]), st["total_duration"])
            return st, "Skipped.", st["current_sentence_text"], st["current_sentence_id"], progress, None

        skip_btn.click(
            handle_skip,
            inputs=[state],
            outputs=[state, msg_box, sentence_box, sentence_id_box, progress_box, audio_rec],
        )

        def do_logout(st):
            st.update({
                "logged_in": False,
                "username": None,
                "dialect_code": None,
                "completed_sentences": [],
                "total_duration": 0.0,
                "current_sentence_id": "",
                "current_sentence_text": "",
            })
            return (
                st,
                "",
                "",
                "",
                "",
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(visible=False),
            )

        logout_btn.click(
            do_logout,
            inputs=[state],
            outputs=[
                state,
                info,
                username_box,
                progress_box,
                msg_box,
                login_view,
                register_view,
                main_view,
            ],
        )

    return demo


if __name__ == "__main__":
    port = int(os.environ.get("GRADIO_SERVER_PORT", 7860))
    app = build_app()
    app.launch(
        server_name="0.0.0.0",
        server_port=port,
        debug=False,
    )
# ===============================
