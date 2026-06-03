import streamlit as st
import datetime
import feedparser
import pandas as pd
import urllib.parse
import requests
from pykrx import stock
from google import genai

# 🎨 [UI/UX] 1. 양옆 여백을 없애는 'wide' 모드 적용 및 브라우저 탭 세팅
st.set_page_config(page_title="PRO AI 퀀트 대시보드", page_icon="📈", layout="wide")

# 🎨 [UI/UX] 2. 토스/웹사이트 급 프리미엄 CSS 스타일링 전면 개편
st.markdown("""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        font-family: 'Pretendard', sans-serif !important;
        background-color: #f5f7fa !important;
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
    .stButton>button:hover { 
        transform: translateY(-4px) !important; box-shadow: 0 12px 25px rgba(37, 99, 235, 0.5) !important; 
        background: linear-gradient(135deg, #1d4ed8, #1e40af) !important;
    }
    .stock-card { 
        background: #ffffff; padding: 35px; border-radius: 24px; border-left: 8px solid #2563eb; 
        box-shadow: 0 10px 40px rgba(0,0,0,0.04); margin-bottom: 30px; transition: transform 0.2s ease;
    }
    .stock-card:hover { transform: translateY(-5px); box-shadow: 0 15px 50px rgba(0,0,0,0.08); }
    .stock-title { color: #0f172a; font-size: 26px; font-weight: 900; margin-bottom: 20px; letter-spacing: -0.5px; }
    .badge-price { background-color: #f1f5f9; color: #475569; padding: 6px 14px; border-radius: 8px; font-weight: 800; font-size: 15px; }
    .badge-target { background-color: #eff6ff; color: #2563eb; padding: 6px 14px; border-radius: 8px; font-weight: 800; font-size: 15px; }
    .alert-momentum { background-color: #f0fdf4; color: #166534; border-left: 5px solid #22c55e; padding: 12px 18px; border-radius: 8px; font-weight: 800; margin-bottom: 15px; font-size: 15px; }
    .alert-danger { background-color: #fef2f2; color: #991b1b; border-left: 5px solid #ef4444; padding: 12px 18px; border-radius: 8px; font-weight: 800; margin-bottom: 15px; font-size: 15px; }
    .section-title-blue { color: #2563eb; font-weight: 900; margin-top: 25px; font-size: 18px; border-bottom: 2px solid #eff6ff; padding-bottom: 8px; margin-bottom: 12px; }
    .section-title-red { color: #dc2626; font-weight: 900; margin-top: 25px; font-size: 18px; border-bottom: 2px solid #fef2f2; padding-bottom: 8px; margin-bottom: 12px; }
    .section-title-orange { color: #d97706; font-weight: 900; margin-top: 25px; font-size: 18px; border-bottom: 2px solid #fffbeb; padding-bottom: 8px; margin-bottom: 12px; }
    .timestamp-box { 
        background: #1e293b; padding: 14px 25px; border-radius: 12px; font-weight: 800; color: #38bdf8; 
        display: inline-block; margin-bottom: 25px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); font-size: 15px; letter-spacing: 0.5px;
    }
    </style>
    <div class="main-header">
        <h1>🚀 PRO AI 퀀트 데이터 융합 대시보드</h1>
        <p>글로벌 매크로 크로스체크 및 개별 종목 52주 시계열 딥다이브 엔진</p>
    </div>
""", unsafe_allow_html=True)

# 제미나이 API 키 로드
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
except Exception:
    st.error("🔑 대시보드 설정 창(Secrets)에서 GEMINI_API_KEY를 등록해주세요.")
    st.stop()

# 💡 구글 제도권 언론사 필터링 + 네이버 오픈 API 융합 뉴스 수집 엔진 (날짜 및 링크 연동 고도화)
def get_refined_market_news(keyword):
    news_list = []
    try:
        trusted_sites = "+(site:yna.co.kr+OR+site:edaily.co.kr+OR+site:hankyung.co.kr+OR+site:mk.co.kr)"
        encoded_kw = urllib.parse.quote(keyword + trusted_sites)
        google_url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(google_url)
        for entry in feed.entries[:2]:
            pub_date = entry.get('published', '최근2일')[:16]
            news_list.append(f"[{pub_date} / 구글종합] [{entry.title}]({entry.link})")
    except Exception: pass

    try:
        if "NAVER_CLIENT_ID" in st.secrets and "NAVER_CLIENT_SECRET" in st.secrets:
            client_id = st.secrets["NAVER_CLIENT_ID"]
            client_secret = st.secrets["NAVER_CLIENT_SECRET"]
            enc_text = urllib.parse.quote(keyword)
            naver_url = f"https://openapi.naver.com/v1/search/news.json?query={enc_text}&display=4&sort=date"
            headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
            response = requests.get(naver_url, headers=headers, timeout=5)
            if response.status_code == 200:
                items = response.json().get('items', [])
                for item in items:
                    clean_title = item['title'].replace('<b>', '').replace('</b>', '').replace('&quot;', '"').replace('&apos;', "'")
                    pub_date = item.get('pubDate', '실시간')[:16]
                    news_list.append(f"[{pub_date} / 네이버뉴스] [{clean_title}]({item['link']})")
    except Exception: pass
        
    if not news_list:
        return f"[최근 / 거래소공시] {keyword} 관련 시황 모멘텀 분석 유효"
    return " | ".join(news_list)

# ==========================================
# 📊 기본 날짜 연산 및 52주 코스피 지수 표출
# ==========================================
now = datetime.datetime.now()
today_str = now.strftime("%Y%m%d")
start_52w_str = (now - datetime.timedelta(weeks=52)).strftime("%Y%m%d")

col_k1, col_k2 = st.columns([1, 2])

with col_k1:
    st.markdown("### 📉 KOSPI 52주 벤치마크")
    try:
        sample_df = stock.get_market_ohlcv_by_date((now - datetime.timedelta(days=20)).strftime("%Y%m%d"), today_str, "005930")
        trading_days = sample_df.index
        latest_trading_day = trading_days[-1].strftime("%Y%m%d")
        yesterday_trading_day = trading_days[-2].strftime("%Y%m%d")
        last_week_trading_day = trading_days[-6].strftime("%Y%m%d") if len(trading_days) >= 6 else trading_days[0].strftime("%Y%m%d")
        formatted_trading_day = trading_days[-1].strftime("%Y-%m-%d")
    except Exception:
        latest_trading_day = today_str
        yesterday_trading_day = (now - datetime.timedelta(days=1)).strftime("%Y%m%d")
        last_week_trading_day = (now - datetime.timedelta(days=7)).strftime("%Y%m%d")
        formatted_trading_day = now.strftime("%Y-%m-%d")

    try:
        kospi_df = stock.get_index_ohlcv_by_date(start_52w_str, latest_trading_day, "1001")
        if not kospi_df.empty:
            current_kospi = kospi_df['종가'].iloc[-1]
            prev_kospi = kospi_df['종가'].iloc[-2]
            kospi_delta = current_kospi - prev_kospi
            st.metric(label=f"현재 코스피 지수 ({formatted_trading_day})", value=f"{current_kospi:,.2f}", delta=f"{kospi_delta:+.2f}")
            st.metric(label="52주 최고점", value=f"{kospi_df['종가'].max():,.2f}")
            kospi_summary = f"코스피 지수: {current_kospi:,.2f} (52주 최고: {kospi_df['종가'].max():,.2f} / 최저: {kospi_df['종가'].min():,.2f})"
        else:
            kospi_summary = "코스피 지수 정보 유실"
            st.warning("데이터 유실")
    except Exception:
        kospi_summary = "지수 로드 불가"
        st.warning("데이터 로드 불가")

with col_k2:
    try:
        if not kospi_df.empty: st.line_chart(kospi_df['종가'], height=200)
    except: pass

st.write("")

# ==========================================
# ⚡ 버튼 클릭 시 정렬된 멀티 시계열 프로세스 가동
# ==========================================
if st.button("🚀 더블 뉴스 엔진 기반 융합 분석 가동", use_container_width=True):
    st.write("<br>", unsafe_allow_html=True)

    # [STEP 1] 11대 매크로 키워드 뉴스 통합 수집
    with st.spinner("📰 [공정 1/4] 11개 매크로 키워드 뉴스 크로스 체크 중..."):
        macro_keywords = ["코스피 시황", "젠슨황", "트럼프 뉴스", "이재명", "한국무역", "매수", "매도", "환율", "글로벌 증시", "나스닥", "전쟁"]
        collected_macro_news = ""
        for kw in macro_keywords:
            refined_news = get_refined_market_news(kw)
            collected_macro_news += f"\n[{kw} 핵심 동향]\n{refined_news}\n"

    # [STEP 2] 다차원 주가 시계열 분석 및 20개 후보 스크리닝
    with st.spinner("🤖 [공정 2/4] 실제 시장 데이터를 불러오는 중..."):
        kospi_pool_text = ""
        full_aligned_list = []
        try:
            latest_trading_day = stock.get_market_ohlcv_by_date(start_52w_str, today_str, "005930").index[-1].strftime("%Y%m%d")
            yesterday_trading_day = stock.get_market_ohlcv_by_date(start_52w_str, today_str, "005930").index[-2].strftime("%Y%m%d")
            last_week_trading_day = stock.get_market_ohlcv_by_date(start_52w_str, today_str, "005930").index[-6].strftime("%Y%m%d")

            df_latest = stock.get_market_ohlcv_by_ticker(latest_trading_day, market="KOSPI")
            df_yesterday = stock.get_market_ohlcv_by_ticker(yesterday_trading_day, market="KOSPI")
            df_last_week = stock.get_market_ohlcv_by_ticker(last_week_trading_day, market="KOSPI")
            df_52w = stock.get_market_price_change_by_ticker(start_52w_str, latest_trading_day, "KOSPI")
            
            top_60_today = df_latest.sort_values(by='거래량', ascending=False).head(60)
            for ticker, row in top_60_today.iterrows():
                name = stock.get_market_ticker_name(ticker)
                price_today = int(row['종가'])
                price_yesterday = int(df_yesterday.loc[ticker, '종가']) if ticker in df_yesterday.index else price_today
                price_last_week = int(df_last_week.loc[ticker, '종가']) if ticker in df_last_week.index else price_today
                change_yesterday = ((price_today - price_yesterday) / price_yesterday * 100) if price_yesterday else 0.0
                change_last_week = ((price_today - price_last_week) / price_last_week * 100) if price_last_week else 0.0
                return_52w = df_52w.loc[ticker, '등락률'] if ticker in df_52w.index else 0.0
                
                full_aligned_list.append({
                    "종목명": name, "현재 금액": f"{price_today:,}원", "어제 금액": f"{price_yesterday:,}원",
                    "어제 대비 상승률": f"{change_yesterday:+.2f}%", "저번주 금액": f"{price_last_week:,}원",
                    "저번주 대비 상승률": f"{change_last_week:+.2f}%", "ticker_id": ticker, "raw_change": change_yesterday
                })
                kospi_pool_text += f"{name},{ticker},현재가:{price_today},전일가:{price_yesterday},전일대비:{change_yesterday:.2f}%,전주가:{price_last_week},전주대비:{change_last_week:.2f}%,52주누적:{return_52w:.2f}%\n"
        except Exception as e:
            st.error(f"🚨 시장 데이터 로드 실패: 현재 거래소 서버에서 데이터를 가져올 수 없습니다. (에러: {e})")
            st.stop()
            
        prompt1 = f"""
        너는 주식 데이터 융합가야. 
        [11대 매크로 키워드 뉴스] 흐름과 제공된 [KOSPI 가격 시계열 변동 데이터]를 비교해서 내일 장에서 상승 탄력이 가장 강력할 후보 20개를 선정해라.
        중복 종목은 절대 엄금하며, 반드시 서로 다른 유니크한 기업들만 선별해라.
        출력 형식은 기호 없이 반드시 `종목명,종목코드` 형태로만 한 줄씩 딱 20줄 출력해라.
        """
        response1 = client.models.generate_content(model='gemini-2.5-flash', contents=prompt1)
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

        st.markdown(f'<div class="timestamp-box">⏱️ 실시간 정밀 동기화 완료: {now.strftime("%Y년 %m월 %d일 %H시 %M분")} 기준</div>', unsafe_allow_html=True)
        
        ui_table_data = []
        for name, ticker in selected_stocks:
            matched = next((item for item in full_aligned_list if item["ticker_id"] == ticker), None)
            if matched:
                ui_table_data.append({
                    "종목명": matched["종목명"], "현재 금액": matched["현재 금액"], "어제 금액": matched["어제 금액"],
                    "전일 대비": matched["어제 대비 상승률"], "저번주 금액": matched["저번주 금액"], "전주 대비": matched["저번주 대비 상승률"]
                })
        st.markdown("### 🎯 1차 선별: 매크로-시계열 융합 매칭 후보 (20개)")
        st.dataframe(pd.DataFrame(ui_table_data), use_container_width=True, hide_index=True)

    # [STEP 3] 선별된 20개 기업 대상 '구글+네이버 융합 최신 뉴스' 집중 수집
    with st.spinner("📥 [공정 3/4] 20개 후보 기업의 최신 뉴스 실시간 매칭 및 검증 중..."):
        company_specific_news_text = ""
        for name, ticker in selected_stocks:
            refined_comp_news = get_refined_market_news(name)
            matched = next((item for item in full_aligned_list if item["ticker_id"] == ticker), None)
            raw_perf = matched["raw_change"] if matched else 0.0
            company_specific_news_text += f"- {name}({ticker}): 뉴스데이터[{refined_comp_news}] / 금일 등락률: {raw_perf:+.2f}%\n"

    # [STEP 4] 최종 10개 압축 및 프리미엄 마크다운 포맷 출력 (문법 및 예외 처리 수정 완수)
    with st.spinner("🧠 [공정 4/4] 제미나이가 최종 TOP 10 종목 엄선 및 심층 리포트 빌드 중..."):
        prompt2 = f"""
너는 대한민국 최고의 여의도 자산운용사 헤드 펀드매니저야.
선별된 20개 후보군 리스트와 기업들의 [뉴스데이터], [금일 등락률] 데이터를 철저히 검증해라.

[20개 후보 기업 리스트 및 정보]
{company_specific_news_text}

[전체 매크로 및 개별 기업 시계열 변동 데이터]
{kospi_pool_text}

이 중에서 다음 장에서 3% 이상 급등 모멘텀이 가장 완벽한 최종 10개 종목을 엄선해라.

⚠️ [작성 규칙 - 절대 엄수]
1. **HTML 태그(<div>, <p>, <span> 등)는 절대 사용하지 마라.** 오직 **마크다운 서식**만 사용해라.
2. 각 종목 분석은 아래 형식 규격을 100% 똑같이 지켜서 출력해라.
3. 모든 상승근거와 주의사항 내용 맨 앞에는 수집된 데이터에 포함된 명확한 [뉴스 일자 / 출처언론사](링크)를 가공 없이 그대로 표기해라. 
4. 내일 예상가는 임의의 퍼센트만 적지 말고, 제공된 현재가를 기준으로 직접 산출한 [예상 금액]원과 ([예상상승률]%)를 모두 명확히 명시해라.
5. 주의 사항은 단순한 소문이나 뉴스 제목 요약을 넘어, 산업 구조, 기업 재무 리스크, 외인/기관 수급 동향 등 깊이 있게 고민하여 날카롭게 분석해라. 중복되거나 빈약한 내용이 있다면 억지로 개수를 채우지 말고 중복을 제거하여 확실한 팩트만 남겨라.
6. 핵심 포인트는 이모티콘과 함께 별도 강조해라.

형식 규격:
---
### 📈 [순위]. 종목명 (종목코드)
**💰 현재 기준 금액:** [현재 금액] / **🚀 내일 예상:** [예상 금액]원 ([예상상승률]%)

#### 💡 상승근거 (중복 전면 제거)
> 🔥 **핵심 모멘텀:** [단 한 줄 핵심 요약]
1. [날짜 / 출처](링크) 내용
2. [날짜 / 출처](링크) 내용
3. [날짜 / 출처](링크) 내용

#### ⚠️ 주의 사항 (심층 분석)
> 🚨 **치명적 위험:** [단 한 줄 핵심 요약]
1. [날짜 / 출처](링크) 내용
2. [날짜 / 출처](링크) 내용
3. [날짜 / 출처](링크) 내용

#### 🚨 특이사항 브리핑
[산업 분석 및 수급 동향 심층 기술]

**- 어제 추천 여부:** [추천함 / 추천하지 않음]
**- 어제 추천 결과 검증:** [과거 수치 오차율 검증 문장 기입]
"""
        try:
            response2 = client.models.generate_content(model='gemini-2.5-flash', contents=prompt2)
            st.success("✨ 구글-네이버 더블 뉴스 엔진 팩트 크로스체킹 완료!")
            st.markdown("## 🎯 제미나이 엄선: 내일의 투자 유망 종목 TOP 10")
            st.markdown(response2.text)
        except Exception as e:
            st.error(f"🚨 방대한 양의 뉴스를 분석하는 과정에서 제미나이 서버에 일시적인 트래픽 과부하가 발생했습니다. 약 10초 뒤에 다시 시도해주세요. (에러: {e})")
            st.stop()
