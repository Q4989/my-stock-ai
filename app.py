import requests
import urllib.parse
import feedparser
import streamlit as st

def get_refined_news(keyword):
    news_inputs = []
    
    # 1. [구글 뉴스] 메이저 언론사 필터링 수집
    # 연합뉴스, 이데일리, 한경, 매경 기사만 정밀 타격
    trusted_sites = "+(site:yna.co.kr+OR+site:edaily.co.kr+OR+site:hankyung.co.kr+OR+site:mk.co.kr)"
    encoded_kw = urllib.parse.quote(keyword + trusted_sites)
    google_url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=ko&gl=KR&ceid=KR:ko"
    
    feed = feedparser.parse(google_url)
    for entry in feed.entries[:3]:
        news_inputs.append(f"[구글/제도권언론] {entry.title}")
        
    # 2. [네이버 뉴스] 공식 검색 API 호출
    try:
        client_id = st.secrets["NAVER_CLIENT_ID"]
        client_secret = st.secrets["NAVER_CLIENT_SECRET"]
        
        enc_text = urllib.parse.quote(keyword)
        # sort=date (최신순), display=3 (3개 추출)
        naver_url = f"https://openapi.naver.com/v1/search/news.json?query={enc_text}&display=3&sort=date"
        
        headers = {
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret
        }
        
        response = requests.get(naver_url, headers=headers)
        if response.status_code == 200:
            items = response.json().get('items', [])
            for item in items:
                # 네이버 API는 제목에 <b> 태그 등이 섞여 나오므로 정제 필요
                clean_title = item['title'].replace('<b>', '').replace('</b>', '').replace('&quot;', '"')
                news_inputs.append(f"[네이버/실시간] {clean_title}")
    except Exception:
        pass # 네이버 키 미등록 시 구글 뉴스 데이터만 가지고 진행하도록 방탄 처리
        
    return " | ".join(news_inputs)
