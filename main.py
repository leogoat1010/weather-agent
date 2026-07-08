"""
Weather Agent - 天气助手 v2
多城市 · 个性化播报 · DeepSeek AI · HTML邮件
新增：灾害预警 · 空气质量 · 体感温度 · 每日毛选
"""
import os
import sys
import json
import smtplib
from datetime import datetime, timezone, timedelta
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
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
FRIENDS_FILE = os.path.join(os.path.dirname(__file__), "friends.json")

# ---------- 城市 → 和风天气 Location ID ----------
CITY_IDS = {
    "北京": "101010100", "上海": "101020100", "广州": "101280101",
    "深圳": "101280601", "杭州": "101210101", "南京": "101190101",
    "成都": "101270101", "武汉": "101200101", "西安": "101110101",
    "重庆": "101040100", "苏州": "101190401", "天津": "101030100",
    "长沙": "101250101", "郑州": "101180101", "济南": "101120101",
    "青岛": "101120201", "大连": "101070201", "厦门": "101230201",
    "福州": "101230101", "合肥": "101220101",
    "新乡": "101180301", "昆山": "101190404",
}

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# ---------- 生活指数类型 ----------
INDICES_TYPES = {
    1: "运动指数",
    2: "洗车指数",
    3: "穿衣指数",
    5: "紫外线指数",
    8: "舒适度指数",
}

# ---------- 天气文字 → Emoji 映射 ----------
WEATHER_ICON_MAP = {
    "晴": "&#x2600;&#xFE0F;",
    "少云": "&#x1F324;&#xFE0F;",
    "晴间多云": "&#x26C5;",
    "多云": "&#x26C5;",
    "阴": "&#x2601;&#xFE0F;",
    "小雨": "&#x1F327;&#xFE0F;",
    "中雨": "&#x1F327;&#xFE0F;",
    "大雨": "&#x26C8;&#xFE0F;",
    "暴雨": "&#x26C8;&#xFE0F;",
    "大暴雨": "&#x26C8;&#xFE0F;",
    "特大暴雨": "&#x26C8;&#xFE0F;",
    "阵雨": "&#x1F326;&#xFE0F;",
    "雷阵雨": "&#x26C8;&#xFE0F;",
    "雨夹雪": "&#x1F328;&#xFE0F;",
    "小雪": "&#x1F328;&#xFE0F;",
    "中雪": "&#x2744;&#xFE0F;",
    "大雪": "&#x2744;&#xFE0F;",
    "暴雪": "&#x2744;&#xFE0F;",
    "雾": "&#x1F32B;&#xFE0F;",
    "霾": "&#x1F636;&#x200D;&#x1F32B;&#xFE0F;",
    "浮尘": "&#x1F4A8;",
    "扬沙": "&#x1F4A8;",
    "沙尘暴": "&#x1F4A8;",
}


def weather_icon(text):
    """根据天气描述文字返回 HTML emoji 实体"""
    for key, icon in WEATHER_ICON_MAP.items():
        if key in text:
            return icon
    return "&#x1F324;&#xFE0F;"


# ==================== 数据加载 ====================

def load_friends():
    """加载好友配置（GitHub 用 Secret，本地用文件）"""
    config_str = os.getenv("FRIENDS_CONFIG")
    if config_str:
        return json.loads(config_str)
    with open(FRIENDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_mao_quotes():
    """加载毛选语录"""
    quotes_file = os.path.join(os.path.dirname(__file__), "mao_quotes.json")
    with open(quotes_file, "r", encoding="utf-8") as f:
        return json.load(f)


def get_daily_mao_quote(quotes):
    """根据日期获取每日毛选语录（年积日取模，同一天所有人看到同一条）"""
    day_of_year = datetime.now(timezone(timedelta(hours=8))).timetuple().tm_yday
    idx = day_of_year % len(quotes)
    return quotes[idx]


# ==================== 城市定位 ====================

def get_location_id(city):
    """根据城市名获取和风天气 location ID"""
    if city in CITY_IDS:
        return CITY_IDS[city]
    for name, lid in CITY_IDS.items():
        if city.lower() in name.lower() or name in city:
            return lid
    raise Exception(f"找不到城市「{city}」，请在 CITY_IDS 中手动添加。已知城市：{list(CITY_IDS.keys())}")


# ==================== 和风天气 API ====================

def get_weather(location_id):
    """获取7天天气预报"""
    url = f"{QWEATHER_HOST}/v7/weather/7d"
    resp = requests.get(url, params={"location": location_id, "key": QWEATHER_KEY})
    data = resp.json()
    if data.get("code") != "200":
        raise Exception(f"天气API出错：{data}")
    return data["daily"]


def get_now_weather(location_id):
    """获取实时天气（含体感温度）"""
    url = f"{QWEATHER_HOST}/v7/weather/now"
    resp = requests.get(url, params={"location": location_id, "key": QWEATHER_KEY})
    data = resp.json()
    if data.get("code") != "200":
        return None
    return data["now"]


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


def get_warnings(location_id):
    """获取城市灾害天气预警"""
    url = f"{QWEATHER_HOST}/v7/warning/now"
    resp = requests.get(url, params={"location": location_id, "key": QWEATHER_KEY})
    data = resp.json()
    if data.get("code") != "200":
        return []
    return data.get("warning", [])


def get_air_quality(location_id):
    """获取城市实时空气质量"""
    url = f"{QWEATHER_HOST}/v7/air/now"
    resp = requests.get(url, params={"location": location_id, "key": QWEATHER_KEY})
    data = resp.json()
    if data.get("code") != "200":
        return None
    return data["now"]


# ==================== 数据 → 文本 ====================

def build_weather_text(daily, now_weather=None):
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
    # 实时温度 & 体感温度
    if now_weather:
        lines.append(
            f"\n当前温度{now_weather['temp']}°C，"
            f"体感温度{now_weather['feelsLike']}°C，"
            f"{now_weather['text']}"
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


def build_warning_text(warnings):
    """把预警信息整理成文本"""
    if not warnings:
        return ""
    lines = ["\n⚠️ 天气预警："]
    for w in warnings:
        lines.append(f"{w['title']}：{w['text']}（等级：{w['level']}）")
    return "\n".join(lines)


def build_aqi_text(aqi):
    """把空气质量整理成文本"""
    if not aqi:
        return ""
    lines = [f"\n空气质量（AQI）：{aqi['aqi']}，{aqi['category']}"]
    if aqi.get("primary"):
        lines.append(f"首要污染物：{aqi['primary']}")
    return "\n".join(lines)


# ==================== AI 播报 ====================

def ai_summary(send_name, to_name, city, weather_text, indices_text,
               warning_text="", aqi_text=""):
    """用 DeepSeek AI 生成个性化天气播报"""
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "your_api_key_here":
        return None

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )

    tz_beijing = timezone(timedelta(hours=8))
    now = datetime.now(tz_beijing)
    date_str = f"{now.year}/{now.month}/{now.day} {WEEKDAYS[now.weekday()]}"

    # 根据当前时间选问候语
    hour = now.hour
    if 5 <= hour < 12:
        greeting = "早上好"
    elif 12 <= hour < 14:
        greeting = "中午好"
    elif 14 <= hour < 18:
        greeting = "下午好"
    else:
        greeting = "晚上好"

    prompt = f"""你是天气预报助手。请根据以下数据，生成一段约150字的中文天气播报。

要求：
- 以"{to_name}{greeting}，我是{send_name}～今天是{date_str}"开头
- 语气亲切自然，像朋友每天早上发消息
- 概述三天天气趋势
- 根据体感温度给更贴切的穿衣建议
- 提醒下雨天带伞
- 提一句洗车建议和运动建议
- 如果紫外线强，提醒防晒

城市：{city}

=== 天气数据 ===
{weather_text}
{indices_text}
{warning_text}
{aqi_text}"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
    )
    return response.choices[0].message.content


# ==================== HTML 邮件构建（table 布局，兼容各邮件客户端） ====================

def build_html_email(send_name, to_name, city, now_date_str,
                     daily, indices, ai_text, warnings, aqi, mao_quote):
    """构建完整的 HTML 邮件正文"""

    # --- 辅助：天气卡片的单行 ---
    def forecast_row(label, day):
        icon = weather_icon(day["textDay"])
        desc = f"白天{day['textDay']}，夜间{day['textNight']}"
        temp = f"{day['tempMin']}° ~ {day['tempMax']}°"
        return (
            f'<tr>'
            f'<td width="40" style="font-size:13px;font-weight:600;color:#4a90d9;padding:8px 0;">{label}</td>'
            f'<td width="36" style="font-size:24px;padding:8px 0;text-align:center;">{icon}</td>'
            f'<td style="font-size:13px;color:#555;padding:8px 0;">{desc}</td>'
            f'<td width="70" style="font-size:13px;color:#999;padding:8px 0;text-align:right;">{temp}</td>'
            f'</tr>'
        )

    labels = ["今天", "明天", "后天"]
    forecast_rows = "".join(forecast_row(labels[i], daily[i]) for i in range(min(3, len(daily))))

    # --- 生活指数卡片 ---
    indices_items = ""
    if indices:
        seen = set()
        cards = []
        for item in indices:
            name = item["name"]
            if name in seen:
                continue
            seen.add(name)
            # emoji per type
            emoji_map = {"运动指数": "&#x1F3C3;", "洗车指数": "&#x1F6FD;",
                         "穿衣指数": "&#x1F45A;", "紫外线指数": "&#x1F31E;",
                         "舒适度指数": "&#x1F60C;"}
            emoji = emoji_map.get(name, "&#x1F4CC;")
            cards.append(
                f'<td width="50%" style="padding:4px;vertical-align:top;">'
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0">'
                f'<tr><td style="background:#f7f9fc;border-radius:8px;padding:12px;">'
                f'<div style="font-size:20px;margin-bottom:2px;">{emoji}</div>'
                f'<div style="font-size:11px;color:#888;">{name}</div>'
                f'<div style="font-size:13px;color:#333;font-weight:500;">{item["category"]}</div>'
                f'<div style="font-size:11px;color:#aaa;">{item["text"]}</div>'
                f'</td></tr></table></td>'
            )
        # 每行2个
        rows = []
        for i in range(0, len(cards), 2):
            pair = cards[i:i+2]
            if len(pair) == 1:
                pair.append('<td width="50%" style="padding:4px;"></td>')
            rows.append(f'<tr>{"".join(pair)}</tr>')
        indices_items = "".join(rows)

    # --- 预警 section ---
    warning_html = ""
    if warnings:
        warning_rows = ""
        for w in warnings:
            # 颜色按等级
            level_colors = {
                "蓝色": "#4a90d9", "黄色": "#f0ad4e", "橙色": "#f57c00", "红色": "#d9534f",
                "Blue": "#4a90d9", "Yellow": "#f0ad4e", "Orange": "#f57c00", "Red": "#d9534f",
            }
            color = level_colors.get(w.get("level", ""), "#d9534f")
            warning_rows += (
                f'<tr>'
                f'<td style="padding:6px 0;border-bottom:1px solid #fce4e4;">'
                f'<span style="display:inline-block;background:{color};color:#fff;font-size:11px;'
                f'padding:1px 8px;border-radius:3px;margin-right:8px;">{w["level"]}</span>'
                f'<span style="font-size:13px;color:#c0392b;font-weight:600;">{w["title"]}</span>'
                f'<br><span style="font-size:12px;color:#888;">{w.get("text", "")}</span>'
                f'</td></tr>'
            )
        warning_html = (
            f'<tr>'
            f'<td style="padding:16px 0 8px;">'
            f'<div style="font-size:14px;font-weight:600;color:#c0392b;margin-bottom:6px;">'
            f'&#x26A0;&#xFE0F; 天气预警</div>'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0">{warning_rows}</table>'
            f'</td></tr>'
        )

    # --- 空气质量 section ---
    aqi_html = ""
    if aqi:
        # AQI 颜色
        aqi_val = int(aqi.get("aqi", 0))
        if aqi_val <= 50:
            aqi_color, aqi_bg = "#4caf50", "#e8f5e9"
        elif aqi_val <= 100:
            aqi_color, aqi_bg = "#ff9800", "#fff3e0"
        elif aqi_val <= 150:
            aqi_color, aqi_bg = "#f57c00", "#fff3e0"
        elif aqi_val <= 200:
            aqi_color, aqi_bg = "#d9534f", "#fce4e4"
        else:
            aqi_color, aqi_bg = "#9b59b6", "#f3e5f5"

        detail_parts = []
        for k, label in [("pm2p5", "PM2.5"), ("pm10", "PM10"), ("no2", "NO₂"), ("so2", "SO₂"), ("o3", "O₃"), ("co", "CO")]:
            if k in aqi:
                detail_parts.append(f'{label} {aqi[k]}')
        detail_text = " · ".join(detail_parts) if detail_parts else ""

        aqi_html = (
            f'<tr>'
            f'<td style="padding:16px 0 8px;">'
            f'<div style="font-size:14px;font-weight:600;color:#333;margin-bottom:6px;">'
            f'&#x1F4A8; 空气质量</div>'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr>'
            f'<td style="background:{aqi_bg};border-radius:8px;padding:14px 16px;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td width="56" style="font-size:32px;font-weight:700;color:{aqi_color};vertical-align:middle;">{aqi_val}</td>'
            f'<td style="vertical-align:middle;">'
            f'<div style="font-size:14px;font-weight:600;color:#333;">{aqi.get("category", "")}</div>'
            f'<div style="font-size:11px;color:#888;margin-top:2px;">{detail_text}</div>'
            f'</td></tr></table>'
            f'</td></tr></table>'
            f'</td></tr>'
        )

    # --- 毛选 section ---
    mao_html = ""
    if mao_quote:
        mao_html = (
            f'<tr>'
            f'<td style="padding:16px 0 8px;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'bgcolor="#fefaf0" style="background:#fefaf0;border-radius:10px;">'
            f'<tr><td style="padding:16px 20px;text-align:center;border:1px solid #e8d5a0;border-radius:10px;">'
            f'<div style="font-size:11px;color:#b8963c;letter-spacing:2px;margin-bottom:8px;">'
            f'&#x1F4D6; 每日毛选</div>'
            f'<div style="font-size:17px;color:#8b6914;font-weight:700;line-height:1.7;'
            f'font-family:STSong, Songti SC, Noto Serif SC, SimSun, serif;">'
            f'"{mao_quote["quote"]}"</div>'
            f'<div style="font-size:11px;color:#b8963c;margin-top:6px;">'
            f'—— {mao_quote["source"]}</div>'
            f'</td></tr></table>'
            f'</td></tr>'
        )

    # --- 主模板拼装 ---
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0f2f5;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f0f2f5">
<tr><td align="center" style="padding:16px;">

  <!-- 邮件容器 520px -->
  <table width="520" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff" style="border-radius:14px;overflow:hidden;max-width:520px;">

    <!-- ====== HEADER ====== -->
    <tr>
      <td bgcolor="#4a90d9" style="background:linear-gradient(160deg,#4a90d9 0%,#357abd 60%,#2b6cb0 100%);padding:28px 24px 20px;text-align:center;">
        <div style="font-size:54px;line-height:1;margin-bottom:6px;">&#x26C5;</div>
        <div style="color:rgba(255,255,255,0.85);font-size:13px;letter-spacing:2px;">{now_date_str}</div>
        <div style="color:#fff;font-size:26px;font-weight:700;margin-top:4px;">{city}</div>
      </td>
    </tr>

    <!-- 今日温度大数字（取第一天） -->
    <tr>
      <td bgcolor="#4a90d9" style="padding:0 24px 22px;text-align:center;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td align="center">
              <span style="color:#fff;font-size:48px;font-weight:300;line-height:1;">{daily[0]['tempMin']}°</span>
              <span style="color:rgba(255,255,255,0.55);font-size:18px;vertical-align:super;">~ {daily[0]['tempMax']}°C</span>
            </td>
          </tr>
        </table>
        <div style="color:rgba(255,255,255,0.8);font-size:13px;margin-top:4px;">
          白天{daily[0]['textDay']} · {daily[0]['windDirDay']}风{daily[0]['windScaleDay']}级
        </div>
      </td>
    </tr>

    <!-- ====== 未来三天预报 ====== -->
    <tr>
      <td style="padding:20px 24px 12px;">
        <div style="font-size:15px;font-weight:600;color:#333;margin-bottom:4px;">&#x1F4C5; 未来三天</div>
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          {forecast_rows}
        </table>
      </td>
    </tr>

    <!-- 分割线 -->
    <tr><td style="padding:0 24px;"><div style="border-top:1px dashed #e0e0e0;"></div></td></tr>

    <!-- ====== 生活指数 ====== -->
    <tr>
      <td style="padding:16px 24px;">
        <div style="font-size:15px;font-weight:600;color:#333;margin-bottom:8px;">&#x1F3C3; 生活指数</div>
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          {indices_items}
        </table>
      </td>
    </tr>

    <!-- ====== AI 播报正文 ====== -->
    <tr>
      <td style="padding:8px 24px 16px;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#fafbfc">
          <tr>
            <td style="border-left:3px solid #4a90d9;padding:14px 16px;">
              <div style="font-size:14px;color:#444;line-height:1.85;">
                {ai_text.replace(chr(10), '<br>')}
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- ====== 天气预警（可选） ====== -->
    {warning_html}

    <!-- ====== 空气质量（可选） ====== -->
    {aqi_html}

    <!-- ====== 每日毛选 ====== -->
    {mao_html}

    <!-- ====== 底部 ====== -->
    <tr>
      <td bgcolor="#f7f9fc" style="padding:16px 24px;text-align:center;">
        <div style="font-size:10px;color:#aaa;line-height:1.6;">
          &#x1F31F; Weather Agent · 每日自动推送<br>
          数据：和风天气 · AI：DeepSeek
        </div>
      </td>
    </tr>

  </table>

</td></tr></table>
</body></html>"""
    return html


# ==================== 邮件发送 ====================

def send_email(subject, html_body, to_email):
    """发送 HTML 邮件"""
    if not EMAIL_USER or not EMAIL_PASSWORD:
        print("   ⚠️  未配置邮箱，跳过")
        return False

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(EMAIL_USER, EMAIL_PASSWORD)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr(("天气助手", EMAIL_USER))
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        server.sendmail(EMAIL_USER, [to_email], msg.as_string())
        server.quit()
        print(f"   ✅ 已发送 → {to_email}")
        return True
    except Exception as e:
        print(f"   ❌ 发送失败：{e}")
        return False


# ==================== 主流程 ====================

def main():
    print("=" * 50)
    print("🌤️  Weather Agent v2 - 天气助手")
    print("=" * 50)

    tz_beijing = timezone(timedelta(hours=8))
    now = datetime.now(tz_beijing)
    date_str = f"{now.year}年{now.month}月{now.day}日 {WEEKDAYS[now.weekday()]}"

    friends = load_friends()
    mao_quotes = load_mao_quotes()
    mao_quote = get_daily_mao_quote(mao_quotes)
    print(f"\n📋 共 {len(friends)} 位好友 | 📖 今日毛选：{mao_quote['quote'][:20]}...\n")

    for friend in friends:
        send_name = friend["sendName"]
        to_name = friend["toName"]
        email = friend["email"]
        city = friend["city"]

        print(f"{'─' * 50}")
        print(f"📍 {to_name} → {city}（{email}）")

        # 1. 城市定位
        try:
            location_id = get_location_id(city)
        except Exception as e:
            print(f"   ⚠️ 跳过：{e}")
            continue

        # 2. 获取所有天气数据（失败则优雅降级）
        daily = indices = now_weather = warnings = aqi = None
        try:
            daily = get_weather(location_id)
        except Exception as e:
            print(f"   ⚠️ 天气预报获取失败：{e}")
            continue

        try:
            indices = get_life_indices(location_id)
        except Exception as e:
            print(f"   ⚠️ 生活指数获取失败：{e}")

        try:
            now_weather = get_now_weather(location_id)
        except Exception:
            pass

        try:
            warnings = get_warnings(location_id)
            if warnings:
                print(f"   ⚠️ 有 {len(warnings)} 条天气预警")
        except Exception:
            pass

        try:
            aqi = get_air_quality(location_id)
        except Exception:
            pass

        # 3. 构建文本
        weather_text = build_weather_text(daily, now_weather)
        indices_text = build_indices_text(indices) if indices else ""
        warning_text = build_warning_text(warnings) if warnings else ""
        aqi_text = build_aqi_text(aqi) if aqi else ""

        # 4. AI 个性化播报
        print("   ⏳ 生成个性化播报...")
        ai_text = ai_summary(send_name, to_name, city, weather_text, indices_text,
                             warning_text, aqi_text)

        if not ai_text:
            # AI 不可用时的 fallback
            hour = now.hour
            if 5 <= hour < 12:
                greeting = "早上好"
            elif 12 <= hour < 14:
                greeting = "中午好"
            elif 14 <= hour < 18:
                greeting = "下午好"
            else:
                greeting = "晚上好"
            ai_text = f"{to_name}{greeting}～\n\n城市：{city}\n{weather_text}{indices_text}{warning_text}{aqi_text}"

        # 5. 构建 HTML 邮件
        html_body = build_html_email(
            send_name, to_name, city, date_str,
            daily, indices, ai_text, warnings, aqi, mao_quote
        )

        # 6. 发送
        send_email(f"🌤️ {city}今日天气播报", html_body, email)

    print(f"\n{'=' * 50}")
    print("✅ 全部完成")


if __name__ == "__main__":
    main()
