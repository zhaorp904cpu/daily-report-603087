import os
import time
import smtplib
import datetime
import sys
import ssl
import requests
import json
import urllib.parse
import re


def log_to_file(msg):
    print(msg)


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
        "model": "deepseek-reasoner"
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
    last_exc = None
    for i in range(3):
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 200:
                break
            last_exc = RuntimeError(f"HTTP {r.status_code}")
        except Exception as e:
            last_exc = e
        time.sleep(1.5)
    else:
        raise RuntimeError(f"[{stock_name}] 行情接口连接失败: {last_exc}")
    
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
    resp = requests.post(url, headers=headers, json=payload, timeout=300)
    if resp.status_code != 200:
        raise RuntimeError(f"API 报错 ({resp.status_code}): {resp.text}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise RuntimeError(f"API 返回格式异常: {data}")


def get_stock_news(stock_code, stock_name):
    log_to_file(f"📰 [{stock_name}] 正在抓取新闻资讯...")
    news_content = ""
    
    # 1. 抓取公告 (EastMoney)
    url_ann = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params_ann = {
        "sr": "-1",
        "page_size": "5",
        "page_index": "1",
        "ann_type": "A",
        "client_source": "web",
        "stock_list": stock_code,
        "f_node": "0",
        "s_node": "0",
    }
    try:
        r = requests.get(url_ann, params=params_ann, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if "data" in data and "list" in data["data"]:
                news_content += "【近期重要公告】\n"
                for item in data["data"]["list"][:3]:
                    title = item.get("title", "")
                    date = item.get("notice_date", "")[:10]
                    news_content += f"- {date}: {title}\n"
    except Exception as e:
        print(f"⚠️ 公告抓取失败: {e}")

    # 2. 尝试抓取新浪财经个股资讯 (Sina Finance)
    # 既然直接抓取微博困难，我们抓取新浪财经的个股新闻列表，通常包含媒体报道
    try:
        if stock_code.startswith("6"):
            sina_symbol = f"sh{stock_code}"
        else:
            sina_symbol = f"sz{stock_code}"
            
        # 使用新浪财经的新闻接口 (JSONP or HTML)
        # 这里尝试抓取 HTML 页面的一小部分，或者直接跳过，因为之前的测试不太稳定。
        # 我们改用构造“微博搜索链接”提供给 AI 参考（虽然 AI 无法上网，但我们可以告诉用户去点）
        pass
    except Exception:
        pass
    
    return news_content


def get_weibo_search_url(stock_name):
    encoded = urllib.parse.quote(stock_name)
    return f"https://s.weibo.com/weibo?q={encoded}"


def get_weibo_posts(stock_name):
    cookie = os.environ.get("WEIBO_COOKIE")
    if not cookie:
        return ""
    print(f"💬 [{stock_name}] 正在抓取微博舆情...")
    encoded = urllib.parse.quote(stock_name)
    url = f"https://s.weibo.com/weibo?q={encoded}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://s.weibo.com/",
        "Cookie": cookie,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ 微博搜索返回状态码: {resp.status_code}")
            return ""
        text = resp.text
        if "passport.weibo.com" in resp.url or "安全验证" in text[:1000]:
            print("⚠️ 微博需要重新登录或验证，无法获取舆情")
            return ""
        matches = re.findall(r'<p class="txt"[^>]*>(.*?)</p>', text, flags=re.S)
        posts = []
        for raw in matches:
            cleaned = re.sub(r"<.*?>", "", raw)
            cleaned = cleaned.replace("\n", " ").replace("\r", " ").strip()
            if len(cleaned) >= 8 and "微博 weibo.com" not in cleaned:
                posts.append(cleaned)
        unique = []
        for p in posts:
            if p not in unique:
                unique.append(p)
        if not unique:
            return ""
        summary = "【微博近期讨论摘要】\n"
        for p in unique[:8]:
            summary += f"- {p}\n"
        return summary
    except Exception as e:
        print(f"⚠️ 抓取微博舆情失败: {e}")
        return ""


def get_x_tweets(stock_code, stock_name):
    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        return ""
    print(f"🐦 [{stock_name}] 正在抓取 X(Twitter) 推文...")
    url = "https://api.twitter.com/2/tweets/search/recent"
    query = f"\"{stock_name}\" OR \"{stock_code}\" lang:zh -is:retweet"
    params = {
        "query": query,
        "max_results": 10,
        "tweet.fields": "created_at,lang"
    }
    headers = {
        "Authorization": f"Bearer {token}"
    }
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ X API 返回状态码: {resp.status_code}")
            return ""
        data = resp.json()
        tweets = data.get("data", [])
        if not tweets:
            return ""
        content = "【Twitter(X) 近期相关推文摘要】\n"
        for t in tweets[:5]:
            text = t.get("text", "").replace("\n", " ")
            created = t.get("created_at", "")
            content += f"- {created}: {text}\n"
        return content
    except Exception as e:
        print(f"⚠️ 抓取 X 推文失败: {e}")
        return ""


def generate_single_stock_report(info):
    stock_name = info["名称"]
    stock_code = info["代码"]
    
    news_data = get_stock_news(stock_code, stock_name)
    weibo_data = get_weibo_posts(stock_name)
    x_data = get_x_tweets(stock_code, stock_name)
    weibo_url = get_weibo_search_url(stock_name)
    
    log_to_file(f"🧠 [{stock_name}] 正在调用模型: {PROVIDER}...")
    
    prompt = f"""
你是一名长期跟踪{stock_name}({stock_code})的专业卖方分析师，负责撰写“单票监控日报”。

请根据下述“当日行情与技术数据”以及“近期资讯与舆情”，输出一份结构化的 HTML 日报片段。
要求：内容专业、简洁、有观点，避免空泛套话。

【当日行情与技术数据】
- 日期：{info["日期"]}
- 收盘价：{info["收盘"]:.2f} 元，涨跌幅：{info["涨跌幅"]:.2f}% ，涨跌额：{info["涨跌额"]:.2f} 元
- 今开价：{info["今开"]:.2f} 元，最高价：{info["最高"]:.2f} 元，最低价：{info["最低"]:.2f} 元
- 成交额：{info["成交额"]/100000000:.2f} 亿元，成交量：{info["成交量"]:.0f} 手，换手率：{info["换手率"]:.2f}%
- 均线：MA5={info["MA5"]:.2f}，MA10={info["MA10"]:.2f}，MA20={info["MA20"]:.2f}

【近期资讯与舆情输入】
{news_data}
{weibo_data}
{x_data}
(注：微博和 X(Twitter) 均受反爬与权限限制，文本可能不完整。请结合“股价波动幅度”和“成交量”综合推断市场情绪，例如：无利好大涨意味着情绪亢奋/游资炒作；缩量阴跌意味着人气涣散。)

【写作任务】
请严格按照以下模块输出，并使用 HTML 标签（如 h2, h3, p, ul, li, table 等）组织内容。
**注意：不要包含 <html>, <head>, <body> 标签，仅输出 div 片段。**

请将整个报告包裹在一个 <div style="border: 1px solid #ddd; padding: 20px; margin-bottom: 30px; border-radius: 8px; background-color: #fff;"> 容器中。

结构如下：

<div style="border-bottom: 2px solid #3498db; padding-bottom: 10px; margin-bottom: 20px;">
    <h2 style="margin: 0; color: #2c3e50;">{stock_name} ({stock_code}) - 每日深度追踪</h2>
    <div style="font-size: 12px; margin-top: 5px; color: #666;">
        <a href="{weibo_url}" target="_blank" style="color: #e74c3c; text-decoration: none;">🔍 点击查看微博实时舆情</a>
    </div>
</div>

<!-- 重点事件高亮区域 -->
<div style="margin-bottom: 20px; padding: 15px; background-color: #fff3f3; border-left: 5px solid #e74c3c;">
    <h2 style="margin: 0; color: #e74c3c; font-size: 20px; font-weight: bold;">
        🔥 今日最关键事件：[请在此处总结当日发生的最重要的一件事，如无重大事件则写“今日无重大消息，情绪主导”]
    </h2>
</div>

一、<h3>当日核心结论</h3>
用 2~4 句简洁文字，总结：
1) 今天股价和成交的核心变化是什么；
2) 该变化更多来自情绪波动，还是基本面或事件驱动；
3) 对短期(1~2 周)和中期(3~6 个月)的观点是偏多、中性还是偏谨慎。

二、<h3>当日交易与技术面</h3>
1) 生成一张 HTML 表格 (table)，包含列：收盘、涨跌幅、成交额(亿)、换手率。
   (数值保留两位小数，**注意：表格中不再列出具体均线数值**)
2) 在表格下用 1~2 句简练文字，仅分析：
   a) 量价配合是否健康；
   b) 是否出现关键的突破或反转形态（如吞没、启明星等），不必纠结于具体均线支撑位。

三、<h3>基本面与估值跟踪</h3>
在不编造具体财务数字的前提下，从以下角度定性评估：
1) **{stock_name}** 在其所属行业（如医药、新能源等）的定位、核心产品和当前成长逻辑；
2) 市场对其收入增速和盈利能力的预期变化；
3) 行业政策或宏观环境对该公司的潜在影响；
4) 当前估值水平的定性判断（偏低、合理、偏高）。

    四、<h3>事件与风险跟踪（深度舆情分析）</h3>
    **重点部分：结合“公告”与“行情”推演情绪**
    1) **舆情与事件梳理**：概括近期公告要点（如有），或指出“今日无重大公告，行情主要受市场情绪/板块轮动主导”。对你在本段引用的**每一条重要公告或具体事件**，务必在描述中明确标注【公告/事件日期】，例如“2026-01-15 公司发布……公告”。若引用微博或 Twitter(X) 等社交媒体中的具体观点或信息，请在句中或句后标注【发帖日期】，例如“（微博 2026-01-15）”、“（X 2026-01-15）”。
2) **财务影响推演**：定性分析事件对公司【营收/利润/成本】的潜在影响（如无事件，则分析宏观/行业因素）。
3) **盈利预期修正**：判断当前市场对公司未来的盈利预期是否发生变化。

    五、<h3>后续观察要点与策略思路</h3>
    1) 给出 2~3 个需要重点观察的价格或技术信号（如“若有效跌破 MA20...”）；
    2) 针对不同类型投资者（稳健型/激进型）给出简要策略建议。

    六、<h3>数据与信息来源及时间说明</h3>
    请在报告结尾补充一个简短的小节，列表形式列出本报告使用的主要数据与信息来源，并注明时间范围，例如：
    - 行情与成交数据：来自东方财富 K 线接口，数据截至 {info["日期"]} 收盘；
    - 公告与公司新闻：来自东方财富公告接口，主要引用近几日公告（以各公告原文日期为准）；
    - 社交媒体舆情：来自微博检索链接和 Twitter(X) API，内容为报告生成当日附近检索到的公开信息，引用具体观点时在文中已标注发帖日期。

</div>

【格式要求】
1) 仅输出 HTML 代码片段。
    2) 风格参考专业券商研报，理性、克制、逻辑严密。
"""
    if PROVIDER == "gemini":
        result = call_gemini_http(prompt)
    else:
        result = call_openai_compatible_api(prompt)
    
    log_to_file(f"✅ [{stock_name}] 模型生成完成")
    return result


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
        <h1>📈 自选品种追踪日报 ({datetime.date.today()})</h1>
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
    
    print("🏁 程序执行结束")


if __name__ == "__main__":
    main()
