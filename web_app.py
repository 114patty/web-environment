from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from flask_cors import CORS
from pymongo import MongoClient
import datetime
from datetime import timedelta
from pytz import timezone, UTC
import os # 導入 os 模組
from dateutil import parser as dtparser  # pip install python-dateutil
from werkzeug.middleware.proxy_fix import ProxyFix
from functools import wraps
from apscheduler.schedulers.background import BackgroundScheduler
from pymongo import ASCENDING


# 壓縮資料
def compress_segments(docs):
    MAX_GAP_MS = 5 * 60 * 1000
    segments, segment = [], None
    last_state = last_mac = None
    last_ts_ms = None

    for doc in docs:
        state = str(doc.get("Posture_state", "unknown"))
        mac_v = doc.get("safe_Mac")
        ts = doc.get("timestamp")
        ts_ms = (ts.timestamp() if isinstance(ts, datetime.datetime)
                 else dtparser.isoparse(ts).timestamp()) * 1000.0

        if (segment and last_state == state and last_mac == mac_v):        # and last_ts_ms is not None and ts_ms - last_ts_ms <= MAX_GAP_MS
            segment["endTime"] = ts_ms
            segment["duration"] = (segment["endTime"] - segment["startTime"]) / 1000.0
        else:
            if segment:
                # 確保有 duration
                segment["duration"] = (segment["endTime"] - segment["startTime"]) / 1000.0
                segments.append(segment)
            segment = {"state": state, "startTime": ts_ms, "endTime": ts_ms, "safe_Mac": mac_v, "duration": 0.0}

        last_state, last_mac, last_ts_ms = state, mac_v, ts_ms

    if segment:
        segment["duration"] = (segment["endTime"] - segment["startTime"]) / 1000.0
        segments.append(segment)

    return segments

# 每小時自動壓縮 (ETL)
def hourly_etl():
    now = datetime.datetime.now(tz)
    last_hour_end = now.replace(minute=0, second=0, microsecond=0)
    last_hour_start = last_hour_end - datetime.timedelta(hours=1)

    # 檢查這一小時是否已經壓縮過
    check_query = {
        "startTime": {"$gte": last_hour_start.timestamp()*1000,
                      "$lt":  last_hour_end.timestamp()*1000}
    }
    exists = mongo_segments.count_documents(check_query)

    if exists > 0:
        print(f"[ETL] {last_hour_start} 已壓縮過，跳過")
        return

    # 查 raw 資料
    raw_query = {"timestamp": {"$gte": last_hour_start, "$lt": last_hour_end}}
    raw_cursor = mongo_data.find(
        raw_query,
        {"_id": 0, "timestamp": 1, "Posture_state": 1, "safe_Mac": 1}
    ).sort("timestamp", 1)

    raw_segments = compress_segments(raw_cursor)

    # for seg in raw_segments:
    #     seg["duration"] = (seg["endTime"] - seg["startTime"]) / 1000.0

    if raw_segments:
        mongo_segments.insert_many(raw_segments)
        print(f"[ETL] 壓縮 {last_hour_start} ~ {last_hour_end} → {len(raw_segments)} 段")


def full_etl():
    """把整個歷史資料從 raw 壓縮到 posture_segments"""
    first_doc = mongo_data.find_one(sort=[("timestamp", 1)])
    last_doc  = mongo_data.find_one(sort=[("timestamp", -1)])

    if not first_doc or not last_doc:
        return "⚠️ 沒有資料"

    start_time = first_doc["timestamp"]
    end_time   = last_doc["timestamp"]

    # 以小時為單位，逐段壓縮
    current = start_time.replace(minute=0, second=0, microsecond=0)
    total_segments = 0

    while current < end_time:
        next_hour = current + datetime.timedelta(hours=1)

        # 檢查這小時是否已經壓縮過
        check_query = {
            "startTime": {"$gte": current.timestamp()*1000,
                          "$lt":  next_hour.timestamp()*1000}
        }
        exists = mongo_segments.count_documents(check_query)
        if exists > 0:
            print(f"[FULL ETL] {current} 已壓縮過，跳過")
            current = next_hour
            continue

        # 找這小時的 raw
        raw_query = {"timestamp": {"$gte": current, "$lt": next_hour}}
        raw_cursor = mongo_data.find(
            raw_query,
            {"_id": 0, "timestamp": 1, "Posture_state": 1, "safe_Mac": 1}
        ).sort("timestamp", 1)

        raw_segments = compress_segments(raw_cursor)

        # for seg in raw_segments:
        #     seg["duration"] = (seg["endTime"] - seg["startTime"]) / 1000.0
        if raw_segments:
            mongo_segments.insert_many(raw_segments)
            total_segments += len(raw_segments)
            print(f"[FULL ETL] 壓縮 {current} ~ {next_hour} → {len(raw_segments)} 段")

        current = next_hour

    return f"✅ 全部歷史壓縮完成，共寫入 {total_segments} 段"



scheduler = BackgroundScheduler()
scheduler.add_job(hourly_etl, 'cron', minute=5)  # 每小時第 5 分鐘跑一次
scheduler.start()

app = Flask(__name__, static_folder='static')

app.wsgi_app = ProxyFix(app.wsgi_app, x_host=1)  # 接受不同 Host header


CORS(app)
tz = timezone('Asia/Taipei')
now = datetime.datetime.now(UTC)
# **重要：請替換為一個真正隨機且安全的密鑰**
# 這是 Flask 會話加密的密鑰。在生產環境中，應使用更複雜且保密的密鑰。
app.secret_key = 'your_super_secret_and_long_key_here_please_change_this_immediately' 
app.permanent_session_lifetime = timedelta(minutes=10)

# 假設的帳號密碼 (實際應用中應從數據庫中獲取或使用更安全的驗證方式)
# 在生產環境中，密碼應該被雜湊處理（hashed），而不是明文儲存。
USERS = {
    "admin": "user",
    "user": "0123"
}

# --- MongoDB 連線設定 (與樹莓派上的一致) ---
# MONGO_URI = "mongodb://localhost:27017/" # 網頁應用程式運行在同一台電腦，所以用 localhost
pd = "20021205patty"
MONGO_URI = f"mongodb+srv://114patty:{pd}@cluster0.hjdwg6c.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_NAME = "F332"
COLLECTION_NAME = "posture_data"

# 初始化連線
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]

# 原始資料 (每秒姿態)
mongo_data = db["posture_data"]

# 壓縮後段落資料 (新 collection)
mongo_segments = db["posture_segments"]

# 啟動時建立索引（如果已存在不會重複建立）
mongo_data.create_index([("mac", ASCENDING), ("timestamp", ASCENDING)])
# 啟動時建立索引（如果已存在不會重複建立）
mongo_data.create_index([("safe_Mac", ASCENDING), ("timestamp", ASCENDING)])
mongo_segments.create_index([("safe_Mac", ASCENDING), ("startTime", ASCENDING)])


# mongo_client = None
# mongo_collection = None

# 共用裝飾器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            session.clear()
            # 加上 expired=1 的參數，讓登入頁知道是 session 過期
            return redirect(url_for('login_page', expired=1))
        return f(*args, **kwargs)
    return decorated_function

def connect_to_mongodb_web():
    """連接到 MongoDB 資料庫。"""
    global mongo_client, mongo_collection
    try:
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command('ping') # 測試連線
        db = mongo_client[DB_NAME]
        mongo_collection = db[COLLECTION_NAME]
        print("網頁應用程式成功連接到 MongoDB")
    except Exception as e:
        print(f"網頁應用程式連接 MongoDB 失敗: {e}")
        mongo_client = None
        mongo_collection = None

# 在應用程式啟動時嘗試連接 MongoDB
connect_to_mongodb_web()

# ----------------- 登入相關路由 -----------------
@app.route('/')
def login_page():
    try:
        if 'logged_in' in session and session['logged_in']:
            return redirect(url_for('data_dashboard'))
        return render_template('login.html', request=request)  # 如果模板有使用 request 物件
    except BadRequest as e:
        print("Bad request error:", e)
        return "Bad Request", 400

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')

    if username in USERS and USERS[username] == password:
        session.permanent = True  # ✅ 不要設定為永久，讓它關閉視窗就失效
        session['logged_in'] = True
        session['username'] = username # 可選：儲存使用者名稱
        return jsonify(success=True)
    else:
        return jsonify(success=False, message='無效的帳號或密碼')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('login_page'))

@app.route('/auto_logout', methods=['POST'])
def auto_logout():
    session.clear()  # 清除所有登入 session
    return '', 204   # 回傳 204 No Content，適合給 background request 用

# --- 路由：主頁面 (數據監測儀表板) ---
@app.route('/homepage')
# @login_required
def data_dashboard():
    # 如果用戶未登入，重定向到登入頁
    if not ('logged_in' in session and session['logged_in']):
        return redirect(url_for('login_page'))
    # 檔名.html
    return render_template('index.html')

# --- 路由：提供最新數據的 API ---
@app.route('/api/latest_data')
def get_latest_data():
    # print("💡 收到 /api/latest_data 請求")

    if mongo_collection is not None:
        try:
            latest_readings = list(mongo_collection.find().sort("timestamp", -1).limit(100))
            print(f"[DEBUG] 總共取得 {len(latest_readings)} 筆最新資料")

            print("=== 最新資料 ===")
            # 將 ObjectId 轉換為字串，因為 ObjectId 無法直接 JSON 序列化
            for doc in latest_readings:
                doc['_id'] = str(doc['_id'])
                # if isinstance(doc.get('timestamp'), datetime.datetime):
                #     local_ts = doc['timestamp'].astimezone(tz)
                #     doc['timestamp'] = local_ts.strftime('%Y-%m-%d %H:%M:%S.%f')[:-4]
            return jsonify(latest_readings)
        except Exception as e:
            print(f"從 MongoDB 獲取數據失敗: {e}")
            # 如果數據庫連線斷開，嘗試重新連線
            connect_to_mongodb_web() 
            return jsonify({"error": "Failed to retrieve data", "details": str(e)}), 500
    else:
        # 如果初始連線失敗，這裡也嘗試重新連線
        connect_to_mongodb_web() 
        return jsonify({"error": "MongoDB not connected"}), 500

# --- Mac 資料 ---
@app.route('/api/mac_list')
def get_mac_list():
    if mongo_collection is not None:
        try:
            macs = mongo_collection.distinct('safe_Mac')
            return jsonify(macs)
        except Exception as e:
            return jsonify({"error": "Failed to retrieve MAC list", "details": str(e)}), 500
    else:
        connect_to_mongodb_web()
        return jsonify({"error": "MongoDB not connected"}), 500          

# --- 路由：提供指定時間範圍或全部數據的 API ---
@app.route('/api/history_data')
def history_data():
    if mongo_collection is not None:
        try:
            minutes = request.args.get("minutes", default=None, type=int)
            hours = request.args.get("hours", default=None, type=int)
            full = request.args.get("full", default=0, type=int)
            limit   = request.args.get("limit",   default=10000, type=int)
            
            query = {}

            if hours:
                now = datetime.datetime.now(tz)
                start_time = now - datetime.timedelta(hours=hours)
                query = {"timestamp": {"$gte": start_time}}
            elif minutes:
                now = datetime.datetime.now(tz)
                start_time = now - datetime.timedelta(minutes=minutes)
                query = {"timestamp": {"$gte": start_time}}

            mac = request.args.get("mac") or request.args.get("safe_Mac")
            if mac:
                query["safe_Mac"] = mac
            

            data = []
            cursor = (mongo_collection.find(query)
                                     .sort("timestamp", -1)  # 遞增，省去 reverse
                                     .limit(limit))
            for doc in cursor:
                doc['_id'] = str(doc['_id'])
                # if isinstance(doc.get('timestamp'), datetime.datetime):
                #     doc['timestamp'] = doc['timestamp'].isoformat() + "Z"
                data.append(doc)

            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# 取history_data壓縮後的資料(姿態圖表用)
# @app.route('/api/history_posechart')
# def history_posechart():
#     print("✅ 收到 /api/history_posechart 請求")

#     try:
#         minutes = request.args.get("minutes", type=int)
#         hours   = request.args.get("hours",   default=24,type=int)
#         limit   = request.args.get("limit",   default=1000, type=int)
#         mac     = request.args.get("mac") or request.args.get("safe_Mac")

#         query = {}
#         now = datetime.datetime.now(tz)
#         # minutes = 30  # 查過去幾分鐘的資料
#         start_time = now - timedelta(minutes=minutes)

#         query = {
#             'timestamp': {'$gte': start_time}
#         }

#         # if minutes is not None:
#         #     query["timestamp"] = {"$gte": now - datetime.timedelta(minutes=minutes)}
#         # else:
#         #     query["timestamp"] = {"$gte": now - datetime.timedelta(hours=hours or 24)}

#         if mac:
#             query["safe_Mac"] = mac

#         cursor = mongo_collection.find(query).sort("timestamp", 1).limit(limit)
#         docs = list(cursor)
#         print(f"[DEBUG] Query: {query}, 找到 {len(docs)} 筆資料")

#         segments = []
#         segment = None
#         MAX_GAP_MS = 5 * 60 * 1000

#         for doc in docs:
#             state_raw = str(doc.get("Posture_state") or doc.get("state") or "unknown")
#             state = state_raw
#             mac_v = doc.get("safe_Mac")

#             ts = doc.get("timestamp")
#             if isinstance(ts, datetime.datetime):
#                 ts = ts.astimezone(tz)
#                 ts_ms = int(ts.timestamp() * 1000.0)
#             else:
#                 ts_ms = int(dtparser.isoparse(ts).timestamp() * 1000.0)


#             if (
#                 segment
#                 and segment["state"] == state
#                 and segment["safe_Mac"] == mac_v
#                 and ts_ms - segment["endTime"] <= MAX_GAP_MS
#             ):
#                 segment["endTime"] = ts_ms
#             else:
#                 if segment:
#                     segments.append(segment)
#                 segment = {
#                     "state": state,
#                     "startTime": ts_ms,
#                     "endTime": ts_ms,
#                     "safe_Mac": mac_v,
#                 }

#         if segment:
#             segments.append(segment)

#         return jsonify(segments)

#     except Exception as e:
#         return jsonify({"error": str(e)}), 500

@app.route('/api/debug_time')
def debug_time():
    now = datetime.datetime.now(tz)
    return jsonify({
        "now": now.isoformat(),
        "ts": int(now.timestamp() * 1000)
    })


@app.route('/api/history_posechart')
def history_posechart():
    try:
        minutes = request.args.get("minutes", type=int)
        hours   = request.args.get("hours",   type=int)
        full    = request.args.get("full",    default=0, type=int)

        MAX_LIMIT = 900000
        SAFE_DEFAULT_LIMIT = 100000
        limit = request.args.get("limit", default=SAFE_DEFAULT_LIMIT, type=int) or SAFE_DEFAULT_LIMIT
        limit = min(limit, MAX_LIMIT)

        # ---- 裝置參數 ----
        mac = request.args.get("mac") or request.args.get("safe_Mac")
        macs_str = request.args.get("macs")  # 例如 macs=F7792BAEB511,ABCD12345678
        macs = [m.strip() for m in macs_str.split(",")] if macs_str else None

        query = {}
        now = datetime.datetime.now(tz)

        # ---- 時間限制 ----
        if hours:
            if hours > 24:
                return jsonify({"error": "最多只能查 24 小時"}), 400
            query["timestamp"] = {"$gte": now - datetime.timedelta(hours=hours)}
        elif minutes:
            query["timestamp"] = {"$gte": now - datetime.timedelta(minutes=minutes)}
        elif not full:
            query["timestamp"] = {"$gte": now - datetime.timedelta(minutes=30)}
        else:
            return jsonify({"error": "full=1 必須指定 mac 或 macs"}), 400

        # ---- 裝置條件 ----
        if macs:
            query["safe_Mac"] = {"$in": macs}
        elif mac:
            query["safe_Mac"] = mac

        # ---- pipeline ----
        pipeline = [
            {"$match": query},
            {"$sort": {"timestamp": -1}},
            {"$limit": limit},
            {"$sort": {"timestamp": 1}},
            {"$project": {"_id": 0, "timestamp": 1, "Posture_state": 1, "safe_Mac": 1}},
        ]
        cursor = mongo_collection.aggregate(pipeline, allowDiskUse=True)

        # ✅ 用共用的壓縮函式
        docs = list(cursor)
        segments = compress_segments(docs)
        return jsonify(segments)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    #     # ---- 段落壓縮 ----
    #     MAX_GAP_MS = 5 * 60 * 1000
    #     segments, segment = [], None
    #     last_state = last_mac = None
    #     last_ts_ms = None

    #     for doc in cursor:
    #         state = str(doc.get("Posture_state", "unknown"))
    #         mac_v = doc.get("safe_Mac")
    #         ts = doc.get("timestamp")
    #         ts_ms = (ts.timestamp() if isinstance(ts, datetime.datetime)
    #                  else dtparser.isoparse(ts).timestamp()) * 1000.0

    #         if (segment and last_state == state and last_mac == mac_v ):  # and last_ts_ms is not None and ts_ms - last_ts_ms <= MAX_GAP_MS
    #             segment["endTime"] = ts_ms
    #         else:
    #             if segment:
    #                 segments.append(segment)
    #             segment = {
    #                 "state": state,
    #                 "startTime": ts_ms,
    #                 "endTime": ts_ms,
    #                 "safe_Mac": mac_v,
    #             }

    #         last_state, last_mac, last_ts_ms = state, mac_v, ts_ms

    #     if segment:
    #         segments.append(segment)

    #     return jsonify(segments)

    # except Exception as e:
    #     return jsonify({"error": str(e)}), 500


# @app.route('/api/all_history_posechart')
# def all_history_posechart():
#     try:
#         minutes = request.args.get("minutes", type=int)
#         hours   = request.args.get("hours",   type=int)
#         full    = request.args.get("full",    default=0, type=int)

#         MAX_LIMIT = 50000
#         limit = request.args.get("limit", default=10000, type=int) or 10000
#         limit = min(limit, MAX_LIMIT)

#         # 裝置參數
#         mac = request.args.get("mac") or request.args.get("safe_Mac")
#         macs_str = request.args.get("macs")
#         macs = [m.strip() for m in macs_str.split(",")] if macs_str else None

#         # ---- 時間範圍 ----
#         now = datetime.datetime.now(tz)
#         start_time = None
#         if hours:
#             if hours > 24:
#                 return jsonify({"error": "最多只能查 24 小時"}), 400
#             start_time = now - datetime.timedelta(hours=hours)
#         elif minutes:
#             start_time = now - datetime.timedelta(minutes=minutes)
#         elif not full:
#             start_time = now - datetime.timedelta(minutes=30)

#         # ---- Query base ----
#         query = {}
#         if start_time:
#             query["startTime"] = {"$gte": start_time.timestamp() * 1000}

#         if macs:
#             query["safe_Mac"] = {"$in": macs}
#         elif mac:
#             query["safe_Mac"] = mac

#         # ---- 查 posture_segments（壓縮過的歷史資料） ----
#         seg_cursor = (
#             mongo_collection_segments
#                 .find(query, {"_id": 0, "safe_Mac": 1, "state": 1, "startTime": 1, "endTime": 1})
#                 .sort("startTime", 1)
#                 .limit(limit)
#         )
#         seg_docs = list(seg_cursor)

#         # ---- 查今天的 raw，補即時資料 ----
#         today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
#         raw_query = {}
#         if macs:
#             raw_query["safe_Mac"] = {"$in": macs}
#         elif mac:
#             raw_query["safe_Mac"] = mac
#         raw_query["timestamp"] = {"$gte": today_start}

#         raw_cursor = (
#             mongo_collection_raw
#                 .find(raw_query, {"_id": 0, "timestamp": 1, "Posture_state": 1, "safe_Mac": 1})
#                 .sort("timestamp", 1)
#                 .limit(limit)
#         )

#         # 壓縮 raw → segments
#         def compress_segments(docs):
#             MAX_GAP_MS = 5 * 60 * 1000
#             segments, segment = [], None
#             last_state = last_mac = None
#             last_ts_ms = None

#             for doc in docs:
#                 state = str(doc.get("Posture_state", "unknown"))
#                 mac_v = doc.get("safe_Mac")
#                 ts = doc.get("timestamp")
#                 ts_ms = (ts.timestamp() if isinstance(ts, datetime.datetime)
#                          else dtparser.isoparse(ts).timestamp()) * 1000.0

#                 if (segment and last_state == state and last_mac == mac_v and
#                     last_ts_ms is not None and ts_ms - last_ts_ms <= MAX_GAP_MS):
#                     segment["endTime"] = ts_ms
#                 else:
#                     if segment:
#                         segments.append(segment)
#                     segment = {"state": state, "startTime": ts_ms, "endTime": ts_ms, "safe_Mac": mac_v}

#                 last_state, last_mac, last_ts_ms = state, mac_v, ts_ms

#             if segment:
#                 segments.append(segment)

#             return segments

#         raw_segments = compress_segments(raw_cursor)

#         # ---- 合併 posture_segments + raw_segments ----
#         all_segments = seg_docs + raw_segments
#         all_segments.sort(key=lambda x: x["startTime"])  # 保證時間順序

#         print(f"[DEBUG] v2 Query: segments={len(seg_docs)}, raw_today={len(raw_segments)}, total={len(all_segments)}")

#         return jsonify(all_segments)

#     except Exception as e:
#         return jsonify({"error": str(e)}), 500

@app.route('/api/run_etl')
def run_etl():
    hourly_etl()
    return jsonify({"status": "ok"})

@app.route('/api/full_etl')
def run_full_etl():
    result = full_etl()
    return jsonify({"status": result})

@app.route('/api/last_timestamp')
def last_timestamp():
    latest = mongo_data.find_one(sort=[("timestamp", -1)])
    if not latest:
        return jsonify({"last_ts": None})
    ts = latest["timestamp"]
    ts_ms = ts.timestamp() * 1000 if isinstance(ts, datetime.datetime) else dtparser.isoparse(ts).timestamp() * 1000
    return jsonify({"last_ts": ts_ms})


@app.route('/api/all_history_posechart')
def all_history_posechart():
    try:
        minutes = request.args.get("minutes", type=int)
        hours   = request.args.get("hours",   type=int)
        full    = request.args.get("full",    default=0, type=int)

        MAX_LIMIT = 80000
        limit = request.args.get("limit", default=10000, type=int) or 10000
        limit = min(limit, MAX_LIMIT)

        # 裝置參數
        mac = request.args.get("mac") or request.args.get("safe_Mac")
        macs_str = request.args.get("macs")
        macs = [m.strip() for m in macs_str.split(",")] if macs_str else None

        # ---- 時間範圍 ----
        now = datetime.datetime.now(tz)
        query = {}
        if hours:
            if hours > 24:
                return jsonify({"error": "最多只能查 24 小時"}), 400
            query["startTime"] = {"$gte": (now - datetime.timedelta(hours=hours)).timestamp() * 1000}
        elif minutes:
            query["startTime"] = {"$gte": (now - datetime.timedelta(minutes=minutes)).timestamp() * 1000}
        elif not full:
            query["startTime"] = {"$gte": (now - datetime.timedelta(minutes=30)).timestamp() * 1000}

        if macs:
            query["safe_Mac"] = {"$in": macs}
        elif mac:
            query["safe_Mac"] = mac

        # ---- 查壓縮後的 segments ----
        seg_cursor = (
            mongo_segments
                .find(query, {"_id": 0, "safe_Mac": 1, "state": 1,
                              "startTime": 1, "endTime": 1})
                .sort("startTime", 1)
                .limit(limit)
        )
        seg_docs = list(seg_cursor)

        # === 2. 查今天的 raw 資料 ===
        # today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # raw_query = {"timestamp": {"$gte": today_start}}
        raw_query = {"timestamp": {"$gte": now - datetime.timedelta(minutes=10)}}
        if mac:
            raw_query["safe_Mac"] = mac
        elif macs:
            raw_query["safe_Mac"] = {"$in": macs}

        raw_cursor = (
            mongo_data
                .find(raw_query, {"_id":0,"timestamp":1,"Posture_state":1,"safe_Mac":1})
                .sort("timestamp", 1)
        )
        raw_segments = compress_segments(raw_cursor)

        # === 3. 合併兩邊的結果 ===
        all_segments = seg_docs + raw_segments
        all_segments.sort(key=lambda x: x["startTime"])

        print(f"[DEBUG] Query={query}, 返回 {len(seg_docs)} 筆壓縮資料")
        print(f"[DEBUG] seg={len(seg_docs)}, raw_today={len(raw_segments)}, total={len(all_segments)}")
        return jsonify(all_segments)
        # return jsonify(seg_docs)

    except Exception as e:
        return jsonify({"error": str(e)}), 500




# --- 路由：提供所有數據的 API (不推薦用於大量數據，僅作範例) ---
@app.route('/api/all_data')
@login_required
def get_all_data(): 
    # # 檢查用戶是否已登入
    if not ('logged_in' in session and session['logged_in']):
        return jsonify({"error": "未經授權，請先登入"}), 401 # 返回未授權錯誤
        
    if mongo_collection is not None:
        try:
            all_readings = []
            for doc in mongo_collection.find():
                doc['_id'] = str(doc['_id'])
                if isinstance(doc.get('timestamp'), datetime.datetime):
                    doc['timestamp'] = (doc['timestamp'] + datetime.timedelta(hours=8)).isoformat()
                all_readings.append(doc)
            return jsonify(all_readings)
        except Exception as e:
            print(f"從 MongoDB 獲取所有數據失敗: {e}")
            connect_to_mongodb_web()
            return jsonify({"error": "Failed to retrieve all data", "details": str(e)}), 500
    else:
        connect_to_mongodb_web()
        return jsonify({"error": "MongoDB not connected"}), 500

# --- 主題顏色 ---
@app.route('/theme')
@login_required
def theme_page():
    return render_template('theme.html')  # 新增一個 theme.html

# --- 歷史紀錄 ---
@app.route('/history')
@login_required
def history():
    return render_template('history.html')

# --- 居家追蹤 ---
@app.route('/home_monitor')
@login_required
def home_monitor():
    return render_template('home-monitor.html')

# --- 設定 ---
@app.route('/settings')
@login_required
def setting():
    return render_template('settings.html')

# --- 飲食紀錄 ---
@app.route('/diet')
@login_required
def diet():
    return render_template('diet.html')

@app.route('/test')
def test_route():
    return "Test route works! This page does not use cookies or sessions."


if __name__ == '__main__':
    # 設定允許的 Host
    # app.config['SERVER_NAME'] = "192.168.1.156:8080"

    # 確保 'templates' 資料夾存在，如果沒有會自動創建
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    # 設置 Flask 在所有可用介面監聽 (0.0.0.0)，這樣其他裝置也能透過 IP 訪問
    # 在開發環境中，debug=True 會自動重載程式碼並提供詳細錯誤訊息
    app.run(host='0.0.0.0', port=5050, debug=True)
