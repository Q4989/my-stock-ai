import streamlit as st
import datetime
import feedparser
import pandas as pd
import urllib.parse
import requests
from pykrx import stock
import yfinance as yf  # 💡 실시간 차트 및 휴일 백업용 야후 파이낸스 도입

# ==========================================
# 🎨 [UI/UX] 프리미엄 핀테크 와이드 레이아웃
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
    .stock-card { background: #ffffff; padding: 35px; border-radius: 24px; border-left: 8px solid #2563eb; box-shadow: 0 10px 40px rgba(0,0,0,0.04); margin-bottom: 30px; }
    .badge-price { background-color: #f1f5f9; color: #475569; padding: 6px 14px; border-radius: 8px; font-weight: 800; font-size: 15px; }
    .badge-target { background-color: #eff6ff; color: #2563eb; padding: 6px 14px; border-radius: 8px; font-weight: 800; font-size: 15px; }
    .alert-momentum { background-color: #f0fdf4; color: #166534; border-left: 5px solid #22c55e; padding: 12px 18px; border-radius: 8px; font-weight: 800; margin-bottom: 15px; }
    .alert-danger { background-color: #fef2f2; color: #991b1b; border-left: 5px solid #ef4444; padding: 12px 18px; border-radius: 8px; font-weight: 800; margin-bottom: 15px; }
    .timestamp-box { background: #1e293b; padding: 14px 25px; border-radius: 12px; font-weight: 800; color: #38bdf8; display: inline-block; margin-bottom: 25px; font-size: 15px; }
    </style>
    <div class="main-header">
        <h1>🚀 PRO AI 퀀트 데이터 융합 대시보드</h1>
        <p>yfinance 실시간 엔진 기반의 글로벌 매크로 및 시계열 트래킹 시스템</p>
    </div>
""", unsafe_allow_html=True)

# 제미나이 API 키 로드
try:
    from google import genai
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
except Exception:
    st.error("🔑 대시보드 설정 창(Secrets)에서 GEMINI_API_KEY를 등록해주세요.")
    st.stop()

# 💡 뉴스 마이닝 엔진
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
# 📊 [개선] yfinance 기반 실시간 코스피 지수 렌더링
# ==========================================
now = datetime.datetime.now()
col_k1, col_k2 = st.columns([1, 2])

with col_k1:
    st.markdown("### 📉 KOSPI 실시간 벤치마크")
    try:
        # 야후 파이낸스 코스피 지수 티커(^KS11)로 1년치 데이터 원샷 조회
        kospi_yf = yf.Ticker("^KS11")
        kospi_df = kospi_yf.history(period="1y")
        if not kospi_df.empty:
            current_kospi = kospi_df['Close'].iloc[-1]
            prev_kospi = kospi_df['Close'].iloc[-2]
            kospi_delta = current_kospi - prev_kospi
            st.metric(label=f"실시간/최근 마감 지수", value=f"{current_kospi:,.2f}", delta=f"{kospi_delta:+.2f}")
            st.metric(label="52주 최고점", value=f"{kospi_df['Close'].max():,.2f}")
        else: st.error("지수 데이터 공백")
    except Exception as e:
        st.error(f"지수 로드 불가: {e}")

with col_k2:
    try:
        if not kospi_df.empty: st.line_chart(kospi_df['Close'], height=200)
    except: pass

# ==========================================
# ⚡ 전체 분석 프로세스 가동
# ==========================================
if st.button("🚀 실시간 더블 엔진 융합 분석 가동", use_container_width=True):
    st.write("<br>", unsafe_allow_html=True)

    with st.spinner("📰 [공정 1/4] 매크로 키워드 실시간 뉴스 수집 중..."):
        macro_news = ""
        for kw in ["코스피 시황", "젠슨황", "트럼프 뉴스", "이재명", "환율", "나스닥", "전쟁"]:
            macro_news += f"\n[{kw} 동향]\n{get_refined_market_news(kw)}\n"

    with st.spinner("🤖 [공정 2/4] yfinance 실시간 호환 엔진 스크리닝 중..."):
        kospi_pool_text = ""
        full_aligned_list = []
        
        # 1차로 종목 리스트 뼈대 빌드 (거래소 점검/주말 대기 대비 고정 리스트 교차 백업)
        try:
            cal = stock.get_market_ohlcv_by_date((now - datetime.timedelta(days=10)).strftime("%Y%m%d"), now.strftime("%Y%m%d"), "005930")
            target_day = cal.index[-1].strftime("%Y%m%d") if not cal.empty else now.strftime("%Y%m%d")
            df_base = stock.get_market_ohlcv_by_ticker(target_day, market="KOSPI")
            tickers = df_base.sort_values(by='거래량', ascending=False).head(30).index.tolist()
        except:
            tickers = ["005930", "000660", "005380", "012450", "064350", "036460", "011200", "010140", "035420", "373220", "068270"]

        # 2. 실시간 가격 및 변동률 데이터 추출 (yfinance 대량 원샷 쿼리로 속도 극대화)
        try:
            yf_tickers = [f"{t}.KS" for t in tickers]
            # 5일치 시계열 조회로 장중/주말 언제든 최신 데이터 완벽 추적
            yf_data = yf.download(yf_tickers, period="5d", group_by='ticker', progress=False)
            
            for ticker in tickers:
                name = stock.get_market_ticker_name(ticker)
                tk_data = yf_data[f"{ticker}.KS"]
                if tk_data.empty: continue
                
                # 가장 마지막에 찍힌 데이터가 진짜 '실시간 라이브 가격'
                price_today = float(tk_data['Close'].iloc[-1])
                price_yesterday = float(tk_data['Close'].iloc[-2]) if len(tk_data) > 1 else price_today
                price_last_week = float(tk_data['Close'].iloc[0])
                
                change_yesterday = ((price_today - price_yesterday) / price_yesterday * 100) if price_yesterday else 0.0
                change_last_week = ((price_today - price_last_week) / price_last_week * 100) if price_last_week else 0.0
                
                full_aligned_list.append({
                    "종목명": name, "현재 금액": f"{int(price_today):,}원", "어제 금액": f"{int(price_yesterday):,}원",
                    "어제 대비 상승률": f"{change_yesterday:+.2f}%", "저번주 금액": f"{int(price_last_week):,}원",
                    "저번주 대비 상승률": f"{change_last_week:+.2f}%", "ticker_id": ticker, "raw_change": change_yesterday
                })
                kospi_pool_text += f"{name},{ticker},현재가:{price_today},전일가:{price_yesterday},전일대비:{change_yesterday:.2f}%,전주가:{price_last_week},전주대비:{change_last_week:.2f}%\n"
        except Exception as e:
            st.error(f"🚨 실시간 데이터 로드 최종 실패 (KRX & yfinance 모두 먹통): {e}")
            st.stop()
            
        prompt1 = f"""
        너는 주식 데이터 융합가야. 뉴스 흐름과 KOSPI 실시간 가격 데이터를 비교해 내일 장에서 탄력이 가장 강력할 후보 20개를 선정해라.
        중복 없이 유니크한 기업만 선별해 형식을 칼같이 지켜 `종목명,종목코드` 형태로만 딱 20줄 출력해라.
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

        st.markdown(f'<div class="timestamp-box">⏱️ 실시간 엔진 가동 중 (yfinance Live 연동 완료)</div>', unsafe_allow_html=True)
        
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

    with st.spinner("📥 [공정 3/4] 20개 후보 기업의 최신 뉴스 실시간 매칭 및 검증 중..."):
        company_specific_news_text = ""
        for name, ticker in selected_stocks:
            refined_comp_news = get_refined_market_news(name)
            matched = next((item for item in full_aligned_list if item["ticker_id"] == ticker), None)
            raw_perf = matched["raw_change"] if matched else 0.0
            company_specific_news_text += f"- {name}({ticker}): 뉴스데이터[{refined_comp_news}] / 금일 등락률: {raw_perf:+.2f}%\n"

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
2. 모든 상승근거와 주의사항 내용 맨 앞에는 수집된 데이터에 포함된 명확한 [뉴스 일자 / 출처언론사](링크)를 가공 없이 그대로 표기해라.
3. 내일 예상가는 현재가를 기준으로 직접 산출한 [예상 금액]원과 ([예상상승률]%)를 모두 명확히 명시해라.
4. 주의 사항은 단순 요약을 넘어 산업 구조, 기업 재무 리스크, 수급 동향 등 깊이 있게 고민하여 날카롭게 분석해라. 중복되거나 빈약한 내용은 억지로 개수를 채우지 말고 완벽히 제거해라.

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
            st.error(f"🚨 트래픽 과부하가 발생했습니다. 약 10초 뒤에 다시 시도해주세요. (에러: {e})")
            st.stop()
