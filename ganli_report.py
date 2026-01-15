import os
import time
import smtplib
import datetime
import sys
import ssl
import requests
import json

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# --- 配置部分 ---
PROVIDER = os.environ.get("REPORT_PROVIDER", "deepseek")

MY_MAIL = os.environ.get("REPORT_MAIL", "121438169@qq.com")
MY_PASS = os.environ.get("REPORT_MAIL_PASS", "uimpjxbvhgmlbide")

# 支持多标的配置，格式：代码:名称,代码:名称
# 默认值：603087:甘李药业
REPORT_STOCKS_STR = os.environ.get("REPORT_STOCKS", "603087:甘李药业")

MODEL_CONFIG = {
    "gemini": {
        "api_key": os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY"),
        "base_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "model": "gemini-1.5-flash"
    },
    "deepseek": {
        "api_key": os.environ.get("DEEPSEEK_API_KEY", "sk-d32f992aa8e749599bfe4079f2ac7a25"),
        "base_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat"
    },
    "grok": {
        "api_key": os.environ.get("GROK_API_KEY", "YOUR_GROK_API_KEY"),
        "base_url": "https://api.x.ai/v1/chat/completions",
        "model": "grok-beta"
    },
    "qwen": {
        "api_key": os.environ.get("QWEN_API_KEY", "YOUR_QWEN_API_KEY"),
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-plus"
    }
}

if not MY_MAIL or "你的QQ邮箱" in MY_MAIL:
    raise RuntimeError("请先配置 MY_MAIL")
if not MY_PASS or "SMTP授权码" in MY_PASS:
    raise RuntimeError("请先配置 MY_PASS")

current_config = MODEL_CONFIG.get(PROVIDER)
if not current_config:
    raise RuntimeError(f"未知的厂商: {PROVIDER}")
if not current_config["api_key"] or "YOUR_" in current_config["api_key"]:
    raise RuntimeError(f"请先在 MODEL_CONFIG 中填入 {PROVIDER} 的 api_key")


def gen_eastmoney_secid(code: str) -> str:
    if code.startswith("6"):
        return f"1.{code}"
    return f"0.{code}"


def get_market_data(stock_code, stock_name):
    """
    获取指定股票的行情数据
    """
    print(f"📡 [{stock_name}] 正在抓取行情...")
    secid = gen_eastmoney_secid(stock_code)
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
        r = requests.get(url, params=params, timeout=10)
    except Exception as e:
        raise RuntimeError(f"[{stock_name}] 行情接口连接失败: {e}")
    
    if r.status_code != 200:
        raise RuntimeError(f"[{stock_name}] 东方财富接口请求失败: {r.status_code}")
    
    data = r.json()
    if "data" not in data or not data["data"] or "klines" not in data["data"]:
        raise RuntimeError(f"[{stock_name}] 东方财富返回数据不完整")
    
    klines = data["data"]["klines"]
    if len(klines) < 21:
        raise RuntimeError(f"[{stock_name}] 历史数据不足 21 条")
    
    last21 = [k.split(",") for k in klines[-21:]]
    last20 = last21[-20:]
    closes = [float(k[2]) for k in last20]
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    today = last20[-1]
    yest = last21[-21]
    
    return {
        "代码": stock_code,
        "名称": stock_name,
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


def generate_single_stock_report(info):
    """
    生成单只股票的 HTML 报告片段
    """
    stock_name = info["名称"]
    stock_code = info["代码"]
    
    print(f"🧠 [{stock_name}] 正在调用模型: {PROVIDER}...")
    
    prompt = f"""
你是一名长期跟踪{stock_name}({stock_code})的专业卖方医药分析师，负责撰写“单票监控日报”。

请根据下述“当日行情与技术数据”，输出一份结构化的 HTML 报告片段。

【当日行情与技术数据】
- 日期：{info["日期"]}
- 收盘价：{info["收盘"]:.2f} 元，涨跌幅：{info["涨跌幅"]:.2f}% ，涨跌额：{info["涨跌额"]:.2f} 元
- 今开价：{info["今开"]:.2f} 元，最高价：{info["最高"]:.2f} 元，最低价：{info["最低"]:.2f} 元
- 成交额：{info["成交额"]/100000000:.2f} 亿元，成交量：{info["成交量"]:.0f} 手，换手率：{info["换手率"]:.2f}%
- 均线：MA5={info["MA5"]:.2f}，MA10={info["MA10"]:.2f}，MA20={info["MA20"]:.2f}

【写作任务】
请输出 HTML 代码（不要包含 <html> 或 <body> 标签，因为这将作为大报告的一部分），结构如下：

<div style="border: 1px solid #ddd; padding: 15px; margin-bottom: 20px; border-radius: 8px;">
    <h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">{stock_name} ({stock_code}) - {info["日期"]}</h2>
    
    <h3>1. 核心结论</h3>
    <p>（此处用2-3句话总结今日走势核心特征，以及对短期趋势的定性判断）</p>

    <h3>2. 技术面概览</h3>
    <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%;">
        <tr style="background-color: #f2f2f2;">
            <th>收盘</th><th>涨跌幅</th><th>成交额(亿)</th><th>换手率</th><th>MA5</th><th>MA20</th>
        </tr>
        <tr>
            <td>{info["收盘"]:.2f}</td>
            <td>{info["涨跌幅"]:.2f}%</td>
            <td>{info["成交额"]/100000000:.2f}</td>
            <td>{info["换手率"]:.2f}%</td>
            <td>{info["MA5"]:.2f}</td>
            <td>{info["MA20"]:.2f}</td>
        </tr>
    </table>
    <p>（简要点评量价配合情况及均线支撑/压力状态）</p>

    <h3>3. 策略建议</h3>
    <p>（针对短线和中线投资者的操作建议，如：持有、观望、逢低吸纳等）</p>
</div>

【注意】
- 仅输出 HTML 代码片段。
- 保持客观冷静的分析师语调。
"""
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
        f"【{PROVIDER.upper()} 研报】多股监控日报 - {datetime.date.today()}",
        "utf-8",
    )

    # 保存本地副本
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_report.html")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"📄 已将报告保存为本地文件: {report_path}")
    except Exception as e:
        print(f"⚠️ 保存本地报告失败: {repr(e)}")

    print("📧 正在通过 465 端口发送邮件...")
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=30, context=context) as server:
            server.login(MY_MAIL, MY_PASS)
            server.sendmail(MY_MAIL, [MY_MAIL], msg.as_bytes())
        print("✅ 邮件发送成功")
    except Exception as e:
        print(f"❌ 邮件发送失败: {repr(e)}")
        error_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_error.log")
        try:
            with open(error_log, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now()} 发送失败: {repr(e)}\n")
        except Exception:
            pass


def main():
    # 解析股票列表
    # 格式: "603087:甘李药业,300750:宁德时代"
    stock_list = []
    items = REPORT_STOCKS_STR.split(",")
    for item in items:
        if ":" in item:
            code, name = item.strip().split(":", 1)
            stock_list.append((code.strip(), name.strip()))
        else:
            print(f"⚠️ 格式错误忽略: {item}")

    if not stock_list:
        print("❌ 未配置有效的股票列表")
        return

    full_report_html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: '微软雅黑', sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
            h1 {{ text-align: center; color: #333; }}
            .footer {{ text-align: center; margin-top: 30px; font-size: 12px; color: #888; }}
        </style>
    </head>
    <body>
        <h1>📈 AI 每日投研简报 ({datetime.date.today()})</h1>
        <p style="text-align: center;">模型: {PROVIDER} | 标的数量: {len(stock_list)}</p>
        <hr>
    """

    success_count = 0
    for code, name in stock_list:
        try:
            info = get_market_data(code, name)
            report_segment = generate_single_stock_report(info)
            full_report_html += report_segment
            success_count += 1
            # 避免API速率限制，稍作停顿
            time.sleep(2)
        except Exception as e:
            print(f"❌ [{name}] 处理失败: {e}")
            full_report_html += f"""
            <div style="border: 1px solid red; padding: 10px; margin-bottom: 20px; border-radius: 8px; background-color: #fff0f0;">
                <h3>❌ {name} ({code}) - 生成失败</h3>
                <p>错误信息: {e}</p>
            </div>
            """

    full_report_html += """
        <div class="footer">
            <p>本报告由 AI 自动生成，仅供参考，不构成投资建议。</p>
        </div>
    </body>
    </html>
    """

    if success_count > 0:
        send_mail(full_report_html)
    else:
        print("❌ 没有成功生成任何股票的报告，跳过发送邮件")


if __name__ == "__main__":
    main()
