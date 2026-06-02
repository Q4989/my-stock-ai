import streamlit as st
import datetime
import feedparser
import pandas as pd
import urllib.parse
from pykrx import stock
from google import genai

# 🎨 [UI/UX] 1. 모바일 및 웹 화면 최적화 및 레이아웃 스타일링
st.set_page_config(page_title="PRO AI 주식 대시보드", page_icon="📈", layout="centered")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { background: linear-gradient(135deg, #0052D4, #4364F7, #6FB1FC); color: white; border: none; border-radius: 8px; font-weight: bold; padding: 15px; }
    .stock-card { background-color: white; padding: 20px; border-radius: 12px; border-left: 5px solid #4364F7; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 15px; }
    .metric-box { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.03); text-align: center; border: 1px solid #eef2f5; }
    </style>
""", unsafe_allow_html=True)

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
    sample_df = stock.get_market_ohlcv_by_date((now - datetime.timedelta(days=14)).strftime("%Y%m%d"), today_str, "005930")
    latest_trading_day = sample_df.index[-1].strftime("%Y%m%d")
    formatted_trading_day = sample_df.index[-1].strftime("%Y-%m-%d")
except Exception:
    latest_trading_day = today_str
    formatted_trading_day = now.strftime("%Y-%m-%d")

try:
    kospi_df = stock.get_index_ohlcv_by_date(start_52w_str, latest_trading_day, "1001")
    if not kospi_df.empty:
        current_kospi = kospi_df['종가'].iloc[-1]
        prev_kospi = kospi_df['종가'].iloc[-2]
        kospi_delta = current_kospi - prev_kospi
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric(label=f"코스피 지수 ({formatted_trading_day} 마감 기준)", value=f"{current_kospi:,.2f}", delta=f"{kospi_delta:+.2f}")
        with col2:
            st.metric(label="52주 최고점", value=f"{kospi_df['종가'].max():,.2f}")
            
        st.line_chart(kospi_df['종가'], height=200)
        kospi_summary = f"현재 코스피 지수는 {current_kospi:,.2f}포인트이며, 52주 최고점은 {kospi_df['종가'].max():,.2f}점, 최저점은 {kospi_df['종가'].min():,.2f}점입니다."
    else:
        kospi_summary = "코스피 지수 데이터를 불러올 수 없습니다."
except Exception:
    kospi_summary = "지수 데이터를 불러오지 못했습니다."

# ==========================================
# 🚀 실행 버튼
# ==========================================
if st.button("⚡ 실시간 융합 데이터 분석 및 TOP 10 종목 추출", use_container_width=True):
    candidate_stocks_text = ""
    candidate_list_for_ui = []
    
    with st.spinner("📦 1. 시장 주도주 20개 후보군 선별 중..."):
        try:
            # 정상적인 상황일 때 한국거래소에서 20개 종목 수집
            market_df = stock.get_market_price_change_by_ticker(latest_trading_day, latest_trading_day, "KOSPI")
            if market_df.empty:
                raise ValueError("거래소 응답 데이터가 비어있습니다.")
                
            top_20_stocks = market_df.sort_values(by=['거래량', '등락률'], ascending=False).head(20)
            
            for ticker, row in top_20_stocks.iterrows():
                name = stock.get_market_ticker_name(ticker)
                candidate_list_for_ui.append({"종목명": name, "등락률(%)": round(row['등락률'], 2), "거래량": row['거래량']})
                
                encoded_name = urllib.parse.quote(name)
                comp_url = f"https://news.google.com/rss/search?q={encoded_name}&hl=ko&gl=KR&ceid=KR:ko"
                comp_feed = feedparser.parse(comp_url)
                comp_news_text = ""
                for entry in comp_feed.entries[:2]:
                    comp_news_text += f"[{entry.title}] "
                
                candidate_stocks_text += f"- {name}({ticker}): 등락률 {row['등락률']:.2f}%, 거래량 {row['거래량']:,} / 최근뉴스: {comp_news_text}\n"
                
            st.subheader(f"🎯 AI가 선별한 주도주 후보군 (20개 / {formatted_trading_day} 기준)")
            st.dataframe(pd.DataFrame(candidate_list_for_ui), use_container_width=True)
            
        except Exception:
            # 💡 [방탄 로직] 자정 점검 등으로 pykrx가 터지면 대한민국 대표 우량주 15개로 우회 자동 전환
            st.warning("⚠️ 한국거래소(KRX) 서버 점검 시간입니다. 국내 주요 우량주(Blue Chips)를 대상으로 분석을 우회 진행합니다.")
            
            fallback_stocks = {
                "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "현대차": "005380.KS", 
                "기아": "000270.KS", "LG에너지솔루션": "373220.KS", "삼성바이오로직스": "207940.KS",
                "셀트리온": "068270.KS", "네이버": "035420.KS", "카카오": "035720.KS", 
                "POSCO홀딩스": "005490.KS", "신한지주": "055550.KS", "삼성물산": "028260.KS"
            }
            
            for name, ticker in fallback_stocks.items():
                candidate_list_for_ui.append({"종목명": name, "등락률(%)": "점검중", "거래량": "점검중"})
                
                encoded_name = urllib.parse.quote(name)
                comp_url = f"https://news.google.com/rss/search?q={encoded_name}&hl=ko&gl=KR&ceid=KR:ko"
                comp_feed = feedparser.parse(comp_url)
                comp_news_text = ""
                for entry in comp_feed.entries[:2]:
                    comp_news_text += f"[{entry.title}] "
                
                candidate_stocks_text += f"- {name}({ticker}): [주요 우량주] / 최근뉴스: {comp_news_text}\n"
                
            st.subheader("🎯 AI 분석 대상 종목 (대한민국 시가총액 상위 우량주)")
            st.dataframe(pd.DataFrame(candidate_list_for_ui), use_container_width=True)

    with st.spinner("📰 2. 11개 확장 매크로 키워드 뉴스 마이닝 중..."):
        macro_keywords = ["코스피 시황", "젠슨황", "트럼프 뉴스", "이재명", "한국무역", "매수", "매도", "환율", "글로벌 증시", "나스닥", "전쟁"]
        collected_macro_news = ""
        
        for kw in macro_keywords:
            encoded_kw = urllib.parse.quote(kw)
            url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=ko&gl=KR&ceid=KR:ko"
            feed = feedparser.parse(url)
            collected_macro_news += f"\n[{kw} 최신 동향]\n"
            for entry in feed.entries[:2]:
                collected_macro_news += f"- {entry.title}\n"

    with st.spinner("🤖 3. 제미나이가 논리 구조 분석 후 TOP 10 압축 중..."):
        prompt = f"""
        너는 대한민국 최고의 여의도 펀드매니저이자 금융 데이터 분석가야.
        제공된 52주 코스피 시황, 11개 핵심 매크로 뉴스, 시장 후보군 종목들과 해당 기업의 뉴스를 종합 분석해줘.

        [1. 코스피 52주 매크로 시황]
        {kospi_summary}

        [2. 11대 경제/정치 키워드 뉴스]
        {collected_macro_news}

        [3. 분석 대상 기업 리스트 및 기업 뉴스]
        {candidate_stocks_text}

        위 정보를 융합하여 '다음 장에서 가장 강력하게 상승할 모멘텀을 가진 최종 종목들(최대 10개)'을 엄선해줘.
        
        ⚠️ [출력 지침 - 중요] 
        - 절대 학술 논문처럼 길고 지루하게 쓰지 마라. 바쁜 투자자가 한눈에 읽고 판단할 수 있도록 아주 상세하면서도 "핵심 요약 방식(Bullet Points)"으로 간결하게 작성해라.
        - 각 종목당 구조는 무조건 아래 형식을 칼같이 지켜라. (HTML 태그를 융합해서 가독성을 올려줘)

        형식 예시:
        <div class="stock-card">
            <h3>📈 순위. 종목명 (종목코드)</h3>
            <p><b>💡 핵심 상승 근거:</b> 매크로 뉴스(예: 환율, 트럼프, 젠슨황 등 발언) 및 기업 호재 뉴스와 엮어서 명확하고 임팩트 있게 2줄 이내 작성</p>
            <p><b>⚠️ 주의 리스크:</b> 해당 기업 혹은 관련 섹터가 직면한 직관적인 위험 요소 1줄 작성</p>
        </div>
        """

        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        
        st.success("✨ AI 종합 압축 분석이 완료되었습니다!")
        st.markdown(f"## 🎯 제미나이 엄선: 다음 장 투자 유망 종목 TOP 10")
        st.markdown(response.text, unsafe_allow_html=True)
