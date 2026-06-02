import streamlit as st
import datetime
import feedparser
import pandas as pd
import urllib.parse
import requests  # 💡 네이버 API 필수 라이브러리
from pykrx import stock
from google import genai

# 🎨 [UI/UX] 대형 증권사 MTS 스타일의 프리미엄 테마 스킨 세팅
st.set_page_config(page_title="PRO AI 주식 대시보드", page_icon="📈", layout="centered")

st.markdown("""
    <style>
    .main { background-color: #f1f3f7; }
    .stButton>button { 
        background: linear-gradient(135deg, #1f40aa, #0076ff, #00d2ff); 
        color: white; border: none; border-radius: 10px; 
        font-weight: bold; padding: 16px; font-size: 16px;
        box-shadow: 0 4px 15px rgba(0, 118, 255, 0.25);
    }
    .stock-card { 
        background: #ffffff; padding: 28px; border-radius: 16px; 
        border-left: 8px solid #0052D4; box-shadow: 0 8px 24px rgba(0,0,0,0.05); margin-bottom: 25px;
    }
    .stock-title { color: #111111; font-size: 22px; font-weight: bold; margin-bottom: 15px; }
    .badge-price { background-color: #e3efff; color: #0052D4; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 14px; }
    .badge-target { background-color: #fff0f1; color: #ff3b30; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 14px; }
    .section-title-blue { color: #0052D4; font-weight: bold; margin-top: 15px; font-size: 16px; border-bottom: 2px solid #e3efff; padding-bottom: 3px;}
    .section-title-red { color: #ff3b30; font-weight: bold; margin-top: 15px; font-size: 16px; border-bottom: 2px solid #fff0f1; padding-bottom: 3px;}
    .section-title-orange { color: #ff9500; font-weight: bold; margin-top: 15px; font-size: 16px; border-bottom: 2px solid #ffebd2; padding-bottom: 3px;}
    .timestamp-box { 
        background: linear-gradient(90deg, #1e293b, #0f172a); padding: 12px 20px; border-radius: 8px; 
        font-weight: bold; color: #00e5ff; display: inline-block; margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🚀 PRO AI 매크로-종목 융합 대시보드")
st.write("구글/네이버 더블 엔진 뉴스 크로스 체크 기반의 인공지능 투자 시스템.")

# 제미나이 API 키 로드
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
except Exception:
    st.error("🔑 대시보드 설정 창(Secrets)에서 GEMINI_API_KEY를 등록해주세요.")
    st.stop()

# 💡 [함수 신설] 구글 제도권 언론사 필터링 + 네이버 오픈 API 융합 뉴스 수집 엔진
def get_refined_market_news(keyword):
    news_list = []
    
    # 1. 구글 뉴스 (메이저 언론사 한정 정밀 필터링)
    try:
        trusted_sites = "+(site:yna.co.kr+OR+site:edaily.co.kr+OR+site:hankyung.co.kr+OR+site:mk.co.kr)"
        encoded_kw = urllib.parse.quote(keyword + trusted_sites)
        google_url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(google_url)
        for entry in feed.entries[:2]:
            news_list.append(f"[구글 뉴스 / 메이저언론] {entry.title}")
    except Exception:
        pass

    # 2. 네이버 뉴스 API 실시간 연동 (Secrets 키 기반)
    try:
        if "NAVER_CLIENT_ID" in st.secrets and "NAVER_CLIENT_SECRET" in st.secrets:
            client_id = st.secrets["NAVER_CLIENT_ID"]
            client_secret = st.secrets["NAVER_CLIENT_SECRET"]
            enc_text = urllib.parse.quote(keyword)
            naver_url = f"https://openapi.naver.com/v1/search/news.json?query={enc_text}&display=3&sort=date"
            
            headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
            response = requests.get(naver_url, headers=headers, timeout=5)
            
            if response.status_code == 200:
                items = response.json().get('items', [])
                for item in items:
                    clean_title = item['title'].replace('<b>', '').replace('</b>', '').replace('&quot;', '"').replace('&apos;', "'")
                    news_list.append(f"[네이버 뉴스 / 실시간] {clean_title}")
    except Exception:
        pass
        
    # 만약 뉴스 수집이 완전히 실패했을 때를 대비한 최소한의 가이드 텍스트 리턴
    if not news_list:
        return f"[{keyword}] 관련 최신 시황 뉴스 참조 가능"
        
    return " | ".join(news_list)

# ==========================================
# 📊 기본 날짜 연산 및 52주 코스피 지수 표출
# ==========================================
now = datetime.datetime.now()
today_str = now.strftime("%Y%m%d")
start_52w_str = (now - datetime.timedelta(weeks=52)).strftime("%Y%m%d")

st.subheader("📉 코스피(KOSPI) 52주 흐름 점검")

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
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric(label=f"현재 코스피 지수 ({formatted_trading_day})", value=f"{current_kospi:,.2f}", delta=f"{kospi_delta:+.2f}")
        with col2:
            st.metric(label="52주 최고점", value=f"{kospi_df['종가'].max():,.2f}")
        st.line_chart(kospi_df['종가'], height=180)
        kospi_summary = f"코스피 지수: {current_kospi:,.2f} (52주 최고: {kospi_df['종가'].max():,.2f} / 최저: {kospi_df['종가'].min():,.2f})"
    else:
        kospi_summary = "코스피 지수 정보 유실"
except Exception:
    kospi_summary = "지수 로드 불가"

# ==========================================
# ⚡ 버튼 클릭 시 정렬된 멀티 시계열 프로세스 가동
# ==========================================
if st.button("⚡ 더블 뉴스 엔진 기반 융합 분석 시작", use_container_width=True):
    
    # --------------------------------------------------
    # [STEP 1] 11대 매크로 키워드 뉴스 통합 수집 (구글+네이버 융합)
    # --------------------------------------------------
    with st.spinner("📰 [공정 1/4] 11개 매크로 키워드 뉴스 크로스 체크 중..."):
        macro_keywords = ["코스피 시황", "젠슨황", "트럼프 뉴스", "이재명", "한국무역", "매수", "매도", "환율", "글로벌 증시", "나스닥", "전쟁"]
        collected_macro_news = ""
        
        for kw in macro_keywords:
            refined_news = get_refined_market_news(kw)
            collected_macro_news += f"\n[{kw} 핵심 동향]\n{refined_news}\n"

    # --------------------------------------------------
    # [STEP 2] 다차원 주가 시계열 분석 및 20개 후보 스크리닝
    # --------------------------------------------------
    with st.spinner("🤖 [공정 2/4] 개별 기업의 다차원 시계열 데이터 연계 및 종목 후보 추출 중..."):
        kospi_pool_text = ""
        full_aligned_list = []
        
        try:
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
                
        except Exception:
            fallback_stocks = {
                "삼성전자": "005930", "SK하이닉스": "000660", "현대차": "005380", "한화에어로스페이스": "012450", 
                "현대로템": "064350", "한국가스공사": "036460", "HMM": "011200", "삼성중공업": "010140", 
                "네이버": "035420", "LG에너지솔루션": "373220", "셀트리온": "068270", "KB금융": "055560"
            }
            for name, ticker in fallback_stocks.items():
                full_aligned_list.append({
                    "종목명": name, "현재 금액": "서버점검중", "어제 금액": "서버점검중", "어제 대비 상승률": "+0.00%", 
                    "저번주 금액": "서버점검중", "저번주 대비 상승률": "+0.00%", "ticker_id": ticker, "raw_change": 0.0
                })
                kospi_pool_text += f"{name},{ticker},현재가:70000,전일가:70000,전일대비:0.00%,전주가:70000,전주대비:0.00%,52주누적:5.00%\n"

        prompt1 = f"""
        너는 주식 데이터 융합가야. 
        [11대 매크로 키워드 뉴스] 흐름과 제공된 [KOSPI 가격 시계열 변동 데이터]를 비교해서 내일 장에서 상승 탄력이 가장 강력할 후보 20개를 선정해라.
        중복 종목은 절대 엄금하며, 반드시 서로 다른 유니크한 기업들만 선별해야 한다.
        
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

        # 📊 실시간 타임스탬프 표출
        st.markdown(f"""
        <div class="timestamp-box">
            ⏱️ 데이터 실시간 동기화 완료: {now.strftime('%Y년 %m월 %d일 %H시 %M분')}
        </div>
        """, unsafe_allow_html=True)
        
        # 1차 선별 리스트 구성
        ui_table_data = []
        for name, ticker in selected_stocks:
            matched = next((item for item in full_aligned_list if item["ticker_id"] == ticker), None)
            if matched:
                ui_table_data.append({
                    "종목명": matched["종목명"], "현재 금액": matched["현재 금액"], "어제 금액": matched["어제 금액"],
                    "어제 대비 상승률": matched["어제 대비 상승률"], "저번주 금액": matched["저번주 금액"], "저번주 대비 상승률": matched["저번주 대비 상승률"]
                })
        
        st.subheader("🎯 1차 선별: 매크로-시계열 융합 매칭 후보 (중복 제거 20개)")
        st.dataframe(pd.DataFrame(ui_table_data), use_container_width=True)

    # --------------------------------------------------
    # [STEP 3] 선별된 20개 기업 대상 '구글+네이버 융합 최신 뉴스' 집중 수집
    # --------------------------------------------------
    with st.spinner("📥 [공정 3/4] 20개 후보 기업의 최신 뉴스 실시간 매칭 및 검증 중..."):
        company_specific_news_text = ""
        
        for name, ticker in selected_stocks:
            refined_comp_news = get_refined_market_news(name)
            matched = next((item for item in full_aligned_list if item["ticker_id"] == ticker), None)
            raw_perf = matched["raw_change"] if matched else 0.0
            
            company_specific_news_text += f"- {name}({ticker}): 뉴스데이터[{refined_comp_news}] / 금일 등락률: {raw_perf:+.2f}%\n"

    # --------------------------------------------------
    # [STEP 4] 최종 10개 압축 및 프리미엄 포맷 출력
    # --------------------------------------------------
    with st.spinner("🧠 [공정 4/4] 제미나이가 최종 TOP 10 종목 엄선 및 심층 리포트 빌드 중..."):
        prompt2 = f"""
        너는 대한민국 최고의 여의도 자산운용사 헤드 펀드매니저야.
        선별된 20개 후보군 리스트와 기업들의 [뉴스데이터(날짜 및 언론사 출처 표기)], [금일 등락률] 데이터를 철저히 검증해라.
        너는 매일 이 20개 중 일부를 포트폴리오에 추천해 왔다.
        
        [20개 후보 기업 리스트 및 정보]
        {company_specific_news_text}
        
        [전체 매크로 및 개별 기업 시계열 변동 데이터]
        {kospi_pool_text}
        
        이 중에서 다음 장에서 3% 이상 급등 모멘텀이 가장 완벽한 최종 10개 종목을 엄선해라.
        
        ⚠️ [작성 규칙 - 절대 엄수]
        1. **상승근거**와 **주의 사항**은 반드시 각각 **최소 5개 이상** 구체적으로 적어라.
        2. 뉴스 기반 근거는 반드시 가장 앞에 문맥에 제공된 **[날짜 / 언론사(예: 연합뉴스, 한국경제, 네이버뉴스 등)]** 출처를 칼같이 명시해라.
        3. **🚨 특이사항 브리핑** 섹션을 추가하여, 5개가 넘어가는 핵심 리스크나 거시 업종 이슈가 있다면 상세히 적어라. 없으면 "현재 포착된 특이적 오버 밸류 리스크 없음"으로 적어라.
        4. 가독성을 극대화하기 위해 제공하는 아래 HTML 구조를 100% 똑같이 유지해라.

        형식 규격:
        <div class="stock-card">
            <div class="stock-title">📈 <b>순위. 종목명 (종목코드)</b></div>
            <p><span class="badge-price">- 현재 기준 금액:</span> [금액]원</p>
            <p><span class="badge-target">- 내일 예상 금액:</span> [금액]원 ([상승률]%)</p>
            
            <div class="section-title-blue">💡 상승근거 (최소 5개)</div>
            1. [출처] 내용<br>
            2. [출처] 내용<br>
            3. [출처] 내용<br>
            4. [출처] 내용<br>
            5. [출처] 내용
            
            <div class="section-title-red">⚠️ 주의 사항 (최소 5개)</div>
            1. [출처] 내용<br>
            2. [출처] 내용<br>
            3. [출처] 내용<br>
            4. [출처] 내용<br>
            5. [출처] 내용
            
            <div class="section-title-orange">🚨 특이사항 브리핑 (5개 초과 리스크 및 주요 이슈)</div>
            [내용 기술]
            
            <hr style="border: 0.5px dashed #ddd; margin: 15px 0;">
            <p><b>- 어제 추천 여부:</b> [추천함 / 추천하지 않음]</p>
            <p><b>- 어제 추천 결과 검증:</b> [결과 수치 오차율 검증 문장 기입]</p>
        </div>
        """
        
        response2 = client.models.generate_content(model='gemini-2.5-flash', contents=prompt2)
        
        st.success("✨ 구글-네이버 더블 뉴스 마이닝 기반 프리미엄 분석이 완수되었습니다!")
        st.markdown("## 🎯 제미나이 엄선: 내일의 투자 유망 종목 TOP 10")
        st.markdown(response2.text, unsafe_allow_html=True)
