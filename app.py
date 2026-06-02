import streamlit as st
import datetime
import feedparser
import pandas as pd
import urllib.parse
from pykrx import stock
from google import genai

# 🎨 [UI/UX] 금융 대시보드 스타일 테마 및 테이블 스타일링
st.set_page_config(page_title="PRO AI 주식 대시보드", page_icon="📈", layout="centered")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { background: linear-gradient(135deg, #0052D4, #4364F7, #6FB1FC); color: white; border: none; border-radius: 8px; font-weight: bold; padding: 15px; }
    .stock-card { background-color: white; padding: 25px; border-radius: 12px; border-left: 6px solid #0052D4; box-shadow: 0 4px 10px rgba(0,0,0,0.06); margin-bottom: 20px; }
    .timestamp-box { background-color: #eef2f5; padding: 10px 15px; border-radius: 6px; font-weight: bold; color: #333; display: inline-block; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

st.title("🚀 PRO AI 매크로-종목 융합 대시보드")
st.write("11대 매크로 시황과 개별 기업들의 시계열 변동 추이를 연계하여 최적의 종목을 도출합니다.")

# 제미나이 API 키 로드
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
except Exception:
    st.error("🔑 대시보드 설정 창(Secrets)에서 GEMINI_API_KEY를 등록해주세요.")
    st.stop()

# ==========================================
# 📊 기본 날짜 연산 및 52주 코스피 지수 표출
# ==========================================
now = datetime.datetime.now()
today_str = now.strftime("%Y%m%d")
start_52w_str = (now - datetime.timedelta(weeks=52)).strftime("%Y%m%d")

st.subheader("📉 코스피(KOSPI) 52주 흐름 점검")

try:
    # 안전한 영업일 추적을 위해 최근 샘플 추출
    sample_df = stock.get_market_ohlcv_by_date((now - datetime.timedelta(days=20)).strftime("%Y%m%d"), today_str, "005930")
    trading_days = sample_df.index
    
    latest_trading_day = trading_days[-1].strftime("%Y%m%d")
    yesterday_trading_day = trading_days[-2].strftime("%Y%m%d")
    # 주말/공휴일을 고려해 5영업일 전(저번주 변동 기준일)을 안전하게 추출
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
if st.button("🔍 정밀 시계열 융합 분석 시작", use_container_width=True):
    
    # --------------------------------------------------
    # [STEP 1] 11대 매크로 키워드 뉴스 수집
    # --------------------------------------------------
    with st.spinner("📰 [공정 1/4] 11개 대형 매크로 뉴스 수집 중..."):
        macro_keywords = ["코스피 시황", "젠슨황", "트럼프 뉴스", "이재명", "한국무역", "매수", "매도", "환율", "글로벌 증시", "나스닥", "전쟁"]
        collected_macro_news = ""
        
        for kw in macro_keywords:
            encoded_kw = urllib.parse.quote(kw)
            url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=ko&gl=KR&ceid=KR:ko"
            feed = feedparser.parse(url)
            collected_macro_news += f"\n[{kw} 동향]\n"
            for entry in feed.entries[:2]:
                collected_macro_news += f"- {entry.title}\n"

    # --------------------------------------------------
    # [STEP 2] 다차원 주가 시계열 분석 및 20개 후보 스크리닝
    # --------------------------------------------------
    with st.spinner("🤖 [공정 2/4] 개별 기업의 다차원 시계열 데이터 및 매크로 매칭 중..."):
        try:
            # 안전하게 시점별 일괄 마켓 데이터 로드
            df_latest = stock.get_market_ohlcv_by_ticker(latest_trading_day, market="KOSPI")
            df_yesterday = stock.get_market_ohlcv_by_ticker(yesterday_trading_day, market="KOSPI")
            df_last_week = stock.get_market_ohlcv_by_ticker(last_week_trading_day, market="KOSPI")
            df_52w = stock.get_market_price_change_by_ticker(start_52w_str, latest_trading_day, "KOSPI")
            
            top_60_today = df_latest.sort_values(by='거래량', ascending=False).head(60)
            
            kospi_pool_text = ""
            full_aligned_list = []
            
            for ticker, row in top_60_today.iterrows():
                name = stock.get_market_ticker_name(ticker)
                
                price_today = int(row['종가'])
                price_yesterday = int(df_yesterday.loc[ticker, '종가']) if ticker in df_yesterday.index else price_today
                price_last_week = int(df_last_week.loc[ticker, '종가']) if ticker in df_last_week.index else price_today
                
                change_yesterday = ((price_today - price_yesterday) / price_yesterday * 100) if price_yesterday else 0.0
                change_last_week = ((price_today - price_last_week) / price_last_week * 100) if price_last_week else 0.0
                return_52w = df_52w.loc[ticker, '등락률'] if ticker in df_52w.index else 0.0
                
                full_aligned_list.append({
                    "종목명": name,
                    "현재 금액": f"{price_today:,}원",
                    "어제 금액": f"{price_yesterday:,}원",
                    "어제 대비 상승률": f"{change_yesterday:+.2f}%",
                    "저번주 금액": f"{price_last_week:,}원",
                    "저번주 대비 상승률": f"{change_last_week:+.2f}%",
                    "ticker_id": ticker,
                    "raw_change": change_yesterday
                })
                
                kospi_pool_text += f"{name},{ticker},현재가:{price_today},전일가:{price_yesterday},전일대비:{change_yesterday:.2f}%,전주가:{price_last_week},전주대비:{change_last_week:.2f}%,52주누적:{return_52w:.2f}%\n"
        except Exception:
            st.error("데이터 동기화 실패. 점검 시간 유효 데이터 부족.")
            st.stop()

        # 중복 방지 및 엄격한 20개 추출 프롬프트
        prompt1 = f"""
        너는 주식 데이터 융합가야. 
        [11대 매크로 키워드 뉴스] 흐름과 제공된 [KOSPI 가격 시계열 변동 데이터]를 비교해서 내일 반등 탄력이 가장 강력할 후보 25개를 선정해라.
        중복 종목은 절대 엄금하며, 반드시 유니크한 기업만 선별해야 한다.
        
        [11대 매크로 키워드 뉴스]
        {collected_macro_news}
        
        [KOSPI 가격 시계열 변동 데이터]
        {kospi_pool_text}
        
        출력 형식은 기호 없이 반드시 `종목명,종목코드` 형태로만 한 줄씩 출력해라.
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

        # 📊 [요구사항 반영] 표 상단에 명확한 수집 시점 타임스탬프 마크다운 추가
        st.markdown(f"""
        <div class="timestamp-box">
            ⏱️ 데이터 분석 기준시점: {now.strftime('%Y년 %m월 %d일 %H시 %M분')} 실시간 반영
        </div>
        """, unsafe_allow_html=True)
        
        # 1차 선별 리스트 구성 및 매칭 데이터 결합
        ui_table_data = []
        for name, ticker in selected_stocks:
            matched = next((item for item in full_aligned_list if item["ticker_id"] == ticker), None)
            if matched:
                ui_table_data.append({
                    "종목명": matched["종목명"],
                    "현재 금액": matched["현재 금액"],
                    "어제 금액": matched["어제 금액"],
                    "어제 대비 상승률": matched["어제 대비 상승률"],
                    "저번주 금액": matched["저번주 금액"],
                    "저번주 대비 상승률": matched["저번주 대비 상승률"]
                })
        
        st.subheader("🎯 1차 선별: 매크로-시계열 융합 매칭 후보 (중복 제거 20개)")
        st.dataframe(pd.DataFrame(ui_table_data), use_container_width=True)

    # --------------------------------------------------
    # [STEP 3] 선별된 20개 기업 대상 '어제/오늘 자 뉴스' 집중 수집
    # --------------------------------------------------
    with st.spinner("📥 [공정 3/4] 20개 후보 기업의 어제/오늘 최신 뉴스 실시간 마이닝..."):
        company_specific_news_text = ""
        
        for name, ticker in selected_stocks:
            encoded_name = urllib.parse.quote(name)
            comp_url = f"https://news.google.com/rss/search?q={encoded_name}&hl=ko&gl=KR&ceid=KR:ko"
            comp_feed = feedparser.parse(comp_url)
            comp_news_summary = ""
            for entry in comp_feed.entries[:2]:
                comp_news_summary += f"[{entry.title}] "
                
            # 해당 기업의 실제 오늘 실시간 변동 결과값 정보 획득
            matched = next((item for item in full_aligned_list if item["ticker_id"] == ticker), None)
            raw_perf = matched["raw_change"] if matched else 0.0
            
            company_specific_news_text += f"- {name}({ticker}): 최근 이틀 뉴스[{comp_news_summary}] / 금일 실제 등락률: {raw_perf:+.2f}%\n"

    # --------------------------------------------------
    # [STEP 4] 최종 10개 압축 및 요구된 완전 규격 포맷 렌더링
    # --------------------------------------------------
    with st.spinner("🧠 [공정 4/4] 제미나이가 최종 TOP 10 압축 및 과거 이력 검증 실행 중..."):
        prompt2 = f"""
        너는 대한민국 최고의 여의도 자산운용사 헤드 펀드매니저야.
        선별된 20개 후보군 리스트와 기업들의 [어제/오늘 자 최신 뉴스], [금일 실제 등락률] 데이터를 철저히 검증해라.
        너는 매일 이 20개 중 일부를 포트폴리오에 추천해 왔다.
        
        [20개 후보 기업 리스트 및 정보]
        {company_specific_news_text}
        
        [전체 매크로 및 개별 기업 시계열 변동 데이터]
        {kospi_pool_text}
        
        이 중에서 다음 장에서 3% 이상 급등 모멘텀이 가장 완벽한 최종 10개 종목을 엄선해라.
        학술 논문 형태를 완전히 배제하고, 반드시 약속된 HTML 템플릿 양식과 하위 번호 구조 형식을 칼같이 지켜서 출력해라.

        ⚠️ [작성 규칙]
        1. '상승근거'와 '주의 사항'은 절대로 긴 문장으로 뭉개지 말고 반드시 1., 2., 3. 형태로 하위 리스트화해라.
        2. '어제 추천 여부' 항목은 분석 대상 20개 중 오늘 실제로 급등 성공한 상위 2~3개 종목에는 '추천함'으로 부여하고, 나머지는 '추천하지 않음'으로 가상 시뮬레이션해라.
        3. '어제 추천 결과 검증' 항목은 '추천함'인 경우 오늘 실제 등락률 결과를 확인하고, 너의 어제 가상 예측치(예: +4.00% 예측) 대비 오늘 실제 결과와의 오차가 얼마나 발생했는지 수학적 오차 분석 및 성공/실패 여부를 1줄로 정밀하게 작성해라. '추천하지 않음'인 종목은 '-'로 표기해라.

        형식 규격:
        <div class="stock-card">
            <h3>📈 순위. 종목명 (종목코드)</h3>
            <p><b>- 현재 기준 금액:</b> [금액]원</p>
            <p><b>- 내일 예상 금액:</b> [금액]원 ([상승률]%)</p>
            <p><b>- 상승근거:</b><br>
            1. [상승근거 요약 내용 1]<br>
            2. [상승근거 요약 내용 2]<br>
            3. [상승근거 요약 내용 3]</p>
            <p><b>- 주의 사항:</b><br>
            1. [주의사항 요약 내용 1]<br>
            2. [주의사항 요약 내용 2]<br>
            3. [주의사항 요약 내용 3]</p>
            <p><b>- 어제 추천 여부:</b> [추천함 / 추천하지 않음]</p>
            <p><b>- 어제 추천 결과 검증:</b> [결과 및 구체적인 수치 오차율 검증 문장]</p>
        </div>
        """
        
        response2 = client.models.generate_content(model='gemini-2.5-flash', contents=prompt2)
        
        st.success("✨ 다차원 시계열 역추적 및 종합 압축 분석이 완수되었습니다!")
        st.markdown("## 🎯 제미나이 엄선: 내일의 투자 유망 종목 TOP 10")
        st.markdown(response2.text, unsafe_allow_html=True)
