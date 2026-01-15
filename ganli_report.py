import os
import smtplib
import datetime
import sys
import ssl
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PROVIDER = os.getenv("REPORT_PROVIDER", "deepseek")

MY_MAIL = os.getenv("REPORT_MAIL", "")
MY_PASS = os.getenv("REPORT_MAIL_PASS", "")

MODEL_CONFIG = {
    "gemini": {
        "api_key": os.getenv("GEMINI_API_KEY", ""),
        "base_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "model": "gemini-1.5-flash"
    },
    "deepseek": {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat"
    },
    "grok": {
        "api_key": os.getenv("GROK_API_KEY", ""),
        "base_url": "https://api.x.ai/v1/chat/completions",
        "model": "grok-beta"
    },
    "qwen": {
        "api_key": os.getenv("QWEN_API_KEY", ""),
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-plus"
    }
}

STOCK_CODE = os.getenv("REPORT_STOCK_CODE", "603087")
STOCK_NAME = os.getenv("REPORT_STOCK_NAME", "甘李药业")
COMPANY_PROFILE = os.getenv(
    "REPORT_COMPANY_PROFILE",
    "当前标的为甘李药业，属于A股医药板块，核心产品包括胰岛素等糖尿病用药。"
)

if not MY_MAIL:
    raise RuntimeError("REPORT_MAIL 未配置")
if not MY_PASS:
    raise RuntimeError("REPORT_MAIL_PASS 未配置")

current_config = MODEL_CONFIG.get(PROVIDER)
if not current_config:
    raise RuntimeError(f"未知的厂商: {PROVIDER}")
if not current_config["api_key"]:
    raise RuntimeError(f"{PROVIDER} 的 api_key 未配置")


def gen_eastmoney_secid(code: str) -> str:
    if code.startswith("6"):
        return f"1.{code}"
    return f"0.{code}"


def get_market_data():
    print(f"正在抓取行情 (使用模型: {PROVIDER} - {current_config['model']})...")
    secid = gen_eastmoney_secid(STOCK_CODE)
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "klt": "101",
        "fqt": "1",
        "beg": "0",
        "end": "20500101",
        "lmt": "60",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
    except Exception as e:
        raise RuntimeError(f"行情接口连接失败: {e}")
    if r.status_code != 200:
        raise RuntimeError(f"东方财富接口请求失败: {r.status_code}")
    data = r.json()
    if "data" not in data or not data["data"] or "klines" not in data["data"]:
        raise RuntimeError("东方财富返回数据不完整")
    klines = data["data"]["klines"]
    if len(klines) < 21:
        raise RuntimeError("历史数据不足 21 条")
    last21 = [k.split(",") for k in klines[-21:]]
    last20 = last21[-20:]
    closes = [float(k[2]) for k in last20]
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    today = last20[-1]
    yest = last21[-21]
    return {
        "代码": STOCK_CODE,
        "名称": STOCK_NAME,
        "日期": today[0],
        "今开": float(today[1]),
        "收盘": float(today[2]),
        "昨收": float(yest[2]),
        "最高": float(today[3]),
        "最低": float(today[4]),
        "成交量": float(today[5]),
        "成交额": float(today[6]),
        "振幅": float(today[7]),
        "涨跌幅": float(today[8]),
        "涨跌额": float(today[9]),
        "换手率": float(today[10]),
        "MA5": ma5,
        "MA10": ma10,
        "MA20": ma20,
        "最新价": float(today[2]),
    }


def call_gemini_http(prompt: str) -> str:
    cfg = MODEL_CONFIG["gemini"]
    api_key = cfg["api_key"]
    model = cfg["model"]
    base_url = cfg["base_url"]
    url = f"{base_url}/{model}:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(url, json=payload, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini 报错 ({resp.status_code}): {resp.text}")
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini 返回格式异常: {data}")


def call_openai_compatible_api(prompt: str) -> str:
    api_key = current_config["api_key"]
    model = current_config["model"]
    url = current_config["base_url"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"API 报错 ({resp.status_code}): {resp.text}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise RuntimeError(f"API 返回格式异常: {data}")


def generate_report(info):
    today = datetime.date.today().strftime("%Y-%m-%d")
    prompt = f"""
你是一名长期跟踪{STOCK_NAME}({STOCK_CODE})的专业卖方分析师，负责撰写“单票监控日报”。

标的公司简介：{COMPANY_PROFILE}

请根据下述“当日行情与技术数据”，输出一份结构化的 HTML 日报，要求内容专业、简洁、有观点，避免空泛套话。

【当日行情与技术数据】
- 日期：{info["日期"]}
- 收盘价：{info["收盘"]:.2f} 元，涨跌幅：{info["涨跌幅"]:.2f}% ，涨跌额：{info["涨跌额"]:.2f} 元
- 今开价：{info["今开"]:.2f} 元，最高价：{info["最高"]:.2f} 元，最低价：{info["最低"]:.2f} 元
- 成交额：{info["成交额"]/100000000:.2f} 亿元，成交量：{info["成交量"]:.0f} 手，换手率：{info["换手率"]:.2f}%
- 均线：MA5={info["MA5"]:.2f}，MA10={info["MA10"]:.2f}，MA20={info["MA20"]:.2f}

【写作任务】
请严格按照以下模块输出，并使用 HTML 标题、段落和表格组织内容：

一、<h2>当日核心结论</h2>
用 2~4 句简洁文字，总结：
1) 今天股价和成交的核心变化是什么（例如：放量上涨、缩量回调、放量下跌等）；
2) 该变化更多来自情绪波动，还是基本面或事件驱动；
3) 对短期(1~2 周)和中期(3~6 个月)的观点是偏多、中性还是偏谨慎，以及是否需要调整关注度或仓位倾向(只需定性描述)。

二、<h2>当日交易与技术面</h2>
1) 先生成一张 HTML 表格，列出以下字段作为列：
   收盘价、今开价、昨收价、最高价、最低价、涨跌幅、成交额(亿元)、成交量(万手)、换手率、振幅、MA5、MA10、MA20。
   表格中请使用数值保留两位小数，成交额以亿元、成交量以万手展示。
2) 在表格下用 1~2 段文字分析：
   a) 收盘价相对 MA5/MA10/MA20 所处位置，是明显强势区间、震荡区间还是偏弱区域；
   b) 今日量价配合是否健康，例如：放量上涨、缩量回调、放量滞涨、缩量阴跌等；
   c) 是否接近或突破近期重要支撑位/压力位（可以定性描述为“接近前期平台支撑”“临近前高压力”等）。

三、<h2>基本面与估值跟踪</h2>
在不编造具体财务数字的前提下，从以下角度定性评估当前股价所隐含的预期：
1) 公司所处细分行业的定位、产品结构和成长逻辑；
2) 收入增速、盈利能力、现金流质量的大致情况(可以用“维持中高速增长”“现金流质量有一定压力”等表述)；
3) 行业政策、竞争格局对中期盈利能力的潜在影响；
4) 相对于 A 股同类公司和自身历史区间，目前估值大致偏便宜、偏合理还是偏贵(只做方向性判断)。

四、<h2>事件与风险跟踪</h2>
用无序列表列出未来 1~3 个月需要重点跟踪的事件和风险类别，包括但不限于：
1) 公司层面：产品进度、产能扩张、合作与订单、合规与质量事件等；
2) 行业与政策：监管政策、价格政策、行业需求变化等；
3) 市场与资金：机构持仓变化、重要股东减持计划、异常波动监管等。
对于每一类，请简要说明“若出现不利结果可能带来的影响方向”(如压缩盈利空间、扰动估值中枢等)。

五、<h2>后续观察要点与策略思路</h2>
1) 给出 2~3 个需要重点观察的价格或技术信号，例如：
   “若有效跌破 MA20 且放量，则短期趋势明显转弱，应降低仓位偏好”等；
2) 给出对中长期投资者的总体策略倾向(例如：阶段性波动中维持中长期配置价值、仍需等待更明确的业绩验证或海外放量信号等)；
3) 明确指出当前更适合哪类投资者关注(如稳健型、成长型、短线交易型)，并说明原因。

【格式要求】
1) 全文必须为 HTML 片段，使用 <h1>、<h2>、<p>、<ul>、<li>、<table>、<thead>、<tbody>、<tr>、<th>、<td> 等标签组织内容；
2) 标题结构清晰，正文以段落和列表为主，避免大段空洞堆砌；
3) 不要出现 Markdown 语法(例如“## 标题”)；
4) 不要虚构精确财务数字和监管结论，可以使用“当前市场普遍预期”“估值大致处于行业中游水平”等定性表述；
5) 风格参考专业券商研报，理性、克制，少用煽情语句。
"""
    print(f"正在调用模型: {PROVIDER}...")
    if PROVIDER == "gemini":
        return call_gemini_http(prompt)
    else:
        return call_openai_compatible_api(prompt)


def send_mail(html_content):
    from email.mime.text import MIMEText
    from email.header import Header
    from email.utils import formataddr

    msg = MIMEText(html_content, "html", "utf-8")
    msg["From"] = formataddr((str(Header("AI 投研助手", "utf-8")), MY_MAIL))
    msg["To"] = formataddr((str(Header("投资者", "utf-8")), MY_MAIL))
    msg["Subject"] = Header(
        f"【{PROVIDER.upper()} 研报】{STOCK_NAME} - {datetime.date.today()}",
        "utf-8",
    )

    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ganli_report.html")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"已将报告保存为本地文件: {report_path}")
    except Exception as e:
        print(f"保存本地报告失败: {repr(e)}")

    print("正在通过 465 端口发送邮件...")
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=30, context=context) as server:
            server.login(MY_MAIL, MY_PASS)
            server.sendmail(MY_MAIL, [MY_MAIL], msg.as_bytes())
        print("邮件发送成功")
    except Exception as e:
        print(f"邮件发送失败: {repr(e)}")


if __name__ == "__main__":
    try:
        s_info = get_market_data()
        report_html = generate_report(s_info)
        send_mail(report_html)
    except Exception as e:
        print(f"执行失败: {e}")
