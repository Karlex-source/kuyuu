import json
import random
import time
import requests
from flask import Flask, render_template, request, g, jsonify

import psycopg2
from psycopg2.extras import RealDictCursor

# 初始化Flask应用
app = Flask(__name__)

# --- 数据库配置 ---
DB_CONFIG = {
    "dbname": "examdb",
    "user": "karlex",
    "password": "828124@ZBL",
    "host": "8.154.86.53",
    "port": "5432"
}

# --- 应用级变量 ---
SUBJECTS = [] # 用于存储从数据库加载的科目列表

# --- API配置 ---
API_BASE_URL = "https://yunyj.linyi.net/api/read/getlog"
API_TOKEN = "gzEx3e-ySUy3XGgzsKOZtw"
# 科目名称到libid的映射（需要根据实际情况配置）
SUBJECT_LIBID_MAP = {
    "语文": 1,
    "数学": 2,
    "英语": 3,
    "物理": 4,
    "化学": 5,
    "生物": 6,
    "政治": 7,
    "历史": 8,
    "地理": 9,
}

def get_db():
    """获取数据库连接"""
    if 'db' not in g:
        try:
            # 使用RealDictCursor让查询结果返回字典形式，方便处理
            g.db = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
        except psycopg2.OperationalError as e:
            print(f"[!] 数据库连接失败: {e}")
            g.db = None
    return g.db

@app.teardown_appcontext
def close_db(exception):
    """请求结束时自动关闭数据库连接"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def load_subjects():
    """在应用启动时加载所有科目列表"""
    global SUBJECTS
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT subject_name FROM scores ORDER BY subject_name;")
        subjects_records = cur.fetchall()
        SUBJECTS = [record[0] for record in subjects_records]
        cur.close()
        conn.close()
        print(f"[+] 成功加载科目列表: {SUBJECTS}")
    except Exception as e:
        print(f"[!] 加载科目列表失败: {e}")
        if conn:
            conn.close()

# --- 路由和视图函数 ---
@app.route('/', methods=['GET'])
def index():
    # 渲染主页面，并传递科目列表
    return render_template('index.html', subjects=SUBJECTS, result=None, error=None)

@app.route('/query', methods=['POST'])
def query_paper():
    """处理试卷ID查询请求"""
    search_result = None
    error_message = None
    
    conn = get_db()
    if conn is None:
        return render_template('index.html', subjects=SUBJECTS, error="数据库连接失败，请检查后端服务。")

    paper_id_query = request.form.get('paperid', '').strip()
    
    if not paper_id_query:
        error_message = "请输入一个试卷ID。"
    else:
        try:
            paper_id = int(paper_id_query)
            cur = conn.cursor()
            query = "SELECT * FROM scores WHERE paper_id = %s ORDER BY item_id;"
            cur.execute(query, (paper_id,))
            rows = cur.fetchall()
            cur.close()

            if rows:
                search_result = process_rows(rows, fetch_double_scores_now=False)
            else:
                error_message = f"未能在数据库中找到试卷ID: {paper_id_query}"
        except ValueError:
            error_message = "请输入一个有效的数字ID。"
        except psycopg2.Error as e:
            error_message = f"数据库查询错误: {e}"

    return render_template('index.html', subjects=SUBJECTS, result=search_result, error=error_message)

@app.route('/random/<subject_name>')
def random_paper(subject_name):
    """处理按科目随机获取试卷的请求 (返回JSON)"""
    conn = get_db()
    if conn is None:
        return jsonify({"error": "数据库连接失败"}), 500
    
    try:
        cur = conn.cursor()
        # 先获取该科目的一个随机 paper_id
        cur.execute("SELECT paper_id FROM scores WHERE subject_name = %s ORDER BY RANDOM() LIMIT 1;", (subject_name,))
        random_paper_record = cur.fetchone()
        
        if not random_paper_record:
            return jsonify({"error": f"科目 '{subject_name}' 中没有数据"}), 404
            
        random_paper_id = random_paper_record['paper_id']
        
        # 再根据这个随机 paper_id 获取完整数据
        query = "SELECT * FROM scores WHERE paper_id = %s ORDER BY item_id;"
        cur.execute(query, (random_paper_id,))
        rows = cur.fetchall()
        cur.close()

        if rows:
            # 使用与主查询相同的处理函数
            result_data = process_rows(rows, fetch_double_scores_now=False)
            return jsonify(result_data)
        else:
            # 这种情况理论上不会发生
            return jsonify({"error": "获取随机试卷数据时出错"}), 500

    except psycopg2.Error as e:
        return jsonify({"error": f"数据库查询错误: {e}"}), 500

def extract_libid_from_url(image_url):
    """从图片URL中提取libid（题号）
    
    例如: http://.../3896792/2.jpg -> libid=2
    """
    try:
        if not image_url:
            return None
        # 获取URL的最后一部分（文件名）
        filename = image_url.split('/')[-1]
        # 去掉扩展名，获取数字
        libid_str = filename.replace('.jpg', '').replace('.png', '').replace('.jpeg', '')
        libid = int(libid_str)
        return libid
    except (ValueError, AttributeError, IndexError) as e:
        print(f"[!] 从URL提取libid失败: {image_url}, 错误: {e}")
        return None

def fetch_double_scores(exam_id, paper_id, libid, item_id=None):
    """调用API获取双评得分
    
    Args:
        exam_id: 考试ID
        paper_id: 试卷ID
        libid: 科目ID
        item_id: 题目ID（可选，如果提供则只获取该题目的数据）
    """
    try:
        # 构建API请求URL
        timestamp = int(time.time() * 1000)  # 毫秒时间戳
        url = f"{API_BASE_URL}?examid={exam_id}&paperid={paper_id}&libid={libid}&_={timestamp}"
        
        # 如果提供了item_id，添加到URL参数中
        if item_id is not None:
            url += f"&itemid={item_id}"
        
        # 设置请求头
        headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'accept-language': 'zh-CN,zh;q=0.9',
            'authorization': f'Bearer {API_TOKEN}',
            'cache-control': 'no-cache',
            'content-type': 'application/x-www-form-urlencoded',
            'pragma': 'no-cache',
            'referer': 'https://yunyj.linyi.net/read/check/paper',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # 打印完整的请求信息
        print("=" * 80)
        print("[API请求详情]")
        print(f"请求方法: GET")
        print(f"请求URL: {url}")
        print(f"请求头:")
        for key, value in headers.items():
            # 隐藏token的完整内容，只显示前几位
            if key.lower() == 'authorization':
                print(f"  {key}: {value[:20]}...")
            else:
                print(f"  {key}: {value}")
        print("=" * 80)
        
        # 发送请求
        print(f"[DEBUG] 正在发送API请求...")
        response = requests.get(url, headers=headers, timeout=10)
        
        # 打印响应信息
        print("=" * 80)
        print("[API响应详情]")
        print(f"响应状态码: {response.status_code}")
        print(f"响应头:")
        for key, value in response.headers.items():
            print(f"  {key}: {value}")
        print(f"\n响应体 (原始文本，前2000字符):")
        response_text = response.text
        print(response_text[:2000])
        if len(response_text) > 2000:
            print(f"... (还有 {len(response_text) - 2000} 个字符)")
        print("=" * 80)
        
        response.raise_for_status()
        
        # 解析JSON响应
        try:
            data = response.json()
            print(f"[DEBUG] JSON解析成功")
            
            # 打印JSON数据的完整内容（格式化）
            print("=" * 80)
            print("[API响应JSON数据]")
            json_str = json.dumps(data, ensure_ascii=False, indent=2)
            if len(json_str) > 5000:
                print(json_str[:5000])
                print(f"... (还有 {len(json_str) - 5000} 个字符)")
            else:
                print(json_str)
            print("=" * 80)
            
            # 打印返回数据的统计信息
            if isinstance(data, list):
                print(f"[DEBUG] API返回了 {len(data)} 条记录")
                # 统计不同itemid的数量
                itemids = set()
                for record in data:
                    if isinstance(record, dict) and 'itemid' in record:
                        itemids.add(record['itemid'])
                print(f"[DEBUG] API返回的itemid列表: {sorted(itemids)}")
            elif isinstance(data, dict):
                print(f"[DEBUG] API返回字典，键: {list(data.keys())}")
            
            return data
        except json.JSONDecodeError as json_err:
            print(f"[!] JSON解析失败: {json_err}")
            print(f"[!] 响应文本: {response_text[:1000]}")
            return None
            
    except requests.exceptions.RequestException as e:
        print("=" * 80)
        print("[API请求异常]")
        print(f"异常类型: {type(e).__name__}")
        print(f"异常信息: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"响应状态码: {e.response.status_code}")
            print(f"响应头: {dict(e.response.headers)}")
            print(f"响应内容: {e.response.text[:1000]}")
        print("=" * 80)
        return None
    except Exception as e:
        print("=" * 80)
        print("[未知异常]")
        print(f"异常类型: {type(e).__name__}")
        print(f"异常信息: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        return None

def parse_double_scores(api_data, item_id):
    """从API返回的数据中解析指定题目的双评得分
    
    API返回格式：列表，每个元素是一个评卷记录
    每条记录包含：
    - itemid: 题号
    - jn: 评卷员编号（1=一评，2=二评）
    - score: 该评卷员的评分
    """
    try:
        if not api_data:
            return None, None
        
        # API返回的是列表，每个元素是评卷记录
        if not isinstance(api_data, list):
            # 如果是字典，尝试提取列表
            if isinstance(api_data, dict):
                for key in ['data', 'items', 'list', 'result', 'records', 'rows']:
                    if key in api_data and isinstance(api_data[key], list):
                        api_data = api_data[key]
                        break
                else:
                    return None, None
            else:
                return None, None
        
        score1 = None  # 一评（jn=1）
        score2 = None  # 二评（jn=2）
        
        print(f"[DEBUG] 开始解析 item_id={item_id}，API数据有 {len(api_data)} 条记录")
        
        # 遍历所有记录，找到匹配item_id的记录
        for idx, record in enumerate(api_data):
            if not isinstance(record, dict):
                continue
            
            # 获取itemid（支持多种字段名）
            record_itemid = None
            for key in ['itemid', 'item_id', 'itemId', 'id', 'question_id', 'questionId']:
                if key in record:
                    try:
                        record_itemid = int(record[key])
                        print(f"[DEBUG] 记录{idx}: 找到itemid={record_itemid} (字段名={key})")
                        break
                    except (ValueError, TypeError):
                        continue
            
            # 检查是否匹配当前item_id
            if record_itemid is None:
                print(f"[DEBUG] 记录{idx}: 未找到itemid字段，跳过")
                continue
            
            if record_itemid != int(item_id):
                print(f"[DEBUG] 记录{idx}: itemid={record_itemid} != 目标item_id={item_id}，跳过")
                continue
            
            print(f"[DEBUG] 记录{idx}: itemid匹配成功！开始提取分数...")
            
            # 获取评卷员编号（jn字段：1=一评，2=二评）
            jn = None
            for key in ['jn', 'judgeNum', 'judge_num', 'rater', 'raterNum', 'rater_num']:
                if key in record:
                    try:
                        jn = int(record[key])
                        print(f"[DEBUG] 记录{idx}: jn={jn} (字段名={key})")
                        break
                    except (ValueError, TypeError):
                        continue
            
            if jn is None:
                print(f"[DEBUG] 记录{idx}: 未找到jn字段")
                continue
            
            # 获取评分（score字段）- 直接使用score字段
            score = None
            if 'score' in record:
                try:
                    val = record['score']
                    if val is not None and val != '' and str(val).upper() != 'N/A':
                        score = float(val)
                        print(f"[DEBUG] 记录{idx}: score={score} (类型={type(record['score'])})")
                    else:
                        print(f"[DEBUG] 记录{idx}: score字段值为空或N/A: {val}")
                except (ValueError, TypeError) as e:
                    print(f"[DEBUG] 记录{idx}: score字段转换失败: {e}, 值={record.get('score')}")
            
            if score is None:
                print(f"[DEBUG] 记录{idx}: 未找到有效的score字段")
                continue
            
            # 根据jn字段分配一评和二评
            if jn == 1:
                score1 = score
                print(f"[DEBUG] 记录{idx}: 设置一评(jn=1)={score1}")
            elif jn == 2:
                score2 = score
                print(f"[DEBUG] 记录{idx}: 设置二评(jn=2)={score2}")
            else:
                print(f"[DEBUG] 记录{idx}: jn={jn} 不是1或2，忽略")
        
        # 如果找到了数据，返回
        if score1 is not None or score2 is not None:
            print(f"[DEBUG] 解析成功: item_id={item_id}, 一评(jn=1)={score1}, 二评(jn=2)={score2}")
            return score1, score2
        else:
            print(f"[DEBUG] 未找到 item_id={item_id} 的匹配数据")
            return None, None
            
    except Exception as e:
        print(f"[!] 解析双评得分时出错: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def process_rows(rows, fetch_double_scores_now=False):
    """将从数据库获取的行数据处理成前端需要的格式
    
    Args:
        rows: 数据库查询结果
        fetch_double_scores_now: 是否立即获取双评得分（False则只返回数据库中的最终分）
    """
    if not rows:
        return None
    
    paper_data = {
        'paperid': rows[0]['paper_id'],
        'examid': rows[0]['exam_id'],
        'subject': rows[0]['subject_name'],
        'items': [],
        'total_score': 0  # 主观题总分
    }
    
    # 获取exam_id和paper_id用于API调用
    exam_id = rows[0]['exam_id']
    paper_id = rows[0]['paper_id']
    subject_name = rows[0]['subject_name']
    
    # 先快速返回数据库中的最终分
    for row in rows:
        item_id = row['item_id']
        image_url = row.get('image_url', '')
        
        # 从数据库获取最终分
        try:
            final_score_db = float(row.get('score', 0)) if row.get('score') is not None else 0
            final_score_display = int(final_score_db) if final_score_db == int(final_score_db) else final_score_db
            # 累加总分
            if isinstance(final_score_display, (int, float)):
                paper_data['total_score'] += final_score_display
        except (ValueError, TypeError):
            final_score_display = 'N/A'
        
        # 从图片URL中提取libid
        libid = extract_libid_from_url(image_url)
        if libid is None:
            # 如果无法提取，尝试使用科目ID作为fallback
            libid = SUBJECT_LIBID_MAP.get(subject_name, 4)
        
        item = {
            'item_id': item_id,
            'score': final_score_display,  # 最终分（从数据库获取）
            'score1': 'N/A',  # 一评（稍后异步获取）
            'score2': 'N/A',  # 二评（稍后异步获取）
            'url': image_url,
            'score_time': row['score_time'].strftime('%Y-%m-%d %H:%M:%S') if row['score_time'] else 'N/A',
            'libid': libid  # 保存libid用于后续API调用
        }
        
        paper_data['items'].append(item)
    
    # 如果需要立即获取双评得分（同步模式）
    if fetch_double_scores_now:
        print(f"[+] 正在获取双评得分: examid={exam_id}, paperid={paper_id}, subject={subject_name}")
        for item in paper_data['items']:
            item_id = item['item_id']
            libid = item.get('libid')
            
            if libid is None:
                libid = SUBJECT_LIBID_MAP.get(subject_name, 4)
            
            print(f"\n[+] 正在获取 item_id={item_id} 的双评得分 (libid={libid})...")
            api_data = fetch_double_scores(exam_id, paper_id, libid, item_id=item_id)
            
            if api_data:
                score1, score2 = parse_double_scores(api_data, item_id)
                if score1 is not None:
                    item['score1'] = int(score1) if score1 == int(score1) else score1
                if score2 is not None:
                    item['score2'] = int(score2) if score2 == int(score2) else score2
                
                # 如果有双评数据，重新计算最终分
                if score1 is not None and score2 is not None:
                    final_score = round((score1 + score2) / 2, 2)
                    item['score'] = int(final_score) if final_score == int(final_score) else final_score
    
    return paper_data

@app.route('/api/double-scores/<int:exam_id>/<int:paper_id>/<int:item_id>/<int:libid>')
def get_double_scores_api(exam_id, paper_id, item_id, libid):
    """异步获取双评得分的API端点"""
    try:
        api_data = fetch_double_scores(exam_id, paper_id, libid, item_id=item_id)
        if api_data:
            score1, score2 = parse_double_scores(api_data, item_id)
            result = {
                'item_id': item_id,
                'score1': int(score1) if score1 is not None and score1 == int(score1) else score1,
                'score2': int(score2) if score2 is not None and score2 == int(score2) else score2
            }
            # 如果有双评数据，计算最终分
            if score1 is not None and score2 is not None:
                final_score = round((score1 + score2) / 2, 2)
                result['score'] = int(final_score) if final_score == int(final_score) else final_score
            return jsonify(result)
        else:
            return jsonify({'error': 'API调用失败'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- 启动应用 ---
if __name__ == '__main__':
    with app.app_context():
        load_subjects() # 应用启动时预加载科目列表
    app.run(host='0.0.0.0', port=5000, debug=True)