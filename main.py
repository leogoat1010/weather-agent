"""
Weather Agent - 天气助手
阶段七：和风天气 + 生活指数 + DeepSeek AI + 微信推送
"""
import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
import requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

# ---------- 配置 ----------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
QWEATHER_HOST = os.getenv("QWEATHER_HOST", "https://devapi.qweather.com")
QWEATHER_KEY = os.getenv("QWEATHER_KEY")
CITY = os.getenv("CITY", "Shanghai")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO", "")

# ---------- 城市 → 和风天气 Location ID ----------
CITY_IDS = {
    "北京": "101010100", "上海": "101020100", "广州": "101280101",
    "深圳": "101280601", "杭州": "101210101", "南京": "101190101",
    "成都": "101270101", "武汉": "101200101", "西安": "101110101",
    "重庆": "101040100", "苏州": "101190401", "天津": "101030100",
    "长沙": "101250101", "郑州": "101180101", "济南": "101120101",
    "青岛": "101120201", "大连": "101070201", "厦门": "101230201",
    "福州": "101230101", "合肥": "101220101",
}


def get_location_id(city):
    """根据城市名获取和风天气 location ID"""
    if city in CITY_IDS:
        return CITY_IDS[city]

    # 不在预设列表里，尝试拼音/英文城市名
    for name, lid in CITY_IDS.items():
        if city.lower() in name.lower() or name in city:
            return lid

    raise Exception(f"找不到城市「{city}」，请在 CITY_IDS 中手动添加。已知城市：{list(CITY_IDS.keys())}")

# ---------- 生活指数类型 ----------
INDICES_TYPES = {
    1: "运动指数",
    2: "洗车指数",
    3: "穿衣指数",
    5: "紫外线指数",
    8: "舒适度指数",
}


def get_weather(location_id):
    """获取7天天气预报（和风天气）"""
    url = f"{QWEATHER_HOST}/v7/weather/7d"
    resp = requests.get(url, params={"location": location_id, "key": QWEATHER_KEY})
    data = resp.json()
    if data.get("code") != "200":
        raise Exception(f"天气API出错：{data}")
    return data["daily"]


def get_life_indices(location_id):
    """获取今天的生活指数"""
    types = ",".join(str(t) for t in INDICES_TYPES.keys())
    url = f"{QWEATHER_HOST}/v7/indices/1d"
    resp = requests.get(url, params={
        "location": location_id,
        "key": QWEATHER_KEY,
        "type": types,
    })
    data = resp.json()
    if data.get("code") != "200":
        return []
    return data["daily"]


def build_weather_text(daily):
    """把天气数据整理成纯文本，喂给 AI"""
    labels = ["今天", "明天", "后天"]
    lines = []

    for i, day in enumerate(daily[:3]):
        lines.append(
            f"{labels[i]}（{day['fxDate']}）："
            f"白天{day['textDay']}，夜间{day['textNight']}，"
            f"{day['tempMin']}°C ~ {day['tempMax']}°C，"
            f"湿度{day['humidity']}%，降水量{day['precip']}mm，"
            f"紫外线指数{day['uvIndex']}，"
            f"{day['windDirDay']}风{day['windScaleDay']}级"
        )

    return "\n".join(lines)


def build_indices_text(daily_indices):
    """把生活指数整理成纯文本"""
    if not daily_indices:
        return ""

    lines = ["\n今日生活指数："]
    seen = set()
    for item in daily_indices:
        name = item["name"]
        if name in seen:
            continue
        seen.add(name)
        lines.append(f"{name}：{item['category']}，{item['text']}")

    return "\n".join(lines)


def ai_summary(weather_text, indices_text):
    """用 DeepSeek AI 生成人性化天气播报"""
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "your_api_key_here":
        return None

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )

    prompt = f"""你是天气预报助手。请根据以下数据，生成一段约150字的中文天气播报。

要求：
- 语气亲切自然，像朋友每天早上发消息
- 概述三天天气趋势
- 提醒下雨天带伞
- 根据穿衣指数和温度给穿衣建议
- 提一句洗车建议和运动建议
- 如果紫外线强，提醒防晒

城市：{CITY}

=== 天气数据 ===
{weather_text}
{indices_text}"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
    )

    return response.choices[0].message.content


def send_email(subject, body, to_emails):
    """通过 QQ 邮箱 SMTP 发送邮件"""
    if not EMAIL_USER or not EMAIL_PASSWORD:
        print("⚠️  未配置邮箱，跳过邮件推送")
        return False
    if not to_emails:
        print("⚠️  未配置收件人，跳过邮件推送")
        return False

    # 构建 HTML 邮件
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("天气助手", EMAIL_USER))
    msg["To"] = to_emails

    html_body = body.replace("\n", "<br>")
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        recipients = [e.strip() for e in to_emails.split(",") if e.strip()]
        server.sendmail(EMAIL_USER, recipients, msg.as_string())
        server.quit()
        print(f"✅ 邮件已发送至：{', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败：{e}")
        return False


def main():
    print("=" * 40)
    print("🌤️  Weather Agent - 天气助手")
    print("=" * 40)

    # 1. 查城市 ID
    print(f"\n📍 查询城市：{CITY}")
    location_id = get_location_id(CITY)
    print(f"   城市ID：{location_id}")

    # 2. 获取天气 + 生活指数
    daily = get_weather(location_id)
    indices = get_life_indices(location_id)

    weather_text = build_weather_text(daily)
    indices_text = build_indices_text(indices)

    # 3. AI 总结
    print("\n⏳ 正在用 AI 整理天气播报...\n")
    summary = ai_summary(weather_text, indices_text)

    if summary:
        print(summary)
        send_email(f"🌤️ {CITY}今日天气播报", summary, EMAIL_TO)
    else:
        print("⚠️  未配置 DeepSeek API Key，使用基础输出：\n")
        print(weather_text)
        print(indices_text)

    print("\n" + "=" * 40)


if __name__ == "__main__":
    main()
