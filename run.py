# -*- coding: utf-8 -*-
"""
코스피 오버나잇 전략 봇 VER 2.15 Burst Score Tuned
- pick: 150개 정량 평가 -> 60개 뉴스 평가 -> 20개 Gemini 보정 -> 최종 10개
- sell: 전일 추천 후보의 현재가/잠정 수익률 알림
- 전략: 당일 종가 매수 -> 다음날 아침 매도 / 목표 오버나잇 +3%
※ 투자 권유가 아니라 검증용 도구입니다. 추천은 '신호'가 아니라 '가설'로 보세요.
"""

import os
import json
import time
import datetime as dt
import traceback
import re
from typing import Any, Dict, List, Tuple

import requests
import pandas as pd
import feedparser
import FinanceDataReader as fdr
import gspread
from google.oauth2.service_account import Credentials
from google import genai


# ======================= 설정 =======================
TARGET_PCT = float(os.environ.get("TARGET_PCT", "3.0"))
UNIVERSE_SIZE = int(os.environ.get("UNIVERSE_SIZE", "150"))
EVAL_POOL_SIZE = int(os.environ.get("EVAL_POOL_SIZE", "150"))
NEWS_POOL_SIZE = int(os.environ.get("NEWS_POOL_SIZE", "60"))
GEMINI_POOL_SIZE = int(os.environ.get("GEMINI_POOL_SIZE", "20"))
MAX_PICKS = int(os.environ.get("MAX_PICKS", "10"))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# 시트 분석용 버전 메타데이터
BOT_VERSION = os.environ.get("BOT_VERSION", "v2.15")
SCORE_VERSION = os.environ.get("SCORE_VERSION", "score_v2.15")
STRATEGY_PROFILE = os.environ.get("STRATEGY_PROFILE", "burst_score_kospi_refined")

# 재추천 검증은 너무 오래된 legacy 실패 이력까지 벌점화하지 않는다.
# 기본값: 최근 21일 이내 + 버전정보가 있는 행만 재추천 벌점에 사용.
REPICK_LOOKBACK_DAYS = int(os.environ.get("REPICK_LOOKBACK_DAYS", "21"))
REPICK_HISTORY_SCOPE = os.environ.get("REPICK_HISTORY_SCOPE", "versioned_recent").strip().lower()

# v2.13 방어 패치 설정
# 성과가 낮았던 5일 급등 추격/재추천 과신/AI 테마 오분류를 보수적으로 다룬다.
CHASE_RET5_WATCH = float(os.environ.get("CHASE_RET5_WATCH", "5"))
CHASE_RET5_REJECT = float(os.environ.get("CHASE_RET5_REJECT", "12"))
CHASE_EXCEPTION_REL = float(os.environ.get("CHASE_EXCEPTION_REL", "5"))
CHASE_EXCEPTION_VOL_RATIO = float(os.environ.get("CHASE_EXCEPTION_VOL_RATIO", "1.5"))
CHASE_EXCEPTION_RET1 = float(os.environ.get("CHASE_EXCEPTION_RET1", "0"))

# v2.14 KOSPI 시장 레짐 필터
# 전날 코스피 급등 후 다음날 되돌림, 전날 코스피 급락 후 다음날 반등 가능성을 반영한다.
KOSPI_SURGE_RET_1D = float(os.environ.get("KOSPI_SURGE_RET_1D", "1.2"))
KOSPI_EXTREME_SURGE_RET_1D = float(os.environ.get("KOSPI_EXTREME_SURGE_RET_1D", "2.0"))
KOSPI_DROP_RET_1D = float(os.environ.get("KOSPI_DROP_RET_1D", "-1.2"))
KOSPI_EXTREME_DROP_RET_1D = float(os.environ.get("KOSPI_EXTREME_DROP_RET_1D", "-2.0"))
KOSPI_5D_SURGE = float(os.environ.get("KOSPI_5D_SURGE", "4.0"))
KOSPI_5D_DROP = float(os.environ.get("KOSPI_5D_DROP", "-4.0"))
KOSPI_VOLATILITY_WATCH = float(os.environ.get("KOSPI_VOLATILITY_WATCH", "1.3"))

# v2.15 3% 폭발점수
# total_score는 안정성/방향성에 강하고, burst_score는 다음날 +3% 가능성에 집중한다.
STABILITY_WEIGHT = float(os.environ.get("STABILITY_WEIGHT", "0.45"))
BURST_WEIGHT = float(os.environ.get("BURST_WEIGHT", "0.55"))
BURST_REJECT_CAP = float(os.environ.get("BURST_REJECT_CAP", "55"))
BURST_WATCH_CAP = float(os.environ.get("BURST_WATCH_CAP", "78"))

KEYWORDS = [
    "코스피", "반도체", "HBM", "메모리", "AI 인공지능", "데이터센터",
    "전력기기", "전선 변압기", "2차전지 배터리", "방산", "K방산",
    "우주항공", "스페이스X", "조선", "원전", "바이오 제약", "자동차",
    "환율 금리", "트럼프", "리사수", "Lisa Su", "머스크", "일론 머스크",
    "테슬라", "Tesla", "전쟁", "지정학", "중동", "우크라이나", "대만"
]

# 기존 12개 컬럼은 앞에 그대로 유지해야 score_matured()의 G:L 업데이트와 호환됨
HEADERS = [
    "pick_date", "ticker", "name", "rationale", "risk",
    "ref_price_pick", "buy_close", "sell_open",
    "overnight_pct", "kospi_pct", "hit", "scored",
    "pick_rank", "stage1_score", "total_score", "liquidity_score",
    "momentum_score", "news_score", "risk_score", "history_score",
    "price_source", "prev_close", "week_close", "ret_1d_pct", "ret_5d_pct",
    "kospi_ret_1d_pct", "relative_strength_1d_pct",
    "volume", "avg_volume_5", "volume_ratio_5", "trading_value", "volatility_5d_pct",
    "news_count", "theme_hits", "ai_memory_hits", "defense_hits", "space_hits",
    "tesla_space_hits", "geo_hits", "bad_hits", "theme_bucket", "score_detail",
    "bot_version", "score_version", "strategy_profile", "quality_gate", "quality_flags",
    "prior_pick_count", "prior_hit_count", "prior_fail_count", "recent_fail_streak",
    "last_pick_date", "last_pick_return_pct", "days_since_last_pick", "repick_status",
    "kospi_regime", "kospi_flags", "kospi_ret_1d_pct", "kospi_ret_5d_pct",
    "kospi_volatility_5d_pct", "kospi_regime_action",
    "stability_score", "burst_score", "final_score", "burst_flags",
]


# ======================= 테마 키워드 =======================
AI_MEMORY_THEME_KEYWORDS = [
    "AI", "인공지능", "생성형AI", "온디바이스AI",
    "HBM", "HBM3", "HBM3E", "HBM4",
    "메모리", "DRAM", "D램", "DDR5", "LPDDR",
    "NAND", "낸드", "SSD",
    "반도체", "시스템반도체", "파운드리", "패키징", "첨단패키징", "CXL", "칩렛",
    "웨이퍼", "EUV", "노광", "식각", "증착", "장비", "소재", "부품",
    "엔비디아", "NVIDIA", "GPU", "AMD", "리사수", "Lisa Su",
    "TSMC", "마이크론", "Micron", "브로드컴", "Broadcom",
    "데이터센터", "서버", "AI서버", "전력", "전력기기", "전선", "변압기",
    "냉각", "액침냉각"
]

DEFENSE_THEME_KEYWORDS = [
    "방산", "방위산업", "국방", "군수", "K방산", "K-방산",
    "무기체계", "수주", "수출", "전차", "자주포", "장갑차",
    "미사일", "탄약", "포탄", "레이더", "요격", "방공", "대공",
    "드론", "무인기", "군용드론", "잠수함", "함정", "전투기", "항공기"
]

SPACE_THEME_KEYWORDS = [
    "우주항공", "항공우주", "우주산업", "위성", "위성통신", "저궤도위성",
    "발사체", "로켓", "누리호", "스페이스X", "SpaceX", "스타링크", "Starlink",
    "UAM", "드론", "항공"
]

TESLA_SPACE_TECH_KEYWORDS = [
    "테슬라", "Tesla", "머스크", "일론 머스크", "Elon Musk",
    "스페이스X", "SpaceX", "스타링크", "Starlink",
    "자율주행", "로보택시", "전기차", "배터리", "ESS"
]

GEOPOLITICAL_RISK_KEYWORDS = [
    "전쟁", "확전", "분쟁", "군사충돌", "무력충돌", "공습", "보복공격",
    "미사일 발사", "제재", "봉쇄", "휴전", "종전", "중동", "이스라엘", "이란",
    "러시아", "우크라이나", "북한", "대만", "대만해협", "남중국해"
]

BAD_KEYWORDS = [
    "거래정지", "상장폐지", "횡령", "배임", "감사의견", "관리종목", "불성실공시",
    "실적쇼크", "적자전환", "어닝쇼크", "유상증자", "감자", "압수수색", "리콜", "소송", "하한가"
]

GENERAL_THEME_KEYWORDS = [
    "조선", "원전", "바이오", "제약", "2차전지", "자동차", "로봇", "화장품",
    "수출", "실적", "트럼프", "관세", "보조금", "규제완화"
]

THEME_KEYWORDS = (
    AI_MEMORY_THEME_KEYWORDS + DEFENSE_THEME_KEYWORDS + SPACE_THEME_KEYWORDS
    + TESLA_SPACE_TECH_KEYWORDS + GENERAL_THEME_KEYWORDS + GEOPOLITICAL_RISK_KEYWORDS
)


# ----------------------------- 공통 유틸 -----------------------------
def env(key: str) -> str:
    v = os.environ.get(key)
    if not v:
        raise RuntimeError(f"환경변수 {key} 가 비어있습니다. GitHub Secrets를 확인하세요.")
    return v


def now_kst() -> dt.datetime:
    return dt.datetime.utcnow() + dt.timedelta(hours=9)


def safe_float(v, default=None):
    try:
        if v in ("", None):
            return default
        return float(v)
    except Exception:
        return default


def clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def pct_change(now, base) -> float:
    try:
        if now is None or base in (None, "", 0):
            return 0.0
        return (float(now) - float(base)) / float(base) * 100
    except Exception:
        return 0.0


def price_source_label(source: str) -> str:
    if source == "naver":
        return "네이버 현재가"
    if source == "fdr_close":
        return "최근 종가"
    return "조회 실패"


def fmt_won(v) -> str:
    try:
        if v in ("", None):
            return "-"
        return f"{int(round(float(v))):,}원"
    except Exception:
        return "-"


def fmt_change(price, base) -> str:
    try:
        if price in ("", None) or base in ("", None, 0):
            return "-"
        diff = float(price) - float(base)
        pct = diff / float(base) * 100
        return f"{diff:+,.0f}원 ({pct:+.2f}%)"
    except Exception:
        return "-"


def short_theme(theme: str) -> str:
    theme = str(theme or "-").strip()
    return theme if len(theme) <= 28 else theme[:28] + "…"


def split_saved_text(text: str) -> List[str]:
    return [x.strip() for x in str(text or "").split(" / ") if x.strip()]

def section_lines(title, items, max_items=None):
    """텔레그램 가독성을 위해 섹션 제목과 항목 사이를 정리."""
    values = [str(x).strip() for x in (items or []) if str(x).strip()]
    if max_items:
        values = values[:max_items]
    if not values:
        values = ["-"]
    return [title] + [f"  • {x}" for x in values]


def compact_theme(theme):
    """너무 긴 테마 문자열은 메시지에서 간단히 표시."""
    theme = str(theme or "-").strip()
    if not theme:
        return "-"
    parts = [x.strip() for x in theme.split(",") if x.strip()]
    return " · ".join(parts[:3]) if parts else theme


def format_evidence_lines(news_items, max_items=2):
    """
    이유/주의 앞에 표시할 근거 요약.
    예: 🧾 근거
          • 06/05 · 한국경제: HBM 수요 확대...
    """
    lines = []
    for d, s, t in (news_items or [])[:max_items]:
        date = str(d or "").strip()
        src = str(s or "").strip()
        title = str(t or "").strip()

        meta = " · ".join(x for x in [date, src] if x)
        if meta and title:
            lines.append(f"  • {meta}: {title[:54]}")
        elif title:
            lines.append(f"  • {title[:60]}")

    if not lines:
        return []

    return ["🧾 근거"] + lines


def dedupe(items: List[str]) -> List[str]:
    out, seen = [], set()
    for x in items:
        x = str(x).strip()
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def split_telegram_message(text: str, limit: int = 3500) -> List[str]:
    if len(text) <= limit:
        return [text]
    sep = "━━━━━━━━━━━━"
    blocks = text.split("\n" + sep + "\n")
    chunks, cur = [], ""
    for block in blocks:
        candidate = block if not cur else cur + "\n" + sep + "\n" + block
        if len(candidate) <= limit:
            cur = candidate
        else:
            if cur:
                chunks.append(cur)
            if len(block) <= limit:
                cur = block
            else:
                for i in range(0, len(block), limit):
                    chunks.append(block[i:i + limit])
                cur = ""
    if cur:
        chunks.append(cur)
    return chunks


def tg_send(text: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("텔레그램 설정 없음, 콘솔 출력만:\n", text[:2000])
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in split_telegram_message(text):
        try:
            r = requests.post(url, data={"chat_id": chat, "text": chunk}, timeout=15)
            if not r.ok:
                print("텔레그램 전송 실패:", r.status_code, r.text[:300])
        except Exception as e:
            print("텔레그램 전송 예외:", e)


def gemini_generate(prompt: str, retries: int = 4):
    client = genai.Client(api_key=env("GEMINI_API_KEY"))
    for attempt in range(retries):
        try:
            return client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        except Exception as e:
            msg = str(e)
            retryable = (
                "503" in msg or "UNAVAILABLE" in msg or "429" in msg
                or "overloaded" in msg.lower() or "rate" in msg.lower()
            )
            if retryable and attempt < retries - 1:
                time.sleep(8 * (attempt + 1))
                continue
            raise


def get_sheet():
    info = json.loads(env("GCP_SERVICE_ACCOUNT"))
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(env("SHEET_ID"))
    ws = sh.sheet1
    try:
        first_row = ws.row_values(1)
    except Exception:
        first_row = []
    if first_row[:len(HEADERS)] != HEADERS:
        ws.batch_update([{"range": "A1", "values": [HEADERS]}])
    return ws


def is_trading_day(date=None) -> bool:
    d = date or now_kst().date()
    if d.weekday() >= 5:
        return False
    try:
        start = (d - dt.timedelta(days=10)).strftime("%Y-%m-%d")
        df = fdr.DataReader("KS11", start, d.strftime("%Y-%m-%d"))
        if df.empty:
            print("거래일 확인: 지수 데이터 없음. 평일이므로 일단 진행.")
            return True
        last_date = pd.to_datetime(df.index[-1]).date()
        if last_date < d:
            print(f"거래일 확인: 최신 지수 데이터가 {last_date}까지입니다. 평일이므로 일단 진행.")
        return True
    except Exception as e:
        print("거래일 확인 실패, 평일이므로 일단 진행:", e)
        return True


# ----------------------------- 가격 / 지표 -----------------------------
def get_price_quote(ticker: str) -> Dict[str, Any]:
    try:
        url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{ticker}"
        data = requests.get(url, timeout=8).json()
        price = float(data["result"]["areas"][0]["datas"][0]["nv"])
        return {"price": price, "source": "naver"}
    except Exception:
        pass
    try:
        df = fdr.DataReader(ticker, (now_kst().date() - dt.timedelta(days=10)).strftime("%Y-%m-%d"))
        if not df.empty:
            return {"price": float(df["Close"].iloc[-1]), "source": "fdr_close"}
    except Exception:
        pass
    return {"price": None, "source": "fail"}


def get_current_price(ticker: str):
    return get_price_quote(ticker)["price"]


def get_recent_metrics(ticker: str, current_price=None) -> Dict[str, Any]:
    out = {
        "prev_close": "", "week_close": "", "ret_1d_pct": 0.0, "ret_5d_pct": 0.0,
        "volume": "", "avg_volume_5": "", "volume_ratio_5": 0.0,
        "trading_value": "", "volatility_5d_pct": 0.0,
    }
    try:
        start = (now_kst().date() - dt.timedelta(days=45)).strftime("%Y-%m-%d")
        df = fdr.DataReader(ticker, start)
        if df.empty or "Close" not in df.columns:
            return out
        today = now_kst().date()
        dates = pd.to_datetime(df.index).date
        prior = df[dates < today].copy()
        if prior.empty:
            prior = df.copy()
        if len(prior) < 2:
            return out
        prev_close = float(prior["Close"].iloc[-1])
        prev2_close = float(prior["Close"].iloc[-2])
        week_close = float(prior["Close"].iloc[-6]) if len(prior) >= 6 else float(prior["Close"].iloc[0])
        ref_price = current_price if current_price not in ("", None) else prev_close
        base_1d = prev_close if current_price not in ("", None) else prev2_close
        volume, avg_volume_5, volume_ratio_5, trading_value = "", "", 0.0, ""
        if "Volume" in prior.columns:
            vol_series = pd.to_numeric(prior["Volume"], errors="coerce").dropna()
            if not vol_series.empty:
                volume = float(vol_series.iloc[-1])
                avg_volume_5 = float(vol_series.tail(5).mean()) if len(vol_series) >= 1 else volume
                volume_ratio_5 = (volume / avg_volume_5) if avg_volume_5 else 0.0
                trading_value = prev_close * volume if volume else ""
        volatility_5d_pct = 0.0
        try:
            close = pd.to_numeric(prior["Close"], errors="coerce").dropna()
            returns = close.pct_change().dropna().tail(5)
            volatility_5d_pct = float(returns.std() * 100) if len(returns) >= 2 else 0.0
        except Exception:
            pass
        out.update({
            "prev_close": prev_close,
            "week_close": week_close,
            "ret_1d_pct": pct_change(ref_price, base_1d),
            "ret_5d_pct": pct_change(ref_price, week_close),
            "volume": volume,
            "avg_volume_5": avg_volume_5,
            "volume_ratio_5": volume_ratio_5,
            "trading_value": trading_value,
            "volatility_5d_pct": volatility_5d_pct,
        })
        return out
    except Exception as e:
        print("최근 지표 계산 실패:", ticker, e)
        return out


def price_history(ticker: str):
    """직전 거래일/전주/전달 기준 종가와 일자. 오늘 행은 제외."""
    try:
        start = (now_kst().date() - dt.timedelta(days=70)).strftime("%Y-%m-%d")
        df = fdr.DataReader(ticker, start)
        if df.empty:
            return None
        today = now_kst().date()
        prior = [(pd.to_datetime(x).date(), float(df["Close"].iloc[i]))
                 for i, x in enumerate(df.index) if pd.to_datetime(x).date() < today]
        if not prior:
            return None
        y_date, y_close = prior[-1]
        lw_date, lw_close = prior[-6] if len(prior) >= 6 else prior[0]
        # 약 1개월 전 = 20거래일 전 기준. 데이터가 부족하면 가장 오래된 값 사용.
        m_date, m_close = prior[-21] if len(prior) >= 21 else prior[0]
        return (
            y_date.strftime("%m/%d"), y_close,
            lw_date.strftime("%m/%d"), lw_close,
            m_date.strftime("%m/%d"), m_close,
        )
    except Exception:
        return None


# ----------------------------- 후보 풀 / 뉴스 -----------------------------
def is_excluded_instrument(code: str, name: str) -> bool:
    n = str(name or "").strip()
    u = n.upper()
    exclude_tokens = [
        "KODEX", "TIGER", "KBSTAR", "ACE", "HANARO", "SOL ",
        "KOSEF", "ARIRANG", "TIMEFOLIO", "RISE", "PLUS", "ETF", "ETN",
        "스팩", "SPAC", "리츠", "REIT"
    ]
    if any(tok in u for tok in exclude_tokens):
        return True
    if n.endswith("우") or n.endswith("우B") or "(우)" in n or "우선주" in n:
        return True
    return False


def get_universe() -> List[Tuple[str, str]]:
    """
    KOSPI 유니버스 생성.
    FinanceDataReader의 KOSPI listing이 404/차단/당일 파일 미생성으로 실패할 수 있어
    여러 fallback을 순서대로 시도한다.

    1) fdr.StockListing("KOSPI")
    2) fdr.StockListing("KRX") 후 KOSPI 필터
    3) fdr.SnapDataReader("KRX/INDEX/STOCK/1028") 코스피200 구성종목
    4) KRX KIND 상장법인 목록
    5) 정적 대형주 fallback
    """

    def normalize_listing(df, source_name: str) -> List[Tuple[str, str]]:
        if df is None or df.empty:
            return []

        cols = {str(c).lower(): c for c in df.columns}

        code_col = (
            cols.get("code")
            or cols.get("symbol")
            or cols.get("종목코드")
            or cols.get("단축코드")
        )
        name_col = (
            cols.get("name")
            or cols.get("종목명")
            or cols.get("회사명")
            or cols.get("한글 종목명")
        )

        if not code_col or not name_col:
            print(f"{source_name}: 종목코드/종목명 컬럼을 찾지 못함: {list(df.columns)}")
            return []

        data = df.dropna(subset=[code_col, name_col]).copy()

        market_col = (
            cols.get("market")
            or cols.get("marketid")
            or cols.get("시장구분")
            or cols.get("시장")
        )
        if market_col:
            market_s = data[market_col].astype(str).str.upper()
            kospi_mask = (
                market_s.str.contains("KOSPI", na=False)
                | market_s.str.contains("STK", na=False)
                | market_s.str.contains("유가", na=False)
                | market_s.str.contains("거래소", na=False)
            )
            if kospi_mask.any():
                data = data[kospi_mask].copy()

        rank_col = None
        if "amount" in cols:
            rank_col = cols["amount"]
        elif "marcap" in cols:
            rank_col = cols["marcap"]
        elif "marketcap" in cols:
            rank_col = cols["marketcap"]
        elif "시가총액" in df.columns:
            rank_col = "시가총액"
        elif "거래대금" in df.columns:
            rank_col = "거래대금"
        elif "volume" in cols and "close" in cols:
            data["_tv"] = (
                pd.to_numeric(data[cols["volume"]], errors="coerce")
                * pd.to_numeric(data[cols["close"]], errors="coerce")
            )
            rank_col = "_tv"

        if rank_col and rank_col in data.columns:
            data[rank_col] = pd.to_numeric(data[rank_col], errors="coerce")
            data = data.sort_values(rank_col, ascending=False)

        out = []
        for _, r in data.iterrows():
            raw_code = str(r[code_col]).strip()
            code = re.sub(r"\D", "", raw_code).zfill(6)
            name = str(r[name_col]).strip()

            if len(code) != 6 or not name:
                continue
            if is_excluded_instrument(code, name):
                continue

            out.append((code, name))
            if len(out) >= UNIVERSE_SIZE:
                break

        deduped = []
        seen = set()
        for code, name in out:
            if code in seen:
                continue
            seen.add(code)
            deduped.append((code, name))

        print(f"{source_name}: {len(deduped)}개 유니버스 확보")
        return deduped

    try:
        df = fdr.StockListing("KOSPI")
        out = normalize_listing(df, 'fdr.StockListing("KOSPI")')
        if out:
            return out
    except Exception as e:
        print('fdr.StockListing("KOSPI") 실패:', e)

    try:
        df = fdr.StockListing("KRX")
        out = normalize_listing(df, 'fdr.StockListing("KRX")')
        if out:
            return out
    except Exception as e:
        print('fdr.StockListing("KRX") 실패:', e)

    try:
        df = fdr.SnapDataReader("KRX/INDEX/STOCK/1028")
        out = normalize_listing(df, 'fdr.SnapDataReader("KRX/INDEX/STOCK/1028")')
        if out:
            return out[:UNIVERSE_SIZE]
    except Exception as e:
        print('코스피200 SnapDataReader 실패:', e)

    try:
        url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13&marketType=stockMkt"
        tables = pd.read_html(url, encoding="euc-kr")
        if tables:
            out = normalize_listing(tables[0], "KRX KIND stockMkt")
            if out:
                return out[:UNIVERSE_SIZE]
    except Exception as e:
        print("KRX KIND 상장법인 fallback 실패:", e)

    static = [
        ("005930", "삼성전자"), ("000660", "SK하이닉스"), ("373220", "LG에너지솔루션"),
        ("207940", "삼성바이오로직스"), ("005380", "현대차"), ("000270", "기아"),
        ("068270", "셀트리온"), ("005490", "POSCO홀딩스"), ("051910", "LG화학"),
        ("035420", "NAVER"), ("000810", "삼성화재"), ("006400", "삼성SDI"),
        ("028260", "삼성물산"), ("012330", "현대모비스"), ("105560", "KB금융"),
        ("055550", "신한지주"), ("035720", "카카오"), ("032830", "삼성생명"),
        ("086790", "하나금융지주"), ("138040", "메리츠금융지주"), ("015760", "한국전력"),
        ("033780", "KT&G"), ("009540", "HD한국조선해양"), ("034020", "두산에너빌리티"),
        ("000720", "현대건설"), ("010130", "고려아연"), ("042660", "한화오션"),
        ("047810", "한국항공우주"), ("012450", "한화에어로스페이스"), ("064350", "현대로템"),
        ("079550", "LIG넥스원"), ("241560", "두산밥캣"), ("267260", "HD현대일렉트릭"),
        ("329180", "HD현대중공업"), ("267250", "HD현대"), ("010140", "삼성중공업"),
        ("010620", "HD현대미포"), ("011200", "HMM"), ("003550", "LG"),
        ("066570", "LG전자"), ("034730", "SK"), ("096770", "SK이노베이션"),
        ("003670", "포스코퓨처엠"), ("011070", "LG이노텍"), ("009150", "삼성전기"),
        ("000150", "두산"), ("034220", "LG디스플레이"), ("090430", "아모레퍼시픽"),
        ("010950", "S-Oil"), ("018260", "삼성에스디에스"), ("030200", "KT"),
        ("017670", "SK텔레콤"), ("316140", "우리금융지주"), ("024110", "기업은행"),
        ("251270", "넷마블"), ("259960", "크래프톤"), ("352820", "하이브"),
        ("010120", "LS ELECTRIC"), ("006260", "LS"), ("001440", "대한전선"),
        ("103140", "풍산"), ("298040", "효성중공업"), ("004020", "현대제철"),
        ("011790", "SKC"), ("047050", "포스코인터내셔널"), ("003490", "대한항공"),
        ("180640", "한진칼"), ("271560", "오리온"), ("097950", "CJ제일제당"),
        ("000100", "유한양행"), ("128940", "한미약품"), ("326030", "SK바이오팜"),
    ]

    print(f"정적 fallback 사용: {len(static)}개")
    return [(c, n) for c, n in static if not is_excluded_instrument(c, n)][:UNIVERSE_SIZE]


def get_macro_news() -> str:
    lines = []
    for kw in KEYWORDS:
        try:
            q = requests.utils.quote(kw)
            url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
            for e in feedparser.parse(url).entries[:2]:
                lines.append(f"[{kw}] {e.title}")
        except Exception:
            continue
    return "\n".join(lines)[:6000]


def clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "")).strip()


def normalize_title_key(title: str) -> str:
    t = clean_title(title).lower()
    t = re.sub(r"[^0-9a-z가-힣]+", "", t)
    return t[:50]


def get_stock_news(name: str, limit: int = 3) -> List[Tuple[str, str, str]]:
    items, seen = [], set()
    try:
        q = requests.utils.quote(name)
        url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
        for e in feedparser.parse(url).entries:
            title = e.title or ""
            src = ""
            try:
                src = (e.get("source", {}) or {}).get("title", "") or ""
            except Exception:
                src = ""
            if not src and " - " in title:
                title, src = title.rsplit(" - ", 1)
            date = time.strftime("%m/%d", e.published_parsed) if e.get("published_parsed") else ""
            key = normalize_title_key(title)
            if not key or key in seen:
                continue
            seen.add(key)
            items.append((date, src.strip(), clean_title(title)))
            if len(items) >= limit:
                break
    except Exception:
        pass
    nid = os.environ.get("NAVER_CLIENT_ID")
    nsec = os.environ.get("NAVER_CLIENT_SECRET")
    if nid and nsec and len(items) < limit + 2:
        try:
            headers = {"X-Naver-Client-Id": nid, "X-Naver-Client-Secret": nsec}
            q = requests.utils.quote(name)
            url = f"https://openapi.naver.com/v1/search/news.json?query={q}&display=5&sort=date"
            res = requests.get(url, headers=headers, timeout=8)
            if res.ok:
                for it in res.json().get("items", []):
                    title = re.sub(r"<[^>]+>", "", it.get("title", "")).replace("&quot;", '"').strip()
                    pub = it.get("pubDate", "")
                    date = ""
                    if pub:
                        try:
                            date = dt.datetime.strptime(pub[:16], "%a, %d %b %Y").strftime("%m/%d")
                        except Exception:
                            pass
                    key = normalize_title_key(title)
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    items.append((date, "네이버뉴스", clean_title(title)))
                    if len(items) >= limit + 2:
                        break
        except Exception:
            pass
    return items


def likely_ai_memory_core(name: str, news_items: List[Tuple[str, str, str]], news_info: Dict[str, Any] = None) -> bool:
    """
    v2.13: AI/메모리 테마 오분류 방지.
    금융/통신/정유/지주처럼 AI 키워드가 주변 뉴스에 섞이기 쉬운 종목은
    실제 반도체/부품/장비/전력/데이터센터 연관 키워드가 있어야 AI/메모리 핵심 테마로 인정한다.
    """
    name_l = str(name or "").lower()
    text = " ".join([str(name or "")] + [str(t or "") for _, _, t in (news_items or [])]).lower()

    weak_business_keywords = [
        "금융", "은행", "지주", "증권", "보험", "카드", "캐피탈",
        "텔레콤", "telecom", "통신", "유플러스", "s-oil", "에쓰오일", "정유", "석유",
    ]
    weak_name = any(k in name_l for k in weak_business_keywords)

    core_keywords = [
        "반도체", "hbm", "메모리", "dram", "d램", "ddr", "nand", "낸드",
        "패키징", "cxl", "칩렛", "웨이퍼", "euv", "식각", "증착", "파운드리",
        "gpu", "엔비디아", "nvidia", "amd", "리사수", "tsmc", "마이크론",
        "ai서버", "ai 서버", "데이터센터", "전력기기", "변압기", "전선", "냉각",
        "mlcc", "기판", "pcb", "fc-bga", "디스플레이", "oled", "전자부품",
    ]
    core_hit = any(k.lower() in text for k in core_keywords)

    core_name_keywords = [
        "전자", "전기", "하이닉스", "반도체", "전선", "디스플레이", "이노텍",
        "전력", "일렉트릭", "테크", "테크놀로지", "하이텍", "전기", "대덕전자",
        "해성디에스", "db하이텍", "삼성전기", "lg디스플레이",
    ]
    core_name = any(k.lower() in name_l for k in core_name_keywords)

    if weak_name and not (core_hit or core_name):
        return False

    return core_hit or core_name



def keyword_hits(text: str, keywords: List[str]) -> List[str]:
    text_l = str(text or "").lower()
    hits, seen = [], set()
    for kw in keywords:
        k = str(kw)
        kl = k.lower()
        if kl and kl in text_l and kl not in seen:
            hits.append(k)
            seen.add(kl)
    return hits


def analyze_news_items(items: List[Tuple[str, str, str]]) -> Dict[str, Any]:
    text = " ".join(t for _, _, t in items)
    ai_memory_hits = keyword_hits(text, AI_MEMORY_THEME_KEYWORDS)
    defense_hits = keyword_hits(text, DEFENSE_THEME_KEYWORDS)
    space_hits = keyword_hits(text, SPACE_THEME_KEYWORDS)
    tesla_space_hits = keyword_hits(text, TESLA_SPACE_TECH_KEYWORDS)
    geo_hits = keyword_hits(text, GEOPOLITICAL_RISK_KEYWORDS)
    bad_hits = keyword_hits(text, BAD_KEYWORDS)
    theme_hits = keyword_hits(text, THEME_KEYWORDS)
    is_ai_memory_theme = len(ai_memory_hits) > 0
    is_defense_theme = len(defense_hits) > 0
    is_space_theme = len(space_hits) > 0
    is_tesla_space_theme = len(tesla_space_hits) > 0
    has_geo_risk = len(geo_hits) > 0
    has_bad_issue = len(bad_hits) > 0
    geo_benefit_theme = has_geo_risk and (is_defense_theme or is_space_theme)
    bucket = []
    if is_ai_memory_theme:
        bucket.append("AI/메모리")
    if is_defense_theme:
        bucket.append("방산")
    if is_space_theme:
        bucket.append("우주항공")
    if is_tesla_space_theme:
        bucket.append("테슬라/스페이스X")
    if geo_benefit_theme:
        bucket.append("지정학수혜")
    elif has_geo_risk:
        bucket.append("지정학리스크")
    if has_bad_issue:
        bucket.append("악재주의")
    if not bucket and theme_hits:
        bucket.append("일반테마")
    if not bucket:
        bucket.append("비테마")
    return {
        "news_count": len(items),
        "theme_hits": ",".join(theme_hits),
        "ai_memory_hits": ",".join(ai_memory_hits),
        "defense_hits": ",".join(defense_hits),
        "space_hits": ",".join(space_hits),
        "tesla_space_hits": ",".join(tesla_space_hits),
        "geo_hits": ",".join(geo_hits),
        "bad_hits": ",".join(bad_hits),
        "theme_hit_count": len(theme_hits),
        "ai_memory_hit_count": len(ai_memory_hits),
        "defense_hit_count": len(defense_hits),
        "space_hit_count": len(space_hits),
        "tesla_space_hit_count": len(tesla_space_hits),
        "geo_hit_count": len(geo_hits),
        "bad_hit_count": len(bad_hits),
        "is_ai_memory_theme": is_ai_memory_theme,
        "is_defense_theme": is_defense_theme,
        "is_space_theme": is_space_theme,
        "is_tesla_space_theme": is_tesla_space_theme,
        "is_leading_theme": is_ai_memory_theme or is_defense_theme or is_space_theme or is_tesla_space_theme,
        "has_geo_risk": has_geo_risk,
        "geo_benefit_theme": geo_benefit_theme,
        "has_bad_issue": has_bad_issue,
        "theme_bucket": ",".join(bucket),
    }


# ----------------------------- 점수 계산 -----------------------------
def score_stage1(metrics: Dict[str, Any]) -> Dict[str, Any]:
    trading_value = safe_float(metrics.get("trading_value"), 0) or 0
    volume_ratio = safe_float(metrics.get("volume_ratio_5"), 0) or 0
    ret_1d = safe_float(metrics.get("ret_1d_pct"), 0) or 0
    ret_5d = safe_float(metrics.get("ret_5d_pct"), 0) or 0
    kospi_1d = safe_float(metrics.get("kospi_ret_1d_pct"), 0) or 0
    rel = ret_1d - kospi_1d
    volatility = safe_float(metrics.get("volatility_5d_pct"), 0) or 0
    price_ok = safe_float(metrics.get("prev_close")) is not None
    volume_ok = safe_float(metrics.get("volume"), 0) not in (None, 0)
    if trading_value >= 300_000_000_000:
        liquidity = 25
    elif trading_value >= 150_000_000_000:
        liquidity = 22
    elif trading_value >= 70_000_000_000:
        liquidity = 18
    elif trading_value >= 30_000_000_000:
        liquidity = 14
    elif trading_value >= 10_000_000_000:
        liquidity = 9
    else:
        liquidity = 4
    volume_score = 8
    if volume_ratio >= 2.0:
        volume_score += 10
    elif volume_ratio >= 1.5:
        volume_score += 7
    elif volume_ratio >= 1.2:
        volume_score += 4
    elif volume_ratio < 0.7:
        volume_score -= 3
    volume_score = clamp(volume_score, 0, 20)
    relative_score = 10
    if rel >= 5:
        relative_score += 8
    elif rel >= 3:
        relative_score += 6
    elif rel >= 1.5:
        relative_score += 4
    elif rel <= -3:
        relative_score -= 5
    elif rel <= -1.5:
        relative_score -= 3
    relative_score = clamp(relative_score, 0, 20)
    trend_score = 7
    if 3 <= ret_5d <= 25:
        trend_score += 6
    elif 0 <= ret_5d < 3:
        trend_score += 3
    elif 25 < ret_5d <= 40:
        trend_score += 2
    elif ret_5d > 40:
        trend_score -= 2
    elif ret_5d < -8:
        trend_score -= 4
    trend_score = clamp(trend_score, 0, 15)
    heat_score = 7
    if 0 <= ret_1d <= 8:
        heat_score += 2
    elif 8 < ret_1d <= 15:
        heat_score += 1
    elif ret_1d > 18:
        heat_score -= 2
    if ret_5d > 45:
        heat_score -= 3
    elif 20 <= ret_5d <= 35:
        heat_score += 1
    if volatility > 8:
        heat_score -= 2
    heat_score = clamp(heat_score, 0, 10)
    stability = 10
    if not price_ok:
        stability -= 5
    if not volume_ok:
        stability -= 3
    if trading_value < 5_000_000_000:
        stability -= 2
    stability = clamp(stability, 0, 10)
    total = liquidity + volume_score + relative_score + trend_score + heat_score + stability
    detail = (
        f"stage1={total:.1f}, liq={liquidity:.1f}, vol={volume_score:.1f}, "
        f"rel={relative_score:.1f}, trend={trend_score:.1f}, heat={heat_score:.1f}, "
        f"stable={stability:.1f}, ret1d={ret_1d:+.2f}, ret5d={ret_5d:+.2f}, "
        f"rel1d={rel:+.2f}, volRatio={volume_ratio:.2f}"
    )
    return {"stage1_score": round(total, 2), "stage1_detail": detail, "relative_strength_1d_pct": round(rel, 2)}


def get_history_score(rows: List[Dict[str, Any]], ticker: str) -> float:
    """
    v2.8: 종목별 과거 성과 점수는 표본이 충분할 때만 약하게 반영.
    기존 데이터에서 history_score가 실패 종목을 과도하게 밀어올리는 현상이 있어
    5회 미만은 중립값 7.5, 5회 이상도 4~9점 범위로 제한한다.
    """
    t = str(ticker).zfill(6)
    rets, hits = [], 0
    for r in rows:
        if str(r.get("ticker", "")).zfill(6) != t:
            continue
        if str(r.get("scored")).upper() not in ("TRUE", "1"):
            continue
        ret = safe_float(r.get("overnight_pct"))
        if ret is None:
            continue
        rets.append(ret)
        if str(r.get("hit")).upper() == "TRUE":
            hits += 1
    if len(rets) < 5:
        return 7.5
    avg = sum(rets) / len(rets)
    hit_rate = hits / len(rets) * 100
    score = 7.5 + avg * 0.4
    if hit_rate >= 35:
        score += 1.0
    elif hit_rate <= 15:
        score -= 1.5
    return round(clamp(score, 4, 9), 2)


def analyze_repick_history(rows: List[Dict[str, Any]], ticker: str, as_of: dt.date = None) -> Dict[str, Any]:
    """
    종목별 과거 추천 이력 검증.
    - 재추천 자체는 허용
    - 반복 실패는 감점/제외
    - 눌림 후 회복 신호가 확인되면 예외 허용을 위한 재료를 제공
    """
    as_of = as_of or now_kst().date()
    t = str(ticker).zfill(6)

    hist = []
    for r in rows:
        if str(r.get("ticker", "")).zfill(6) != t:
            continue

        pdate_raw = str(r.get("pick_date", "")).strip()
        if not pdate_raw:
            continue

        try:
            pdate = pd.to_datetime(pdate_raw).date()
        except Exception:
            continue

        # 오늘 이미 저장된 행은 중복 추천 방지 로직에서 따로 처리하므로 이력 계산에서는 제외
        if pdate >= as_of:
            continue

        age_days = (as_of - pdate).days

        # v2.12: 과거 legacy 추천 실패 이력이 새 점수식 후보를 과도하게 막지 않도록 제한.
        # versioned_recent: 버전정보가 있는 최근 행만 재추천 벌점에 사용.
        bot_ver = str(r.get("bot_version", "")).strip().lower()
        score_ver = str(r.get("score_version", "")).strip().lower()
        has_version = bool(bot_ver or score_ver)

        if REPICK_HISTORY_SCOPE in ("versioned_recent", "recent_versioned"):
            if age_days > REPICK_LOOKBACK_DAYS:
                continue
            if not has_version:
                continue
        elif REPICK_HISTORY_SCOPE == "recent":
            if age_days > REPICK_LOOKBACK_DAYS:
                continue
        elif REPICK_HISTORY_SCOPE == "all":
            pass
        else:
            # 알 수 없는 설정이면 안전하게 최근 버전 행만 사용
            if age_days > REPICK_LOOKBACK_DAYS or not has_version:
                continue

        scored = str(r.get("scored", "")).upper() in ("TRUE", "1")
        hit = str(r.get("hit", "")).upper() == "TRUE"
        ret = safe_float(r.get("overnight_pct"))

        hist.append({
            "pick_date": pdate,
            "scored": scored,
            "hit": hit,
            "ret": ret,
        })

    hist = sorted(hist, key=lambda x: x["pick_date"])
    prior_pick_count = len(hist)
    scored_hist = [x for x in hist if x["scored"] and x["ret"] is not None]
    prior_hit_count = sum(1 for x in scored_hist if x["hit"])
    prior_fail_count = sum(1 for x in scored_hist if not x["hit"])

    recent_fail_streak = 0
    for x in reversed(scored_hist):
        if x["hit"]:
            break
        recent_fail_streak += 1

    last = hist[-1] if hist else None
    last_scored = scored_hist[-1] if scored_hist else None

    if not hist:
        status = "first_pick"
    elif last_scored and last_scored["hit"]:
        status = "repick_after_success"
    elif recent_fail_streak >= 3:
        status = "repeated_fail_reject"
    elif recent_fail_streak == 2:
        status = "repeated_fail_watch"
    elif recent_fail_streak == 1:
        status = "repick_after_fail"
    else:
        status = "repick_unscored_history"

    last_pick_date = last["pick_date"] if last else None
    days_since_last_pick = (as_of - last_pick_date).days if last_pick_date else ""

    return {
        "prior_pick_count": prior_pick_count,
        "prior_hit_count": prior_hit_count,
        "prior_fail_count": prior_fail_count,
        "recent_fail_streak": recent_fail_streak,
        "last_pick_date": last_pick_date.isoformat() if last_pick_date else "",
        "last_pick_return_pct": round(last_scored["ret"], 2) if last_scored and last_scored["ret"] is not None else "",
        "days_since_last_pick": days_since_last_pick,
        "repick_status": status,
    }


def apply_repick_adjustments(metrics: Dict[str, Any], score: Dict[str, Any], repick_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    v2.11: 재추천/재재추천 검증 로직.
    반복 실패 종목이 뉴스/테마만으로 계속 올라오는 문제를 줄인다.
    """
    if not repick_info:
        return score

    status = str(repick_info.get("repick_status", "first_pick"))
    prior_pick_count = int(safe_float(repick_info.get("prior_pick_count"), 0) or 0)
    prior_hit_count = int(safe_float(repick_info.get("prior_hit_count"), 0) or 0)
    recent_fail_streak = int(safe_float(repick_info.get("recent_fail_streak"), 0) or 0)
    days_since = safe_float(repick_info.get("days_since_last_pick"))
    last_ret = safe_float(repick_info.get("last_pick_return_pct"))

    ret_1d = safe_float(metrics.get("ret_1d_pct"), 0) or 0
    ret_5d = safe_float(metrics.get("ret_5d_pct"), 0) or 0
    rel = safe_float(score.get("relative_strength_1d_pct"), 0) or 0
    volume_ratio = safe_float(metrics.get("volume_ratio_5"), 0) or 0

    adjusted = dict(score)
    flags = list(adjusted.get("quality_flags", []) or [])
    gate = adjusted.get("quality_gate", "pass") or "pass"

    liquidity_score = safe_float(adjusted.get("liquidity_score"), 0) or 0
    momentum_score = safe_float(adjusted.get("momentum_score"), 0) or 0
    news_score = safe_float(adjusted.get("news_score"), 0) or 0
    risk_score = safe_float(adjusted.get("risk_score"), 0) or 0
    history_score = safe_float(adjusted.get("history_score"), 7.5) or 7.5

    # 반복 실패 이후에도 가격이 실제로 회복된 경우만 예외.
    recovery_confirmed = (
        recent_fail_streak >= 1
        and rel >= 3
        and momentum_score >= 15
        and -10 <= ret_5d <= 3
        and volume_ratio >= 0.9
        and (days_since in ("", None) or safe_float(days_since, 999) >= 3)
    )

    if status == "first_pick":
        pass

    elif status == "repick_after_success":
        # v2.13: 성공 후 재추천 성과가 낮아 가점 제거.
        if recovery_confirmed:
            flags.append("성공 후 재추천 회복 확인")
            risk_score -= 0.5
            news_score = min(news_score, 23)
        else:
            flags.append("성공 후 재추천 과열 주의")
            momentum_score -= 1.5
            risk_score -= 2.0
            news_score = min(news_score, 21)

    elif status == "repick_after_fail":
        if recovery_confirmed:
            flags.append("실패 후 회복 재추천")
            momentum_score += 1.5
            risk_score += 0.5
            status = "repick_recovery"
        else:
            flags.append("직전 실패 후 재추천")
            momentum_score -= 2.5
            risk_score -= 3.0
            news_score = min(news_score, 20)
            if rel < 1 or ret_1d <= 0:
                flags.append("실패 후 재추천 회복 부족")
                gate = "watch" if gate != "reject" else gate
                momentum_score -= 1.5
                risk_score -= 1.5
                news_score = min(news_score, 18)

    elif status == "repeated_fail_watch":
        if recovery_confirmed:
            flags.append("2연속 실패 후 회복 확인")
            gate = "watch" if gate != "reject" else gate
            momentum_score += 1
            risk_score -= 1
            news_score = min(news_score, 22)
            status = "repeated_fail_recovery_watch"
        else:
            flags.append("2연속 실패 재추천 주의")
            gate = "watch" if gate != "reject" else gate
            momentum_score -= 5
            risk_score -= 6
            news_score = min(news_score, 17)
            if rel < 3 or ret_1d <= 0:
                flags.append("2연속 실패 후 회복 부족")
                gate = "reject"

    elif status == "repeated_fail_reject":
        if recovery_confirmed:
            flags.append("3연속 실패 후 강한 회복")
            gate = "watch" if gate != "reject" else gate
            momentum_score -= 2
            risk_score -= 3
            news_score = min(news_score, 19)
            status = "repeated_fail_recovery_watch"
        else:
            flags.append("3연속 실패 재추천 제외")
            gate = "reject"
            momentum_score -= 6
            risk_score -= 6
            news_score = min(news_score, 16)

    else:
        if prior_pick_count > 0:
            flags.append("과거 추천 이력 있음")
            risk_score -= 0.5

    # 큰 손실 직후 너무 빠른 재추천은 쿨다운.
    if last_ret is not None and last_ret <= -5 and days_since not in ("", None):
        ds = safe_float(days_since, 999)
        if ds <= 5 and not recovery_confirmed:
            flags.append("직전 -5% 이하 실패 쿨다운")
            gate = "reject"
            momentum_score -= 5
            risk_score -= 6
            news_score = min(news_score, 16)
            status = "cooldown_reject"
        elif ds <= 10 and not recovery_confirmed:
            flags.append("직전 큰 손실 후 재추천 주의")
            gate = "watch" if gate != "reject" else gate
            momentum_score -= 3
            risk_score -= 4
            news_score = min(news_score, 18)

    # 재추천인데 당일 흐름도 약하면 추가 감점.
    if prior_pick_count >= 1 and rel < 0 and ret_1d < 0 and not recovery_confirmed:
        flags.append("재추천 당일 흐름 약세")
        momentum_score -= 2
        risk_score -= 2
        news_score = min(news_score, 20)

    momentum_score = clamp(momentum_score, 0, 25)
    news_score = clamp(news_score, 0, 25)
    risk_score = clamp(risk_score, 0, 15)
    history_score = clamp(history_score, 4, 9)

    total_score = liquidity_score + momentum_score + news_score + risk_score + history_score
    if gate == "reject":
        total_score = min(total_score, 56)
    elif gate == "watch":
        total_score = min(total_score, 78)

    adjusted.update({
        "total_score": round(total_score, 2),
        "liquidity_score": round(liquidity_score, 2),
        "momentum_score": round(momentum_score, 2),
        "news_score": round(news_score, 2),
        "risk_score": round(risk_score, 2),
        "history_score": round(history_score, 2),
        "quality_gate": gate,
        "quality_flags": flags,
        "repick_status": status,
        "prior_pick_count": prior_pick_count,
        "prior_hit_count": prior_hit_count,
        "prior_fail_count": int(safe_float(repick_info.get("prior_fail_count"), 0) or 0),
        "recent_fail_streak": recent_fail_streak,
        "last_pick_date": repick_info.get("last_pick_date", ""),
        "last_pick_return_pct": repick_info.get("last_pick_return_pct", ""),
        "days_since_last_pick": repick_info.get("days_since_last_pick", ""),
    })

    detail = adjusted.get("score_detail", "")
    adjusted["score_detail"] = (
        f"repick={status}, prior={prior_pick_count}, prior_hit={prior_hit_count}, "
        f"fail_streak={recent_fail_streak}, last_ret={repick_info.get('last_pick_return_pct','')}, "
        f"days_since={repick_info.get('days_since_last_pick','')}, "
        f"repick_scope={REPICK_HISTORY_SCOPE}, lookback={REPICK_LOOKBACK_DAYS}, gate={gate}, "
        f"flags={';'.join(flags)} | {detail}"
    )
    return adjusted



def score_candidate(metrics: Dict[str, Any], news_info: Dict[str, Any], history_score: float = 7.5, stage1_score: float = 0) -> Dict[str, Any]:
    trading_value = safe_float(metrics.get("trading_value"), 0) or 0
    volume_ratio = safe_float(metrics.get("volume_ratio_5"), 0) or 0
    ret_1d = safe_float(metrics.get("ret_1d_pct"), 0) or 0
    ret_5d = safe_float(metrics.get("ret_5d_pct"), 0) or 0
    kospi_1d = safe_float(metrics.get("kospi_ret_1d_pct"), 0) or 0
    rel = ret_1d - kospi_1d
    volatility = safe_float(metrics.get("volatility_5d_pct"), 0) or 0
    news_count = int(news_info.get("news_count", 0) or 0)
    theme_count = int(news_info.get("theme_hit_count", 0) or 0)
    ai_count = int(news_info.get("ai_memory_hit_count", 0) or 0)
    defense_count = int(news_info.get("defense_hit_count", 0) or 0)
    space_count = int(news_info.get("space_hit_count", 0) or 0)
    tesla_count = int(news_info.get("tesla_space_hit_count", 0) or 0)
    geo_count = int(news_info.get("geo_hit_count", 0) or 0)
    bad_count = int(news_info.get("bad_hit_count", 0) or 0)
    is_ai_memory_theme = bool(news_info.get("is_ai_memory_theme"))
    is_defense_theme = bool(news_info.get("is_defense_theme"))
    is_space_theme = bool(news_info.get("is_space_theme"))
    is_tesla_space_theme = bool(news_info.get("is_tesla_space_theme"))
    geo_benefit_theme = bool(news_info.get("geo_benefit_theme"))
    has_geo_risk = bool(news_info.get("has_geo_risk"))
    if trading_value >= 300_000_000_000:
        liquidity_score = 20
    elif trading_value >= 150_000_000_000:
        liquidity_score = 18
    elif trading_value >= 70_000_000_000:
        liquidity_score = 15
    elif trading_value >= 30_000_000_000:
        liquidity_score = 12
    elif trading_value >= 10_000_000_000:
        liquidity_score = 8
    else:
        liquidity_score = 4
    momentum_score = 12.5
    if rel > 5:
        momentum_score += 6
    elif rel > 3:
        momentum_score += 5
    elif rel > 1.5:
        momentum_score += 3
    elif rel < -3:
        momentum_score -= 5
    elif rel < -1.5:
        momentum_score -= 3
    if 3 <= ret_5d <= 25:
        momentum_score += 5
    elif 0 <= ret_5d < 3:
        momentum_score += 2
    elif 25 < ret_5d <= 45:
        momentum_score += 1
    elif ret_5d < -8:
        momentum_score -= 4
    if volume_ratio >= 1.5:
        momentum_score += 3
    elif volume_ratio >= 1.2:
        momentum_score += 1.5
    elif volume_ratio < 0.7:
        momentum_score -= 2
    news_score = 5 + min(news_count, 4) * 2.2 + min(theme_count, 4) * 1.0
    if is_ai_memory_theme:
        news_score += 4 + min(ai_count, 5) * 1.2
    if is_defense_theme:
        news_score += 3 + min(defense_count, 4) * 1.0
    if is_space_theme:
        news_score += 3 + min(space_count, 4) * 1.0
    if is_tesla_space_theme:
        news_score += 2 + min(tesla_count, 4) * 0.8
    if geo_benefit_theme:
        news_score += 3
    news_score = clamp(news_score, 0, 25)
    risk_score = 15 - bad_count * 5
    if has_geo_risk and not geo_benefit_theme:
        risk_score -= min(geo_count, 3) * 1.5
    trend_confirmed = (
        (is_ai_memory_theme or is_defense_theme or is_space_theme or is_tesla_space_theme)
        and bad_count == 0 and rel > 1.5 and trading_value >= 30_000_000_000
    )
    if ret_1d > 10:
        if trend_confirmed:
            momentum_score += 2
            risk_score -= 1
        else:
            risk_score -= 4
    if ret_5d > 20:
        if trend_confirmed:
            momentum_score += 2
            risk_score -= 2
        else:
            risk_score -= 5
    if ret_5d > 35:
        risk_score -= 3
    if ret_5d > 50:
        risk_score -= 3
    if volatility > 10:
        risk_score -= 2
    momentum_score = clamp(momentum_score, 0, 25)
    risk_score = clamp(risk_score, 0, 15)
    history_score = clamp(history_score, 0, 15)
    total_score = liquidity_score + momentum_score + news_score + risk_score + history_score
    detail = (
        f"total={total_score:.1f}, stage1={stage1_score:.1f}, liq={liquidity_score:.1f}, "
        f"mom={momentum_score:.1f}, news={news_score:.1f}, risk={risk_score:.1f}, hist={history_score:.1f}, "
        f"ret1d={ret_1d:+.2f}, ret5d={ret_5d:+.2f}, rel={rel:+.2f}, volRatio={volume_ratio:.2f}, "
        f"theme={news_info.get('theme_bucket','')}"
    )
    return {
        "total_score": round(total_score, 2),
        "liquidity_score": round(liquidity_score, 2),
        "momentum_score": round(momentum_score, 2),
        "news_score": round(news_score, 2),
        "risk_score": round(risk_score, 2),
        "history_score": round(history_score, 2),
        "relative_strength_1d_pct": round(rel, 2),
        "score_detail": detail,
        "trend_confirmed": trend_confirmed,
    }


def apply_v28_quality_adjustments(metrics: Dict[str, Any], news_info: Dict[str, Any], score: Dict[str, Any]) -> Dict[str, Any]:
    """
    2026-06 실적 재검토 반영 보정.
    핵심: 뉴스 점수보다 상대강도/모멘텀/5일 위치를 우선한다.
    """
    trading_value = safe_float(metrics.get("trading_value"), 0) or 0
    volume_ratio = safe_float(metrics.get("volume_ratio_5"), 0) or 0
    ret_1d = safe_float(metrics.get("ret_1d_pct"), 0) or 0
    ret_5d = safe_float(metrics.get("ret_5d_pct"), 0) or 0
    kospi_1d = safe_float(metrics.get("kospi_ret_1d_pct"), 0) or 0
    rel = ret_1d - kospi_1d
    volatility = safe_float(metrics.get("volatility_5d_pct"), 0) or 0

    is_ai_memory_theme = bool(news_info.get("is_ai_memory_theme"))
    is_defense_theme = bool(news_info.get("is_defense_theme"))
    is_space_theme = bool(news_info.get("is_space_theme"))
    is_tesla_space_theme = bool(news_info.get("is_tesla_space_theme"))
    bad_count = safe_float(news_info.get("bad_hit_count"), 0) or 0

    liquidity_score = safe_float(score.get("liquidity_score"), 0) or 0
    momentum_score = safe_float(score.get("momentum_score"), 0) or 0
    news_score = safe_float(score.get("news_score"), 0) or 0
    risk_score = safe_float(score.get("risk_score"), 0) or 0
    history_score = clamp(safe_float(score.get("history_score"), 7.5) or 7.5, 4, 9)

    quality_flags = []
    quality_gate = "pass"

    # 실제 25건 0승 구간. 뉴스가 좋아도 가격 흐름이 깨진 후보는 제외 우선.
    if rel < -5:
        quality_flags.append("상대강도 -5%p 미만")
        quality_gate = "reject"
        momentum_score -= 4
        risk_score -= 5
        news_score = min(news_score, 18)

    # momentum_score < 8도 실측상 0승. 8~10은 제외는 아니지만 강한 감점.
    if momentum_score < 8:
        quality_flags.append("모멘텀 8점 미만")
        quality_gate = "reject"
        risk_score -= 4
        news_score = min(news_score, 18)
    elif momentum_score < 10:
        quality_flags.append("모멘텀 약세")
        risk_score -= 3
        news_score = min(news_score, 20)
    elif momentum_score < 12:
        quality_flags.append("모멘텀 확인 부족")
        risk_score -= 1
        news_score = min(news_score, 22)


    # v2.9: 반도체/AI 메모리 테마 고점 조정 방어.
    # 테마가 살아 있어도 가격 흐름이 식으면 오버나잇에서는 뉴스 점수 만점 추격을 막는다.
    # 단, 5일 눌림 후 상대강도가 회복되는 경우는 눌림목으로 인정한다.
    if is_ai_memory_theme:
        semi_downtrend = (ret_1d < 0 and ret_5d < 0 and rel < 0)
        semi_peak_rollover = (ret_5d >= 12 and ret_1d < 0 and rel < 1.5)
        semi_weak_rebound = (-8 <= ret_5d <= 2 and rel < 0 and volume_ratio < 1.0)
        semi_pullback_recovery = (-10 <= ret_5d <= 0 and rel >= 1.5 and volume_ratio >= 0.9)

        if semi_pullback_recovery:
            quality_flags.append("반도체 눌림 후 회복")
            momentum_score += 2
            risk_score += 1
        elif semi_peak_rollover:
            quality_flags.append("반도체 고점 이탈 주의")
            momentum_score -= 4
            risk_score -= 5
            news_score = min(news_score, 18)
        elif semi_downtrend:
            quality_flags.append("반도체 하락 추세 확인")
            momentum_score -= 3
            risk_score -= 4
            news_score = min(news_score, 18)
        elif semi_weak_rebound:
            quality_flags.append("반도체 반등 확인 부족")
            momentum_score -= 2
            risk_score -= 2
            news_score = min(news_score, 20)

    # 뉴스 만점이어도 가격/모멘텀이 확인되지 않으면 뉴스 점수 캡.
    if news_score >= 24 and (momentum_score < 12 or rel < 0):
        quality_flags.append("뉴스 대비 가격 확인 부족")
        news_score = min(news_score, 18)
        risk_score -= 2

    # 오버나잇 기준으로는 5일 급등 추격보다 눌림목이 유리.
    if -10 <= ret_5d <= 0 and momentum_score >= 15 and rel >= 0:
        quality_flags.append("눌림 후 반등 우위")
        momentum_score += 3
        risk_score += 1
    elif -10 <= ret_5d <= 5 and momentum_score >= 15 and rel >= 2:
        quality_flags.append("상대강도 동반 눌림")
        momentum_score += 2
        risk_score += 1

    # v2.13: 5일 급등 추격 방어 강화.
    # 강한 상대강도/거래량/당일 흐름이 없으면 5일 급등 구간은 보수적으로 본다.
    strong_chase_exception = (
        rel >= CHASE_EXCEPTION_REL
        and volume_ratio >= CHASE_EXCEPTION_VOL_RATIO
        and ret_1d >= CHASE_EXCEPTION_RET1
        and bad_count == 0
    )

    if ret_5d >= CHASE_RET5_REJECT:
        if strong_chase_exception:
            quality_flags.append("5일 급등 강한 추세 예외")
            risk_score -= 1
            news_score = min(news_score, 23)
        else:
            quality_flags.append("5일 12% 이상 급등 추격 제한")
            quality_gate = "watch" if quality_gate != "reject" else quality_gate
            momentum_score -= 5
            risk_score -= 5
            news_score = min(news_score, 18)

            if is_ai_memory_theme and ret_1d <= 0:
                quality_flags.append("AI/반도체 급등 후 음봉")
                momentum_score -= 2
                risk_score -= 2
                news_score = min(news_score, 16)

            if rel < 0 or ret_1d < -2:
                quality_flags.append("급등 후 상대강도 약화")
                quality_gate = "reject"

    elif ret_5d >= CHASE_RET5_WATCH:
        if strong_chase_exception:
            quality_flags.append("5일 상승 추세 유지")
            risk_score -= 0.5
        else:
            quality_flags.append("5일 5~12% 추격 주의")
            quality_gate = "watch" if quality_gate != "reject" else quality_gate
            momentum_score -= 3
            risk_score -= 3
            news_score = min(news_score, 20)

    if ret_5d >= 20 and rel < 3:
        quality_flags.append("단기 과열 심화")
        momentum_score -= 2
        risk_score -= 2

    if ret_1d <= -5 and rel < 0:
        quality_flags.append("하락 중 진입 주의")
        momentum_score -= 2
        risk_score -= 3
        news_score = min(news_score, 20)

    if ret_1d > 6 and ret_5d >= 10:
        quality_flags.append("단기 급등 당일 추격")
        risk_score -= 3

    if volume_ratio < 0.7 and rel < 0:
        quality_flags.append("거래량 확인 부족")
        risk_score -= 2

    if volatility > 10:
        risk_score -= 2
    elif volatility > 8:
        risk_score -= 1

    momentum_score = clamp(momentum_score, 0, 25)
    news_score = clamp(news_score, 0, 25)
    risk_score = clamp(risk_score, 0, 15)
    total_score = liquidity_score + momentum_score + news_score + risk_score + history_score

    if quality_gate == "reject":
        total_score = min(total_score, 58)
    elif quality_gate == "watch":
        total_score = min(total_score, 78)

    adjusted = dict(score)
    adjusted.update({
        "total_score": round(total_score, 2),
        "liquidity_score": round(liquidity_score, 2),
        "momentum_score": round(momentum_score, 2),
        "news_score": round(news_score, 2),
        "risk_score": round(risk_score, 2),
        "history_score": round(history_score, 2),
        "relative_strength_1d_pct": round(rel, 2),
        "quality_gate": quality_gate,
        "quality_flags": quality_flags,
    })
    detail = adjusted.get("score_detail", "")
    adjusted["score_detail"] = (
        f"total={total_score:.1f}, liq={liquidity_score:.1f}, mom={momentum_score:.1f}, "
        f"news={news_score:.1f}, risk={risk_score:.1f}, hist={history_score:.1f}, "
        f"ret1d={ret_1d:+.2f}, ret5d={ret_5d:+.2f}, rel={rel:+.2f}, volRatio={volume_ratio:.2f}, "
        f"gate={quality_gate}, flags={';'.join(quality_flags)} | base: {detail}"
    )
    adjusted["trend_confirmed"] = bool(
        score.get("trend_confirmed")
        and quality_gate != "reject"
        and rel >= 0
        and trading_value >= 30_000_000_000
        and "5일 급등 추격 주의" not in quality_flags
        and "5일 12% 이상 급등 추격 제한" not in quality_flags
        and "5일 5~12% 추격 주의" not in quality_flags
    )
    return adjusted


# ----------------------------- Gemini 최종 해석 -----------------------------
def gemini_rank_and_commentary(candidates: List[Dict[str, Any]], max_picks: int) -> Tuple[List[str], Dict[str, Tuple[List[str], List[str]]]]:
    if not candidates:
        return [], {}
    blocks = []
    valid_codes = {x["code"] for x in candidates}
    for x in candidates:
        code, name = x["code"], x["name"]
        score, metrics, news_info = x["score"], x["metrics"], x["news_info"]
        news_titles = " / ".join(f"{d} {s} {t}" for d, s, t in x.get("news_items", [])[:4]) or "최근 뉴스 특이사항 없음"
        blocks.append(
            f"{code}|{name}|총점 {score['total_score']:.1f}|유동성 {score['liquidity_score']:.1f}|"
            f"모멘텀 {score['momentum_score']:.1f}|뉴스 {score['news_score']:.1f}|리스크 {score['risk_score']:.1f}|"
            f"1일 {safe_float(metrics.get('ret_1d_pct'), 0):+.2f}%|5일 {safe_float(metrics.get('ret_5d_pct'), 0):+.2f}%|"
            f"상대강도 {score.get('relative_strength_1d_pct', 0):+.2f}%|거래량비 {safe_float(metrics.get('volume_ratio_5'), 0):.2f}|"
            f"재추천 {score.get('repick_status', 'first_pick')}|과거추천 {score.get('prior_pick_count', 0)}|"
            f"연속실패 {score.get('recent_fail_streak', 0)}|직전수익 {score.get('last_pick_return_pct', '')}|"
            f"테마 {news_info.get('theme_bucket','')}|키워드 {news_info.get('theme_hits','')}|악재 {news_info.get('bad_hits','')}|뉴스 {news_titles}"
        )
    prompt = f"""너는 한국 주식 오버나잇 후보 검증 담당자다.
아래 후보는 이미 정량 점수로 추려진 {len(candidates)}개 종목이다.
이 중 오늘 종가 매수 -> 내일 아침 매도 관점에서 최종 {max_picks}개 이하만 선택해라.

판단 기준:
- 정량 점수는 존중하되, 뉴스 문맥과 테마 지속성을 보정해라.
- AI, HBM, 메모리, 반도체, 데이터센터, 전력기기 관련 급등은 단순 과열로만 보지 말고 주도 테마 지속 가능성을 판단해라.
- 우주항공, 방산, 국방, 전쟁/지정학 이슈도 주도 테마 후보로 판단하되, 전쟁/확전/군사충돌 뉴스는 방산·우주항공·무기체계·수주·수출과 연결되는 경우에만 긍정 모멘텀으로 봐라.
- 단순 지정학 불안만 있고 직접 수혜 연결고리가 약하면 주의사항에 반영해라.
- 1일/5일 급등 종목은 단발 과열인지, 주도 테마 지속인지 구분해라.
- 상대강도 -5%p 미만, 모멘텀 약세, 5일 급등 후 상대강도 둔화는 제외 우선으로 봐라.
- 반대로 주도 테마 안에서 5일 수익률 -10~0% 눌림 후 상대강도가 회복되는 후보는 긍정적으로 봐라.
- 재추천 이력은 중요하게 반영해라. 첫 추천은 중립, 직전 실패 후 재추천은 보수적으로, 2회 이상 연속 실패는 강한 회복 신호가 없으면 제외 우선으로 봐라.
- 성공 후 재추천도 무조건 긍정으로 보지 마라. 오버나잇에서는 이미 한 번 튄 종목의 다음날 힘이 약해질 수 있다.
- 5일 상승률 5% 이상은 무조건 좋은 신호가 아니다. 상대강도, 거래량, 당일 흐름이 강하지 않으면 추격 위험으로 봐라.
- 금융/통신/정유 업종은 AI라는 단어만으로 AI/메모리 핵심 테마로 분류하지 마라. 실제 반도체, 부품, 장비, 전력, 데이터센터 연관성이 필요하다.
- 코스피 지수가 전날 급등했는지 급락했는지 확인해라. 전날 코스피 급등 후에는 되돌림 위험, 전날 코스피 급락 후에는 기술적 반등 가능성을 고려하되, 개별 종목의 상대강도와 거래량이 확인될 때만 긍정적으로 봐라.
- 악재 키워드가 있거나 뉴스 근거가 빈약하면 제외하거나 주의사항에 강하게 반영해라.

출력 규칙:
- 후보 목록의 종목코드만 사용.
- 각 줄은 정확히 아래 형식만 사용.
- 선택 종목은 Y, 제외 종목은 N.
- 이유와 주의는 각각 2~5개 항목, 항목 구분은 ;; 사용.
- 다른 설명, 번호, 마크다운 금지.

형식:
종목코드@@Y/N@@이유1;;이유2;;이유3@@주의1;;주의2;;주의3

[후보]
{chr(10).join(blocks)}
"""
    try:
        resp = gemini_generate(prompt)
        text = resp.text or ""
    except Exception as e:
        print("Gemini 최종 해석 실패:", e)
        return [], {}
    selected_codes, commentary = [], {}
    for line in text.splitlines():
        line = line.strip().strip("`").lstrip("-* ").strip()
        if "@@" not in line:
            continue
        parts = line.split("@@")
        if len(parts) < 4:
            continue
        code = parts[0].strip()
        code = code.zfill(6) if code.isdigit() else code
        if code not in valid_codes:
            continue
        yn = parts[1].strip().upper()
        reasons = [x.strip() for x in parts[2].split(";;") if x.strip()] or ["정량 점수와 뉴스 모멘텀 확인"]
        risks = [x.strip() for x in parts[3].split(";;") if x.strip()] or ["단기 변동성 주의"]
        commentary[code] = (reasons[:5], risks[:5])
        if yn == "Y" and code not in selected_codes:
            selected_codes.append(code)
    return selected_codes[:max_picks], commentary


def fallback_commentary(item: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    news_info, score, metrics = item.get("news_info", {}), item.get("score", {}), item.get("metrics", {})
    reasons = []
    for d, s, t in item.get("news_items", [])[:3]:
        tag = "·".join(x for x in (d, s) if x)
        reasons.append((f"({tag}) " if tag else "") + t[:42])
    if news_info.get("theme_bucket"):
        reasons.append(f"{news_info.get('theme_bucket')} 테마 확인")
    reasons.append(f"후보점수 {score.get('total_score', 0):.1f}점")
    reasons.append(f"상대강도 {score.get('relative_strength_1d_pct', 0):+.2f}%")
    risks = []
    if score.get("quality_flags"):
        risks.append("품질 플래그: " + ", ".join(score.get("quality_flags")[:3]))
    if news_info.get("bad_hits"):
        risks.append(f"악재 키워드 확인: {news_info.get('bad_hits')}")
    if news_info.get("has_geo_risk") and not news_info.get("geo_benefit_theme"):
        risks.append("지정학 리스크 단독 반영 주의")
    if safe_float(metrics.get("ret_5d_pct"), 0) > 35:
        risks.append("단기 급등 후 차익실현 가능성")
    risks.append("오버나잇 변동성 주의")
    return dedupe(reasons)[:5], dedupe(risks)[:5]


# ----------------------------- 채점 / 성적 -----------------------------
def overnight_return(ticker: str, pick_date: dt.date):
    try:
        start = (pick_date - dt.timedelta(days=12)).strftime("%Y-%m-%d")
        end = now_kst().date().strftime("%Y-%m-%d")
        df = fdr.DataReader(ticker, start, end)
        if df.empty:
            return None
        idx = [pd.to_datetime(x).date() for x in df.index]
        if pick_date not in idx:
            return None
        pos = idx.index(pick_date)
        if pos + 1 >= len(df):
            return None
        buy = float(df["Close"].iloc[pos])
        nxt = df.iloc[pos + 1]
        sell = float(nxt["Open"]) if "Open" in df.columns and not pd.isna(nxt["Open"]) else float(nxt["Close"])
        if buy <= 0:
            return None
        return buy, sell, (sell - buy) / buy * 100
    except Exception as e:
        print("채점 실패", ticker, e)
        return None


def read_records(ws) -> List[Tuple[int, Dict[str, Any]]]:
    values = ws.get_all_values()
    out = []
    for i, row in enumerate(values[1:], start=2):
        rec = {h: (row[j] if j < len(row) else "") for j, h in enumerate(HEADERS)}
        out.append((i, rec))
    return out


def score_matured(ws):
    for rownum, row in read_records(ws):
        if str(row.get("scored")).upper() in ("TRUE", "1"):
            continue
        ticker = str(row.get("ticker", "")).zfill(6)
        pdate_str = str(row.get("pick_date", ""))
        if not ticker or not pdate_str:
            continue
        try:
            pdate = pd.to_datetime(pdate_str).date()
        except Exception:
            continue
        r = overnight_return(ticker, pdate)
        if r is None:
            continue
        buy, sell, ret = r
        kr = overnight_return("KS11", pdate)
        kpct = round(kr[2], 2) if kr else ""
        hit = "TRUE" if ret >= TARGET_PCT else "FALSE"
        ws.batch_update([{
            "range": f"G{rownum}:L{rownum}",
            "values": [[round(buy, 1), round(sell, 1), round(ret, 2), kpct, hit, "TRUE"]],
        }])
        time.sleep(0.5)


def track_record(ws) -> str:
    rows = [rec for _, rec in read_records(ws)]
    scored = [r for r in rows if str(r.get("scored")).upper() in ("TRUE", "1") and r.get("overnight_pct") not in ("", None)]
    if not scored:
        return "📊 누적 성적: 아직 채점된 추천이 없습니다."
    rets = [float(r["overnight_pct"]) for r in scored]
    n = len(rets)
    hr = sum(1 for r in scored if str(r.get("hit")).upper() == "TRUE") / n * 100
    avg = sum(rets) / n
    kos = [float(r["kospi_pct"]) for r in scored if r.get("kospi_pct") not in ("", None)]
    avg_k = sum(kos) / len(kos) if kos else 0.0
    return (f"📊 누적 성적 (추천 {n}건)\n"
            f"- 적중률(+{TARGET_PCT:.0f}%↑): {hr:.0f}%  /  평균: {avg:+.2f}%\n"
            f"- 코스피 평균 {avg_k:+.2f}% 대비 초과 {avg - avg_k:+.2f}%p")


def record_picks(ws, recorded: List[Dict[str, Any]]):
    today = now_kst().date().strftime("%Y-%m-%d")
    existing = set()
    for _, rec in read_records(ws):
        if str(rec.get("pick_date")) == today and str(rec.get("ticker")):
            existing.add(str(rec.get("ticker")).zfill(6))
    new_rows = []
    for item in recorded:
        code = item["code"]
        if code in existing:
            print("이미 기록된 종목 스킵:", code)
            continue
        row_map = {
            "pick_date": today, "ticker": code, "name": item.get("name", code),
            "rationale": item.get("reason", ""), "risk": item.get("risk", ""),
            "ref_price_pick": round(item["price"], 1) if item.get("price") else "",
            "buy_close": "", "sell_open": "", "overnight_pct": "", "kospi_pct": "", "hit": "", "scored": "FALSE",
            **{k: item.get(k, "") for k in HEADERS[12:]}
        }
        new_rows.append([row_map.get(h, "") for h in HEADERS])
    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")


def kospi_regime_from_metrics(kospi_metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    v2.14: KOSPI 시장 레짐 판별.
    - 전날 급등: 다음날 되돌림/차익실현 위험
    - 전날 급락: 다음날 기술적 반등 가능성
    - 단, 단순 반대로 베팅하지 않고 개별 종목의 상대강도/거래량과 함께 사용
    """
    km = kospi_metrics or {}
    k1 = safe_float(km.get("ret_1d_pct"), 0) or 0
    k5 = safe_float(km.get("ret_5d_pct"), 0) or 0
    kvol = safe_float(km.get("volatility_5d_pct"), 0) or 0

    flags = []
    regime = "normal"
    action = "neutral"
    penalty = 0.0
    rebound_bias = 0.0

    if k1 >= KOSPI_EXTREME_SURGE_RET_1D:
        regime = "extreme_surge_pullback_risk"
        action = "defensive"
        flags.append("코스피 전일 2% 이상 급등")
        penalty += 4.0
    elif k1 >= KOSPI_SURGE_RET_1D:
        regime = "surge_pullback_risk"
        action = "defensive"
        flags.append("코스피 전일 급등 후 되돌림 주의")
        penalty += 2.5

    if k1 <= KOSPI_EXTREME_DROP_RET_1D:
        regime = "extreme_drop_rebound_watch"
        action = "rebound_watch"
        flags.append("코스피 전일 2% 이상 급락")
        rebound_bias += 3.0
        penalty += 1.0
    elif k1 <= KOSPI_DROP_RET_1D:
        regime = "drop_rebound_watch"
        action = "rebound_watch"
        flags.append("코스피 전일 급락 후 반등 가능성")
        rebound_bias += 2.0

    if k5 >= KOSPI_5D_SURGE:
        flags.append("코스피 5일 급등 부담")
        penalty += 1.5
        if action == "neutral":
            action = "defensive"
            regime = "five_day_surge_burden"

    if k5 <= KOSPI_5D_DROP:
        flags.append("코스피 5일 낙폭 과대")
        rebound_bias += 1.0
        if action == "neutral":
            action = "rebound_watch"
            regime = "five_day_drop_rebound_watch"

    if kvol >= KOSPI_VOLATILITY_WATCH:
        flags.append("코스피 변동성 확대")
        penalty += 1.0

    return {
        "kospi_regime": regime,
        "kospi_action": action,
        "kospi_flags": flags,
        "kospi_penalty": round(penalty, 2),
        "kospi_rebound_bias": round(rebound_bias, 2),
        "kospi_ret_1d_pct": round(k1, 2),
        "kospi_ret_5d_pct": round(k5, 2),
        "kospi_volatility_5d_pct": round(kvol, 2),
    }


def apply_kospi_regime_adjustment(metrics: Dict[str, Any], score: Dict[str, Any], kospi_regime: Dict[str, Any]) -> Dict[str, Any]:
    """
    v2.14: 시장 전체 휩쏘/되돌림 레짐을 개별 후보 점수에 반영.
    - 코스피 급등 다음날: 5일 급등 추격/약한 상대강도 후보를 더 보수적으로
    - 코스피 급락 다음날: 상대강도와 거래량이 살아 있는 눌림목은 반등 후보로 소폭 가점
    """
    kr = kospi_regime or {}
    action = str(kr.get("kospi_action", "neutral"))

    adjusted = dict(score)
    flags = list(adjusted.get("quality_flags", []) or [])
    gate = adjusted.get("quality_gate", "pass") or "pass"

    liquidity_score = safe_float(adjusted.get("liquidity_score"), 0) or 0
    momentum_score = safe_float(adjusted.get("momentum_score"), 0) or 0
    news_score = safe_float(adjusted.get("news_score"), 0) or 0
    risk_score = safe_float(adjusted.get("risk_score"), 0) or 0
    history_score = safe_float(adjusted.get("history_score"), 7.5) or 7.5

    ret_1d = safe_float(metrics.get("ret_1d_pct"), 0) or 0
    ret_5d = safe_float(metrics.get("ret_5d_pct"), 0) or 0
    rel = safe_float(adjusted.get("relative_strength_1d_pct"), 0) or 0
    volume_ratio = safe_float(metrics.get("volume_ratio_5"), 0) or 0

    kospi_flags = list(kr.get("kospi_flags", []) or [])
    if action != "neutral":
        for f in kospi_flags:
            if f not in flags:
                flags.append(f)

    penalty = safe_float(kr.get("kospi_penalty"), 0) or 0
    rebound_bias = safe_float(kr.get("kospi_rebound_bias"), 0) or 0

    if action == "defensive":
        market_resistant = (
            rel >= 3
            and ret_1d >= 0
            and volume_ratio >= 1.0
            and ret_5d <= 5
        )
        chase_risk = (ret_5d >= 5 or ret_1d >= 4)

        if market_resistant and not chase_risk:
            flags.append("코스피 급등 후에도 상대강도 유지")
            risk_score -= min(1.0, penalty * 0.3)
        else:
            flags.append("코스피 급등 후 되돌림 방어")
            momentum_score -= penalty * 0.7
            risk_score -= penalty * 0.9
            news_score = min(news_score, 22 if penalty < 4 else 19)
            gate = "watch" if gate != "reject" else gate

            if chase_risk and rel < 3:
                flags.append("시장 급등 후 개별 추격 위험")
                momentum_score -= 2
                risk_score -= 2
                news_score = min(news_score, 18)

            if ret_5d >= 12 and rel < 3:
                flags.append("시장 되돌림 구간 5일 급등 추격 제외")
                gate = "reject"

    elif action == "rebound_watch":
        rebound_candidate = (
            rel >= 2
            and volume_ratio >= 0.9
            and -12 <= ret_5d <= 3
        )
        oversold_rebound = (
            -12 <= ret_5d <= 0
            and rel >= 0
            and volume_ratio >= 1.0
        )
        weak_in_selloff = (
            rel < -3
            or (ret_1d < 0 and volume_ratio < 0.8)
        )

        if rebound_candidate or oversold_rebound:
            flags.append("코스피 급락 후 반등 후보")
            momentum_score += min(2.5, rebound_bias)
            risk_score += 0.5
            news_score = min(news_score + 0.5, 24)
        elif weak_in_selloff:
            flags.append("코스피 급락에도 상대약세")
            momentum_score -= 2
            risk_score -= 3
            news_score = min(news_score, 20)
            gate = "watch" if gate != "reject" else gate
        else:
            flags.append("코스피 급락 후 반등 확인 부족")
            risk_score -= 1
            news_score = min(news_score, 22)

    momentum_score = clamp(momentum_score, 0, 25)
    news_score = clamp(news_score, 0, 25)
    risk_score = clamp(risk_score, 0, 15)
    history_score = clamp(history_score, 4, 9)

    total_score = liquidity_score + momentum_score + news_score + risk_score + history_score
    if gate == "reject":
        total_score = min(total_score, 58)
    elif gate == "watch":
        total_score = min(total_score, 78)

    adjusted.update({
        "total_score": round(total_score, 2),
        "liquidity_score": round(liquidity_score, 2),
        "momentum_score": round(momentum_score, 2),
        "news_score": round(news_score, 2),
        "risk_score": round(risk_score, 2),
        "history_score": round(history_score, 2),
        "quality_gate": gate,
        "quality_flags": flags,
        "kospi_regime": kr.get("kospi_regime", "normal"),
        "kospi_flags": " / ".join(kospi_flags),
        "kospi_ret_1d_pct": kr.get("kospi_ret_1d_pct", ""),
        "kospi_ret_5d_pct": kr.get("kospi_ret_5d_pct", ""),
        "kospi_volatility_5d_pct": kr.get("kospi_volatility_5d_pct", ""),
        "kospi_regime_action": action,
    })

    detail = adjusted.get("score_detail", "")
    adjusted["score_detail"] = (
        f"kospi_regime={kr.get('kospi_regime','normal')}, action={action}, "
        f"kospi_ret1d={kr.get('kospi_ret_1d_pct','')}, kospi_ret5d={kr.get('kospi_ret_5d_pct','')}, "
        f"kospi_flags={';'.join(kospi_flags)} | {detail}"
    )
    return adjusted



def apply_burst_score_adjustment(metrics: Dict[str, Any], news_info: Dict[str, Any], score: Dict[str, Any]) -> Dict[str, Any]:
    """
    v2.15: +3% 오버나잇 성공 가능성을 별도로 보는 burst_score.
    기존 total_score는 방향성/안정성을 어느 정도 설명하지만, +3% hit를 직접 설명하지 못했으므로
    상대강도, 거래량비, 5일 위치, 테마, 코스피 레짐을 조합해 final_score를 재계산한다.
    """
    adjusted = dict(score)

    stability_score = safe_float(score.get("total_score"), 0) or 0
    gate = score.get("quality_gate", "pass") or "pass"
    quality_flags = list(score.get("quality_flags", []) or [])
    burst_flags = []

    ret_1d = safe_float(metrics.get("ret_1d_pct"), 0) or 0
    ret_5d = safe_float(metrics.get("ret_5d_pct"), 0) or 0
    rel = safe_float(score.get("relative_strength_1d_pct"), 0) or 0
    volume_ratio = safe_float(metrics.get("volume_ratio_5"), 0) or 0
    volatility = safe_float(metrics.get("volatility_5d_pct"), 0) or 0

    is_ai = bool(news_info.get("is_ai_memory_theme"))
    is_defense = bool(news_info.get("is_defense_theme"))
    is_space = bool(news_info.get("is_space_theme"))
    is_tesla = bool(news_info.get("is_tesla_space_theme"))
    geo_benefit = bool(news_info.get("geo_benefit_theme"))
    has_geo_risk = bool(news_info.get("has_geo_risk")) and not geo_benefit
    theme_bucket = str(news_info.get("theme_bucket", ""))

    kospi_action = str(score.get("kospi_regime_action", "neutral") or "neutral")
    kospi_ret_1d = safe_float(score.get("kospi_ret_1d_pct"), 0) or 0
    kospi_ret_5d = safe_float(score.get("kospi_ret_5d_pct"), 0) or 0

    # 1) 기본 burst score
    burst_score = 35.0

    # 2) 상대강도: 분석상 가장 유의미했던 변수
    if rel >= 8:
        burst_score += 22
        burst_flags.append("초강한 상대강도")
    elif rel >= 5:
        burst_score += 17
        burst_flags.append("강한 상대강도")
    elif rel >= 3:
        burst_score += 11
        burst_flags.append("상대강도 우위")
    elif rel >= 1.5:
        burst_score += 5
    elif rel < -5:
        burst_score -= 22
        burst_flags.append("상대강도 급약세")
    elif rel < -3:
        burst_score -= 14
        burst_flags.append("상대강도 약세")
    elif rel < 0:
        burst_score -= 7

    # 3) 거래량비: 3% 이상 확률을 높이는 촉매로 사용
    if volume_ratio >= 2.0:
        burst_score += 15
        burst_flags.append("거래량 강확대")
    elif volume_ratio >= 1.5:
        burst_score += 11
        burst_flags.append("거래량 확대")
    elif volume_ratio >= 1.2:
        burst_score += 6
    elif volume_ratio < 0.7:
        burst_score -= 9
        burst_flags.append("거래량 부족")

    # 4) 5일 위치: 급등 추격보다 눌림/완만한 상승을 우대
    if -10 <= ret_5d <= 0:
        burst_score += 14
        burst_flags.append("눌림 후 반등 구간")
    elif 0 < ret_5d <= 3:
        burst_score += 11
        burst_flags.append("완만한 상승 구간")
    elif 3 < ret_5d <= 5:
        burst_score += 3
    elif 5 < ret_5d < 12:
        burst_score -= 10
        burst_flags.append("5일 5~12% 추격 부담")
    elif ret_5d >= 12:
        burst_score -= 22
        burst_flags.append("5일 12% 이상 추격 부담")
    elif ret_5d < -15:
        burst_score -= 7
        burst_flags.append("5일 낙폭 과대 후 확인 필요")

    # 5) 당일 흐름
    if 0 <= ret_1d <= 5:
        burst_score += 5
    elif ret_1d < 0 and rel >= 3:
        burst_score += 2
        burst_flags.append("지수 대비 버팀")
    elif ret_1d <= -5:
        burst_score -= 10
        burst_flags.append("당일 하락 과다")
    elif ret_1d >= 8:
        burst_score -= 6
        burst_flags.append("당일 급등 추격")

    # 6) 테마별 burst 보정
    if geo_benefit:
        burst_score += 8
        burst_flags.append("지정학 수혜 테마")
    if is_space:
        burst_score += 7
        burst_flags.append("우주항공 테마")
    if is_tesla:
        burst_score += 6
        burst_flags.append("테슬라/스페이스X 테마")
    if is_defense:
        burst_score += 5
        burst_flags.append("방산 테마")
    if is_ai:
        burst_score += 3
        burst_flags.append("AI/메모리 테마")
    if "비테마" in theme_bucket:
        burst_score -= 12
        burst_flags.append("비테마 감점")
    if "일반테마" in theme_bucket:
        burst_score -= 6
        burst_flags.append("일반테마 감점")
    if has_geo_risk:
        burst_score -= 9
        burst_flags.append("지정학 리스크 단독")

    # 7) 코스피 레짐 세분화
    if kospi_action == "defensive":
        # 코스피 급등 후 되돌림 구간에서는 5일 급등/약한 상대강도 후보를 더 보수적으로.
        if ret_5d >= 5 or rel < 3:
            burst_score -= 8
            burst_flags.append("코스피 급등 후 방어")
        elif rel >= 5 and -10 <= ret_5d <= 3 and volume_ratio >= 1.0:
            burst_score += 3
            burst_flags.append("방어장 상대강도 유지")

    elif kospi_action == "rebound_watch":
        # 모든 rebound_watch가 좋은 게 아니라, 진짜 급락 후 강한 개별 반등 후보만 가점.
        qualified_rebound = (
            kospi_ret_1d <= -2.0
            and kospi_ret_5d <= -4.0
            and rel >= 3
            and volume_ratio >= 0.9
            and -12 <= ret_5d <= 3
        )
        weak_rebound = (
            rel < 0
            or ret_5d > 5
            or volume_ratio < 0.8
        )

        if qualified_rebound:
            burst_score += 10
            burst_flags.append("코스피 급락 후 강한 반등 후보")
        elif weak_rebound:
            burst_score -= 8
            burst_flags.append("코스피 반등장 부적합")
        else:
            burst_score -= 2
            burst_flags.append("코스피 반등 확인 대기")

    # 8) 변동성
    if volatility >= 10:
        burst_score -= 5
        burst_flags.append("개별 변동성 과다")
    elif 3 <= volatility <= 8:
        burst_score += 2

    # 9) 재추천 상태 보정
    repick_status = str(score.get("repick_status", "first_pick") or "first_pick")
    if repick_status == "repick_after_success":
        burst_score -= 8
        burst_flags.append("성공 후 재추천 추격 주의")
    elif repick_status in ("repeated_fail_watch", "repeated_fail_recovery_watch"):
        burst_score -= 7
        burst_flags.append("반복 실패 이력")
    elif repick_status == "repick_after_fail":
        if rel >= 3 and -10 <= ret_5d <= 3 and volume_ratio >= 0.9:
            burst_score += 2
            burst_flags.append("실패 후 회복 재도전")
        else:
            burst_score -= 5
            burst_flags.append("실패 후 재추천 감점")

    # 10) quality gate와 결합
    burst_score = clamp(burst_score, 0, 100)
    final_score = stability_score * STABILITY_WEIGHT + burst_score * BURST_WEIGHT

    if gate == "reject":
        final_score = min(final_score, BURST_REJECT_CAP)
    elif gate == "watch":
        final_score = min(final_score, BURST_WATCH_CAP)

    adjusted.update({
        "stability_score": round(stability_score, 2),
        "burst_score": round(burst_score, 2),
        "final_score": round(final_score, 2),
        "total_score": round(final_score, 2),
        "burst_flags": " / ".join(dedupe(burst_flags)[:8]),
    })

    detail = adjusted.get("score_detail", "")
    adjusted["score_detail"] = (
        f"final={final_score:.1f}, stability={stability_score:.1f}, burst={burst_score:.1f}, "
        f"burst_flags={';'.join(dedupe(burst_flags))} | {detail}"
    )
    return adjusted



# ----------------------------- 실행 흐름 -----------------------------
def run_pick():
    if not is_trading_day():
        print("오늘 휴장. 스킵.")
        return
    ws = get_sheet()
    try:
        score_matured(ws)
    except Exception as e:
        print("채점 단계 오류:", e)
    existing_rows = [rec for _, rec in read_records(ws)]
    universe = get_universe()
    print(f"유니버스: {len(universe)}개 / 1단계 평가: {min(EVAL_POOL_SIZE, len(universe))}개")
    kospi_metrics = get_recent_metrics("KS11")
    kospi_regime = kospi_regime_from_metrics(kospi_metrics)
    kospi_ret_1d = safe_float(kospi_metrics.get("ret_1d_pct"), 0) or 0
    kospi_ret_5d = safe_float(kospi_metrics.get("ret_5d_pct"), 0) or 0
    kospi_vol_5d = safe_float(kospi_metrics.get("volatility_5d_pct"), 0) or 0
    print("KOSPI regime:", kospi_regime)
    stage1_pool = []
    for idx, (code, name) in enumerate(universe[:EVAL_POOL_SIZE], start=1):
        try:
            metrics = get_recent_metrics(code)
            metrics["kospi_ret_1d_pct"] = kospi_ret_1d
            metrics["kospi_ret_5d_pct"] = kospi_ret_5d
            metrics["kospi_volatility_5d_pct"] = kospi_vol_5d
            s1 = score_stage1(metrics)
            stage1_pool.append({"code": code, "name": name, "metrics": metrics, "stage1": s1})
            if idx % 25 == 0:
                print(f"1단계 평가 진행: {idx}개")
        except Exception as e:
            print("1단계 평가 실패:", code, name, e)
        time.sleep(0.03)
    stage1_pool = sorted(stage1_pool, key=lambda x: x["stage1"]["stage1_score"], reverse=True)
    news_targets = stage1_pool[:NEWS_POOL_SIZE]
    print(f"2단계 뉴스 평가 대상: {len(news_targets)}개")
    stage2_pool = []
    for idx, item in enumerate(news_targets, start=1):
        code, name = item["code"], item["name"]
        try:
            news_items = get_stock_news(name, limit=3)
            news_info = analyze_news_items(news_items)

            # v2.13: AI/메모리 테마 오분류 방지
            if news_info.get("is_ai_memory_theme") and not likely_ai_memory_core(name, news_items, news_info):
                news_info["is_ai_memory_theme"] = False
                news_info["ai_memory_hits"] = ""
                news_info["theme_bucket"] = str(news_info.get("theme_bucket", "")).replace("AI/메모리", "").strip(", /")
                news_info["theme_bucket"] = news_info["theme_bucket"] or "일반/기타"
                news_info["theme_hits"] = str(news_info.get("theme_hits", "")).replace("AI", "").replace("반도체", "").strip(", /")

            history_score = get_history_score(existing_rows, code)
            repick_info = analyze_repick_history(existing_rows, code)
            score = score_candidate(item["metrics"], news_info, history_score=history_score, stage1_score=item["stage1"]["stage1_score"])
            score = apply_v28_quality_adjustments(item["metrics"], news_info, score)
            score = apply_repick_adjustments(item["metrics"], score, repick_info)
            score = apply_kospi_regime_adjustment(item["metrics"], score, kospi_regime)
            score = apply_burst_score_adjustment(item["metrics"], news_info, score)
            if news_info.get("bad_hit_count", 0) >= 2:
                print("악재 키워드 다수로 제외:", code, name, news_info.get("bad_hits"))
                continue
            if score.get("quality_gate") == "reject":
                print("품질 게이트 제외:", code, name, score.get("quality_flags"))
                continue
            item.update({"news_items": news_items, "news_info": news_info, "history_score": history_score, "repick_info": repick_info, "score": score})
            stage2_pool.append(item)
            if idx % 15 == 0:
                print(f"2단계 뉴스 평가 진행: {idx}개")
        except Exception as e:
            print("2단계 뉴스 평가 실패:", code, name, e)
        time.sleep(0.08)
    stage2_pool = sorted(stage2_pool, key=lambda x: x["score"]["total_score"], reverse=True)
    gemini_targets = stage2_pool[:GEMINI_POOL_SIZE]
    print(f"3단계 Gemini 대상: {len(gemini_targets)}개")
    refreshed = []
    for item in gemini_targets:
        code = item["code"]
        quote = get_price_quote(code)
        price, source = quote["price"], quote["source"]
        metrics = get_recent_metrics(code, price)
        metrics["kospi_ret_1d_pct"] = kospi_ret_1d
        metrics["kospi_ret_5d_pct"] = kospi_ret_5d
        metrics["kospi_volatility_5d_pct"] = kospi_vol_5d
        score = score_candidate(metrics, item["news_info"], history_score=item["history_score"], stage1_score=item["stage1"]["stage1_score"])
        score = apply_v28_quality_adjustments(metrics, item["news_info"], score)
        score = apply_repick_adjustments(metrics, score, item.get("repick_info", {}))
        score = apply_kospi_regime_adjustment(metrics, score, kospi_regime)
        score = apply_burst_score_adjustment(metrics, item["news_info"], score)
        if score.get("quality_gate") == "reject":
            print("가격 갱신 후 품질 게이트 제외:", code, item.get("name"), score.get("quality_flags"))
            continue
        item.update({"price": price, "price_source": source, "metrics": metrics, "score": score})
        refreshed.append(item)
        time.sleep(0.08)
    refreshed = sorted(refreshed, key=lambda x: x["score"]["total_score"], reverse=True)
    selected_codes, commentary = gemini_rank_and_commentary(refreshed, MAX_PICKS)
    by_code = {x["code"]: x for x in refreshed}
    selected = []
    for code in selected_codes:
        if code in by_code and code not in [x["code"] for x in selected]:
            selected.append(by_code[code])
    for item in refreshed:
        if len(selected) >= MAX_PICKS:
            break
        if item["code"] not in [x["code"] for x in selected]:
            selected.append(item)
    selected = selected[:MAX_PICKS]
    display, recorded = [], []
    for rank, item in enumerate(selected, start=1):
        code, name = item["code"], item["name"]
        price, price_source = item.get("price"), item.get("price_source", "fail")
        metrics, news_info, score = item["metrics"], item["news_info"], item["score"]
        reasons, risks = commentary.get(code, fallback_commentary(item))
        reasons = dedupe(reasons)[:6] or ["-"]
        risks = dedupe(risks)[:6] or ["-"]
        display.append({
            "code": code, "name": name, "price": price, "price_source": price_source,
            "ph": price_history(code), "reasons": reasons, "risks": risks,
            "rank": rank, "score": score, "metrics": metrics, "news_info": news_info,
            "repick_status": score.get("repick_status", "first_pick"),
        })
        recorded.append({
            "code": code, "name": name, "price": price, "reason": " / ".join(reasons), "risk": " / ".join(risks),
            "pick_rank": rank, "stage1_score": item["stage1"]["stage1_score"],
            "total_score": score["total_score"], "liquidity_score": score["liquidity_score"],
            "momentum_score": score["momentum_score"], "news_score": score["news_score"],
            "risk_score": score["risk_score"], "history_score": score["history_score"],
            "price_source": price_source, "prev_close": metrics.get("prev_close", ""), "week_close": metrics.get("week_close", ""),
            "ret_1d_pct": round(safe_float(metrics.get("ret_1d_pct"), 0), 2),
            "ret_5d_pct": round(safe_float(metrics.get("ret_5d_pct"), 0), 2),
            "kospi_ret_1d_pct": round(kospi_ret_1d, 2), "relative_strength_1d_pct": score.get("relative_strength_1d_pct", ""),
            "volume": metrics.get("volume", ""), "avg_volume_5": metrics.get("avg_volume_5", ""),
            "volume_ratio_5": round(safe_float(metrics.get("volume_ratio_5"), 0), 2),
            "trading_value": metrics.get("trading_value", ""),
            "volatility_5d_pct": round(safe_float(metrics.get("volatility_5d_pct"), 0), 2),
            "news_count": news_info.get("news_count", ""), "theme_hits": news_info.get("theme_hits", ""),
            "ai_memory_hits": news_info.get("ai_memory_hits", ""), "defense_hits": news_info.get("defense_hits", ""),
            "space_hits": news_info.get("space_hits", ""), "tesla_space_hits": news_info.get("tesla_space_hits", ""),
            "geo_hits": news_info.get("geo_hits", ""), "bad_hits": news_info.get("bad_hits", ""),
            "theme_bucket": news_info.get("theme_bucket", ""), "score_detail": score.get("score_detail", ""),
            "bot_version": BOT_VERSION,
            "score_version": SCORE_VERSION,
            "strategy_profile": STRATEGY_PROFILE,
            "quality_gate": score.get("quality_gate", ""),
            "quality_flags": " / ".join(score.get("quality_flags", [])) if isinstance(score.get("quality_flags", []), list) else str(score.get("quality_flags", "")),
            "prior_pick_count": score.get("prior_pick_count", 0),
            "prior_hit_count": score.get("prior_hit_count", 0),
            "prior_fail_count": score.get("prior_fail_count", 0),
            "recent_fail_streak": score.get("recent_fail_streak", 0),
            "last_pick_date": score.get("last_pick_date", ""),
            "last_pick_return_pct": score.get("last_pick_return_pct", ""),
            "days_since_last_pick": score.get("days_since_last_pick", ""),
            "repick_status": score.get("repick_status", "first_pick"),
            "kospi_regime": score.get("kospi_regime", ""),
            "kospi_flags": score.get("kospi_flags", ""),
            "kospi_ret_1d_pct": score.get("kospi_ret_1d_pct", ""),
            "kospi_ret_5d_pct": score.get("kospi_ret_5d_pct", ""),
            "kospi_volatility_5d_pct": score.get("kospi_volatility_5d_pct", ""),
            "kospi_regime_action": score.get("kospi_regime_action", ""),
            "stability_score": score.get("stability_score", ""),
            "burst_score": score.get("burst_score", ""),
            "final_score": score.get("final_score", score.get("total_score", "")),
            "burst_flags": score.get("burst_flags", ""),
        })
    record_picks(ws, recorded)
    head = now_kst().strftime("%m/%d %H:%M")
    SEP = "━━━━━━━━━━━━"
    parts = [
        f"🚀 {head} · 오늘의 오버나잇 후보 {len(display)}개",
        "🔎 150 정량 → 60 뉴스 → 20 검증 → 최종 선별",
    ]
    if not display:
        parts.append("후보를 뽑지 못했습니다. (뉴스/데이터 확인 필요)")
    for item in display:
        code, name, price = item["code"], item["name"], item["price"]
        pstr = fmt_won(price) if price else "조회 실패"
        score, metrics, news_info = item["score"], item["metrics"], item["news_info"]
        b = [
            f"📈 {item['rank']}. {name} ({code})",
            f"💰 {pstr} · {price_source_label(item['price_source'])}",
            f"🧮 {score['total_score']:.1f}점 · 🧨 폭발 {safe_float(score.get('burst_score'), 0):.1f} · 🏷️ {short_theme(news_info.get('theme_bucket', '-'))}",
        ]
        if score.get("repick_status") and score.get("repick_status") != "first_pick":
            b.append(
                f"🔁 재추천: {score.get('repick_status')} · "
                f"과거 {score.get('prior_pick_count', 0)}회 / 연속실패 {score.get('recent_fail_streak', 0)}회"
            )
        if score.get("kospi_regime") and score.get("kospi_regime") != "normal":
            b.append(
                f"🌊 코스피: {score.get('kospi_regime_action', '')} · "
                f"1D {safe_float(score.get('kospi_ret_1d_pct'), 0):+.2f}% / "
                f"5D {safe_float(score.get('kospi_ret_5d_pct'), 0):+.2f}%"
            )

        b += [
            f"📊 1D {safe_float(metrics.get('ret_1d_pct'), 0):+.2f}% · "
            f"5D {safe_float(metrics.get('ret_5d_pct'), 0):+.2f}% · "
            f"RS {score.get('relative_strength_1d_pct', 0):+.2f}%",
        ]
        if item["ph"]:
            y_lbl, y_close, lw_lbl, lw_close, m_lbl, m_close = item["ph"]
            b.append(f"📅 어제대비({y_lbl}): {fmt_change(price, y_close)}")
            b.append(f"📆 전주대비({lw_lbl}): {fmt_change(price, lw_close)}")
            b.append(f"🗓️ 전달대비({m_lbl}): {fmt_change(price, m_close)}")

        reasons = item["reasons"][:4]
        risks = item["risks"][:3]
        b += ["", "💡 이유"] + [f"  • {r}" for r in reasons]
        b += ["", "⚠️ 주의"] + [f"  • {r}" for r in risks]
        parts.append("\n".join(b))
    parts.append(track_record(ws))
    parts.append(f"🎯 목표 +{TARGET_PCT:.0f}% · 종가 매수 → 내일 아침 매도 · 판단·책임 본인")
    tg_send(("\n" + SEP + "\n").join(parts))


def run_sell():
    if not is_trading_day():
        print("오늘 휴장. 스킵.")
        return
    ws = get_sheet()
    rows = [rec for _, rec in read_records(ws)]
    dates = sorted({str(r.get("pick_date", "")) for r in rows if r.get("pick_date")})
    if not dates:
        tg_send("기록이 없습니다.")
        return
    last = dates[-1]
    targets = [r for r in rows if str(r.get("pick_date")) == last]
    head = now_kst().strftime("%m/%d %H:%M")
    SEP = "━━━━━━━━━━━━"
    parts = [f"🚀 {head} · 오버나잇 매도 참고 알림", "", f"📌 추천일: {last}"]
    if not targets:
        parts.append("점검할 종목이 없습니다.")
    else:
        for r in targets:
            code = str(r.get("ticker", "")).zfill(6)
            name = str(r.get("name", code))
            quote = get_price_quote(code)
            price, source = quote["price"], quote["source"]
            base = safe_float(r.get("ref_price_pick")) or safe_float(r.get("buy_close"))
            pstr = fmt_won(price) if price else "조회 실패"
            total_score = safe_float(r.get("total_score"))
            theme_bucket = r.get("theme_bucket", "")
            b = [
                f"📈 {name} ({code})",
                f"💰 {pstr} · {price_source_label(source)}",
            ]
            if total_score is not None or theme_bucket:
                score_txt = f"{total_score:.1f}점" if total_score is not None else "점수 없음"
                b.append(f"🧮 전일 {score_txt} · 🏷️ {short_theme(theme_bucket)}")
            if price and base:
                now_ret = pct_change(price, base)
                target_price = base * (1 + TARGET_PCT / 100)
                gap_to_target = pct_change(price, target_price)
                b.append(f"📊 기준대비 {now_ret:+.2f}% · 목표까지 {gap_to_target:+.2f}%")
                b.append(f"📌 기준 {fmt_won(base)} · 목표 {fmt_won(target_price)}")
            reasons = split_saved_text(r.get("rationale")) or ["-"]
            risks = split_saved_text(r.get("risk")) or ["-"]
            b += ["", "💡 이유"] + [f"  • {x}" for x in reasons[:3]]
            b += ["", "⚠️ 주의"] + [f"  • {x}" for x in risks[:3]]
            parts.append("\n".join(b))
            time.sleep(0.1)
    parts.append(track_record(ws))
    parts.append(f"🎯 목표 +{TARGET_PCT:.0f}% · 아침 매도 참고 · 판단·책임 본인")
    tg_send(("\n" + SEP + "\n").join(parts))



def run_score_silent():
    """
    오전 09:30 자동 실행용.
    텔레그램 sell 알림은 보내지 않고, 시트에 전일 추천 결과만 조용히 채점한다.
    """
    ws = get_sheet()
    score_matured(ws)
    print("silent score completed: previous picks scored without Telegram sell alert")


def main():
    # workflow에서 명시적으로 내려준 RUN_MODE를 최우선 사용
    # 14:55 KST = pick, 09:30 KST = score(조용한 채점)
    mode = (os.environ.get("RUN_MODE") or "").strip().lower()
    sched = (os.environ.get("SCHEDULE") or "").strip()

    if not mode:
        if sched == "55 5 * * 1-5":
            mode = "pick"
        elif sched == "30 0 * * 1-5":
            mode = "score"
        else:
            raise RuntimeError(f"RUN_MODE를 판별할 수 없습니다. SCHEDULE={sched!r}")

    if mode not in ("pick", "score", "sell"):
        raise RuntimeError(f"잘못된 RUN_MODE={mode!r}, SCHEDULE={sched!r}")

    try:
        print(f"resolved_mode={mode}, schedule={sched}")
        if mode == "pick":
            run_pick()
        elif mode == "score":
            run_score_silent()
        else:
            # 수동으로 sell을 넣은 경우에만 기존 매도 참고 알림 실행
            run_sell()
    except Exception as e:
        tg_send(
            f"❌ 봇 실행 오류({mode})\n"
            f"schedule={sched}\n"
            f"{e}\n"
            f"{traceback.format_exc()[:3500]}"
        )
        raise


if __name__ == "__main__":
    main()
