"""
7주차 1번 수업: 사이드바 필터, 집단 비교 및 드릴다운 추가하기
6주차 시각화 리포트와 같은 형태입니다. 오늘 여기에 필터를 붙여 대시보드로 만듭니다.
"""
import sqlite3

import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="사용자 행동 탐색 대시보드", layout="wide")
st.title("사용자 행동 탐색 대시보드")
st.caption("주별 세션 퍼널 | 플랫폼 · 유입 경로별 | 2025.07 ~ 2026.06")

# ------------------------------------------------------------
# 0. 필요한 데이터만 추출 — 쓸 테이블과 컬럼만 메모리 DB에 올리고, 정제 테이블 events를 처음 한 번만 만듦
# ------------------------------------------------------------
DATA_DIR = "data"                          # 원본 CSV를 넣어 둔 폴더
NEEDED = {                                 # 이번 대시보드에 필요한 테이블과 컬럼
    "app_events": ["event_id", "event_datetime", "customer_id", "session_id",
                   "event_name", "platform", "traffic_source"],
}

@st.cache_resource
def get_db():                              # 필요한 컬럼만 메모리 DB에 올리고, 정제 테이블 events를 만듦 (처음 한 번만)
    con = sqlite3.connect(":memory:", check_same_thread=False)
    for name, cols in NEEDED.items():
        pd.read_csv(f"{DATA_DIR}/{name}.csv", usecols=cols).to_sql(name, con, index=False)
    # 5주차 제외 규칙: QA 계정 제외 · 중복 이벤트 제거
    con.execute("""
        CREATE TABLE events AS
        SELECT event_id, event_datetime, customer_id, session_id, event_name, platform, traffic_source
          FROM (SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY session_id, event_datetime, event_name
                                          ORDER BY event_id) AS dup
                  FROM app_events
                 WHERE customer_id NOT LIKE 'QA%')
         WHERE dup = 1
    """)
    # 세션별로 묶는 집계가 빨라지도록 session_id에 인덱스를 붙임 (없으면 첫 실행이 몇 분 걸릴 수 있음)
    con.execute("CREATE INDEX idx_events_session ON events(session_id)")
    return con

# ------------------------------------------------------------
# 1. 데이터 준비 — 정제된 events 테이블을 SQL로 집계
# ------------------------------------------------------------
@st.cache_data
def query(sql):                            # SQL을 실행해 표로 돌려줌
    return pd.read_sql(sql, get_db())

# 주 × 플랫폼 × 유입 경로별 세션 퍼널
SQL_WEEKLY_FUNNEL = """
WITH s AS (                                 -- 세션의 첫 이벤트로 플랫폼 · 유입 경로 · 주 정하기
    SELECT session_id, platform, traffic_source,
           DATE(MIN(event_datetime), 'weekday 0', '-6 days') AS 주시작일
      FROM events
     GROUP BY session_id
)
SELECT s.주시작일,
       s.platform       AS 플랫폼,
       s.traffic_source AS 유입경로,
       COUNT(DISTINCT e.session_id)                                                       AS 세션수,
       COUNT(DISTINCT CASE WHEN e.event_name = 'view_restaurant' THEN e.session_id END)   AS 조회세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'add_to_cart'     THEN e.session_id END)   AS 장바구니세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'begin_checkout'  THEN e.session_id END)   AS 결제시작세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'order_complete'  THEN e.session_id END)   AS 주문세션,
       SUM(CASE WHEN e.event_name = 'payment_fail' THEN 1 ELSE 0 END)                     AS 결제실패
  FROM events e
  JOIN s ON e.session_id = s.session_id
 WHERE s.주시작일 < '2026-06-29'            -- 이틀치뿐인 마지막 주 제외
 GROUP BY 1, 2, 3
 ORDER BY 1, 2, 3
"""

@st.cache_data
def load_data():
    data = query(SQL_WEEKLY_FUNNEL)
    data["주시작일"] = pd.to_datetime(data["주시작일"]).dt.date
    return data

df = load_data()                           # 주 × 플랫폼 × 유입 경로별 세션 퍼널

# ------------------------------------------------------------
# 사이드바 필터
# ------------------------------------------------------------
st.sidebar.header("필터")

# 기간 필터 (select_slider)
dates = sorted(df["주시작일"].unique())
start_date, end_date = st.sidebar.select_slider(
    "기간",
    options=dates,
    value=(dates[0], dates[-1])
)

# 플랫폼 필터 (multiselect)
platforms = st.sidebar.multiselect(
    "플랫폼",
    options=df["플랫폼"].unique(),
    default=df["플랫폼"].unique()
)

# 유입 경로 필터 (multiselect)
traffic_sources = st.sidebar.multiselect(
    "유입 경로",
    options=df["유입경로"].unique(),
    default=df["유입경로"].unique()
)

# 세 필터를 모두 적용한 데이터 f 생성
f = df[
    (df["주시작일"] >= start_date) &
    (df["주시작일"] <= end_date) &
    (df["플랫폼"].isin(platforms)) &
    (df["유입경로"].isin(traffic_sources))
]

# f가 비어 있으면 경고 표시 후 멈춤
if f.empty:
    st.warning("선택한 조건에 해당하는 데이터가 없습니다. 필터를 바꿔 주세요.")
    st.stop()

# ------------------------------------------------------------
# 2. KPI 카드
# ------------------------------------------------------------
def rate(a, b):
    return a / b * 100 if b else 0

t = f[["세션수", "결제시작세션", "주문세션"]].sum()
c1, c2, c3 = st.columns(3)
c1.metric("세션 수", f"{t['세션수']:,}개")
c2.metric("주문 전환율 (방문 → 주문)", f"{rate(t['주문세션'], t['세션수']):.1f}%")
c3.metric("결제 전환율 (결제 시작 → 주문)", f"{rate(t['주문세션'], t['결제시작세션']):.1f}%")

st.divider()

# ------------------------------------------------------------
# 3. 차트
# ------------------------------------------------------------
left, right = st.columns(2)

# 3-1. 주별 결제 전환율 (플랫폼별)
wp = f.groupby(["주시작일", "플랫폼"])[["결제시작세션", "주문세션"]].sum().reset_index()
wp["결제전환율"] = (wp["주문세션"] / wp["결제시작세션"] * 100).round(1)
fig1 = px.line(wp, x="주시작일", y="결제전환율", color="플랫폼", markers=True,
               title="주별 결제 전환율 (플랫폼별)")
fig1.update_layout(yaxis_title="결제 전환율 (%)", xaxis_title="")
left.plotly_chart(fig1, width="stretch")

# 3-2. 세션 퍼널
steps = {"1.방문": "세션수", "2.식당조회": "조회세션", "3.장바구니": "장바구니세션",
         "4.결제시작": "결제시작세션", "5.주문완료": "주문세션"}
fun = pd.DataFrame({"단계": list(steps), "세션수": [f[c].sum() for c in steps.values()]})
fig2 = px.funnel(fun, x="세션수", y="단계", title="세션 퍼널")
right.plotly_chart(fig2, width="stretch")

# 3-3. 유입 경로별 주문 전환율
ws = f.groupby("유입경로")[["세션수", "주문세션"]].sum().reset_index()
ws["주문전환율"] = (ws["주문세션"] / ws["세션수"] * 100).round(1)
ws = ws.sort_values("주문전환율")
fig3 = px.bar(ws, x="주문전환율", y="유입경로", orientation="h", text_auto=".1f",
              hover_data=["세션수"], title="유입 경로별 주문 전환율")
fig3.update_xaxes(range=[0, ws["주문전환율"].max() * 1.2] if not ws.empty else [0, 100])
fig3.update_layout(xaxis_title="주문 전환율 (%)", yaxis_title="")
st.plotly_chart(fig3, width="stretch")

# ------------------------------------------------------------
# 4. 분석을 위한 비교 퍼널 추가 (전체 df vs 필터 적용 f 비교)
# ------------------------------------------------------------
st.divider()
st.subheader("📊 퍼널 비교 분석 (전체 vs 선택 조건)")

fun_all = pd.DataFrame({"단계": list(steps), "전체": [df[c].sum() for c in steps.values()]})
fun_filtered = pd.DataFrame({"단계": list(steps), "선택 조건": [f[c].sum() for c in steps.values()]})
fun_comp = pd.merge(fun_all, fun_filtered, on="단계")
fun_comp_melted = fun_comp.melt(id_vars="단계", value_vars=["전체", "선택 조건"], var_name="구분", value_name="세션수")

fig_comp = px.bar(
    fun_comp_melted,
    x="세션수",
    y="단계",
    color="구분",
    barmode="group",
    title="전체 데이터 vs 현재 필터 조건 퍼널 비교",
    orientation="h",
    text_auto=True
)
fig_comp.update_layout(xaxis_title="세션수", yaxis_title="")
st.plotly_chart(fig_comp, width="stretch")

# ------------------------------------------------------------
# 5. 집단 비교 영역 추가
# ------------------------------------------------------------
st.divider()
st.subheader("👥 집단 비교")

# 비교 기준 선택 (가로 배치)
group_col = st.radio("비교 기준", ["플랫폼", "유입경로"], horizontal=True)

# 집단별 5단계 퍼널 데이터 집계
step_cols = {
    "1.방문": "세션수",
    "2.식당조회": "조회세션",
    "3.장바구니": "장바구니세션",
    "4.결제시작": "결제시작세션",
    "5.주문완료": "주문세션"
}
grouped = f.groupby(group_col)[list(step_cols.values())].sum().reset_index()

# 세션 수가 500개 미만인 집단 확인
low_sessions = grouped[grouped["세션수"] < 500]
if not low_sessions.empty:
    low_group_names = ", ".join(low_sessions[group_col].astype(str))
    st.caption(f"⚠️ 경고: '{low_group_names}' 집단의 세션 수가 500개 미만으로, 값이 크게 흔들릴 수 있습니다.")

c_left, c_right = st.columns(2)

# 왼쪽: 누적 전환율(첫 단계 대비 %) 퍼널
cum_df = grouped.copy()
for col in step_cols.values():
    cum_df[col] = (cum_df[col] / cum_df["세션수"] * 100).round(1)

cum_melted = cum_df.melt(id_vars=group_col, value_vars=list(step_cols.values()), var_name="단계", value_name="누적전환율")
rev_steps = {v: k for k, v in step_cols.items()}
cum_melted["단계"] = cum_melted["단계"].map(rev_steps)

fig_left_funnel = px.funnel(
    cum_melted,
    x="누적전환율",
    y="단계",
    color=group_col,
    title=f"집단별 누적 전환율 퍼널 ({group_col} 기준)"
)
fig_left_funnel.update_layout(xaxis_title="누적 전환율 (%)", yaxis_title="")
c_left.plotly_chart(fig_left_funnel, width="stretch")

# 오른쪽: 단계 전환율(직전 단계 대비 %) 막대 (barmode="group")
step_keys = list(step_cols.keys())
step_vals = list(step_cols.values())

trans_records = []
for _, row in grouped.iterrows():
    g_val = row[group_col]
    for i in range(1, len(step_vals)):
        curr_col = step_vals[i]
        prev_col = step_vals[i-1]
        curr_val = row[curr_col]
        prev_val = row[prev_col]
        rate_val = (curr_val / prev_val * 100) if prev_val > 0 else 0
        trans_records.append({
            group_col: g_val,
            "단계": step_keys[i],
            "단계전환율": round(rate_val, 1),
            "기준세션수": prev_val
        })

trans_df = pd.DataFrame(trans_records)

fig_right_bar = px.bar(
    trans_df,
    x="단계전환율",
    y="단계",
    color=group_col,
    barmode="group",
    orientation="h",
    text_auto=".1f",
    hover_data=["기준세션수"],
    title=f"집단별 단계 전환율 비교 ({group_col} 기준)"
)
fig_right_bar.update_layout(xaxis_title="단계 전환율 (%)", yaxis_title="")
c_right.plotly_chart(fig_right_bar, width="stretch")

# ------------------------------------------------------------
# 6. 드릴다운: 언제부터, 무엇 때문일까 영역 추가
# ------------------------------------------------------------
st.divider()
st.subheader("🔍 드릴다운: 언제부터, 무엇 때문일까")

# f에 존재하는 해당 group_col의 값들 추출
available_groups = sorted(f[group_col].unique())

col_sel1, col_sel2 = st.columns(2)
selected_group = col_sel1.selectbox("자세히 볼 집단", options=available_groups)
selected_step_name = col_sel2.selectbox(
    "단계",
    options=["방문 → 식당조회", "식당조회 → 장바구니", "장바구니 → 결제시작", "결제시작 → 주문"]
)

# 단계별 분모/분자 매핑
step_mapping = {
    "방문 → 식당조회": ("세션수", "조회세션"),
    "식당조회 → 장바구니": ("조회세션", "장바구니세션"),
    "장바구니 → 결제시작": ("장바구니세션", "결제시작세션"),
    "결제시작 → 주문": ("결제시작세션", "주문세션")
}
denom_col, numer_col = step_mapping[selected_step_name]

# 다른 축 결정 (플랫폼이면 유입경로, 유입경로면 플랫폼)
other_col = "유입경로" if group_col == "플랫폼" else "플랫폼"

# 차트 ① 데이터 준비
# 선택한 집단만 필터링
f_sub = f[f[group_col] == selected_group]

# 주별, other_col별로 분모와 분자 합계 집계
df_drill1 = f_sub.groupby(["주시작일", other_col])[[denom_col, numer_col]].sum().reset_index()

# 전환율 계산 (분모가 0이면 NaN 처리하여 빈 값으로 두기)
df_drill1["전환율"] = df_drill1.apply(
    lambda row: (row[numer_col] / row[denom_col] * 100) if row[denom_col] > 0 else np.nan,
    axis=1
)
df_drill1["전환율"] = df_drill1["전환율"].round(1)

# 차트 ① (위) 선 차트
fig_drill1 = px.line(
    df_drill1,
    x="주시작일",
    y="전환율",
    color=other_col,
    markers=True,
    title=f"① {selected_group}의 주별 {selected_step_name} 전환율 — {other_col}별로 쪼개 보기"
)
fig_drill1.update_layout(yaxis_title="전환율 (%)", xaxis_title="")
st.plotly_chart(fig_drill1, width="stretch")
st.caption("모든 갈래가 같은 시점에 함께 움직였다면, 그 축은 원인이 아닙니다.")

# 차트 ② 데이터 준비 (결제실패 건수)
f_copy = f.copy()
f_copy["구분"] = np.where(f_copy[group_col] == selected_group, str(selected_group), "그 외")

df_drill2 = f_copy.groupby(["주시작일", "구분"])["결제실패"].sum().reset_index()

color_map = {str(selected_group): "darkred", "그 외": "gray"}

fig_drill2 = px.bar(
    df_drill2,
    x="주시작일",
    y="결제실패",
    color="구분",
    barmode="group",
    color_discrete_map=color_map,
    title=f"② 주별 결제 실패 건수: {selected_group}(진한 빨간색) vs 그 외(회색)"
)
fig_drill2.update_layout(yaxis_title="결제 실패 건수", xaxis_title="")
st.plotly_chart(fig_drill2, width="stretch")
st.caption("문제가 생긴 시점과 함께 움직였다면 원인 후보입니다. 함께 움직였다고 원인이 확정되지는 않습니다.")