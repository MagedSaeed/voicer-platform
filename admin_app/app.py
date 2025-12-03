import os
import io
from pathlib import Path
from datetime import datetime

import boto3
import gradio as gr
import matplotlib.pyplot as plt
import soundfile as sf  # for reading wav from bytes
from dotenv import load_dotenv
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash

# ===============================
# CONFIG & GLOBALS
# ===============================

load_dotenv()

BASE_DIR = Path(__file__).parent if "__file__" in globals() else Path(".").resolve()

AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY", "")
AWS_SECRET_KEY = os.environ.get("AWS_SECRET_KEY", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "voicer-storage")
AWS_REGION = os.environ.get("AWS_REGION", "me-south-1")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")

# Prefer service role key if provided (recommended for admin apps)
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_KEY")
    or os.environ.get("SUPABASE_ANON_KEY")
    or ""
)

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ Supabase env vars not set for admin app")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


def _create_s3_client():
    aws_access_key = os.environ.get("AWS_ACCESS_KEY", "")
    aws_secret_key = os.environ.get("AWS_SECRET_KEY", "")
    if not aws_access_key or not aws_secret_key:
        print("Using IAM role or instance profile for S3 (admin app)")
        return boto3.client("s3", region_name=AWS_REGION)
    print("Using explicit access keys for S3 (admin app)")
    return boto3.client(
        "s3",
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=AWS_REGION,
    )


S3_CLIENT = _create_s3_client()

# Same country list as main app
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

COUNTRY_FILTER_CHOICES = ["All"] + sorted(COUNTRY_CODES.keys())

RECORDING_TARGET_MINUTES = 60
RECORDING_TARGET_SECONDS = RECORDING_TARGET_MINUTES * 60


# ===============================
# ADMIN AUTH HELPERS (Supabase)
# ===============================

def get_admin_by_email(email):
    if not supabase:
        return None
    try:
        resp = supabase.table("admins").select("*").eq("email", email.lower()).execute()
        data = resp.data or []
        return data[0] if data else None
    except Exception as e:
        print("get_admin_by_email error:", e)
        return None


def create_admin(name, email, password):
    """
    Sign-up for admin. Will be created with approved = false.
    You (owner) have to set approved = true manually in Supabase.
    """
    if not supabase:
        return False, "Supabase not configured"

    email = email.lower()
    existing = get_admin_by_email(email)
    if existing:
        return False, "Email already registered as admin"

    hashed_pw = generate_password_hash(password)
    payload = {
        "name": name,
        "email": email,
        "password": hashed_pw,
        "approved": False,
        "created_at": datetime.utcnow().isoformat(),
    }

    try:
        resp = supabase.table("admins").insert(payload).execute()
        if resp.data:
            return True, "Registered successfully. Waiting for approval from owner."
        return False, "Failed to create admin"
    except Exception as e:
        print("create_admin error:", e)
        msg = getattr(e, "message", None) or str(e)
        return False, f"Admin sign-up failed on the server. Raw: {msg}"


def authenticate_admin(email, password):
    """
    Login for admin. Requires approved = true.
    """
    if not supabase:
        return False, "Supabase not configured", None

    admin = get_admin_by_email(email)
    if not admin:
        return False, "Invalid email or password", None

    if not check_password_hash(admin.get("password", ""), password):
        return False, "Invalid email or password", None

    if not admin.get("approved", False):
        return False, "Your admin account is not approved yet.", None

    return True, "OK", admin


# ===============================
# DATA HELPERS (USERS + SESSIONS)
# ===============================

def fetch_users():
    """
    Load all users from Supabase.
    """
    if not supabase:
        return [], "Supabase not configured"

    try:
        resp = supabase.table("users").select(
            "username,name,email,country,dialect_code,gender,age,created_at"
        ).execute()
        data = resp.data or []
        return data, ""
    except Exception as e:
        print("fetch_users error:", e)
        return [], str(e)


def fetch_sessions():
    """
    Load all sessions from Supabase.
    """
    if not supabase:
        return [], "Supabase not configured"

    try:
        resp = supabase.table("sessions").select(
            "username,completed_sentences,total_recording_duration"
        ).execute()
        data = resp.data or []
        return data, ""
    except Exception as e:
        print("fetch_sessions error:", e)
        return [], str(e)


def get_users_with_sessions(country_filter=None):
    """
    Join users + sessions in Python.
    country_filter: either 'All' / None, or a specific country name.
    """
    users, err_u = fetch_users()
    if err_u:
        return [], f"Users error: {err_u}"

    sessions, err_s = fetch_sessions()
    if err_s:
        return [], f"Sessions error: {err_s}"

    sess_by_username = {s["username"]: s for s in sessions}

    rows = []
    for u in users:
        if country_filter and country_filter != "All":
            if (u.get("country") or "") != country_filter:
                continue

        username = u.get("username")
        sess = sess_by_username.get(username, {})
        total_dur = float(sess.get("total_recording_duration") or 0.0)
        completed_sentences = sess.get("completed_sentences") or []
        rows.append({
            "username": username,
            "name": u.get("name") or "",
            "email": u.get("email") or "",
            "country": u.get("country") or "",
            "dialect_code": u.get("dialect_code") or "",
            "gender": u.get("gender") or "",
            "age": u.get("age") or "",
            "created_at": u.get("created_at") or "",
            "total_duration": total_dur,
            "num_sentences": len(completed_sentences),
        })

    return rows, ""


# ===============================
# S3 HELPERS
# ===============================

def list_user_recordings(username, dialect_code):
    """
    List a user's wav files in S3.

    In main app you use:
      {country_code}/{username}/wavs/{username}_{sentence_id}.wav
    """
    if not S3_CLIENT or not S3_BUCKET:
        return [], "S3 not configured"

    try:
        if "-" in dialect_code:
            country_code = dialect_code.split("-", 1)[0]
        else:
            country_code = dialect_code or "unk"

        prefix = f"{country_code}/{username}/wavs/"
        print("S3 prefix:", prefix)
        resp = S3_CLIENT.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
        print("S3 list_objects_v2 response:", resp)
        contents = resp.get("Contents", [])
        keys = [obj["Key"] for obj in contents]
        return keys, ""
    except Exception as e:
        print("list_user_recordings error:", e)
        return [], str(e)


def generate_presigned_urls(keys):
    """
    Generate presigned URLs for a list of S3 keys.
    Used only for clickable links in Markdown, not for audio preview.
    """
    if not S3_CLIENT or not S3_BUCKET:
        return {}

    urls = {}
    for k in keys:
        try:
            url = S3_CLIENT.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": S3_BUCKET, "Key": k},
                ExpiresIn=3600,  # 1 hour
            )
            print("Presigned URL for", k, ":", url)
            urls[k] = url
        except Exception as e:
            print("generate_presigned_urls error for key", k, ":", e)
    return urls


def load_audio_from_s3(key):
    """
    Download a wav from S3 and return as (sample_rate, numpy_array),
    which gr.Audio(type="numpy") understands.

    This bypasses Gradio's URL downloader and avoids 400 errors.
    """
    if not S3_CLIENT or not S3_BUCKET:
        return None

    try:
        obj = S3_CLIENT.get_object(Bucket=S3_BUCKET, Key=key)
        data = obj["Body"].read()
        audio, sr = sf.read(io.BytesIO(data))  # audio: np.ndarray
        return (sr, audio)
    except Exception as e:
        print("load_audio_from_s3 error for key", key, ":", e)
        return None


# ===============================
# STATS HELPERS
# ===============================

def compute_global_stats(rows):
    """
    rows: list of dicts from get_users_with_sessions(...)
    """
    num_users = len(rows)
    total_duration = sum(r["total_duration"] for r in rows)
    total_sentences = sum(r["num_sentences"] for r in rows)

    avg_duration = total_duration / num_users if num_users > 0 else 0.0
    avg_sentences = total_sentences / num_users if num_users > 0 else 0.0

    return {
        "num_users": num_users,
        "total_duration": total_duration,
        "total_sentences": total_sentences,
        "avg_duration": avg_duration,
        "avg_sentences": avg_sentences,
    }


def make_gender_plot(rows):
    counts = {}
    g_dict = {"ذكر": "Male", "أنثى": "Female"}  # Arabic to English
    for r in rows:
        g = (g_dict[r["gender"]] or "Unknown").strip() or "Unknown"
        counts[g] = counts.get(g, 0) + 1

    if not counts:
        return None

    labels = list(counts.keys())
    values = list(counts.values())

    fig, ax = plt.subplots()
    ax.bar(labels, values)
    ax.set_title("Gender distribution")
    ax.set_ylabel("Number of users")
    ax.set_xlabel("Gender")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    fig.tight_layout()
    return fig


def make_dialect_plot(rows, max_labels=10):
    counts = {}
    for r in rows:
        d = (r["dialect_code"] or "Unknown").strip() or "Unknown"
        counts[d] = counts.get(d, 0) + 1

    if not counts:
        return None

    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    labels = [k for k, _ in sorted_items[:max_labels]]
    values = [v for _, v in sorted_items[:max_labels]]

    fig, ax = plt.subplots()
    ax.bar(labels, values)
    ax.set_title("Dialect distribution (top {})".format(max_labels))
    ax.set_ylabel("Number of users")
    ax.set_xlabel("Dialect code")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    return fig

def make_dialect_time_plot(rows, max_labels=10):
    """
    Total recording minutes per dialect (top N by time).
    """
    if not rows:
        return None

    totals = {}
    for r in rows:
        d = (r["dialect_code"] or "Unknown").strip() or "Unknown"
        totals[d] = totals.get(d, 0.0) + r["total_duration"]

    if not totals:
        return None

    # Sort dialects by total recording time (descending)
    sorted_items = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    labels = [k for k, _ in sorted_items[:max_labels]]
    values = [v / 60.0 for _, v in sorted_items[:max_labels]]  # minutes

    fig, ax = plt.subplots()
    ax.bar(labels, values)
    ax.set_title(f"Top {len(labels)} dialects by total recording time")
    ax.set_ylabel("Total minutes recorded")
    ax.set_xlabel("Dialect code")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    return fig


def make_country_compare_plot(rows):
    """
    Total recording minutes per country (cross-country view).
    """
    if not rows:
        return None

    country_totals = {}
    for r in rows:
        c = (r["country"] or "Unknown").strip() or "Unknown"
        country_totals[c] = country_totals.get(c, 0.0) + r["total_duration"]

    labels = list(country_totals.keys())
    values = [country_totals[c] / 60.0 for c in labels]  # minutes

    fig, ax = plt.subplots()
    ax.bar(labels, values)
    ax.set_title("Total recording time by country")
    ax.set_ylabel("Total minutes recorded")
    ax.set_xlabel("Country")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    return fig


def make_country_progress_plot(rows, target_seconds=RECORDING_TARGET_SECONDS):
    """
    For each country, compare:
      - Achieved total minutes
      - Target total minutes (num_users_in_country * target_seconds)
    """
    if not rows:
        return None

    total_by_country = {}
    users_by_country = {}

    for r in rows:
        c = (r["country"] or "Unknown").strip() or "Unknown"
        total_by_country[c] = total_by_country.get(c, 0.0) + r["total_duration"]
        users_by_country[c] = users_by_country.get(c, 0) + 1

    labels = []
    achieved_min = []
    target_min = []

    for c in total_by_country:
        labels.append(c)
        total_sec = total_by_country[c]
        n_users = users_by_country[c]
        achieved_min.append(total_sec / 60.0)
        target_min.append(n_users * target_seconds / 60.0)

    if not labels:
        return None

    fig, ax = plt.subplots()
    x = range(len(labels))

    ax.bar(x, target_min, label="Target per user)", alpha=0.3)
    ax.bar(x, achieved_min, label="Achieved", width=0.5)

    ax.set_title("Country progress vs target")
    ax.set_ylabel("Total minutes")
    ax.set_xlabel("Country")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.legend()
    fig.tight_layout()
    return fig


def make_duration_histogram(rows, scope_label):
    """
    Distribution of per-user recording duration in minutes (for a single country).
    """
    durations_min = [r["total_duration"] / 60.0 for r in rows if r["total_duration"] > 0.0]
    if not durations_min:
        return None

    fig, ax = plt.subplots()
    ax.hist(durations_min, bins=10)
    ax.axvline(RECORDING_TARGET_MINUTES, linestyle="--", linewidth=1)
    ax.set_title(f"Recording duration distribution – {scope_label}")
    ax.set_xlabel("Minutes recorded per user")
    ax.set_ylabel("Number of users")
    fig.tight_layout()
    return fig


def make_user_progress_plot(rows, scope_label, top_n=5):
    """
    Per-speaker progress vs target (%), for a single country.
    """
    if not rows:
        return None

    sorted_rows = sorted(rows, key=lambda r: r["total_duration"], reverse=True)
    subset = sorted_rows[:top_n]

    labels = [r["username"] for r in subset]
    pct_vals = [
        (r["total_duration"] / RECORDING_TARGET_SECONDS * 100.0) if RECORDING_TARGET_SECONDS > 0 else 0.0
        for r in subset
    ]

    if not labels:
        return None

    fig, ax = plt.subplots()
    x = range(len(labels))
    ax.bar(x, pct_vals)
    ax.axhline(100, linestyle="--", linewidth=1)
    ax.set_title(f"Speaker progress vs target – {scope_label}")
    ax.set_ylabel("% of target")
    ax.set_xlabel("Speakers (sorted by duration)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    fig.tight_layout()
    return fig


# ===============================
# GRADIO ADMIN APP
# ===============================

def build_admin_app():
    with gr.Blocks(title="Arabic Speech Admin Panel") as demo:
        admin_state = gr.State({
            "logged_in": False,
            "admin_email": None,
            "admin_name": None,
            "users_cache": [],
            "recordings_map": {},   # key -> presigned URL for current user (for markdown links)
        })

        gr.Markdown("""
# 🛠️ Admin Panel – Arabic Speech Dataset

Manage admins, view user recordings from S3, and monitor progress.
        """)

        # ---------- LOGIN / SIGN-UP VIEW ----------
        with gr.Row(visible=True) as auth_view:
            # Login column
            with gr.Column(scale=1):
                gr.Markdown("## Admin Login")
                login_email = gr.Textbox(label="Email")
                login_pw = gr.Textbox(label="Password", type="password")
                login_btn = gr.Button("Login", variant="primary")
                login_msg = gr.Markdown("")

            # Sign-up column
            with gr.Column(scale=1):
                gr.Markdown("## Admin Sign up")
                su_name = gr.Textbox(label="Name")
                su_email = gr.Textbox(label="Email")
                su_pw = gr.Textbox(label="Password", type="password")
                su_btn = gr.Button("Sign up")
                su_msg = gr.Markdown("")

        # ---------- MAIN ADMIN VIEW ----------
        with gr.Column(visible=False) as main_view:
            header_md = gr.Markdown("")
            logout_btn = gr.Button("Logout")

            with gr.Tabs():
                # ===== TAB 1: RECORDINGS DASHBOARD =====
                with gr.Tab("Recordings"):
                    gr.Markdown("### View user recordings from S3")

                    country_filter_rec = gr.Dropdown(
                        choices=COUNTRY_FILTER_CHOICES,
                        value="All",
                        label="Filter by country"
                    )
                    load_users_rec_btn = gr.Button("Reload users list")

                    users_df_rec = gr.Dataframe(
                        headers=[
                            "username", "name", "email", "country",
                            "dialect_code", "total_duration(sec)", "#sentences"
                        ],
                        interactive=False,
                        label="Users overview",
                        row_count=(1, "dynamic"),
                    )

                    user_choice_rec = gr.Dropdown(
                        choices=[],
                        label="Select user",
                        value=None,
                    )

                    load_recordings_btn = gr.Button("Load recordings for selected user")

                    selected_user_rec = gr.Textbox(label="Selected username", interactive=False)
                    selected_dialect_rec = gr.Textbox(label="Selected dialect_code", interactive=False)

                    file_choice_rec = gr.Dropdown(
                        choices=[],
                        label="Select recording to preview",
                        value=None,
                    )
                    audio_preview = gr.Audio(
                        label="Preview recording",
                        interactive=False,
                        type="numpy",  # we return (sr, numpy_array) from callbacks
                    )

                    recordings_md = gr.Markdown("")

                # ===== TAB 2: STATISTICS =====
                with gr.Tab("Statistics"):
                    gr.Markdown("### Progress statistics")

                    country_filter_stats = gr.Dropdown(
                        choices=COUNTRY_FILTER_CHOICES,
                        value="All",
                        label="Filter by country"
                    )
                    compute_stats_btn = gr.Button("Compute statistics")

                    stats_md = gr.Markdown("")

                    stats_df = gr.Dataframe(
                        headers=[
                            "username", "country", "dialect_code",
                            "total_duration(sec)", "#sentences", "% of 30-min target"
                        ],
                        interactive=False,
                        label="Per-user stats (top 50 by duration)",
                        row_count=(1, "dynamic"),
                    )

                    gender_plot = gr.Plot(label="Gender distribution")
                    dialect_plot = gr.Plot(label="Dialect distribution")
                    dialect_time_plot = gr.Plot(label="Top dialects by recording time")
                    plot_3 = gr.Plot(label="Recording / country overview")
                    plot_4 = gr.Plot(label="Progress vs target")


        # ======================
        # AUTH CALLBACKS
        # ======================

        def handle_signup(name, email, pw):
            if not (name and email and pw):
                return "❌ Please fill all fields."

            ok, msg = create_admin(name, email, pw)
            prefix = "✅ " if ok else "❌ "
            return prefix + msg

        su_btn.click(
            fn=handle_signup,
            inputs=[su_name, su_email, su_pw],
            outputs=[su_msg],
        )

        def handle_login(email, pw, st):
            ok, msg, admin = authenticate_admin(email, pw)
            if not ok:
                return (
                    st,
                    f"❌ {msg}",
                    gr.update(visible=True),
                    gr.update(visible=False),
                    "",
                )

            st["logged_in"] = True
            st["admin_email"] = admin.get("email")
            st["admin_name"] = admin.get("name")

            header_text = f"### Logged in as **{admin.get('name')}** ({admin.get('email')})"

            return (
                st,
                "",
                gr.update(visible=False),
                gr.update(visible=True),
                header_text,
            )

        login_btn.click(
            fn=handle_login,
            inputs=[login_email, login_pw, admin_state],
            outputs=[admin_state, login_msg, auth_view, main_view, header_md],
        )

        def handle_logout(st):
            st["logged_in"] = False
            st["admin_email"] = None
            st["admin_name"] = None
            st["users_cache"] = []
            st["recordings_map"] = {}
            return (
                st,
                gr.update(visible=True),
                gr.update(visible=False),
                "",
            )

        logout_btn.click(
            fn=handle_logout,
            inputs=[admin_state],
            outputs=[admin_state, auth_view, main_view, header_md],
        )

        # ======================
        # RECORDINGS TAB LOGIC
        # ======================

        def load_users_for_recordings(st, country_filter):
            rows, err = get_users_with_sessions(country_filter)
            if err:
                st["users_cache"] = []
                return (
                    st,
                    [[f"Error: {err}", "", "", "", "", 0.0, 0]],
                    gr.update(choices=[], value=None),
                )

            st["users_cache"] = rows

            table = []
            dropdown_choices = []
            for r in rows:
                table.append([
                    r["username"],
                    r["name"],
                    r["email"],
                    r["country"],
                    r["dialect_code"],
                    round(r["total_duration"], 2),
                    r["num_sentences"],
                ])
                label = f"{r['username']} | {r['name']} | {r['country']} | {r['dialect_code']}"
                dropdown_choices.append(label)

            if not table:
                table = [["<no users>", "", "", "", "", 0.0, 0]]

            default_value = dropdown_choices[0] if dropdown_choices else None

            return st, table, gr.update(choices=dropdown_choices, value=default_value)

        load_users_rec_btn.click(
            fn=load_users_for_recordings,
            inputs=[admin_state, country_filter_rec],
            outputs=[admin_state, users_df_rec, user_choice_rec],
        )

        def load_recordings_for_selected(st, user_choice):
            if not user_choice:
                st["recordings_map"] = {}
                return (
                    st,
                    "❌ Select a user first.",
                    "",
                    "",
                    gr.update(choices=[], value=None),
                    None,
                )

            username = user_choice.split("|", 1)[0].strip()

            dialect_code = "unk"
            for r in st.get("users_cache", []):
                if r["username"] == username:
                    dialect_code = r["dialect_code"]
                    break

            keys, err = list_user_recordings(username, dialect_code)
            if err:
                st["recordings_map"] = {}
                return (
                    st,
                    f"❌ S3 error: `{err}`",
                    username,
                    dialect_code,
                    gr.update(choices=[], value=None),
                    None,
                )

            if not keys:
                st["recordings_map"] = {}
                return (
                    st,
                    f"No recordings found for `{username}`.",
                    username,
                    dialect_code,
                    gr.update(choices=[], value=None),
                    None,
                )

            # Still generate presigned URLs for markdown links (optional)
            url_map = generate_presigned_urls(keys)
            st["recordings_map"] = url_map

            lines = []
            for k in keys:
                url = url_map.get(k)
                if url:
                    lines.append(f"- [{k}]({url})")
                else:
                    lines.append(f"- `{k}` (no URL)")

            md = f"**Recordings for `{username}` ({dialect_code})**:\n\n" + "\n".join(lines)

            choices = keys
            default_key = keys[0]
            default_audio = load_audio_from_s3(default_key)

            return (
                st,
                md,
                username,
                dialect_code,
                gr.update(choices=choices, value=default_key),
                default_audio,
            )

        load_recordings_btn.click(
            fn=load_recordings_for_selected,
            inputs=[admin_state, user_choice_rec],
            outputs=[
                admin_state,
                recordings_md,
                selected_user_rec,
                selected_dialect_rec,
                file_choice_rec,
                audio_preview,
            ],
        )

        def change_preview_file(st, selected_key):
            if not selected_key:
                return None
            # Ignore URLs here; directly load from S3:
            return load_audio_from_s3(selected_key)

        file_choice_rec.change(
            fn=change_preview_file,
            inputs=[admin_state, file_choice_rec],
            outputs=[audio_preview],
        )

        # ======================
        # STATISTICS TAB LOGIC
        # ======================

        def handle_compute_stats(country_filter):
            rows, err = get_users_with_sessions(country_filter)
            if err:
                empty_table = [["", "", "", 0.0, 0, 0.0]]
                return (
                    f"❌ Error: `{err}`",
                    empty_table,
                    None,
                    None,
                    None,
                    None,
                    None,
                )

            # Keep only users who actually recorded something
            rows = [r for r in rows if r["total_duration"] > 0.0]

            stats = compute_global_stats(rows)

            total_sec = stats["total_duration"]
            total_min = int(total_sec // 60)
            total_h  = int(total_min / 60)
            total_sec_rem = int(total_sec % 60)

            avg_sec = stats["avg_duration"]
            avg_min = int(avg_sec // 60)
            avg_h   = int(avg_min / 60)
            avg_sec_rem = int(avg_sec % 60)

            # How many users hit / did not hit the 30-min target
            users_above_target = sum(
                1 for r in rows if r["total_duration"] >= RECORDING_TARGET_SECONDS
            )
            users_below_target = len(rows) - users_above_target

            scope_label = (
                "All countries"
                if not country_filter or country_filter == "All"
                else country_filter
            )

            md = f"""
#### Global statistics ({scope_label})

- Users with any data: **{stats['num_users']}**
- Total recording time: **{total_min}m {total_sec_rem}s** (≈ {total_h:.1f} h)
- Total recorded sentences: **{stats['total_sentences']}**
- Average duration per user: **{avg_min}m {avg_sec_rem}s** (≈ {avg_h:.1f} h)
- Average #sentences per user: **{stats['avg_sentences']:.2f}**

- Users at or above {RECORDING_TARGET_MINUTES} min: **{users_above_target}**
- Users below {RECORDING_TARGET_MINUTES} min: **{users_below_target}**
"""

            # Per-user table: top 50 by duration, with % of target
            sorted_rows = sorted(rows, key=lambda r: r["total_duration"], reverse=True)
            top_n = 50
            table = []
            for r in sorted_rows[:top_n]:
                pct_target = (
                    (r["total_duration"] / RECORDING_TARGET_SECONDS) * 100.0
                    if RECORDING_TARGET_SECONDS > 0
                    else 0.0
                )
                table.append([
                    r["username"],
                    r["country"],
                    r["dialect_code"],
                    round(r["total_duration"], 2),
                    r["num_sentences"],
                    round(pct_target, 1),
                ])
            if not table:
                table = [["<no users>", "", "", 0.0, 0, 0.0]]

            # Plots:
            #  - Gender & dialect always computed on the filtered set (All or specific country)
            #  - plot_3 and plot_4 depend on whether we are in "All" or per-country mode
            gender_fig = make_gender_plot(rows)
            dialect_fig = make_dialect_plot(rows)
            dialect_time_fig = make_dialect_time_plot(rows)

            if not country_filter or country_filter == "All":
                # Cross-country overview
                country_compare_fig = make_country_compare_plot(rows)
                progress_fig = make_country_progress_plot(rows)
            else:
                # Detailed per-speaker view within a single country
                country_compare_fig = make_duration_histogram(rows, scope_label)
                progress_fig = make_user_progress_plot(rows, scope_label)

            return md, table, gender_fig, dialect_fig, dialect_time_fig, country_compare_fig, progress_fig

        compute_stats_btn.click(
            fn=handle_compute_stats,
            inputs=[country_filter_stats],
            outputs=[stats_md, stats_df, gender_plot, dialect_plot, dialect_time_plot, plot_3, plot_4],
        )

    return demo


if __name__ == "__main__":
    port = int(os.environ.get("GRADIO_ADMIN_PORT", 7861))
    app = build_admin_app()
    app.launch(
        server_name="0.0.0.0",
        server_port=port,
        debug=False,
    )
