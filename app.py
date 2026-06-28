
from flask import Flask, request, redirect, jsonify, render_template_string, send_from_directory
from datetime import datetime, timedelta
import json, os, uuid, html, threading, tempfile

app = Flask(__name__)
DATA_FILE = "data.json"
AUTO_DELETE_HOURS = 1
DATA_LOCK = threading.Lock()

HUNTING = ["도삭산 900층", "흉노족", "선비족"]
FARMING = ["해골왕", "어금니"]
QUEST600 = ["800층 600퀘", "900층 600퀘", "선비족 600퀘"]
CLASSES = {
    "전사": ["전사", "검객", "검제", "검황", "검성"],
    "도적": ["도적", "자객", "진검", "귀검", "태성"],
    "주술사": ["주술사", "술사", "현사", "현인", "현자"],
    "도사": ["도사", "도인", "명인", "진인", "진선"],
}
ALL_JOBS = [j for group in CLASSES.values() for j in group]
FILTERS = ["전체", "사냥", "파밍", "600퀘", "도삭산 900층", "흉노족", "선비족", "해골왕", "어금니"]

def now_text():
    return datetime.now().strftime("%m/%d %H:%M")

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def parse_iso(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except Exception:
        return None

def esc(value):
    return html.escape(str(value or ""), quote=True)

def read_data_unlocked():
    if not os.path.exists(DATA_FILE):
        return {"posts": [], "notice": ""}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "posts" not in data:
                data["posts"] = []
            if "notice" not in data:
                data["notice"] = ""
            return data
    except Exception:
        return {"posts": [], "notice": ""}

def save_data_unlocked(data):
    fd, tmp_path = tempfile.mkstemp(prefix="baram_", suffix=".json", dir=".")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DATA_FILE)

def cleanup_unlocked(data):
    cutoff = datetime.now() - timedelta(hours=AUTO_DELETE_HOURS)
    posts = []
    changed = False

    for post in data.get("posts", []):
        closed_at = parse_iso(post.get("closed_at", ""))
        if post.get("closed") and closed_at and closed_at <= cutoff:
            changed = True
            continue
        posts.append(post)

    if changed:
        data["posts"] = posts
        save_data_unlocked(data)

    return data

def load_data():
    with DATA_LOCK:
        return cleanup_unlocked(read_data_unlocked())

def mutate_data(fn):
    with DATA_LOCK:
        data = cleanup_unlocked(read_data_unlocked())
        result = fn(data)
        save_data_unlocked(data)
        return result

def count_slots(post):
    slots = post.get("slots", [])
    total = len(slots)
    filled = sum(1 for s in slots if s.get("char"))
    return filled, total

def is_full(post):
    filled, total = count_slots(post)
    return total > 0 and filled >= total

def status_of(post):
    if post.get("closed") or is_full(post):
        return "모집완료"
    return "모집중"

def ensure_auto_closed(post):
    if is_full(post) and not post.get("closed"):
        post["closed"] = True
        post["closed_at"] = now_iso()

def closed_left(post):
    if not post.get("closed"):
        return ""
    closed_at = parse_iso(post.get("closed_at", ""))
    if not closed_at:
        return "1시간 뒤 자동삭제"
    expire = closed_at + timedelta(hours=AUTO_DELETE_HOURS)
    sec = int((expire - datetime.now()).total_seconds())
    if sec <= 0:
        return "곧 삭제"
    mins = sec // 60
    if mins >= 60:
        return "1시간 뒤 자동삭제"
    return f"{mins}분 뒤 자동삭제"

def filtered_posts(filter_value):
    data = load_data()
    posts = list(reversed(data.get("posts", [])))
    if not filter_value or filter_value == "전체":
        return posts
    return [p for p in posts if p.get("type") == filter_value or p.get("place") == filter_value]

def job_icon(job):
    if job in ["전사", "검객", "검제", "검황", "검성"]:
        return "⚔️"
    if job in ["도적", "자객", "진검", "귀검", "태성"]:
        return "🗡️"
    if job in ["주술사", "술사", "현사", "현인", "현자"]:
        return "🔮"
    if job in ["도사", "도인", "명인", "진인", "진선"]:
        return "💙"
    return "•"

def render_time(post):
    sp = post.get("start_period", "") or post.get("period", "")
    st = post.get("start_time", "")
    ep = post.get("end_period", "")
    et = post.get("end_time", "")
    start_text = (sp + " " + st).strip()
    end_text = (ep + " " + et).strip()
    if start_text and end_text:
        return f"{start_text} ~ {end_text}"
    if start_text:
        return start_text
    if end_text:
        return end_text
    return "시간 미정"



def render_post_card(p):
    pid = esc(p.get("id"))
    st = status_of(p)
    status_class = "done" if st == "모집완료" else "open"
    card_class = "closed-card" if p.get("closed") else ""
    filled, total = count_slots(p)
    remain = max(total - filled, 0)
    remain_text = "모집완료" if remain == 0 and total > 0 else f"{remain}자리 남음"

    owner_id = esc(p.get("owner_id", ""))
    participant_ids = [s.get("participant_id", "") for s in p.get("slots", []) if s.get("participant_id")]
    participants = [s.get("char", "") for s in p.get("slots", []) if s.get("char")]
    participants_attr = esc("|".join(participants))
    participant_ids_attr = esc("|".join(participant_ids))
    chat_count = len(p.get("chats", []))

    copy_lines = [
        f"[{p.get('type','')}] {p.get('place','')}",
        f"채널 {p.get('channel') or '미정'}",
        render_time(p),
    ]

    slot_parts = []
    for s in p.get("slots", []):
        sid = esc(s.get("id"))
        job_raw = s.get("job", "")
        job = esc(job_raw)
        icon = job_icon(job_raw)
        char = esc(s.get("char"))
        participant_id = esc(s.get("participant_id", ""))
        copy_lines.append(f"{job_raw} - {s.get('char') or '모집중'}")
        if char:
            slot_parts.append(f"""
<div class="slot filled" data-participant-id="{participant_id}">
  <div class="slot-left"><span class="job">{icon} {job}</span><span class="char">✅ {char}</span></div>
  <button class="mini red participant-action owner-action" onclick="leaveSlot('{pid}','{sid}')">비우기</button>
</div>
""")
        else:
            slot_parts.append(f"""
<div class="slot">
  <div class="slot-left"><span class="job">{icon} {job}</span><span class="empty">⭕ 모집중</span></div>
  <button class="mini green" onclick="joinSlot('{pid}','{sid}','{job}')">참여</button>
</div>
""")
    slots = "\n".join(slot_parts) if slot_parts else '<div class="small">모집 자리가 없습니다.</div>'
    time_text = esc(render_time(p))
    memo = esc(p.get("memo"))
    memo_html = f'<div class="memo">메모: {memo}</div>' if memo else ""
    left = esc(closed_left(p))
    left_html = f'<div class="closed-left">⏳ {left}</div>' if left else ""
    copy_text = esc("\\n".join(copy_lines))

    return f"""
<div class="card post {card_class}" data-post-id="{pid}" data-owner-id="{owner_id}" data-participants="{participants_attr}" data-participant-ids="{participant_ids_attr}" data-chat-count="{chat_count}" data-place="{esc(p.get("place"))}" data-filled="{filled}">
  <div class="post-top">
    <div>
      <span class="badge {status_class}">{'🟢 ' if st == '모집중' else '🔴 '}{st}</span>
      <span class="badge kind">{esc(p.get("type"))}</span>
    </div>
    <div class="slot-count">👥 {filled}/{total}</div>
  </div>
  <div class="place">{esc(p.get("place"))}</div>
  <div class="remain">{remain_text}</div>
  <div class="meta">📍 채널 {esc(p.get("channel") or "미정")} · ⏰ {time_text}</div>
  <div class="meta">👑 {esc(p.get("owner"))} · {esc(p.get("created"))}</div>
  {memo_html}
  {left_html}
  <div class="slots">{slots}</div>
  <div class="card-actions">
    <button class="big-action copy" onclick="copyPost(`{copy_text}`)">📋 복사</button>
    <button class="big-action chat party-action" onclick="openPartyChat('{pid}')">💬 채팅 <span class="chat-badge">{chat_count}</span></button>
    <a class="big-action gray linkbtn owner-action" href="/edit/{pid}">수정</a>
    <button class="big-action gray owner-action" onclick="closePost('{pid}')">마감</button>
    <button class="big-action red owner-action" onclick="deletePost('{pid}')">삭제</button>
  </div>
</div>
"""

def render_posts(posts):
    if not posts:
        return '<div class="empty-state">현재 모집글이 없습니다.</div>'
    return "\n".join(render_post_card(p) for p in posts)

def find_post(post_id):
    data = load_data()
    for p in data.get("posts", []):
        if p.get("id") == post_id:
            return p
    return None

PAGE = """
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#11131d">
<link rel="manifest" href="/manifest.json">
<title>월하 · 연가 · 연희 파티 모집</title>
<style>
:root{--bg:#0f1016;--card:#1b1d28;--card2:#151722;--line:#303345;--text:#f2f3f7;--muted:#a8acba;--blue:#4b6bff;--green:#23a55a;--red:#d94b4b;--yellow:#ffd36b}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:linear-gradient(180deg,#11131d,#0c0d12);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Malgun Gothic",Arial,sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:12px 12px 88px}
.hero{position:sticky;top:0;z-index:5;background:rgba(15,16,22,.94);backdrop-filter:blur(10px);padding:10px 0 8px;border-bottom:1px solid rgba(255,255,255,.05)}
h1{font-size:22px;margin:0 0 3px;letter-spacing:-.5px}.subtitle{font-size:13px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:14px;margin:12px 0;box-shadow:0 8px 24px rgba(0,0,0,.25)}
.closed-card{opacity:.68}.empty-state{background:var(--card);border:1px dashed #3a3d52;color:var(--muted);border-radius:18px;text-align:center;padding:42px 14px;margin-top:12px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:560px){.grid{grid-template-columns:1fr}}
.btn,button,.linkbtn{border:0;border-radius:14px;padding:12px 14px;background:var(--blue);color:#fff;font-weight:900;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;font-size:16px;min-height:44px}
.btn.gray,button.gray,.linkbtn.gray{background:#3a3d4f}.btn.red,button.red{background:var(--red)}.btn.green,button.green{background:var(--green)}
.main-actions .btn{flex:1}.mini{padding:8px 11px;font-size:13px;border-radius:10px;min-height:34px}
input,select,textarea{width:100%;padding:13px 12px;margin:6px 0 12px;border-radius:14px;border:1px solid #41455c;background:#11131b;color:var(--text);font-size:16px;outline:none}
input:focus,select:focus,textarea:focus{border-color:var(--blue)}
label{font-size:13px;color:var(--muted);font-weight:800}
.tabs{display:flex;gap:7px;overflow-x:auto;padding:10px 0 1px;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}
.tabs a{white-space:nowrap;background:#191b26;border:1px solid var(--line);color:#d9dbea;text-decoration:none;padding:9px 12px;border-radius:999px;font-size:14px;font-weight:800}
.tabs a.on{background:var(--blue);color:white;border-color:var(--blue)}
.post-top{display:flex;justify-content:space-between;align-items:center;gap:8px}.badge{display:inline-block;padding:5px 10px;border-radius:999px;font-size:13px;font-weight:900;margin-right:5px}
.open{background:#123f28;color:#a9ffc8}.done{background:#4b1d1d;color:#ffd0d0}.kind{background:#223163;color:#c3d2ff}
.slot-count{font-weight:1000;background:#11131b;border:1px solid var(--line);border-radius:999px;padding:5px 10px;color:#fff}
.place{font-size:21px;font-weight:1000;margin:10px 0 4px;letter-spacing:-.4px}.meta{color:var(--muted);font-size:14px;line-height:1.55}.memo{color:var(--yellow);font-size:14px;margin-top:5px}.closed-left{color:#ffb3b3;font-size:13px;margin-top:4px;font-weight:800}
.remain{display:inline-block;margin:2px 0 8px;background:#2b2340;color:#dac6ff;border:1px solid #4b3b77;border-radius:999px;padding:5px 10px;font-size:13px;font-weight:1000}
.slots{margin-top:12px;border-top:1px solid var(--line);padding-top:8px}.slot{background:#11131b;border:1px solid #32364a;border-radius:14px;padding:10px;margin:8px 0;display:flex;justify-content:space-between;gap:8px;align-items:center}.slot.filled{background:#152218;border-color:#285637}.slot-left{display:flex;flex-direction:column;gap:2px}.job{font-weight:1000;font-size:16px}.char{color:#fff;font-weight:800}.empty{color:#8d92a5;font-size:13px}
.card-actions{display:grid;grid-template-columns:1fr 1fr 1fr;gap:7px;margin-top:10px}.big-action{min-height:42px;padding:9px 10px;font-size:14px;border-radius:12px}.big-action.copy{background:#25427e}.big-action.gray{background:#3a3d4f}.big-action.red{background:var(--red)}
.hidden{display:none}.notice{color:var(--yellow);font-size:13px}.small{color:var(--muted);font-size:13px}.footer{color:#6f7382;font-size:12px;text-align:center;margin:24px 0 8px}
.quick-slot{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center}
.time-row{display:grid;grid-template-columns:82px 1fr;gap:8px;align-items:center;margin-bottom:10px}
.time-row select{margin:0;min-height:50px;text-align:center;font-weight:900}.time-row input{margin:0;min-height:50px;font-weight:900;letter-spacing:.5px}.time-help{font-size:12px;color:var(--muted);margin-top:-4px;margin-bottom:10px}
.summary{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:10px}.summary-box{background:#11131b;border:1px solid var(--line);border-radius:16px;padding:12px;text-align:center}.summary-box b{display:block;font-size:22px}.summary-box span{font-size:12px;color:var(--muted);font-weight:800}
.fab{position:fixed;right:18px;bottom:20px;width:58px;height:58px;border-radius:50%;background:var(--blue);box-shadow:0 10px 28px rgba(0,0,0,.45);font-size:32px;z-index:50;padding:0}
.toast{position:fixed;left:50%;bottom:90px;transform:translateX(-50%);background:#222638;color:#fff;border:1px solid #555b78;border-radius:999px;padding:10px 16px;font-weight:900;z-index:99;opacity:0;pointer-events:none;transition:.2s}.toast.show{opacity:1}
.my-filter-on .post:not(.mine){display:none}
@media(max-width:520px){.card-actions{grid-template-columns:1fr 1fr}.big-action{width:100%}.summary{grid-template-columns:1fr 1fr 1fr}}
.owner-action{display:none!important}
.owner-action.show{display:inline-flex!important}
.participant-action{display:none!important}
.participant-action.show{display:inline-flex!important}
.protect-notice{font-size:12px;color:#8d92a5;margin-top:6px}

.party-action{display:none!important}
.party-action.show{display:inline-flex!important}
.big-action.chat{background:#2d4f7f}
.chat-badge{margin-left:4px;background:#11131b;border:1px solid #53617d;border-radius:999px;padding:1px 6px;font-size:12px}
.alarm-toggle{position:fixed;left:14px;bottom:22px;z-index:60;background:#24283a;border:1px solid #4b526d;border-radius:999px;padding:10px 13px;font-size:13px;font-weight:900}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:100;display:none;align-items:flex-end}
.modal.show{display:flex}
.chat-panel{width:100%;max-width:820px;margin:0 auto;background:#141722;border:1px solid #33384d;border-radius:20px 20px 0 0;padding:14px;max-height:82vh;display:flex;flex-direction:column}
.chat-head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}
.chat-head b{font-size:18px}
.chat-list{background:#0f1119;border:1px solid #30364b;border-radius:14px;padding:10px;overflow-y:auto;min-height:260px;max-height:52vh}
.chat-msg{padding:8px 10px;border-radius:12px;margin:6px 0;background:#202436}
.chat-msg.mine{background:#173822;border:1px solid #2e7146}
.chat-meta{font-size:12px;color:#a8acba;margin-bottom:3px}
.chat-text{font-size:15px;line-height:1.35;word-break:break-word}
.chat-form{display:grid;grid-template-columns:90px 1fr 68px;gap:7px;margin-top:8px}
.chat-form input{margin:0}
.chat-form button{min-height:46px;padding:8px}
@media(max-width:520px){.card-actions{grid-template-columns:1fr 1fr}.chat-form{grid-template-columns:1fr}.chat-form button{width:100%}.alarm-toggle{bottom:88px}}
</style>
</head>
<body>
<div class="wrap">
<div class="hero">
<h1>🏹 월하 · 연가 · 연희</h1>
<div class="subtitle">바람의나라 클래식 통합 파티 모집</div>
</div>

{% if page == "home" %}
<div class="card">
  <div class="row main-actions">
    <a class="btn" href="/new">+ 구인글</a>
    <a class="btn gray" href="/profile">내 캐릭터</a>
    <button class="btn gray" onclick="toggleMyPosts()">내 참여</button>
  </div>
  <div class="summary">
    <div class="summary-box"><b>{{ open_count }}</b><span>모집중</span></div>
    <div class="summary-box"><b>{{ total_count }}</b><span>전체글</span></div>
    <div class="summary-box"><b id="myCount">0</b><span>내 참여</span></div>
  </div>
  <div class="tabs">
    {% for item in filters %}
      <a class="{% if filter_value == item %}on{% endif %}" href="/?filter={{ item }}">{{ item }}</a>
    {% endfor %}
  </div>
</div>
<div id="postList">{{ post_list | safe }}</div>
{% endif %}

{% if page == "new" or page == "edit" %}
<div class="card">
<h2>{% if page == "edit" %}모집글 수정{% else %}구인글 올리기{% endif %}</h2>
<form method="post" action="{% if page == 'edit' %}/edit/{{ post.id }}{% else %}/create{% endif %}" onsubmit="return prepareSubmit()">
<input type="hidden" name="owner_id" id="ownerIdInput">
<label>작성자 닉네임</label><div class="protect-notice">수정/삭제/마감은 글을 작성한 기기에서만 가능합니다.</div>
<input name="owner" required placeholder="예: 역인" value="{{ post.owner if post else '' }}">

<div class="grid">
  <div>
    <label>종류</label>
    <select name="type" id="typeSelect" onchange="updatePlaces()">
      {% for t in ["사냥","파밍","600퀘"] %}
        <option {% if post and post.type == t %}selected{% endif %}>{{ t }}</option>
      {% endfor %}
    </select>
  </div>
  <div>
    <label>채널 4자리</label>
    <input name="channel" id="channelInput" maxlength="4" inputmode="numeric" placeholder="예: 3385" value="{{ post.channel if post else '' }}">
  </div>
</div>

<label>장소</label>
<select name="place_hunting" id="place_사냥" class="place-select">
{% for p in hunting %}<option {% if post and post.place == p %}selected{% endif %}>{{ p }}</option>{% endfor %}
</select>
<select name="place_farming" id="place_파밍" class="place-select hidden">
{% for p in farming %}<option {% if post and post.place == p %}selected{% endif %}>{{ p }}</option>{% endfor %}
</select>
<select name="place_quest" id="place_600퀘" class="place-select hidden">
{% for p in quest600 %}<option {% if post and post.place == p %}selected{% endif %}>{{ p }}</option>{% endfor %}
</select>

<label>시작시간</label>
<div class="time-row">
  <select name="start_period">
    <option {% if post and post.start_period == "오전" %}selected{% endif %}>오전</option>
    <option {% if post and post.start_period == "오후" %}selected{% endif %}>오후</option>
  </select>
  <input name="start_time" inputmode="numeric" placeholder="예: 09:00" value="{{ post.start_time if post else '' }}">
</div>

<label>종료시간</label>
<div class="time-row">
  <select name="end_period">
    <option {% if post and post.end_period == "오전" %}selected{% endif %}>오전</option>
    <option {% if not post or post.end_period == "오후" %}selected{% endif %}>오후</option>
  </select>
  <input name="end_time" inputmode="numeric" placeholder="예: 11:00" value="{{ post.end_time if post else '' }}">
</div>
<div class="time-help">시간은 직접 입력. 예: 9시, 09:00, 10:30</div>

<label>메모</label>
<textarea name="memo" rows="2" placeholder="예: 1타임, 빠른 진행, 디코 수다팟">{{ post.memo if post else '' }}</textarea>

<div class="card" style="background:var(--card2)">
  <label>모집 자리 추가</label>
  <div class="quick-slot">
    <select id="slotJob">{% for job in jobs %}<option>{{ job }}</option>{% endfor %}</select>
    <button type="button" class="green" onclick="addSlot()">추가</button>
  </div>
  <div id="slotsBox">
    {% if post %}
      {% for slot in post.slots %}
        <div class="slot">
          <div class="slot-left"><span class="job">{{ slot.job }}</span><span class="small">{{ slot.char }}</span></div>
          <button type="button" class="mini red" onclick="this.parentElement.remove()">삭제</button>
          <input type="hidden" name="slots" value="{{ slot.job }}">
          <input type="hidden" name="slot_chars" value="{{ slot.char }}"><input type="hidden" name="slot_participant_ids" value="{{ slot.participant_id }}">
        </div>
      {% endfor %}
    {% endif %}
  </div>
  <div class="notice">수정 시 기존 참여자는 유지돼. 자리 삭제하면 해당 참여자도 사라짐.</div>
</div>

<button type="submit" style="width:100%">저장하기</button>
<a class="btn gray" style="width:100%;margin-top:8px" href="/">취소</a>
</form>
</div>
<script>setTimeout(updatePlaces, 50);</script>
{% endif %}

{% if page == "profile" %}
<div class="card">
<h2>내 캐릭터 등록</h2>
<div class="notice">이 정보는 현재 휴대폰/브라우저에 저장돼. 여러 캐릭터 등록 가능.</div>
<label>캐릭터명</label><input id="charName" placeholder="예: 예인">
<label>직업/차수</label><select id="charJob">{% for job in jobs %}<option>{{ job }}</option>{% endfor %}</select>
<button onclick="saveChar()" style="width:100%">캐릭터 추가</button>
<a class="btn gray" style="width:100%;margin-top:8px" href="/">메인으로</a>
<div id="charList"></div>
</div>
{% endif %}
<div class="footer">월하 · 연가 · 연희 통합 파티 모집 v3.1</div>
</div>
{% if page == "home" %}
<a class="btn fab" href="/new">+</a>
{% endif %}

<button id="alarmToggle" class="alarm-toggle" onclick="toggleAlarm()">🔔 알림 ON</button>

<div id="partyChatModal" class="modal" onclick="if(event.target.id==='partyChatModal')closePartyChat()">
  <div class="chat-panel">
    <div class="chat-head">
      <b id="chatTitle">파티채팅</b>
      <button class="mini gray" onclick="closePartyChat()">닫기</button>
    </div>
    <div id="partyChatList" class="chat-list"></div>
    <div class="chat-form">
      <input id="partyChatName" placeholder="닉네임" maxlength="12">
      <input id="partyChatText" placeholder="메시지 입력" maxlength="120" onkeydown="if(event.key==='Enter')sendPartyChat()">
      <button onclick="sendPartyChat()">전송</button>
    </div>
  </div>
</div>

<div id="toast" class="toast">완료</div>

<script>
if("serviceWorker" in navigator){navigator.serviceWorker.register("/sw.js").catch(()=>{});}
function getClientId(){
  let id=localStorage.getItem("baram_client_id");
  if(!id){
    id=(crypto&&crypto.randomUUID)?crypto.randomUUID():("id_"+Date.now()+"_"+Math.random().toString(16).slice(2));
    localStorage.setItem("baram_client_id",id);
  }
  return id;
}
function prepareSubmit(){
  let input=document.getElementById("ownerIdInput");
  if(input) input.value=getClientId();
  return validateForm();
}
function applyOwnerProtection(){
  const id=getClientId();
  document.querySelectorAll(".post").forEach(post=>{
    const isOwner=post.dataset.ownerId && post.dataset.ownerId===id;
    post.querySelectorAll(".owner-action").forEach(btn=>btn.classList.toggle("show",isOwner));
    post.querySelectorAll(".slot").forEach(slot=>{
      const pid=slot.dataset.participantId || "";
      const canCancel=isOwner || (pid && pid===id);
      slot.querySelectorAll(".participant-action").forEach(btn=>btn.classList.toggle("show",canCancel));
    });
    const inParty=isOwner || (post.dataset.participantIds||"").split("|").includes(id);
    post.querySelectorAll(".party-action").forEach(btn=>btn.classList.toggle("show",inParty));
  });
}
function showToast(msg){let t=document.getElementById("toast"); if(!t)return; t.textContent=msg; t.classList.add("show"); setTimeout(()=>t.classList.remove("show"),1400);}
function fallbackCopy(text){let ta=document.createElement("textarea");ta.value=text;document.body.appendChild(ta);ta.select();try{document.execCommand("copy");showToast("복사되었습니다");}catch(e){alert(text);}document.body.removeChild(ta);}
function copyPost(text){if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(()=>showToast("복사되었습니다")).catch(()=>fallbackCopy(text));}else{fallbackCopy(text);}}
function refreshList(){if(location.pathname==="/"){fetch("/api/posts"+location.search).then(r=>r.text()).then(html=>{let t=document.getElementById("postList"); if(t){t.innerHTML=html;markMyPosts();applyOwnerProtection();scanNotifications();}}).catch(()=>{});}}
setInterval(refreshList,2500);
function updatePlaces(){let type=document.getElementById("typeSelect"); if(!type)return; document.querySelectorAll(".place-select").forEach(el=>el.classList.add("hidden"));let target=document.getElementById("place_"+type.value); if(target)target.classList.remove("hidden");}
function validateForm(){let ch=document.getElementById("channelInput").value.trim();if(ch&&!/^\\d{4}$/.test(ch)){alert("채널은 숫자 4자리로 입력해줘. 예: 3385");return false;}return true;}
function addSlot(){let job=document.getElementById("slotJob").value;let box=document.getElementById("slotsBox");let div=document.createElement("div");div.className="slot";div.innerHTML="<div class='slot-left'><span class='job'>"+job+"</span></div><button type='button' class='mini red' onclick='this.parentElement.remove()'>삭제</button><input type='hidden' name='slots' value='"+job+"'><input type='hidden' name='slot_chars' value=''><input type='hidden' name='slot_participant_ids' value=''>";box.appendChild(div);}
function getChars(){return JSON.parse(localStorage.getItem("baram_chars")||"[]");}
function setChars(chars){localStorage.setItem("baram_chars",JSON.stringify(chars));renderChars();markMyPosts();}
function saveChar(){let name=document.getElementById("charName").value.trim();let job=document.getElementById("charJob").value;if(!name){alert("캐릭터명을 입력해줘.");return;}let chars=getChars();chars.push({name:name,job:job});setChars(chars);document.getElementById("charName").value="";showToast("저장되었습니다");}
function deleteChar(index){let chars=getChars();chars.splice(index,1);setChars(chars);}
function renderChars(){let list=document.getElementById("charList");if(!list)return;let chars=getChars();if(!chars.length){list.innerHTML="<div class='card small'>등록된 캐릭터가 없습니다.</div>";return;}list.innerHTML=chars.map((c,i)=>"<div class='slot'><div class='slot-left'><b>"+c.name+"</b><span>"+c.job+"</span></div><button class='mini red' onclick='deleteChar("+i+")'>삭제</button></div>").join("");}
renderChars();
function joinSlot(postId,slotId,job){let matching=getChars().filter(c=>c.job===job);let name="";if(matching.length===1){name=matching[0].name;}else if(matching.length>1){name=prompt("참여할 캐릭터명을 입력해줘.\\n등록 캐릭터: "+matching.map(c=>c.name).join(", "));}else{name=prompt(job+" 자리 참여 캐릭터명 입력");}if(!name)return;fetch("/join",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({post_id:postId,slot_id:slotId,char:name,participant_id:getClientId()})}).then(()=>{refreshList();showToast("참여되었습니다");});}
function leaveSlot(postId,slotId){if(!confirm("이 자리를 비울까?"))return;fetch("/leave",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({post_id:postId,slot_id:slotId,participant_id:getClientId()})}).then(()=>{refreshList();showToast("취소되었습니다");});}
function closePost(postId){if(!confirm("이 모집글을 마감할까?\\n마감 후 1시간 뒤 자동 삭제됩니다."))return;fetch("/close",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({post_id:postId,owner_id:getClientId()})}).then(()=>refreshList());}
function deletePost(postId){if(!confirm("이 모집글을 바로 삭제할까?"))return;fetch("/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({post_id:postId})}).then(()=>refreshList());}
function alarmOn(){return localStorage.getItem("baram_alarm_off")!=="1";}
function updateAlarmButton(){let b=document.getElementById("alarmToggle");if(b)b.textContent=alarmOn()?"🔔 알림 ON":"🔕 알림 OFF";}
function toggleAlarm(){localStorage.setItem("baram_alarm_off",alarmOn()?"1":"0");updateAlarmButton();showToast(alarmOn()?"알림 켜짐":"알림 꺼짐");}
function notify(msg){if(alarmOn())showToast(msg);}
let knownPosts=JSON.parse(localStorage.getItem("baram_known_posts")||"[]");
let knownChats=JSON.parse(localStorage.getItem("baram_known_chats")||"{}");
let knownFilled=JSON.parse(localStorage.getItem("baram_known_filled")||"{}");
function markMyPosts(){
  const id=getClientId();
  let count=0;
  document.querySelectorAll(".post").forEach(p=>{
    const isOwner=p.dataset.ownerId && p.dataset.ownerId===id;
    const joined=(p.dataset.participantIds||"").split("|").includes(id);
    const mine=isOwner||joined;
    p.classList.toggle("mine",mine);
    if(mine)count++;
  });
  let mc=document.getElementById("myCount");if(mc)mc.textContent=count;
}
function toggleMyPosts(){document.body.classList.toggle("my-filter-on");markMyPosts();showToast(document.body.classList.contains("my-filter-on")?"내 참여/내 글만 보기":"전체 보기");}
function scanNotifications(){
  const id=getClientId();
  document.querySelectorAll(".post").forEach(p=>{
    const postId=p.dataset.postId;
    const place=p.dataset.place||"모집";
    const chatCount=parseInt(p.dataset.chatCount||"0");
    const filled=parseInt(p.dataset.filled||"0");
    const isOwner=p.dataset.ownerId===id;
    const inParty=isOwner||(p.dataset.participantIds||"").split("|").includes(id);
    if(!knownPosts.includes(postId)){
      if(knownPosts.length>0)notify("🆕 새 모집: "+place);
      knownPosts.push(postId);
    }
    if(inParty && knownChats[postId]!==undefined && chatCount>knownChats[postId])notify("💬 새 파티채팅");
    if(isOwner && knownFilled[postId]!==undefined && filled>knownFilled[postId])notify("🔔 새 참여자가 있습니다");
    knownChats[postId]=chatCount;
    knownFilled[postId]=filled;
  });
  knownPosts=knownPosts.slice(-200);
  localStorage.setItem("baram_known_posts",JSON.stringify(knownPosts));
  localStorage.setItem("baram_known_chats",JSON.stringify(knownChats));
  localStorage.setItem("baram_known_filled",JSON.stringify(knownFilled));
}
let currentChatPostId=null;
function openPartyChat(postId){
  currentChatPostId=postId;
  let m=document.getElementById("partyChatModal");
  if(m)m.classList.add("show");
  let saved=localStorage.getItem("baram_chat_name");
  if(saved&&document.getElementById("partyChatName"))document.getElementById("partyChatName").value=saved;
  refreshPartyChat();
}
function closePartyChat(){let m=document.getElementById("partyChatModal");if(m)m.classList.remove("show");currentChatPostId=null;}
function refreshPartyChat(){
  if(!currentChatPostId)return;
  fetch("/api/party_chat/"+currentChatPostId+"?client_id="+encodeURIComponent(getClientId()))
  .then(r=>r.text()).then(html=>{let box=document.getElementById("partyChatList");if(box){box.innerHTML=html;box.scrollTop=box.scrollHeight;}});
}
function sendPartyChat(){
  if(!currentChatPostId)return;
  let name=document.getElementById("partyChatName");
  let text=document.getElementById("partyChatText");
  if(!text||!text.value.trim())return;
  if(name&&name.value.trim())localStorage.setItem("baram_chat_name",name.value.trim());
  fetch("/party_chat/"+currentChatPostId,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({client_id:getClientId(),name:name?name.value.trim():"익명",text:text.value.trim()})})
  .then(r=>r.json()).then(res=>{if(!res.ok){showToast("참여자만 이용 가능");return;}text.value="";refreshPartyChat();refreshList();});
}
setInterval(refreshPartyChat,1600);
markMyPosts();
applyOwnerProtection();
updateAlarmButton();
scanNotifications();
</script>
</body>
</html>
"""

@app.route("/")
def home():
    filter_value = request.args.get("filter", "전체")
    posts = filtered_posts(filter_value)
    open_count = sum(1 for p in posts if status_of(p) == "모집중")
    total_count = len(posts)
    return render_template_string(PAGE, page="home", filter_value=filter_value, filters=FILTERS, post_list=render_posts(posts), jobs=ALL_JOBS, hunting=HUNTING, farming=FARMING, quest600=QUEST600, open_count=open_count, total_count=total_count)

@app.route("/api/posts")
def api_posts():
    filter_value = request.args.get("filter", "전체")
    return render_posts(filtered_posts(filter_value))

@app.route("/new")
def new_post():
    return render_template_string(PAGE, page="new", post=None, jobs=ALL_JOBS, hunting=HUNTING, farming=FARMING, quest600=QUEST600)

@app.route("/profile")
def profile():
    return render_template_string(PAGE, page="profile", jobs=ALL_JOBS)

@app.route("/edit/<post_id>", methods=["GET", "POST"])
def edit_post(post_id):
    if request.method == "GET":
        post = find_post(post_id)
        if not post:
            return redirect("/")
        return render_template_string(PAGE, page="edit", post=post, jobs=ALL_JOBS, hunting=HUNTING, farming=FARMING, quest600=QUEST600)

    def do_edit(data):
        for p in data.get("posts", []):
            if p.get("id") == post_id:
                if p.get("owner_id") and p.get("owner_id") != request.form.get("owner_id", "").strip():
                    return
                post_type = request.form.get("type", "사냥")
                if post_type == "사냥":
                    place = request.form.get("place_hunting", "")
                elif post_type == "파밍":
                    place = request.form.get("place_farming", "")
                else:
                    place = request.form.get("place_quest", "")
                jobs = request.form.getlist("slots")
                chars = request.form.getlist("slot_chars")
                participant_ids = request.form.getlist("slot_participant_ids")
                slots = []
                for idx, job in enumerate(jobs):
                    slots.append({
                        "id": str(uuid.uuid4()),
                        "job": job,
                        "char": chars[idx] if idx < len(chars) else "",
                        "participant_id": participant_ids[idx] if idx < len(participant_ids) else ""
                    })
                p["owner"] = request.form.get("owner", "").strip()
                p["type"] = post_type
                p["place"] = place
                p["channel"] = request.form.get("channel", "").strip()
                p["start_period"] = request.form.get("start_period", "")
                p["start_time"] = request.form.get("start_time", "").strip()
                p["end_period"] = request.form.get("end_period", "")
                p["end_time"] = request.form.get("end_time", "").strip()
                p["memo"] = request.form.get("memo", "").strip()
                p["slots"] = slots
                if not is_full(p):
                    p["closed"] = False
                    p["closed_at"] = ""
                else:
                    ensure_auto_closed(p)
                break
    mutate_data(do_edit)
    return redirect("/")

@app.route("/create", methods=["POST"])
def create():
    def do_create(data):
        post_type = request.form.get("type", "사냥")
        if post_type == "사냥":
            place = request.form.get("place_hunting", "")
        elif post_type == "파밍":
            place = request.form.get("place_farming", "")
        else:
            place = request.form.get("place_quest", "")
        slots = request.form.getlist("slots")
        post = {
            "id": str(uuid.uuid4()),
            "owner": request.form.get("owner", "").strip(),
            "owner_id": request.form.get("owner_id", "").strip(),
            "type": post_type,
            "place": place,
            "channel": request.form.get("channel", "").strip(),
            "start_period": request.form.get("start_period", ""),
            "start_time": request.form.get("start_time", "").strip(),
            "end_period": request.form.get("end_period", ""),
            "end_time": request.form.get("end_time", "").strip(),
            "memo": request.form.get("memo", "").strip(),
            "created": now_text(),
            "closed": False,
            "closed_at": "",
            "slots": [{"id": str(uuid.uuid4()), "job": job, "char": ""} for job in slots],
        }
        data["posts"].append(post)
    mutate_data(do_create)
    return redirect("/")

@app.route("/join", methods=["POST"])
def join():
    req = request.get_json(force=True)
    def do_join(data):
        for post in data.get("posts", []):
            if post.get("id") == req.get("post_id") and not post.get("closed"):
                # 같은 캐릭터 중복 참여 방지
                char_name = req.get("char", "").strip()
                for slot in post.get("slots", []):
                    if slot.get("char") == char_name:
                        return
                for slot in post.get("slots", []):
                    if slot.get("id") == req.get("slot_id") and not slot.get("char"):
                        slot["char"] = char_name
                        slot["participant_id"] = req.get("participant_id", "").strip()
                        ensure_auto_closed(post)
                        return
    mutate_data(do_join)
    return jsonify(ok=True)

@app.route("/leave", methods=["POST"])
def leave():
    req = request.get_json(force=True)
    def do_leave(data):
        for post in data.get("posts", []):
            if post.get("id") == req.get("post_id"):
                is_owner = post.get("owner_id") and post.get("owner_id") == req.get("participant_id")
                for slot in post.get("slots", []):
                    if slot.get("id") == req.get("slot_id"):
                        is_participant = slot.get("participant_id") and slot.get("participant_id") == req.get("participant_id")
                        if not (is_owner or is_participant):
                            return
                        slot["char"] = ""
                        slot["participant_id"] = ""
                        post["closed"] = False
                        post["closed_at"] = ""
                        return
    mutate_data(do_leave)
    return jsonify(ok=True)

@app.route("/close", methods=["POST"])
def close():
    req = request.get_json(force=True)
    def do_close(data):
        for post in data.get("posts", []):
            if post.get("id") == req.get("post_id"):
                if post.get("owner_id") and post.get("owner_id") != req.get("owner_id", ""):
                    return
                post["closed"] = True
                if not post.get("closed_at"):
                    post["closed_at"] = now_iso()
                return
    mutate_data(do_close)
    return jsonify(ok=True)

@app.route("/delete", methods=["POST"])
def delete():
    req = request.get_json(force=True)
    def do_delete(data):
        post_id = req.get("post_id")
        owner_id = req.get("owner_id", "")
        data["posts"] = [
            post for post in data.get("posts", [])
            if not (post.get("id") == post_id and (not post.get("owner_id") or post.get("owner_id") == owner_id))
        ]
    mutate_data(do_delete)
    return jsonify(ok=True)


def can_access_party_chat(post, client_id):
    if not client_id:
        return False
    if post.get("owner_id") == client_id:
        return True
    for slot in post.get("slots", []):
        if slot.get("participant_id") == client_id:
            return True
    return False

def render_party_chats(post, client_id):
    if not can_access_party_chat(post, client_id):
        return '<div class="chat-msg"><div class="chat-text">참여자만 이용 가능합니다.</div></div>'
    chats = post.get("chats", [])[-80:]
    if not chats:
        return '<div class="chat-msg"><div class="chat-text">아직 메시지가 없습니다.</div></div>'
    out = []
    for c in chats:
        mine = " mine" if c.get("client_id") == client_id else ""
        out.append(f"""
<div class="chat-msg{mine}">
  <div class="chat-meta">{esc(c.get("name") or "익명")} · {esc(c.get("time"))}</div>
  <div class="chat-text">{esc(c.get("text"))}</div>
</div>
""")
    return "\\n".join(out)

@app.route("/api/party_chat/<post_id>")
def api_party_chat(post_id):
    client_id = request.args.get("client_id", "")
    post = find_post(post_id)
    if not post:
        return '<div class="chat-msg"><div class="chat-text">모집글이 없습니다.</div></div>'
    return render_party_chats(post, client_id)

@app.route("/party_chat/<post_id>", methods=["POST"])
def party_chat(post_id):
    req = request.get_json(force=True)
    client_id = (req.get("client_id") or "").strip()
    name = (req.get("name") or "익명").strip()[:12]
    text = (req.get("text") or "").strip()[:120]
    if not text:
        return jsonify(ok=False)
    allowed = {"ok": False}
    def do_chat(data):
        for post in data.get("posts", []):
            if post.get("id") == post_id:
                if not can_access_party_chat(post, client_id):
                    allowed["ok"] = False
                    return
                post.setdefault("chats", [])
                post["chats"].append({
                    "client_id": client_id,
                    "name": name,
                    "text": text,
                    "time": datetime.now().strftime("%H:%M")
                })
                if len(post["chats"]) > 100:
                    post["chats"] = post["chats"][-100:]
                allowed["ok"] = True
                return
    mutate_data(do_chat)
    return jsonify(ok=allowed["ok"])

@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "월하 연가 연희 파티모집 v3.1",
        "short_name": "파티채팅",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f1016",
        "theme_color": "#11131d",
        "icons": []
    })

@app.route("/sw.js")
def sw():
    content = """
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());
"""
    return app.response_class(content, mimetype="application/javascript")

if __name__ == "__main__":
    print("월하 · 연가 · 연희 통합 파티 모집 서버 시작")
    print("내 PC 접속: http://127.0.0.1:7777")
    print("같은 와이파이 접속: http://이PC의IP:7777")
    print("마감/모집완료 글은 1시간 뒤 자동 삭제됩니다.")
    app.run(host="0.0.0.0", port=7777, debug=False, threaded=True)
