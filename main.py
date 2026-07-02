"""
Weather Agent - 天气助手
阶段五：获取天气 + AI 整理 + 推送到微信
"""
import os
import sys
import requests
from openai import OpenAI
from dotenv import load_dotenv

# 加载 .env 配置文件
load_dotenv()

# 解决 Windows CMD 中文/emoji 显示问题
sys.stdout.reconfigure(encoding="utf-8")

# ---------- 配置 ----------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN")
CITY = os.getenv("CITY", "Shanghai")

# ---------- 天气翻译表 ----------
WEATHER_CN = {
    "sunny": "晴",
    "clear": "晴",
    "partly cloudy": "多云",
    "cloudy": "阴",
    "overcast": "阴",
    "mist": "薄雾",
    "fog": "雾",
    "light rain": "小雨",
    "light rain shower": "阵雨（小）",
    "patchy rain nearby": "局部阵雨",
    "moderate rain": "中雨",
    "heavy rain": "大雨",
    "patchy light drizzle": "零星小雨",
    "light drizzle": "毛毛雨",
    "thunderstorm": "雷阵雨",
    "snow": "雪",
    "light snow": "小雪",
}


def translate_weather(desc_en):
    """把英文天气描述转成中文（模糊匹配）"""
    desc_lower = desc_en.lower()
    for en, cn in WEATHER_CN.items():
        if en in desc_lower:
            return cn
    return desc_en


def get_weather(city=CITY):
    """调用 wttr.in 获取城市天气数据"""
    url = f"https://wttr.in/{city}?format=j1"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()


def get_day_summary(day):
    """从一天的原始数据中提取关键信息"""
    midday = day["hourly"][4]
    desc_en = midday["weatherDesc"][0]["value"]

    return {
        "date": day["date"],
        "desc": translate_weather(desc_en),
        "desc_en": desc_en,
        "mintemp": day["mintempC"],
        "maxtemp": day["maxtempC"],
    }


def need_umbrella(day):
    """判断当天是否需要带伞"""
    for hour in day["hourly"]:
        if int(hour.get("chanceofrain", "0")) > 50:
            return True
    return False


def ai_summary(data):
    """用 DeepSeek AI 把天气数据整理成一段人性化的播报"""
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "your_api_key_here":
        return None  # 没配 Key 就跳过 AI

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )

    # 组装原始数据，喂给 AI
    days = []
    labels = ["今天", "明天", "后天"]
    for i, day in enumerate(data["weather"]):
        info = get_day_summary(day)
        umbrella = "需要带伞" if need_umbrella(day) else "不用带伞"
        days.append(
            f"{labels[i]}（{info['date']}）：{info['desc_en']}，"
            f"{info['mintemp']}°C ~ {info['maxtemp']}°C，{umbrella}"
        )

    raw_text = "\n".join(days)

    prompt = f"""你是天气预报助手。请根据以下原始天气数据，生成一段约100字的中文天气播报。

要求：
- 语气亲切、自然，像朋友每天早上跟你说天气
- 包含三天的天气概况
- 特别提醒哪几天需要带伞
- 可以适当加一句穿衣建议或生活小贴士

城市：{CITY}
原始数据：
{raw_text}"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
    )

    return response.choices[0].message.content


def send_to_wechat(title, content):
    """通过 PushPlus 推送到个人微信"""
    if not PUSHPLUS_TOKEN or PUSHPLUS_TOKEN == "your_token_here":
        print("⚠️  未配置 PushPlus Token，跳过微信推送")
        return False

    url = "http://www.pushplus.plus/send"
    body = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
    }
    resp = requests.post(url, json=body)
    result = resp.json()
    if result.get("code") == 200:
        print("✅ 已推送到微信")
        return True
    else:
        print(f"❌ 推送失败：{result}")
        return False


def main():
    print("=" * 40)
    print("🌤️  Weather Agent - 天气助手")
    print("=" * 40)

    # 1. 获取天气
    data = get_weather()

    # 2. AI 总结
    print("\n⏳ 正在用 AI 整理天气播报...\n")
    summary = ai_summary(data)

    if summary:
        print(summary)
        # 3. 推送到微信
        send_to_wechat("🌤️ 今日天气播报", summary)
    else:
        print("⚠️  未配置 DeepSeek API Key，使用基础输出：\n")
        labels = ["今天", "明天", "后天"]
        for i, day in enumerate(data["weather"]):
            info = get_day_summary(day)
            umbrella = "🌂 建议带伞" if need_umbrella(day) else "✅ 不用带伞"
            print(f"{labels[i]} ({info['date']})")
            print(f"  天气: {info['desc']}")
            print(f"  温度: {info['mintemp']}°C ~ {info['maxtemp']}°C")
            print(f"  {umbrella}\n")

    print("=" * 40)


if __name__ == "__main__":
    main()
