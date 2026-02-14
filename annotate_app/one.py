# backfill_duration_sec.py
# One-time script to fill duration_sec for OLD annotation rows (where duration_sec is NULL).
# Run locally or as a one-off Railway job with the same env vars as your app.

import os
import io
import time
import wave
import boto3
from supabase import create_client
from pathlib import Path
from dotenv import load_dotenv
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
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
def make_s3():
    if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
        return boto3.client("s3", region_name=AWS_REGION)
    return boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION,
    )

S3 = make_s3()
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

def s3_get_range_bytes(key: str, end: int) -> bytes:
    obj = S3.get_object(Bucket=S3_BUCKET, Key=key, Range=f"bytes=0-{end}")
    return obj["Body"].read()

def wav_duration_seconds_from_s3(key: str) -> float:
    for end in (65535, 262143, 1048575):
        try:
            b = s3_get_range_bytes(key, end)
            with wave.open(io.BytesIO(b), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate and rate > 0:
                    return frames / float(rate)
        except Exception:
            pass

    # fallback full
    obj = S3.get_object(Bucket=S3_BUCKET, Key=key)
    b = obj["Body"].read()
    with wave.open(io.BytesIO(b), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())

def backfill(batch_size: int = 200, sleep_sec: float = 0.1):
    """
    Updates rows where duration_sec IS NULL.
    Assumes your annotations table has an 'id' primary key.
    If you don't have 'id', use sample_id instead (see comment below).
    """
    updated = 0
    offset = 0

    while True:
        resp = (
            sb.table("annotations")
            .select("id,s3_audio_key,duration_sec")
            .is_("duration_sec", "null")
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            break

        for r in rows:
            row_id = r.get("id")
            key = r.get("s3_audio_key")
            if not row_id or not key:
                continue

            try:
                dur = float(wav_duration_seconds_from_s3(key))
                sb.table("annotations").update({"duration_sec": dur}).eq("id", row_id).execute()

                updated += 1
                if updated % 50 == 0:
                    print("updated:", updated)
            except Exception as e:
                print("FAILED row:", row_id, "key:", key, "err:", e)

        time.sleep(sleep_sec)

        # NOTE:
        # We do NOT increase offset here because we're always querying NULL rows.
        # After updating them, they disappear from the result set, so we just keep reading from the start.

    print("DONE. total updated:", updated)

if __name__ == "__main__":
    backfill()
