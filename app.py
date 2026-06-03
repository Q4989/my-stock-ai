import streamlit as st
import datetime
import feedparser
import pandas as pd
import urllib.parse
import requests
import yfinance as yf
from pykrx import stock
from google import genai

# ==========================================
# 🎨 1. UI 디자인 및 프리미엄 CSS (와이드 모드)
# ==========================================
st.set_page_config(page_title="PRO AI 퀀트 대시보드", page_icon="📈", layout="wide")

st.markdown("""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        font-family: 'Pretendard', sans-serif !important; background-color: #f5f7fa !important;
    }
    .main-header {
        background: linear-gradient(135deg, #0f172a, #1e3a8a, #3b82f6);
        padding: 40px 30px; border-radius: 20px; color: white; text-align: center;
        box-shadow: 0 10px 30px rgba(30, 58, 138, 0.2); margin-bottom: 35px; margin-top: -20px;
    }
    .main-header h1 { color: #ffffff; font-weight: 900; font-size: 38px; margin-bottom: 10px; letter-spacing: -1px; }
    .main-header p { color: #bfdbfe; font-size: 18px; font-weight: 500; margin: 0; }
    .stButton>button { 
        background: linear-gradient(135deg, #2563eb, #1d4ed8) !important; color: white !important; 
        border: none !important; border-radius: 16px !important; font-weight: 800 !important; 
        padding: 20px !important; font-size: 18px !important; box-shadow: 0 8px 20px rgba(37, 99, 235, 0.3) !important;
        transition: all 0.3s ease !important; width: 100% !important;
    }
    .stButton>button:hover { transform: translateY(-4px) !important; box-shadow: 0 12px 25px rgba(37, 99, 235, 0.5) !important; }
    .timestamp-box { 
        background: #1e293b; padding: 14px 25px; border-radius: 12px; font-weight: 800; color: #38bdf8; 
        display: inline-block; margin-bottom: 25px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); font-size: 15px;
    }
    </style>
    <div class="main-header">
        <h1>🚀 PRO AI 퀀트 데이터 융합 대시보드</h1>
        <p>KRX & yfinance 폭포수 방어 로직 기반 글로벌 시계열 트래킹 시스템</p>
    </div>
""", unsafe_allow_html=True)

# ==========================================
# 🔑 2. 제미나이 API 설정
# ==========================================
try:
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
except Exception:
    st.error("🔑 대시보드 설정 창(Secrets)에서 GEMINI_API_KEY를 등록해주세요.")
    st.stop()

# ==========================================
# 📰 3. 구글/네이버 뉴스 마이닝 엔진
# ==========================================
def get_refined_market_news(keyword):
    news_list = []
    try:
        trusted_sites = "+(site:yna.co.kr+OR+site:edaily.co.kr+OR+site:hankyung.co.kr+OR+site:mk.co.kr)"
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(keyword + trusted_sites)}&hl=ko&gl=KR&ceid=KR:ko"
        for entry in feedparser.parse(url).entries[:2]:
            news_list.append(f"[{entry.get('published', '최근')[:16]} / 구글종합] [{entry.title}]({entry.link})")
    except: pass

    try:
        if "NAVER_CLIENT_ID" in st.secrets:
            headers = {"X-Naver-Client-Id": st.secrets["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": st.secrets["NAVER_CLIENT_SECRET"]}
            res = requests.get(f"https://openapi.naver.com/v1/search/news.json?query={urllib.parse.quote(keyword)}&display=4&sort=date", headers=headers, timeout=5)
            if res.status_code == 200:
                for item in res.json().get('items', []):
                    title = item['title'].replace('<b>', '').replace('</b>', '').replace('&quot;', '"')
                    news_list.append(f"[{item.get('pubDate', '실시간')[:16]} / 네이버뉴스] [{title}]({item['link']})")
    except: pass
    return " | ".join(news_list) if news_list else f"[최근 / 시황] {keyword} 분석 유효"

# ==========================================
# 📊 4. 기본 날짜 연산 및 코스피 지표 레이아웃
# ==========================================
now = datetime.datetime.now()
today_str = now.strftime("%Y%m%d")
start_52w_str = (now - datetime.timedelta(weeks=52)).strftime("%Y%m%d")

cal_df = stock.get_market_ohlcv_by_date((now - datetime.timedelta(days=14)).strftime("%Y%m%d"), today_str, "005930")
recent_days = [d.strftime("%Y%m%d") for d in cal_df.index]
latest_closed_day = recent_days[-2] if (now.hour < 16 and recent_days[-1] == today_str) else recent_days[-1]

col_k1, col_k2 = st.columns([1, 2])
with col_k1:
    st.markdown("### 📉 KOSPI 벤치마크")
    try:
        kospi_df = stock.get_index_ohlcv_by_date(start_52w_str, latest_closed_day, "1001")
        if not kospi_df.empty:
            c_kospi = kospi_df['종가'].iloc[-1]
            p_kospi = kospi_df['종가'].iloc[-2]
            st.metric(label=f"코스피 지수 ({latest_closed_day})", value=f"{c_kospi:,.2f}", delta=f"{c_kospi - p_kospi:+.2f}")
            st.metric(label="52주 최고점", value=f"{kospi_df['종가'].max():,.2f}")
    except: st.warning("지수 로드 불가")

with col_k2:
    try:
        if not kospi_df.empty: st.line_chart(kospi_df['종가'], height=200)
    except: pass

# ==========================================
# ⚡ 5. 메인 분석 프로세스 가동
# ==========================================
if st.button("🚀 폭포수 융합 엔진 기반 전체 분석 가동", use_container_width=True):
    st.write("<br>", unsafe_allow_html=True)

    with st.spinner("📰 [공정 1/4] 매크로 키워드 실시간 뉴스 수집 중..."):
        macro_keywords = ["코스피 시황", "젠슨황", "트럼프 뉴스", "한국무역", "환율", "나스닥", "전쟁"]
        collected_macro_news = "\n".join([f"[{kw} 동향]\n{get_refined_market_news(kw)}" for kw in macro_keywords])

    with st.spinner("🤖 [공정 2/4] KRX ➡️ YF ➡️ 마감데이터 순차 방어 스크리닝 중..."):
        kospi_pool_text = ""
        full_aligned_list = []
        
        try:
            df_base = stock.get_market_ohlcv_by_ticker(latest_closed_day, market="KOSPI")
            top_60_tickers = df_base.sort_values(by='거래량', ascending=False).head(60).index.tolist()
            
            df_yesterday = stock.get_market_ohlcv_by_ticker(recent_days[-2] if len(recent_days)>=2 else recent_days[0], market="KOSPI")
            df_last_week = stock.get_market_ohlcv_by_ticker(recent_days[-6] if len(recent_days)>=6 else recent_days[0], market="KOSPI")
            
            # [방어 1단계] 실시간 KRX 데이터 시도
            krx_live_ok = False
            df_today_krx = pd.DataFrame()
            try:
                df_temp = stock.get_market_ohlcv_by_ticker(today_str, market="KOSPI")
                if not df_temp.empty and '종가' in df_temp.columns:
                    df_today_krx = df_temp
                    krx_live_ok = True
            except: pass

            # [방어 2단계] 야후 파이낸스 멀티 인덱스 구조 무력화화 고도화
            yf_prices = {}
            if not krx_live_ok:
                try:
                    yf_tickers = [f"{t}.KS" for t in top_60_tickers]
                    # group_by='ticker'를 빼서 표 구조를 단순화시키고 결측치는 앞 데이터로 채움
                    yf_live_data = yf.download(yf_tickers, period="5d", progress=False)
                    if not yf_live_data.empty:
                        # 야후의 꼬인 표 구조에서 'Close' 가격만 안전하게 종목별 매핑 추출
                        for t in top_60_tickers:
                            try:
                                if len(top_60_tickers) == 1:
                                    yf_prices[t] = int(yf_live_data['Close'].iloc[-1])
                                else:
                                    yf_prices[t] = int(yf_live_data['Close'][f"{t}.KS"].dropna().iloc[-1])
                            except: pass
                except: pass

            # 종목별 데이터 가공 조립
            data_source_used = "장 마감 데이터"
            for ticker in top_60_tickers:
                name = stock.get_market_ticker_name(ticker)
                price_yesterday = int(df_yesterday.loc[ticker, '종가']) if ticker in df_yesterday.index else 0
                price_last_week = int(df_last_week.loc[ticker, '종가']) if ticker in df_last_week.index else 0
                price_today = 0
                
                if krx_live_ok and ticker in df_today_krx.index:
                    price_today = int(df_today_krx.loc[ticker, '종가'])
                    data_source_used = "KRX 실시간"
                elif ticker in yf_prices:
                    price_today = yf_prices[ticker]
                    data_source_used = "YFinance 실시간"
                
                # [방어 3단계] 다 안되면 어제자 마감 통계 사용
                if price_today == 0:
                    price_today = int(df_base.loc[ticker, '종가']) if ticker in df_base.index else price_yesterday
                
                change_yesterday = ((price_today - price_yesterday) / price_yesterday * 100) if price_yesterday else 0.0
                change_last_week = ((price_today - price_last_week) / price_last_week * 100) if price_last_week else 0.0
                
                full_aligned_list.append({
                    "종목명": name, "현재 금액": f"{price_today:,}원", "어제 금액": f"{price_yesterday:,}원",
                    "전일 대비": f"{change_yesterday:+.2f}%", "저번주 금액": f"{price_last_week:,}원",
                    "전주 대비": f"{change_last_week:+.2f}%", "ticker_id": ticker, "raw_change": change_yesterday
                })
                kospi_pool_text += f"{name},{ticker},현재가:{price_today},전일가:{price_yesterday},전일대비:{change_yesterday:.2f}%,전주가:{price_last_week},전주대비:{change_last_week:.2f}%\n"
                
        except Exception as e:
            st.error(f"🚨 데이터 로드 완전 실패 (모든 방어선 붕괴): {e}")
            st.stop()
            
        prompt1 = "뉴스 흐름과 주가 데이터를 비교해 내일 장에서 탄력이 가장 강력할 후보 유니크한 20개를 선정해. 형식을 칼같이 지켜 `종목명,종목코드` 형태로만 딱 20줄 출력해."
        response1 = client.models.generate_content(model='gemini-2.5-flash', contents=f"{prompt1}\n\n{collected_macro_news}\n{kospi_pool_text}")
        
        selected_stocks = []
        seen_tickers = set()
        for line in response1.text.strip().split('\n'):
            line = line.strip().replace('`', '').replace('*', '').replace('-', '')
            if ',' in line:
                parts = line.split(',')
                name, ticker = parts[0].strip(), parts[1].strip()
                if ticker not in seen_tickers and len(selected_stocks) < 20:
                    seen_tickers.add(ticker)
                    selected_stocks.append((name, ticker))

        st.markdown(f'<div class="timestamp-box">⏱️ 데이터 추출 완료 (소스: {data_source_used})</div>', unsafe_allow_html=True)
        
        ui_table_data = [item for item in full_aligned_list if item["ticker_id"] in seen_tickers]
        st.markdown("### 🎯 1차 선별: 매크로-시계열 융합 매칭 후보 (20개)")
        st.dataframe(pd.DataFrame(ui_table_data).drop(columns=['ticker_id', 'raw_change'], errors='ignore'), use_container_width=True, hide_index=True)

    with st.spinner("📥 [공정 3/4] 20개 후보 기업 최신 뉴스 실시간 매칭 중..."):
        company_specific_news_text = ""
        for name, ticker in selected_stocks:
            refined_comp_news = get_refined_market_news(name)
            matched = next((item for item in full_aligned_list if item["ticker_id"] == ticker), None)
            raw_perf = matched["raw_change"] if matched else 0.0
            company_specific_news_text += f"- {name}({ticker}): 뉴스데이터[{refined_comp_news}] / 금일 등락률: {raw_perf:+.2f}%\n"

    with st.spinner("🧠 [공정 4/4] 제미나이가 최종 리포트 빌드 중..."):
        prompt2 = f"""
너는 여의도 자산운용사 헤드 펀드매니저야. 아래 데이터를 검증해 최종 10개 종목을 엄선해라.

[데이터]
{company_specific_news_text}
{kospi_pool_text}

⚠️ [작성 규칙 - 절대 엄수]
1. **HTML 태그(<div>, <p>, <span> 등)는 절대 사용 금지.** 마크다운 서식만 사용할 것.
2. 상승근거와 주의사항 내용 맨 앞에는 수집된 [뉴스 일자 / 출처언론사](링크)를 가공 없이 그대로 표기.
3. 내일 예상가는 현재가를 기준으로 직접 산출한 [예상 금액]원과 ([예상상승률]%)를 모두 수식 계산해 명시.
4. 주의 사항은 단순 요약을 넘어 산업/재무/수급 등 깊이 있게 분석할 것. 중복되거나 빈약하면 억지로 채우지 말고 삭제.

형식 규격:
---
### 📈 [순위]. 종목명 (종목코드)
**💰 현재 기준 금액:** [현재 금액]원 / **🚀 내일 예상:** [예상 금액]원 ([예상상승률]%)

#### 💡 상승근거
> 🔥 **핵심 모멘텀:** [단 한 줄 핵심 요약]
1. [날짜 / 출처](링크) 내용
2. [날짜 / 출처](링크) 내용

#### ⚠️ 주의 사항 (심층 분석)
> 🚨 **치명적 위험:** [단 한 줄 핵심 요약]
1. [날짜 / 출처](링크) 내용
2. [날짜 / 출처](링크) 내용

#### 🚨 특이사항 브리핑
[산업 분석 및 수급 동향 심층 기술]

**- 어제 추천 여부:** [결과]
"""
        try:
            response2 = client.models.generate_content(model='gemini-2.5-flash', contents=prompt2)
            st.success("✨ 모든 분석 완료!")
            st.markdown("## 🎯 제미나이 엄선: 내일의 투자 유망 종목 TOP 10")
            st.markdown(response2.text)
        except Exception as e:
            st.error(f"🚨 트래픽 과부하 발생. 잠시 후 시도해주세요. (에러: {e})")
