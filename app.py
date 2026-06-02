import streamlit as st
import datetime
import feedparser
import pandas as pd
from pykrx import stock
from google import genai

# 모바일 화면 최적화 설정
st.set_page_config(page_title="AI 주식 추천", page_icon="📊", layout="centered")

st.title("📊 내일의 3% 급등 유망주 AI 분석")
st.write("당일 주도주 데이터와 주요 인물 뉴스를 융합하여 분석합니다.")

# Streamlit 환경변수에서 제미나이 키 가져오기
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
except Exception:
    st.error("🔑 대시보드 설정에서 GEMINI_API_KEY를 등록해주세요.")
    st.stop()

# 분석 버튼
if st.button("🚀 실시간 AI 추천 종목 뽑기", type="primary", use_container_width=True):
    with st.spinner("오늘의 주가와 뉴스를 분석하는 중입니다..."):
        
        # 1. 주가 데이터 수집
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        try:
            market_df = stock.get_market_price_change_by_ticker(today_str, today_str, "KOSPI")
            top_stocks = market_df.sort_values(by=['거래량', '등락률'], ascending=False).head(15)
            
            stock_list_text = ""
            display_data = []
            for ticker, row in top_stocks.iterrows():
                name = stock.get_market_ticker_name(ticker)
                stock_list_text += f"- {name}({ticker}): 등락률 {row['등락률']:.2f}%, 거래량 {row['거래량']:,}\n"
                display_data.append({"종목명": name, "등락률(%)": round(row['등락률'], 2), "거래량": row['거래량']})
            
            # 화면에 오늘 주도주 간단히 보여주기
            st.subheader("📈 오늘의 시장 주도주 리스트")
            st.dataframe(pd.DataFrame(display_data), use_container_width=True)
            
        except Exception:
            stock_list_text = "- 삼성전자: 등락률 +1.5%, 거래량 15,000,000\n- SK하이닉스: 등락률 +3.2%, 거래량 5,000,000"
            st.warning("장 시작 전이거나 휴일입니다. 샘플 데이터로 분석을 진행합니다.")

        # 2. 뉴스 데이터 수집
        keywords = ["코스피 시황", "젠슨황", "트럼프 뉴스", "이재명"]
        collected_news = ""
        
        for kw in keywords:
            collected_news += f"\n[키워드: {kw}]\n"
            url = f"https://news.google.com/rss/search?q={kw}&hl=ko&gl=KR&ceid=KR:ko"
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                collected_news += f"- {entry.title}\n"

        # 3. 제미나이 AI 분석
        prompt = f"""
        너는 대한민국 최고의 퀀트 투자자이자 뉴스 감성 분석 전문가야.
        아래 제공된 [오늘의 시장 주도주 데이터]와 [주요 키워드 뉴스]를 종합적으로 분석해줘.

        [오늘의 시장 주도주]
        {stock_list_text}

        [당일 주요 키워드 뉴스]
        {collected_news}

        위 데이터들을 매칭하여, 거시적 흐름(코스피 지수 방향, 트럼프/젠슨황/이재명 등 주요 인물 발언의 파장)과 오늘 주가 흐름상 '내일 장에서 최소 3% 이상 추가 상승 모멘텀이 가장 강해 보이는 종목 5개'를 선정해줘.

        출력 양식:
        ### 1. 종목명 (종목코드)
        * **예측 근거:** (뉴스의 인물 멘트나 시황, 거래량 데이터와 연계해서 상세히 설명)
        * **리스크 요인:** (주의해야 할 점 1가지)
        ---
        """

        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        
        # 4. 결과 출력
        st.success("✨ 분석이 완료되었습니다!")
        st.markdown("## 🎯 AI 추천 유망 종목 TOP 5")
        st.info(response.text)
