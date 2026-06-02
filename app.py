import streamlit as st
import datetime
import feedparser
import pandas as pd
import urllib.parse
from pykrx import stock
from google import genai

# 🎨 [UI/UX] 1. 모바일 및 웹 화면 최적화 및 레이아웃 스타일링
st.set_page_config(page_title="PRO AI 주식 대시보드", page_icon="📈", layout="centered")

# 고급스러운 금융 앱 분위기를 위한 커스텀 디자인 세팅
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { background: linear-gradient(135deg, #0052D4, #4364F7, #6FB1FC); color: white; border: none; border-radius: 8px; font-weight: bold; padding: 15px; }
    .stock-card { background-color: white; padding: 20px; border-radius: 12px; border-left: 5px solid #4364F7; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 15px; }
    .metric-box { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.03); text-align: center; border: 1px solid #eef2f5; }
    </style>
""", unsafe_allow_index=True)

st.title("🚀 PRO AI 주식 투자 대시보드")
st.write("거시 경제 흐름과 당일 거래대금 주도주를 결합하여 내일의 유망 종목을 선별합니다.")

# 제미나이 API 키 로드
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
except Exception:
    st.error("🔑 대시보드 설정 창(Secrets)에서 GEMINI_API_KEY를 등록해주세요.")
    st.stop()

# ==========================================
# 📊 [데이터 수집 1] 코스피 최근 52주 전체 데이터 및 지수
# ==========================================
now = datetime.datetime.now()
today_str = now.strftime("%Y%m%d")
start_52w_str = (now - datetime.timedelta(weeks=52)).strftime("%Y%m%d")

st.subheader("📉 코스피(KOSPI) 52주 시장 흐름")

try:
    # 52주간의 코스피 지수 가져오기 (1001: 코스피 시장지수 코드)
    kospi_df = stock.get_index_ohlcv_by_date(start_52w_str, today_str, "1001")
    
    if not kospi_df.empty:
        current_kospi = kospi_df['종가'].iloc[-1]
        prev_kospi = kospi_df['종가'].iloc[-2]
        kospi_delta = current_kospi - prev_kospi
        
        # [UI/UX] 상단 지수 현황 전광판 지표 배치
        col1, col2 = st.columns(2)
        with col1:
            st.metric(label="현재 코스피 지수", value=f"{current_kospi:,.2f}", delta=f"{kospi_delta:+.2f}")
        with col2:
            st.metric(label="52주 최고점", value=f"{kospi_df['종가'].max():,.2f}")
            
        # [UI/UX] 52주 주가 트렌드 선그래프 시각화
        st.line_chart(kospi_df['종가'], height=200)
        kospi_summary = f"현재 코스피 지수는 {current_kospi:,.2f}포인트이며, 52주 최고점은 {kospi_df['종가'].max():,.2f}점, 최저점은 {kospi_df['종가'].min():,.2f}점입니다."
    else:
        kospi_summary = "코스피 지수 데이터를 불러올 수 없습니다."
except Exception:
    kospi_summary = "주말 또는 휴일로 인해 지수 데이터를 불러오지 못했습니다."
    st.info("💡 장 오픈일 평일 오후 3시 30분 이후에 가장 정확한 데이터가 표출됩니다.")

# ==========================================
# 🚀 실행 버튼
# ==========================================
if st.button("⚡ 실시간 융합 데이터 분석 및 TOP 10 종목 추출", use_container_width=True):
    with st.spinner("📦 1. 시장 주도주 20개 후보군 선별 중..."):
        try:
            # 당일 거래량/등락률 기준 코스피 상위 20개 종목 추출
            market_df = stock.get_market_price_change_by_ticker(today_str, today_str, "KOSPI")
            top_20_stocks = market_df.sort_values(by=['거래량', '등락률'], ascending=False).head(20)
            
            candidate_stocks_text = ""
            candidate_list_for_ui = []
            
            # 20개 회사별 이름 매칭 및 개별 회사 뉴스 수집 (어제/오늘 자)
            for ticker, row in top_20_stocks.iterrows():
                name = stock.get_market_ticker_name(ticker)
                candidate_list_for_ui.append({"종목명": name, "등락률(%)": round(row['등락률'], 2), "거래량": row['거래량']})
                
                # 각 개별 회사 뉴스 2개씩 수집
                encoded_name = urllib.parse.quote(name)
                comp_url = f"https://news.google.com/rss/search?q={encoded_name}&hl=ko&gl=KR&ceid=KR:ko"
                comp_feed = feedparser.parse(comp_url)
                comp_news_text = ""
                for entry in comp_feed.entries[:2]:
                    comp_news_text += f"[{entry.title}] "
                
                candidate_stocks_text += f"- {name}({ticker}): 등락률 {row['등락률']:.2f}%, 거래량 {row['거래량']:,} / 최근뉴스: {comp_news_text}\n"
                
            # [UI/UX] 20개 후보군 깔끔한 표로 보여주기
            st.subheader("🎯 AI가 1차 선별한 오늘의 주도주 후보군 (20개)")
            st.dataframe(pd.DataFrame(candidate_list_for_ui), use_container_width=True)
            
        except Exception:
            st.error("당일 종목 데이터를 가져오는데 실패했습니다. 장 중이 아니거나 데이터 레이턴시가 있을 수 있습니다.")
            st.stop()

    with st.spinner("📰 2. 11개 확장 매크로 키워드 뉴스 마이닝 중..."):
        # 사용자가 요청한 11개 대형 키워드 기반 뉴스 탐색
        macro_keywords = ["코스피 시황", "젠슨황", "트럼프 뉴스", "이재명", "한국무역", "매수", "매도", "환율", "글로벌 증시", "나스닥", "전쟁"]
        collected_macro_news = ""
        
        for kw in macro_keywords:
            encoded_kw = urllib.parse.quote(kw)
            url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=ko&gl=KR&ceid=KR:ko"
            feed = feedparser.parse(url)
            collected_macro_news += f"\n[{kw} 최신 동향]\n"
            for entry in feed.entries[:2]: # 키워드당 핵심 뉴스 2개씩 요약
                collected_macro_news += f"- {entry.title}\n"

    with st.spinner("🤖 3. 제미나이가 논리 구조 분석 후 TOP 10 압축 중..."):
        # 제미나이에게 디테일하면서도 간결(가독성 극대화)하게 보고서를 작성하라고 지시
        prompt = f"""
        너는 대한민국 최고의 여의도 펀드매니저이자 금융 데이터 분석가야.
        제공된 52주 코스피 시황, 11개 핵심 매크로 뉴스, 20개의 시장 주도주와 해당 기업의 뉴스를 종합 분석해줘.

        [1. 코스피 52주 매크로 시황]
        {kospi_summary}

        [2. 11대 경제/정치 키워드 뉴스]
        {collected_macro_news}

        [3. 1차 후보군 20개 기업 리스트 및 기업 뉴스]
        {candidate_stocks_text}

        위 정보를 융합하여 '내일 가장 강력하게 상승할 모멘텀을 가진 최종 10개 종목'을 엄선해줘.
        
        ⚠️ [출력 지침 - 중요] 
        - 절대 학술 논문처럼 길고 지루하게 쓰지 마라. 바쁜 투자자가 한눈에 읽고 판단할 수 있도록 아주 상세하면서도 "핵심 요약 방식(Bullet Points)"으로 간결하게 작성해라.
        - 각 종목당 구조는 무조건 아래 형식을 칼같이 지켜라. (HTML 태그를 융합해서 가독성을 올려줘)

        형식 예시:
        <div class="stock-card">
            <h3>📈 순위. 종목명 (종목코드)</h3>
            <p><b>💡 핵심 상승 근거:</b> 매크로 뉴스(예: 환율, 트럼프, 젠슨황 등 발언) 및 당일 거래량 증가 사유와 엮어서 명확하고 임팩트 있게 2줄 이내 작성</p>
            <p><b>⚠️ 주의 리스크:</b> 해당 기업 혹은 관련 섹터가 직면한 직관적인 위험 요소 1줄 작성</p>
        </div>
        """

        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        
        st.success("✨ AI 종합 압축 분석이 완료되었습니다!")
        st.markdown("## 🎯 제미나이 엄선: 내일의 투자 유망 종목 TOP 10")
        
        # HTML 태그가 포함된 제미나이의 결과물을 안전하게 UI에 렌더링
        st.markdown(response.text, unsafe_allow_index=True)
