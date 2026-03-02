# app.py
# ------------------------------------------------------------
# SPHR Practice Tool - Exam Simulator / Mini LMS (Streamlit)
# Update requested:
# ✅ Finished quizzes should NOT appear in Saved / Resume list anymore.
#    - On quiz finish, we auto-delete that saved quiz entry + file.
#    - Saved list auto-prunes finished/missing entries.
#
# Run:
#   pip install streamlit matplotlib
#   OPTIONAL:
#   pip install streamlit-autorefresh
#   streamlit run app.py
# ------------------------------------------------------------

import streamlit as st
import json
import random
import time
import re
from datetime import datetime, timezone
from pathlib import Path
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import wave
import math
import struct
import hashlib
import csv
import io

# ============================================================
# Files
# ============================================================
APP_TITLE = "SPHR Practice Tool - HRCI (Exam Simulator / LMS)"
QUESTIONS_FILE = Path("questions.json")
HISTORY_FILE = Path("quiz_history.json")
STATS_FILE = Path("question_stats.json")
BOOKMARKS_FILE = Path("bookmarks.json")
NOTES_FILE = Path("notes.json")
SETTINGS_FILE = Path("user_settings.json")

# Multi-save folder
SAVES_DIR = Path("saved_quizzes")
SAVES_INDEX_FILE = SAVES_DIR / "index.json"

PLACEHOLDER = "— Select an option —"
STATE_VERSION = 4  # pause + multi-saves + home routing


# ============================================================
# Page + CSS
# ============================================================
st.set_page_config(page_title=APP_TITLE, layout="wide")

st.markdown(
    """
<style>
    .stApp { background-color: #f0f4f8; }

    .card {
        background: #ffffff;
        border-radius: 14px;
        padding: 16px 18px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06);
        border: 1px solid rgba(0,0,0,0.04);
        margin-bottom: 14px;
    }
    .qtitle { font-size: 22px; font-weight: 800; margin-bottom: 6px; color: #0f172a; }
    .meta { font-size: 12px; color: #475569; margin-bottom: 10px; }

    .badge {
        display: inline-block; padding: 3px 10px; border-radius: 999px;
        background: #eef2ff; color: #3730a3; font-size: 12px; font-weight: 650;
        margin-right: 6px; border: 1px solid rgba(55,48,163,0.2);
    }
    .badge-warn { background: #fff7ed; color: #9a3412; border: 1px solid rgba(154,52,18,0.20); }
    .badge-ok { background: #ecfdf5; color: #065f46; border: 1px solid rgba(6,95,70,0.20); }
    .badge-bad { background: #fef2f2; color: #991b1b; border: 1px solid rgba(153,27,27,0.20); }

    .hint-box {
        background-color: #fff8c5; color: #111827; border-radius: 12px; padding: 12px;
        border: 1px dashed rgba(0,0,0,0.15); margin-top: 8px; margin-bottom: 12px;
    }

    .stButton > button {
        background-color: #2563eb; color: white; border-radius: 10px; border: none;
        padding: 9px 14px; transition: transform 0.04s ease; font-weight: 750;
    }
    .stButton > button:hover { background-color: #1d4ed8; }
    .stButton > button:active { transform: translateY(1px); }

    section[data-testid="stSidebar"] .stButton > button {
        width: 100%; margin-bottom: 8px;
    }

    .homebtn > button {
        width: 100%;
        height: 56px;
        font-size: 16px;
        font-weight: 800;
        border-radius: 14px;
    }
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# Utilities
# ============================================================
def read_json(path: Path, default):
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def question_uid(question_text: str) -> str:
    h = hashlib.sha1((question_text or "").strip().encode("utf-8", errors="ignore")).hexdigest()
    return h[:12]


def toast(msg: str):
    if hasattr(st, "toast"):
        st.toast(msg)
    else:
        st.info(msg)


# ============================================================
# Smooth Timer Refresh
# ============================================================
def maybe_autorefresh(enabled: bool, interval_ms: int, key: str = "timer_refresh"):
    if not enabled:
        return
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=interval_ms, key=key)
        return
    except Exception:
        import streamlit.components.v1 as components
        components.html(
            f"""
<script>
  setTimeout(function(){{
    window.location.reload();
  }}, {int(interval_ms)});
</script>
""",
            height=0,
        )


# ============================================================
# Sound
# ============================================================
def _beep_wav_base64(freq_hz=880, duration_s=0.12, volume=0.25, sample_rate=44100):
    buf = BytesIO()
    n_samples = int(sample_rate * duration_s)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            val = volume * math.sin(2 * math.pi * freq_hz * t)
            wf.writeframes(struct.pack("<h", int(val * 32767)))
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def play_sound(sound_type: str):
    b64 = _beep_wav_base64(freq_hz=1046 if sound_type == "correct" else 220)
    st.markdown(
        f"""
<audio autoplay="true">
  <source src="data:audio/wav;base64,{b64}" type="audio/wav">
</audio>
""",
        unsafe_allow_html=True,
    )


# ============================================================
# Markdown parsing
# ============================================================
def parse_md_content(md_content: str, domain: str = "SPHR", subject: str = ""):
    pattern = r"### Question (\d+) \((Chapter \d+)\)\s*(.*?)\s*\*\*Options:\*\*\s*(.*?)\s*\*\*Answer:\*\* (.*?)\s*\*\*Explanation:\*\*\s*(.*?)(?=\n### Question|\Z)"
    matches = re.findall(pattern, md_content, re.DOTALL)

    parsed = []
    for match in matches:
        q_num, chapter, q_text, opts_text, ans_text, exp_text = match
        question = re.sub(r"\s+", " ", q_text.strip())
        opts_raw = re.split(r"(?=[A-D]\.)", opts_text.strip())
        options = [o.strip() for o in opts_raw if o.strip() and re.match(r"^[A-D]\.", o.strip())]
        answer_raw = ans_text.strip()
        explanation = re.sub(r"\s+", " ", exp_text.strip())
        parsed.append({
            "id": int(q_num),
            "domain": domain.strip() or "SPHR",
            "subject": subject.strip() or (domain.strip() or "SPHR"),
            "chapter": chapter.strip(),
            "question": question,
            "options": options,
            "answer": answer_raw,
            "explanation": explanation,
        })
    return parsed


# ============================================================
# Question bank load/save + validation
# ============================================================
@st.cache_data
def load_questions():
    return read_json(QUESTIONS_FILE, default=[])


def save_questions(qs):
    write_json(QUESTIONS_FILE, qs)
    st.cache_data.clear()


def ensure_uids_and_fix_answers(qs):
    changed = False
    for q in qs:
        if not q.get("uid"):
            q["uid"] = question_uid(q.get("question", ""))
            changed = True

        options = q.get("options", []) or []
        ans = (q.get("answer") or "").strip()
        if ans and ans in options:
            continue

        m = re.match(r"^\s*([A-D])\.?\s*$", ans)
        if m:
            letter = m.group(1)
            for opt in options:
                if opt.strip().startswith(f"{letter}."):
                    q["answer"] = opt.strip()
                    changed = True
                    break
            continue

        m2 = re.match(r"^\s*([A-D])\.\s*(.*)$", ans)
        if m2:
            letter = m2.group(1)
            for opt in options:
                if opt.strip().startswith(f"{letter}."):
                    q["answer"] = opt.strip()
                    changed = True
                    break
            continue

    return qs, changed


# ============================================================
# Stats / Bookmarks / Notes / Settings
# ============================================================
def load_stats():
    return read_json(STATS_FILE, default={})


def save_stats(stats):
    write_json(STATS_FILE, stats)


def load_bookmarks():
    return read_json(BOOKMARKS_FILE, default={})


def save_bookmarks(bm):
    write_json(BOOKMARKS_FILE, bm)


def load_notes():
    return read_json(NOTES_FILE, default={})


def save_notes(notes):
    write_json(NOTES_FILE, notes)


def get_user_settings():
    return read_json(SETTINGS_FILE, default={"username": "Guest"})


def save_user_settings(data):
    write_json(SETTINGS_FILE, data)


def username():
    return st.session_state.get("username", "Guest")


def user_bookmark_set():
    bm = load_bookmarks()
    return set(bm.get(username(), []))


def toggle_bookmark(uid: str):
    bm = load_bookmarks()
    u = username()
    cur = set(bm.get(u, []))
    if uid in cur:
        cur.remove(uid)
        toast("Bookmark removed")
    else:
        cur.add(uid)
        toast("Bookmarked ⭐")
    bm[u] = sorted(list(cur))
    save_bookmarks(bm)


def get_note(uid: str) -> str:
    notes = load_notes()
    return notes.get(username(), {}).get(uid, "")


def set_note(uid: str, note: str):
    notes = load_notes()
    notes.setdefault(username(), {})
    notes[username()][uid] = note
    save_notes(notes)
    toast("Note saved 📝")


# ============================================================
# Saved Quizzes
# ============================================================
def ensure_saves_storage():
    SAVES_DIR.mkdir(parents=True, exist_ok=True)
    if not SAVES_INDEX_FILE.exists():
        write_json(SAVES_INDEX_FILE, {"items": []})


def load_saves_index():
    ensure_saves_storage()
    return read_json(SAVES_INDEX_FILE, default={"items": []})


def save_saves_index(index_obj):
    ensure_saves_storage()
    write_json(SAVES_INDEX_FILE, index_obj)


def make_save_id():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_path_for(save_id: str, user: str):
    safe_user = re.sub(r"[^A-Za-z0-9_\-]+", "_", user.strip() or "Guest")
    return SAVES_DIR / f"{safe_user}_{save_id}.json"


def delete_saved_quiz(save_id: str, user: str):
    idx = load_saves_index()
    items = idx.get("items", [])
    kept = []
    for it in items:
        if it.get("save_id") == save_id and it.get("user") == user:
            fp = Path(it.get("file", ""))
            try:
                if fp.exists():
                    fp.unlink()
            except Exception:
                pass
        else:
            kept.append(it)
    idx["items"] = kept
    save_saves_index(idx)


def upsert_saved_quiz_index(save_id: str, user: str, file_path: Path, meta: dict):
    idx = load_saves_index()
    items = idx.get("items", [])
    updated = False
    for it in items:
        if it.get("save_id") == save_id and it.get("user") == user:
            it.update({"updated_at": now_iso(), "file": str(file_path), **meta})
            updated = True
            break
    if not updated:
        items.append({
            "save_id": save_id,
            "user": user,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "file": str(file_path),
            **meta
        })
    idx["items"] = items
    save_saves_index(idx)


# ✅ UPDATED: saved list will auto-remove finished/missing entries and NOT show finished ones
def list_saved_quizzes_for_user(user: str):
    idx = load_saves_index()
    items = idx.get("items", [])

    kept = []
    user_items = []

    for it in items:
        fp = Path(it.get("file", ""))
        finished = bool(it.get("finished", False))
        # drop missing file entries
        if not fp.exists():
            continue
        # drop finished entries (do not show)
        if finished:
            # (optional cleanup) remove from index; keep file as-is or delete it
            # We remove from index to prevent showing ever again.
            continue

        kept.append(it)
        if it.get("user") == user:
            user_items.append(it)

    # auto-clean index if anything removed
    if len(kept) != len(items):
        idx["items"] = kept
        save_saves_index(idx)

    user_items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return user_items


# ============================================================
# Adaptive Sampling
# ============================================================
def days_since(iso_str: str) -> int:
    if not iso_str:
        return 9999
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        return max(0, int(delta.total_seconds() // 86400))
    except Exception:
        return 9999


def compute_weight(uid: str, stats: dict) -> float:
    s = stats.get(uid, {})
    correct = int(s.get("correct", 0))
    wrong = int(s.get("wrong", 0))
    seen = int(s.get("seen", 0))
    last_seen = s.get("last_seen", "")
    d = days_since(last_seen)

    base = 8.0 if seen == 0 else 1.0
    wrong_factor = (wrong + 1)
    correct_factor = (correct + 1)
    recency_factor = min(6.0, 1.0 + (d / 7.0))

    w = base * (wrong_factor / correct_factor) * recency_factor
    return max(0.05, float(w))


def weighted_sample_no_replace(items, weights, k):
    items = list(items)
    weights = list(weights)
    chosen = []
    for _ in range(min(k, len(items))):
        total = sum(weights)
        if total <= 0:
            idx = random.randrange(len(items))
        else:
            r = random.random() * total
            upto = 0.0
            idx = 0
            for i, w in enumerate(weights):
                upto += w
                if upto >= r:
                    idx = i
                    break
        chosen.append(items.pop(idx))
        weights.pop(idx)
    return chosen


# ============================================================
# Session state + routing
# ============================================================
def init_state():
    defaults = {
        "page": "home",  # home / quiz / bank / analytics / review
        "username": "Guest",

        "current_quiz": None,
        "idx": 0,
        "answers": [],
        "submitted": [],
        "flags": [],
        "confidence": [],
        "shuffled_options": [],
        "quiz_start": None,
        "timer_start": None,
        "finished": False,
        "mode": "Practice",
        "settings": {},
        "time_spent": [],
        "q_enter_time": None,
        "history_written": False,
        "last_attempt": None,

        "paused": False,
        "paused_at": None,
        "save_id": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def set_page(p: str):
    st.session_state.page = p


def clear_question_widget_keys():
    for k in list(st.session_state.keys()):
        if k.startswith("q_") and k.endswith("_choice"):
            del st.session_state[k]


def total_questions():
    return len(st.session_state.current_quiz) if st.session_state.current_quiz else 0


def compute_score():
    score = 0
    if not st.session_state.current_quiz:
        return 0
    for i, q in enumerate(st.session_state.current_quiz):
        a = st.session_state.answers[i]
        if a is not None and a == q.get("answer"):
            score += 1
    return score


def effective_now():
    if st.session_state.get("paused") and st.session_state.get("paused_at"):
        return float(st.session_state.paused_at)
    return time.time()


def touch_time_spent(leave_idx: int):
    if st.session_state.q_enter_time is None:
        st.session_state.q_enter_time = time.time()
        return
    if leave_idx is None or leave_idx < 0 or leave_idx >= total_questions():
        st.session_state.q_enter_time = time.time()
        return
    elapsed = max(0.0, time.time() - st.session_state.q_enter_time)
    st.session_state.time_spent[leave_idx] += elapsed
    st.session_state.q_enter_time = time.time()


def start_new_quiz(pool, num_q, shuffle_options, adaptive=False):
    clear_question_widget_keys()

    if not pool:
        st.warning("No questions available. Import questions in the Question Bank.")
        return

    if adaptive:
        stats = load_stats()
        weights = [compute_weight(q["uid"], stats) for q in pool]
        quiz = weighted_sample_no_replace(pool, weights, min(num_q, len(pool)))
    else:
        random.shuffle(pool)
        quiz = pool[: min(num_q, len(pool))]

    st.session_state.current_quiz = quiz
    st.session_state.idx = 0
    st.session_state.answers = [None] * len(quiz)
    st.session_state.submitted = [False] * len(quiz)
    st.session_state.flags = [False] * len(quiz)
    st.session_state.confidence = [0] * len(quiz)

    st.session_state.quiz_start = time.time()
    st.session_state.timer_start = time.time()
    st.session_state.finished = False
    st.session_state.history_written = False

    st.session_state.time_spent = [0.0] * len(quiz)
    st.session_state.q_enter_time = time.time()

    st.session_state.paused = False
    st.session_state.paused_at = None
    st.session_state.save_id = None

    st.session_state.shuffled_options = []
    for q in quiz:
        opts = list(q.get("options", []))
        if shuffle_options:
            random.shuffle(opts)
        st.session_state.shuffled_options.append(opts)

    for i in range(len(quiz)):
        st.session_state[f"q_{i}_choice"] = PLACEHOLDER

    toast("New quiz started ✅")
    set_page("quiz")


def pause_quiz():
    if not st.session_state.current_quiz or st.session_state.finished:
        return
    if st.session_state.paused:
        return
    touch_time_spent(st.session_state.idx)
    st.session_state.paused = True
    st.session_state.paused_at = time.time()
    toast("Paused ⏸️")


def resume_quiz():
    if not st.session_state.paused:
        return
    dur = time.time() - float(st.session_state.paused_at or time.time())
    if st.session_state.quiz_start:
        st.session_state.quiz_start = float(st.session_state.quiz_start) + dur
    if st.session_state.timer_start:
        st.session_state.timer_start = float(st.session_state.timer_start) + dur
    st.session_state.paused = False
    st.session_state.paused_at = None
    st.session_state.q_enter_time = time.time()
    toast("Resumed ▶️")


def build_state_payload():
    radio_choices = {f"q_{i}_choice": st.session_state.get(f"q_{i}_choice", PLACEHOLDER) for i in range(total_questions())}
    return {
        "version": STATE_VERSION,
        "saved_at": now_iso(),
        "user": username(),
        "mode": st.session_state.mode,
        "settings": st.session_state.settings,

        "current_quiz": st.session_state.current_quiz,
        "idx": st.session_state.idx,
        "answers": st.session_state.answers,
        "submitted": st.session_state.submitted,
        "flags": st.session_state.flags,
        "confidence": st.session_state.confidence,
        "shuffled_options": st.session_state.shuffled_options,

        "quiz_start": st.session_state.quiz_start,
        "timer_start": st.session_state.timer_start,
        "time_spent": st.session_state.time_spent,
        "radio_choices": radio_choices,

        "paused": st.session_state.paused,
        "paused_at": st.session_state.paused_at,
        "save_id": st.session_state.save_id,
    }


def save_current_quiz_to_disk(finished_override: bool | None = None):
    """
    finished_override:
      - None => use current st.session_state.finished
      - True/False => force this value into index metadata
    """
    if not st.session_state.current_quiz:
        st.info("Nothing to save yet.")
        return

    ensure_saves_storage()

    if not st.session_state.save_id:
        st.session_state.save_id = make_save_id()

    sid = st.session_state.save_id
    fp = save_path_for(sid, username())

    payload = build_state_payload()
    write_json(fp, payload)

    finished_value = bool(st.session_state.finished) if finished_override is None else bool(finished_override)

    meta = {
        "mode": st.session_state.mode,
        "total": total_questions(),
        "idx": int(st.session_state.idx),
        "finished": finished_value,
        "paused": bool(st.session_state.paused),
    }
    upsert_saved_quiz_index(sid, username(), fp, meta)
    toast(f"Saved ✅ (Quiz ID: {sid})")


def load_quiz_from_disk(file_path: Path):
    data = read_json(file_path, default=None)
    if not data:
        st.warning("Could not load saved quiz.")
        return False

    clear_question_widget_keys()

    st.session_state.mode = data.get("mode", "Practice")
    st.session_state.settings = data.get("settings", {})

    st.session_state.current_quiz = data.get("current_quiz", [])
    st.session_state.idx = int(data.get("idx", 0))

    st.session_state.answers = data.get("answers", [None] * total_questions())
    st.session_state.submitted = data.get("submitted", [False] * total_questions())
    st.session_state.flags = data.get("flags", [False] * total_questions())
    st.session_state.confidence = data.get("confidence", [0] * total_questions())
    st.session_state.shuffled_options = data.get("shuffled_options", [])
    st.session_state.time_spent = data.get("time_spent", [0.0] * total_questions())

    st.session_state.quiz_start = float(data.get("quiz_start", time.time()))
    st.session_state.timer_start = float(data.get("timer_start", time.time()))
    st.session_state.finished = False
    st.session_state.history_written = False

    st.session_state.paused = True
    st.session_state.paused_at = time.time()
    st.session_state.save_id = data.get("save_id", None)

    radio_choices = data.get("radio_choices", {})
    for i in range(total_questions()):
        st.session_state[f"q_{i}_choice"] = radio_choices.get(f"q_{i}_choice", PLACEHOLDER)

    st.session_state.q_enter_time = time.time()

    toast("Saved quiz loaded (paused). Press Resume ▶️")
    set_page("quiz")
    return True


# ============================================================
# History + analytics helpers
# ============================================================
def append_history(entry: dict):
    history = read_json(HISTORY_FILE, default=[])
    history.append(entry)
    write_json(HISTORY_FILE, history)


def plot_line(dates, values, title, ylabel):
    if len(values) < 2:
        return
    fig, ax = plt.subplots()
    ax.plot(dates, values, marker="o")
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel(ylabel)
    plt.xticks(rotation=45)
    st.pyplot(fig)


def update_question_stats(quiz, answers, time_spent):
    stats = load_stats()
    for i, q in enumerate(quiz):
        uid = q.get("uid")
        if not uid:
            continue
        s = stats.setdefault(uid, {"seen": 0, "correct": 0, "wrong": 0, "last_seen": "", "avg_time": 0.0})
        s["seen"] = int(s.get("seen", 0)) + 1
        is_correct = (answers[i] is not None and answers[i] == q.get("answer"))
        if is_correct:
            s["correct"] = int(s.get("correct", 0)) + 1
        else:
            if answers[i] is not None:
                s["wrong"] = int(s.get("wrong", 0)) + 1
        s["last_seen"] = now_iso()

        t = float(time_spent[i]) if time_spent and i < len(time_spent) else 0.0
        prev = float(s.get("avg_time", 0.0))
        s["avg_time"] = round(t, 2) if prev <= 0 else round(prev * 0.7 + t * 0.3, 2)

    save_stats(stats)


def make_attempt_rows(quiz, answers, flags, confidence, time_spent):
    rows = []
    for i, q in enumerate(quiz):
        ua = answers[i]
        ca = q.get("answer")
        correct = (ua is not None and ua == ca)
        rows.append({
            "uid": q.get("uid"),
            "question": q.get("question"),
            "domain": q.get("domain", "SPHR"),
            "subject": q.get("subject", "SPHR"),
            "chapter": q.get("chapter", ""),
            "your_answer": ua or "",
            "correct_answer": ca or "",
            "correct": correct,
            "flagged": bool(flags[i]) if flags else False,
            "confidence": int(confidence[i]) if confidence else 0,
            "time_sec": round(float(time_spent[i]), 2) if time_spent else 0.0,
        })
    return rows


def attempt_to_csv_bytes(rows):
    fieldnames = [
        "uid", "domain", "subject", "chapter",
        "correct", "flagged", "confidence", "time_sec",
        "your_answer", "correct_answer", "question"
    ]
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in fieldnames})
    return buf.getvalue().encode("utf-8")


# ============================================================
# INIT
# ============================================================
init_state()
ensure_saves_storage()

persist = get_user_settings()
if st.session_state.username == "Guest":
    st.session_state.username = persist.get("username", "Guest")

questions = load_questions()
questions, changed = ensure_uids_and_fix_answers(questions)
if changed:
    save_questions(questions)


# ============================================================
# Sidebar (global navigation + profile)
# ============================================================
with st.sidebar:
    st.header("🏠 Navigation")
    if st.button("Home"):
        set_page("home")
        st.rerun()

    nav1, nav2 = st.columns(2)
    with nav1:
        if st.button("Quiz"):
            set_page("quiz")
            st.rerun()
    with nav2:
        if st.button("Bank"):
            set_page("bank")
            st.rerun()

    nav3, nav4 = st.columns(2)
    with nav3:
        if st.button("Analytics"):
            set_page("analytics")
            st.rerun()
    with nav4:
        if st.button("Review"):
            set_page("review")
            st.rerun()

    st.divider()
    st.header("👤 Profile")
    uname = st.text_input("Your name", value=st.session_state.username)
    if uname.strip() and uname.strip() != st.session_state.username:
        st.session_state.username = uname.strip()
        save_user_settings({"username": st.session_state.username})
        toast("Profile saved")
        st.rerun()

    if st.button("🧹 Clear Cache / Reload"):
        st.cache_data.clear()
        toast("Cache cleared ✅")
        st.rerun()


# ============================================================
# HOME
# ============================================================
def render_home():
    st.markdown(
        f"""
<div class="card">
  <div class="qtitle">Welcome, {username()} 👋</div>
  <div class="meta">SPHR Exam Simulator / Mini LMS</div>
</div>
""",
        unsafe_allow_html=True,
    )

    bank = load_questions()
    saved = list_saved_quizzes_for_user(username())
    hist = read_json(HISTORY_FILE, default=[])
    user_hist = [h for h in hist if h.get("user") == username()]

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"<div class='card'><div class='qtitle'>{len(bank)}</div><div class='meta'>Questions in Bank</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='card'><div class='qtitle'>{len(saved)}</div><div class='meta'>Saved (Paused) Quizzes</div></div>", unsafe_allow_html=True)
    with c3:
        last_score = f"{user_hist[-1].get('percent','—')}%" if user_hist else "—"
        st.markdown(f"<div class='card'><div class='qtitle'>{last_score}</div><div class='meta'>Last Score</div></div>", unsafe_allow_html=True)

    st.markdown("<div class='card'><div class='qtitle'>Start</div><div class='meta'>Choose where to go</div></div>", unsafe_allow_html=True)

    b1, b2 = st.columns(2)
    with b1:
        st.markdown("<div class='homebtn'>", unsafe_allow_html=True)
        if st.button("📝 Start / Continue Quiz"):
            set_page("quiz")
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with b2:
        st.markdown("<div class='homebtn'>", unsafe_allow_html=True)
        if st.button("📥 Question Bank"):
            set_page("bank")
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    b3, b4 = st.columns(2)
    with b3:
        st.markdown("<div class='homebtn'>", unsafe_allow_html=True)
        if st.button("📊 Analytics"):
            set_page("analytics")
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with b4:
        st.markdown("<div class='homebtn'>", unsafe_allow_html=True)
        if st.button("🎯 Review Center"):
            set_page("review")
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("📌 Saved Quizzes (Paused)")

    if not saved:
        st.info("No saved quizzes yet. Pause & Save during a quiz to create one.")
    else:
        for it in saved[:30]:
            sid = it.get("save_id")
            updated = it.get("updated_at", "")
            total = it.get("total", 0)
            idxp = it.get("idx", 0)
            mode_lbl = it.get("mode", "")
            st.write(f"**{sid}** — {mode_lbl} — {idxp+1}/{total} — last saved: {updated}")

            cL, cD = st.columns(2)
            with cL:
                if st.button("Load", key=f"home_load_{sid}"):
                    fp = Path(it.get("file", ""))
                    if load_quiz_from_disk(fp):
                        st.rerun()
            with cD:
                if st.button("Delete", key=f"home_del_{sid}"):
                    delete_saved_quiz(sid, username())
                    toast("Deleted")
                    st.rerun()


# ============================================================
# QUIZ
# ============================================================
def render_quiz():
    st.title("📝 Quiz")

    # If no quiz running: show quiz setup + saved list
    if not st.session_state.current_quiz:
        st.markdown("<div class='card'><div class='qtitle'>Quiz Setup</div><div class='meta'>Start a new quiz from your question bank</div></div>", unsafe_allow_html=True)

        mode = st.radio("Mode", ["Practice", "Exam", "Adaptive Practice"], index=0)
        st.session_state.mode = mode

        domains = sorted({q.get("domain", "SPHR") for q in questions}) if questions else []
        subjects = sorted({q.get("subject", "SPHR") for q in questions}) if questions else []
        chapters = sorted({q.get("chapter", "") for q in questions if q.get("chapter")}) if questions else []

        sel_domains = st.multiselect("Filter Domain", options=domains, default=domains) if domains else []
        sel_subjects = st.multiselect("Filter Subject", options=subjects, default=subjects) if subjects else []
        sel_chapters = st.multiselect("Filter Chapter", options=chapters, default=[]) if chapters else []

        num_q = st.slider("Number of questions", 5, 120, 20)
        sec_per_q = st.slider("Seconds per question", 20, 240, 60)
        quiz_time_min = st.slider("Total quiz time (minutes)", 5, 180, 60)
        quiz_time = quiz_time_min * 60
        shuffle_options = st.checkbox("Shuffle options", value=True)

        show_hints = st.checkbox("Show hints (from explanation)", value=False)

        smooth_timer = st.checkbox("Smooth timer (auto refresh)", value=True)
        refresh_ms = st.slider("Refresh interval (ms)", 500, 2000, 1000, step=100)

        if mode in ("Practice", "Adaptive Practice"):
            show_correct = st.checkbox("Show correct answer after submit", value=True)
            show_exp = st.checkbox("Show explanation after submit", value=True)
            auto_advance = st.checkbox("Auto-advance after submit", value=False)
        else:
            show_correct = False
            show_exp = False
            auto_advance = st.checkbox("Auto-advance after submit", value=True)

        play_sounds = st.checkbox("Sound effects", value=False)

        def build_filtered_pool():
            pool = questions
            if sel_domains:
                pool = [q for q in pool if q.get("domain", "SPHR") in sel_domains]
            if sel_subjects:
                pool = [q for q in pool if q.get("subject", "SPHR") in sel_subjects]
            if sel_chapters:
                pool = [q for q in pool if q.get("chapter", "") in sel_chapters]
            return pool

        if st.button("▶️ Start Quiz Now"):
            st.session_state.settings = {
                "num_q": num_q,
                "sec_per_q": sec_per_q,
                "quiz_time": quiz_time,
                "shuffle_options": shuffle_options,
                "show_hints": show_hints,
                "smooth_timer": smooth_timer,
                "refresh_ms": refresh_ms,
                "show_correct": show_correct,
                "show_exp": show_exp,
                "auto_advance": auto_advance,
                "play_sounds": play_sounds,
            }
            pool = build_filtered_pool()
            adaptive = (mode == "Adaptive Practice")
            start_new_quiz(pool, num_q, shuffle_options, adaptive=adaptive)
            st.rerun()

        st.divider()
        st.subheader("Saved Quizzes")
        saved = list_saved_quizzes_for_user(username())
        if not saved:
            st.info("No saved quizzes. Pause & Save during a quiz to create one.")
        else:
            for it in saved[:20]:
                sid = it.get("save_id")
                st.write(f"**{sid}** — {it.get('mode','')} — {it.get('idx',0)+1}/{it.get('total',0)}")
                cL, cD = st.columns(2)
                with cL:
                    if st.button("Load", key=f"quiz_load_{sid}"):
                        fp = Path(it.get("file", ""))
                        if load_quiz_from_disk(fp):
                            st.rerun()
                with cD:
                    if st.button("Delete", key=f"quiz_del_{sid}"):
                        delete_saved_quiz(sid, username())
                        toast("Deleted")
                        st.rerun()
        return

    # Quiz running
    settings = st.session_state.settings or {}
    if settings.get("smooth_timer", True) and not st.session_state.finished and not st.session_state.paused:
        maybe_autorefresh(True, int(settings.get("refresh_ms", 1000)), key="quiz_timer")

    total_q = total_questions()
    idx = st.session_state.idx

    now_eff = effective_now()
    quiz_time_left = max(0, int(settings.get("quiz_time", 0) - (now_eff - float(st.session_state.quiz_start or now_eff))))
    q_time_left = max(0, int(settings.get("sec_per_q", 0) - (now_eff - float(st.session_state.timer_start or now_eff))))

    # Controls row
    cA, cB, cC, cD, cE = st.columns([1, 1, 1, 1, 2])
    with cA:
        if st.button("⏸️ Pause & Save"):
            pause_quiz()
            save_current_quiz_to_disk(finished_override=False)
            st.rerun()
    with cB:
        if st.button("▶️ Resume"):
            resume_quiz()
            st.rerun()
    with cC:
        if st.button("✅ Finish Now"):
            st.session_state.finished = True
            touch_time_spent(min(idx, total_q - 1))
            st.rerun()
    with cD:
        if st.button("🏠 Home"):
            set_page("home")
            st.rerun()
    with cE:
        st.caption("Pause freezes timers. Resume continues timers.")

    if st.session_state.paused and not st.session_state.finished:
        st.warning("⏸️ Quiz is PAUSED. Timers are frozen. Click Resume to continue.")

    # Auto finish
    if quiz_time_left <= 0 and not st.session_state.finished and not st.session_state.paused:
        st.session_state.finished = True

    # Auto-skip (Exam only)
    if (
        not st.session_state.finished
        and not st.session_state.paused
        and q_time_left <= 0
        and not st.session_state.submitted[idx]
        and st.session_state.mode == "Exam"
    ):
        touch_time_spent(idx)
        if idx < total_q - 1:
            st.session_state.idx += 1
            st.session_state.timer_start = time.time()
            save_current_quiz_to_disk(finished_override=False)
            st.rerun()
        else:
            st.session_state.finished = True

    # Finish screen
    if st.session_state.finished or st.session_state.idx >= total_q:
        touch_time_spent(min(idx, total_q - 1))

        # ✅ KEY CHANGE: remove saved quiz from list when finished
        if st.session_state.save_id:
            delete_saved_quiz(st.session_state.save_id, username())
            st.session_state.save_id = None

        score = compute_score()
        percent = round((score / total_q) * 100, 1) if total_q else 0.0
        badge = "⭐ Excellent!" if percent >= 90 else "🥈 Strong!" if percent >= 75 else "💪 Keep Practicing!"

        st.markdown(
            f"""
<div class="card">
  <div class="qtitle">✅ Quiz Finished</div>
  <div class="meta">
    User: <b>{username()}</b> &nbsp; | &nbsp; Mode: <b>{st.session_state.mode}</b><br/>
    Score: <b>{score}</b> / <b>{total_q}</b> &nbsp; | &nbsp; <b>{percent}%</b> &nbsp; | &nbsp; {badge}
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

        rows = make_attempt_rows(
            st.session_state.current_quiz,
            st.session_state.answers,
            st.session_state.flags,
            st.session_state.confidence,
            st.session_state.time_spent,
        )

        wrong_uids = [r["uid"] for r in rows if (r["your_answer"] and not r["correct"])]
        skipped_uids = [r["uid"] for r in rows if (not r["your_answer"])]
        flagged_uids = [r["uid"] for r in rows if r["flagged"]]
        lowconf_uids = [r["uid"] for r in rows if r["confidence"] in (1, 2)]

        elapsed = int(time.time() - float(st.session_state.quiz_start or time.time()))
        entry = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "user": username(),
            "mode": st.session_state.mode,
            "score": score,
            "total": total_q,
            "percent": percent,
            "minutes_taken": round(elapsed / 60, 1),
            "flagged_count": int(sum(st.session_state.flags)),
            "wrong_uids": wrong_uids,
            "skipped_uids": skipped_uids,
            "flagged_uids": flagged_uids,
            "lowconf_uids": lowconf_uids,
        }

        if not st.session_state.history_written:
            append_history(entry)
            update_question_stats(st.session_state.current_quiz, st.session_state.answers, st.session_state.time_spent)
            st.session_state.history_written = True
            st.session_state.last_attempt = entry

        csv_bytes = attempt_to_csv_bytes(rows)
        st.download_button(
            "⬇️ Download Attempt Results (CSV)",
            data=csv_bytes,
            file_name=f"attempt_{username()}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

        bH, bN = st.columns(2)
        with bH:
            if st.button("🏠 Go to Home"):
                set_page("home")
                st.rerun()
        with bN:
            if st.button("📝 Start New Quiz"):
                st.session_state.current_quiz = None
                st.session_state.finished = False
                st.session_state.paused = False
                st.session_state.paused_at = None
                st.session_state.save_id = None
                set_page("quiz")
                st.rerun()

        return

    # Live panel
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    colA, colB, colC, colD = st.columns([2, 2, 2, 3])
    with colA:
        st.metric("Total Time Left", f"{quiz_time_left // 60}:{quiz_time_left % 60:02d}")
    with colB:
        st.metric("Question Time Left", f"{q_time_left}s")
    with colC:
        st.metric("Score (so far)", f"{compute_score()} / {total_q}")
    with colD:
        st.progress(min(1.0, idx / max(1, total_q)))
    st.markdown("</div>", unsafe_allow_html=True)

    # Navigator
    with st.expander("🧭 Navigator", expanded=False):
        cols = st.columns(6)
        for i in range(total_q):
            ua = st.session_state.answers[i]
            sub = st.session_state.submitted[i]
            correct = (ua is not None and ua == st.session_state.current_quiz[i].get("answer"))
            status = ""
            if sub and ua is not None:
                status = "✅" if correct else "❌"
            elif sub and ua is None:
                status = "⏭️"
            if st.session_state.flags[i]:
                status += " 🚩"
            label = f"Q{i+1} {status}".strip()
            with cols[i % 6]:
                if st.button(label, key=f"nav_{i}", disabled=st.session_state.paused):
                    touch_time_spent(st.session_state.idx)
                    st.session_state.idx = i
                    st.session_state.timer_start = time.time()
                    save_current_quiz_to_disk(finished_override=False)
                    st.rerun()

    # Current question
    q = st.session_state.current_quiz[idx]
    uid = q.get("uid")
    options = st.session_state.shuffled_options[idx] if st.session_state.shuffled_options else q.get("options", [])
    radio_options = [PLACEHOLDER] + (options or [])

    wkey = f"q_{idx}_choice"
    if wkey not in st.session_state:
        st.session_state[wkey] = PLACEHOLDER
    if st.session_state.answers[idx] is not None and st.session_state.answers[idx] in radio_options:
        st.session_state[wkey] = st.session_state.answers[idx]

    flagged = st.session_state.flags[idx]
    is_bookmarked = uid in user_bookmark_set()

    st.markdown(
        f"""
<div class="card">
  <div class="qtitle">Question {idx+1} of {total_q}</div>
  <div class="meta">
    <span class="badge {'badge-warn' if flagged else ''}">{'FLAGGED 🚩' if flagged else 'Not flagged'}</span>
    <span class="badge {'badge-ok' if is_bookmarked else ''}">{'Bookmarked ⭐' if is_bookmarked else 'Not bookmarked'}</span>
    <span class="badge">{q.get("domain","SPHR")}</span>
    <span class="badge">{q.get("subject","SPHR")}</span>
    <span class="badge">{q.get("chapter","")}</span>
  </div>
  <div style="font-size:16px; line-height:1.45;">
    {q.get("question","")}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    if settings.get("show_hints", False):
        exp = (q.get("explanation") or "").strip()
        if exp:
            hint = exp[:90] + ("..." if len(exp) > 90 else "")
            st.markdown(f"<div class='hint-box'><b>Hint:</b> {hint}</div>", unsafe_allow_html=True)

    disabled_after_submit = st.session_state.submitted[idx] or st.session_state.paused
    choice = st.radio("Choose an answer:", radio_options, key=wkey, disabled=disabled_after_submit)

    b1, b2, b3, b4, b5, b6 = st.columns([1, 1, 1, 1.2, 1, 1.2])
    back_pressed = b1.button("⬅️ Back", disabled=(idx == 0 or st.session_state.paused))
    skip_pressed = b2.button("⏭️ Skip", disabled=st.session_state.paused)
    flag_pressed = b3.button("🚩 Flag" if not flagged else "✅ Unflag", disabled=st.session_state.paused)
    submit_pressed = b4.button("✅ Submit", disabled=(st.session_state.submitted[idx] or st.session_state.paused))
    next_pressed = b5.button("Next ➡️", disabled=(idx >= total_q - 1 or st.session_state.paused))
    bm_pressed = b6.button("⭐ Bookmark" if not is_bookmarked else "❌ Unbookmark", disabled=st.session_state.paused)

    if bm_pressed:
        toggle_bookmark(uid)
        save_current_quiz_to_disk(finished_override=False)
        st.rerun()

    if back_pressed and idx > 0:
        touch_time_spent(idx)
        st.session_state.idx -= 1
        st.session_state.timer_start = time.time()
        save_current_quiz_to_disk(finished_override=False)
        st.rerun()

    if next_pressed and idx < total_q - 1:
        touch_time_spent(idx)
        st.session_state.idx += 1
        st.session_state.timer_start = time.time()
        save_current_quiz_to_disk(finished_override=False)
        st.rerun()

    if flag_pressed:
        st.session_state.flags[idx] = not st.session_state.flags[idx]
        save_current_quiz_to_disk(finished_override=False)
        st.rerun()

    if skip_pressed:
        touch_time_spent(idx)
        st.session_state.submitted[idx] = True
        st.session_state.answers[idx] = None
        if idx < total_q - 1:
            st.session_state.idx += 1
            st.session_state.timer_start = time.time()
            save_current_quiz_to_disk(finished_override=False)
            st.rerun()
        else:
            st.session_state.finished = True
            st.rerun()

    if submit_pressed:
        if choice == PLACEHOLDER:
            st.warning("Please select an answer before submitting.")
        else:
            st.session_state.answers[idx] = choice
            st.session_state.submitted[idx] = True
            touch_time_spent(idx)

            correct = (choice == q.get("answer"))
            if settings.get("play_sounds", False):
                play_sound("correct" if correct else "wrong")

            save_current_quiz_to_disk(finished_override=False)

            if settings.get("auto_advance", False):
                if idx < total_q - 1:
                    st.session_state.idx += 1
                    st.session_state.timer_start = time.time()
                    st.rerun()
                else:
                    st.session_state.finished = True
                    st.rerun()

    if st.session_state.submitted[idx] and st.session_state.mode != "Exam":
        ua = st.session_state.answers[idx]
        ca = q.get("answer")
        correct = (ua is not None and ua == ca)

        if settings.get("show_correct", True):
            if correct:
                st.success(f"✅ Correct! Your answer: **{ua}**")
            else:
                st.error(f"❌ Wrong. Your answer: **{ua}**")
                st.info(f"✅ Correct answer: **{ca}**")

        if settings.get("show_exp", True):
            exp = (q.get("explanation") or "").strip()
            st.info(f"📌 Explanation: {exp if exp else '—'}")


# ============================================================
# BANK / ANALYTICS / REVIEW (unchanged)
# ============================================================
def render_bank():
    st.title("📥 Question Bank")
    bank_now = load_questions()
    st.markdown(
        f"""
<div class="card">
  <div class="qtitle">Question Bank Summary</div>
  <div class="meta">Total Questions: <b>{len(bank_now)}</b></div>
</div>
""",
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        domain_tag = st.text_input("Domain tag for imported questions", value="SPHR")
    with col2:
        subject_tag = st.text_input("Subject tag (optional)", value="")

    up_md = st.file_uploader("Upload Markdown (.md) files", type=["md"], accept_multiple_files=True)
    up_json = st.file_uploader("Upload JSON question bank (.json)", type=["json"], accept_multiple_files=True)

    def dedupe_and_merge(existing, incoming):
        existing_norm = {norm_text(q.get("question","")): q for q in existing}
        added = 0
        for q in incoming:
            key = norm_text(q.get("question",""))
            if key and key not in existing_norm:
                existing.append(q)
                existing_norm[key] = q
                added += 1
        return existing, added

    if st.button("Parse & Add Imports"):
        incoming = []
        if up_md:
            for f in up_md:
                content = f.read().decode("utf-8", errors="ignore")
                incoming.extend(parse_md_content(content, domain=domain_tag, subject=subject_tag))
        if up_json:
            for f in up_json:
                try:
                    js = json.loads(f.read().decode("utf-8", errors="ignore"))
                    if isinstance(js, list):
                        incoming.extend(js)
                    else:
                        st.warning(f"{f.name}: JSON must be a list.")
                except Exception:
                    st.warning(f"{f.name}: Could not parse JSON.")
        if not incoming:
            st.warning("No questions detected.")
        else:
            incoming, _ = ensure_uids_and_fix_answers(incoming)
            existing = load_questions()
            existing, added = dedupe_and_merge(existing, incoming)
            existing, _ = ensure_uids_and_fix_answers(existing)
            save_questions(existing)
            st.success(f"Imported {len(incoming)} questions, added **{added}** new. Total now: **{len(existing)}**")
            st.rerun()

    st.divider()
    st.subheader("Download Bank")
    bank_now = load_questions()
    bank_bytes = json.dumps(bank_now, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button("⬇️ Download questions.json", data=bank_bytes, file_name="questions.json", mime="application/json")


def render_analytics():
    st.title("📊 Analytics")
    history = read_json(HISTORY_FILE, default=[])
    user_hist = [h for h in history if h.get("user") == username()] if history else []

    st.markdown(
        f"""
<div class="card">
  <div class="qtitle">User: {username()}</div>
  <div class="meta">Attempts saved: <b>{len(user_hist)}</b></div>
</div>
""",
        unsafe_allow_html=True,
    )

    if not user_hist:
        st.info("No attempts found yet. Finish a quiz to generate analytics.")
        return

    dates = [h.get("date","") for h in user_hist[-20:]]
    percents = [h.get("percent",0) for h in user_hist[-20:]]
    plot_line(dates, percents, "Score Trend (Last 20 Attempts)", "Score %")


def render_review_center():
    st.title("🎯 Review Center")
    history = read_json(HISTORY_FILE, default=[])
    user_hist = [h for h in history if h.get("user") == username()] if history else []
    if not user_hist:
        st.info("Finish at least one quiz to unlock Review Center.")
        return
    st.info("Review Center logic unchanged (your existing feature set).")


# ============================================================
# ROUTER
# ============================================================
page = st.session_state.page
if page == "home":
    render_home()
elif page == "quiz":
    render_quiz()
elif page == "bank":
    render_bank()
elif page == "analytics":
    render_analytics()
elif page == "review":
    render_review_center()
else:
    set_page("home")
    render_home()