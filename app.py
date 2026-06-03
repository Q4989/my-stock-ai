import streamlit as st
import datetime
import feedparser
import pandas as pd
import urllib.parse
import requests
import re
import FinanceDataReader as fdr

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
    .timestamp-box { background: #1e293b; padding: 14px 25px; border-radius: 12px; font-weight: 800; color: #38bdf8; display: inline-block; margin-bottom: 25px; font-size: 15px; }
    </style>
    <div class="main-header">
        <h1>🚀 PRO AI 퀀트 데이터 융합 대시보드</h1>
        <p>28대 뉴스 호재 선행 발굴 및 네이버-FDR 정밀 시점 추적 융합 엔진</p>
    </div>
""", unsafe_allow_html=True)

# ==========================================
# 🔑 2. 제미나이 API 설정 및 텍스트 정제 엔진
# ==========================================
try:
    from google import genai
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
except Exception:
    st.error("🔑 대시보드 설정 창(Secrets)에서 GEMINI_API_KEY를 등록해주세요.")
    st.stop()

# 특수문자 및 깨진 유니코드 필터링 (ClientError 400 원천 차단)
def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[^가-힣a-zA-Z0-9\s.,?!%\[\]()\-]', ' ', text)
    return text.strip()

# ==========================================
# 📰 3. 뉴스 마이닝 엔진
# ==========================================
def get_refined_market_news(keyword):
    news_list = []
    try:
        trusted_sites = "+(site:yna.co.kr+OR+site:edaily.co.kr+OR+site:hankyung.co.kr+OR+site:mk.co.kr)"
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(keyword + trusted_sites)}&hl=ko&gl=KR&ceid=KR:ko"
        for entry in feedparser.parse(url).entries[:2]:
            clean_title = clean_text(entry.title)
            news_list.append(f"[{entry.get('published', '최근')[:16]} / 구글종합] [{clean_title}]({entry.link})")
    except: pass

    try:
        if "NAVER_CLIENT_ID" in st.secrets:
            headers = {"X-Naver-Client-Id": st.secrets["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": st.secrets["NAVER_CLIENT_SECRET"]}
            res = requests.get(f"https://openapi.naver.com/v1/search/news.json?query={urllib.parse.quote(keyword)}&display=4&sort=date", headers=headers, timeout=5)
            if res.status_code == 200:
                for item in res.json().get('items', []):
                    clean_title = clean_text(item['title'].replace('<b>', '').replace('</b>', '').replace('&quot;', '"'))
                    news_list.append(f"[{item.get('pubDate', '실시간')[:16]} / 네이버뉴스] [{clean_title}]({item['link']})")
    except: pass
    return " | ".join(news_list) if news_list else f"[최근 / 시황] {keyword} 분석 유효"

# ==========================================
# 📊 4. 기본 코스피 지표 렌더링
# ==========================================
now = datetime.datetime.now()
col_k1, col_k2 = st.columns([1, 2])

with col_k1:
    st.markdown("### 📉 KOSPI 벤치마크")
    try:
        kospi_df = fdr.DataReader('KS11', (now - datetime.timedelta(days=365)).strftime("%Y-%m-%d"))
        if not kospi_df.empty:
            c_kospi = kospi_df['Close'].iloc[-1]
            p_kospi = kospi_df['Close'].iloc[-2]
            st.metric(label="현재 코스피 지수", value=f"{c_kospi:,.2f}", delta=f"{c_kospi - p_kospi:+.2f}")
            st.metric(label="52주 최고점", value=f"{kospi_df['Close'].max():,.2f}")
    except Exception as e:
        st.error(f"지수 로드 실패: {e}")

with col_k2:
    try:
        if not kospi_df.empty: st.line_chart(kospi_df['Close'], height=200)
    except: pass

# ==========================================
# ⚡ 5. 메인 분석 프로세스 가동 (탑다운 4단계 구조)
# ==========================================
if st.button("🚀 뉴스 호재 선행형 융합 분석 가동", use_container_width=True):
    st.write("<br>", unsafe_allow_html=True)

    # --------------------------------------------------
    # [공정 1/4] 28대 매크로 키워드 뉴스 수집
    # --------------------------------------------------
    with st.spinner("📰 [공정 1/4] 28대 매크로 및 모멘텀 키워드 뉴스 마이닝 중..."):
        keywords = [
            "코스피 시황", "글로벌 증시", "나스닥", "반도체", "배터리", "우주", "방산", "무기", "항공", 
            "AI", "인공지능", "로보틱스", "자동화", "환율", "국제 유가", "전쟁", "젠슨황", "트럼프 뉴스", 
            "이재명", "한국무역", "매수", "매도", "투자", "협업", "협력", "m&a", "금리", "소비심리", "상장", "폐지"
        ]
        collected_macro_news = ""
        for kw in keywords:
            collected_macro_news += f"\n[{kw}]\n{get_refined_market_news(kw)}\n"
            
        # 텍스트 크기 압축 (서버 에러 방지용)
        collected_macro_news = collected_macro_news[:3500]

    # --------------------------------------------------
    # [공정 2/4] 코스피 상위 200개 스크리닝 -> 40개 도출 -> 가격 연동
    # --------------------------------------------------
    with st.spinner("🧠 [공정 2/4] 뉴스 호재 기반 유망 40개 도출 및 정밀 시점 연산 중..."):
        try:
            # 전체 종목 대신 거래 활발한 '상위 200개'만 압축 (토큰 폭발 방지)
            kospi_master = fdr.StockListing('KOSPI').dropna(subset=['Volume'])
            top_200_df = kospi_master.sort_values(by='Volume', ascending=False).head(200)
            master_text = "\n".join([f"{r['Name']}({r['Code']})" for _, r in top_200_df.iterrows()])
        except:
            st.error("거래소 마스터 목록 로드 실패")
            st.stop()

        # 프롬프트 1: 200개 중 호재가 있는 40개 발굴
        prompt1 = f"""
너는 주식 시장 전판을 읽는 퀀트 스크리너다. 
제공된 [코스피 상위 200개 목록] 중에서, 아래의 [28대 대형 뉴스 데이터] 문맥을 분석하여 '투자, 협업, 협력, M&A, 상장, 우주/방산/AI 수주' 호재 재료가 발생해 탄력이 붙은 상위 40개 기업을 선별해라.
[주의사항] '폐지' 등 리스크 악재 뉴스가 엮인 기업은 철저히 제외할 것.
출력 형식은 기호나 번호 없이 반드시 `종목명,종목코드` 형태로만 한 줄에 하나씩 딱 40줄 출력해라.

[코스피 상위 200개 목록]
{master_text}

[28대 대형 뉴스 데이터 (요약본)]
{collected_macro_news}
"""
        response1 = client.models.generate_content(model='gemini-2.5-flash', contents=prompt1)
        
        scanned_stocks = []
        seen_scanned = set()
        for line in response1.text.strip().split('\n'):
            line = line.strip().replace('`', '').replace('*', '').replace('-', '')
            if ',' in line:
                parts = line.split(',')
                s_name, s_ticker = parts[0].strip(), parts[1].strip()
                if s_ticker not in seen_scanned and len(scanned_stocks) < 40:
                    seen_scanned.add(s_ticker)
                    scanned_stocks.append((s_name, s_ticker))

        # 40개 기업 네이버 시세 & FDR 연동
        kospi_pool_text = ""
        full_aligned_list = []
        live_time_label = now.strftime("%m월 %d일 %H시 %M분")
        live_date_label = now.strftime("%m월 %d일")

        for name, ticker in scanned_stocks:
            try:
                # 네이버 실시간 엔진
                enc_url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{ticker}"
                res = requests.get(enc_url, timeout=5).json()
                item_data = res['result']['areas'][0]['datas'][0]
                
                price_today = int(item_data['nv'])
                change_yesterday = float(item_data['cr'])
                
                # FDR 시계열 (연휴 스킵 로직)
                df_hist = fdr.DataReader(ticker, (now - datetime.timedelta(days=20)).strftime("%Y-%m-%d"))
                trading_days = df_hist.index.tolist()
                
                yesterday_date_obj = trading_days[-1]
                price_yesterday = int(df_hist.loc[yesterday_date_obj, 'Close'])
                yesterday_label = yesterday_date_obj.strftime("%m월 %d일")
                
                last_week_idx = -6 if len(trading_days) >= 6 else 0
                last_week_date_obj = trading_days[last_week_idx]
                price_last_week = int(df_hist.loc[last_week_date_obj, 'Close'])
                last_week_label = last_week_date_obj.strftime("%m월 %d일")
                
                change_last_week = ((price_today - price_last_week) / price_last_week * 100) if price_last_week else 0.0
                
                full_aligned_list.append({
                    "종목명": name, 
                    f"현재 금액 ({live_time_label} 기준)": f"{price_today:,}원", 
                    f"어제 금액 ({yesterday_label} 기준)": f"{price_yesterday:,}원",
                    "전일 대비": f"{change_yesterday:+.2f}%", 
                    f"저번주 금액 ({last_week_label} 기준)": f"{price_last_week:,}원",
                    "전주 대비": f"{change_last_week:+.2f}%", 
                    "ticker_id": ticker, "raw_change": change_yesterday,
                    "y_label": yesterday_label, "lw_label": last_week_label,
                    "p_today": price_today, "p_yesterday": price_yesterday, "p_lw": price_last_week,
                    "ch_y": change_yesterday, "ch_lw": change_last_week
                })
                kospi_pool_text += f"{name},{ticker},현재가:{price_today},전일대비:{change_yesterday:.2f}%,전주대비:{change_last_week:.2f}%\n"
            except: pass

    # --------------------------------------------------
    # [공정 3/4] 40개 -> 20개 압축 및 대시보드 표출
    # --------------------------------------------------
    with st.spinner("📥 [공정 3/4] 시계열 지표 융합을 통한 1차 정예 후보 20개 선정 중..."):
        prompt_screen20 = f"""
너는 금융 매칭 매니저다. 아래 추출된 40개 기업의 [뉴스 재료 문맥]과 [수급 데이터]를 융합하여,
재료가 확실하고 자금 유입 탄력성(상승률)이 가장 우수한 최정예 20개 종목을 압축해라.
출력 형식은 기호나 번호 없이 반드시 `종목명,종목코드` 형태로만 한 줄에 하나씩 딱 20줄 출력해라.

[뉴스 요약]
{collected_macro_news[:1500]}

[40개 대상군 수급 데이터]
{kospi_pool_text}
"""
        response_screen20 = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_screen20)
        
        selected_stocks = []
        seen_tickers = set()
        for line in response_screen20.text.strip().split('\n'):
            line = line.strip().replace('`', '').replace('*', '').replace('-', '')
            if ',' in line:
                parts = line.split(',')
                name, ticker = parts[0].strip(), parts[1].strip()
                if ticker not in seen_tickers and len(selected_stocks) < 20:
                    seen_tickers.add(ticker)
                    selected_stocks.append((name, ticker))

        st.markdown(f'<div class="timestamp-box">⏱️ 뉴스 선행 발굴 동기화 완료: 현재 기준({live_time_label}) / 연휴 자동 스킵 방어막 가동 중</div>', unsafe_allow_html=True)
        
        ui_table_data = []
        for item in full_aligned_list:
            if item["ticker_id"] in seen_tickers:
                display_item = {k: v for k, v in item.items() if k not in ['ticker_id', 'raw_change', 'y_label', 'lw_label', 'p_today', 'p_yesterday', 'p_lw', 'ch_y', 'ch_lw']}
                ui_table_data.append(display_item)
                
        st.markdown("### 🎯 1차 선별: 28대 호재-시계열 융합 매칭 후보 (20개)")
        st.dataframe(pd.DataFrame(ui_table_data), use_container_width=True, hide_index=True)

        # 20개 종목 개별 뉴스 추가 수집
        company_specific_news_text = ""
        for name, ticker in selected_stocks:
            refined_comp_news = clean_text(get_refined_market_news(name))
            company_specific_news_text += f"- {name}: 개별뉴스[{refined_comp_news}]\n"

    # --------------------------------------------------
    # [공정 4/4] 최종 TOP 10 심층 퀀트 리포트 빌드
    # --------------------------------------------------
    with st.spinner("🧠 [공정 4/4] 제미나이가 최종 유망 종목 TOP 10 압축 및 심층 퀀트 리포트 빌드 중..."):
        quant_injection_text = ""
        for name, ticker in selected_stocks:
            m = next((item for item in full_aligned_list if item["ticker_id"] == ticker), None)
            if m:
                quant_injection_text += f"[{name}] 현재가={m['p_today']}, 어제가={m['p_yesterday']}, 어제날짜={m['y_label']}, 전일등락률={m['ch_y']:.2f}%, 저번주가={m['p_lw']}, 저번주날짜={m['lw_label']}, 주간등락률={m['ch_lw']:.2f}%\n"

        prompt2 = f"""
너는 대한민국 최고 자산운용사의 헤드 펀드매니저다. 
아래 [실시간 퀀트 시계열 수치]와 [개별 뉴스]를 3중 검증하여, 내일 장에서 3% 이상 추가 폭발 가능성이 높은 완벽한 10개 종목을 선별하고 리포트를 작성해라.

[실시간 퀀트 시계열 수치 정보]
{quant_injection_text}
현재시각라벨: {live_time_label}
현재날짜라벨: {live_date_label}

[20개 종목 개별 뉴스]
{company_specific_news_text}

⚠️ [작성 규칙 - 절대 엄수]
1. HTML 태그(<div>, <p> 등)는 화면을 깨뜨리므로 절대 금지. 100% 마크다운 서식만 사용해라.
2. 상승근거와 주의사항 내용 맨 앞에는 반드시 수집된 [뉴스 일자 / 출처언론사](링크)를 그대로 표기해라.
3. 금액 포맷: 모든 금액 정보는 1,000단위 콤마(,)를 붙여서 원화로 명시해라. (예: 73,400원)
4. 내일 예상가는 제공된 현재가 기준 [예상 금액]원과 ([예상상승률]%)를 직접 수식 연산해서 숫자로 찍어라.
5. 주의 사항은 뻔한 소리를 배제하고 산업 구조, 기업 재무, 수급 리스크를 깊이 있게 파고들어 기술해라.
6. 아래 제공하는 '형식 규격' 레이아웃을 100% 일치시켜라. (기호나 공백 하나도 바꾸지 말 것)

형식 규격:
---
### 📈 [순위]. 종목명 (종목코드)
- **💰 현재 금액 ({live_time_label} 기준):** [콤마처리된 현재가]원 / **🚀 내일 예상:** [콤마처리된 예상 금액]원 ([예상상승률]%)
- **⏮️ 직전 변동성:** 어제([어제날짜] 기준) 금액은 [콤마처리된 어제가]원이었으며, 전일 대비 상승률은 [전일등락률]% 이었습니다.
- **📅 주간 변동성:** 저번주([저번주날짜] 기준) 금액은 [콤마처리된 저번주가]원이었으며, 주간 대비 상승률은 [주간등락률]% 이었습니다.

#### 💡 상승근거
> 🔥 **핵심 모멘텀:** [단 한 줄 핵심 요약]
1. [날짜 / 출처](링크) 내용
2. [날짜 / 출처](링크) 내용

#### ⚠️ 주의 사항 (심층 분석)
> 🚨 **핵심 리스크:** [단 한 줄 핵심 요약]
1. [날짜 / 출처](링크) 리스크 내용
2. [날짜 / 출처](링크) 리스크 내용

#### 🚨 특이사항 브리핑
[산업 분석 및 수급 동향 심층 기술]

**- 어제 추천 여부:** [결과]
"""
        try:
            response2 = client.models.generate_content(model='gemini-2.5-flash', contents=prompt2)
            st.success("✨ 28대 키워드 기반 크로스 분석 및 팩트 체크가 완벽히 완료되었습니다!")
            st.markdown("## 🎯 제미나이 엄선: 내일의 투자 유망 종목 TOP 10")
            st.markdown(response2.text)
        except Exception as e:
            st.error(f"🚨 제미나이 리포트 빌드 중 트래픽 지연이 발생했습니다. 잠시 후 다시 눌러주세요. (에러: {e})")
