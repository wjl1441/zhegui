"""
折桂 — 考公备考助手
Streamlit 前端应用（定稿版本）
"""

import asyncio
import streamlit as st
from hybrid_engine import HybridEngine

# 页面配置
st.set_page_config(
    page_title="折桂 — 考公备考助手",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义样式
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@700;900&family=Noto+Sans+SC:wght@400;500;700;900&display=swap');

    :root {
        --primary: #8b5a1f;
        --primary-600: #6f4515;
        --accent: #c18a32;
        --bg: #f6f1e7;
        --paper: #fffaf0;
        --ink: #241a12;
        --muted: #75685b;
        --line: #e7d9c3;
        --soft-line: #f0e5d3;
        --user-bubble: #f5ead8;
        --code-tag: #e7f1df;
        --code-fg: #416a2f;
        --model-tag: #fff0d6;
        --model-fg: #956118;
        --shadow: 0 22px 58px rgba(82,55,25,.14), 0 2px 10px rgba(82,55,25,.07);
        --radius-lg: 24px;
        --radius-md: 16px;
        --radius-sm: 10px;
    }

    /* Streamlit chrome */
    .stApp {
        background:
            radial-gradient(circle at 12% -6%, rgba(193,138,50,.18), transparent 34%),
            radial-gradient(circle at 92% 12%, rgba(95,124,70,.11), transparent 30%),
            linear-gradient(135deg,#fffaf0 0%,var(--bg) 48%,#eee2ce 100%);
        color: var(--ink);
        font-family: "Noto Sans SC", system-ui, sans-serif;
    }
    .stApp:before {
        content:"";
        position: fixed; inset: 0; pointer-events: none; z-index: 0;
        opacity: .38;
        background-image: radial-gradient(rgba(70,48,25,.11) .65px, transparent .65px);
        background-size: 18px 18px;
        mask-image: linear-gradient(to bottom, #000, transparent 72%);
    }
    footer, #MainMenu {visibility: hidden;}
    header[data-testid="stHeader"] {background: transparent;}
    .block-container {
        max-width: 1180px;
        padding-top: 1.15rem;
        padding-bottom: 5rem;
    }
    [data-testid="stMarkdownContainer"] p {line-height: 1.75;}

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg,#fbfdff,#f4f7fb);
        border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] > div:first-child {padding-top: 1.4rem;}
    .zg-sidebar-brand {
        display: flex; align-items: center; gap: 12px;
        padding: 4px 2px 18px;
    }
    .zg-logo {
        width: 42px; height: 42px; border-radius: 14px;
        display: grid; place-items: center;
        color: white; font-family: "Noto Serif SC", "Songti SC", SimSun, serif;
        font-size: 21px; font-weight: 900;
        background: linear-gradient(135deg, #9b6a27, #d1a24a 58%, #7b4b19);
        box-shadow: 0 14px 30px rgba(139,90,31,.26);
    }
    .zg-brand-title {font-size: 22px; font-weight: 900; letter-spacing: -.04em; color: var(--ink);}
    .zg-brand-sub {font-size: 12px; color: var(--muted); margin-top: -2px;}
    [data-testid="stSidebar"] hr {margin: 1.1rem 0; border-color: var(--soft-line);}
    [data-testid="stSidebar"] h3 {font-size: 15px; letter-spacing: -.02em; color: #26364f;}

    /* Stat cards */
    .stat-card {
        background: rgba(255,255,255,.86);
        padding: 15px 16px;
        border-radius: 18px;
        border: 1px solid var(--soft-line);
        box-shadow: 0 8px 20px rgba(26,50,92,.045);
        margin-bottom: 10px;
    }
    .stat-value {
        font-size: 25px;
        line-height: 1;
        font-weight: 900;
        letter-spacing: -.04em;
        color: var(--primary);
    }
    .stat-value.green {color: var(--code-fg);}
    .stat-label {
        margin-top: 8px;
        font-size: 12px;
        color: var(--muted);
        font-weight: 700;
    }

    /* Native controls */
    .stButton > button {
        border-radius: 14px !important;
        border: 1px solid transparent !important;
        background: transparent !important;
        color: #2d394c !important;
        font-weight: 800 !important;
        min-height: 44px;
        transition: transform .18s ease, background .18s ease, border-color .18s ease, color .18s ease, box-shadow .18s ease;
    }
    .stButton > button:hover {
        background: #eef5ff !important;
        border-color: #d5e6ff !important;
        color: var(--primary) !important;
        transform: translateX(2px);
        box-shadow: none !important;
    }
    .stButton > button:focus {box-shadow: 0 0 0 4px rgba(26,115,232,.14) !important;}
    [data-baseweb="select"] > div {
        border-radius: 999px !important;
        border-color: var(--line) !important;
        background: #fff !important;
        font-weight: 800;
    }

    /* Topbar / empty state */
    .zg-topbar {
        position: sticky; top: 0; z-index: 10;
        display: flex; justify-content: space-between; align-items: center; gap: 16px;
        padding: 13px 18px;
        margin: 0 0 18px;
        border: 1px solid rgba(223,229,238,.78);
        border-radius: 22px;
        background: rgba(255,255,255,.82);
        box-shadow: 0 10px 30px rgba(26,50,92,.07);
        backdrop-filter: blur(18px);
    }
    .zg-top-left {display:flex; align-items:center; gap:12px; min-width:0;}
    .zg-top-title {font-weight: 950; font-size: 21px; letter-spacing: -.04em;}
    .zg-top-sub {color: var(--muted); font-size: 12px; margin-top: 1px;}
    .zg-district {
        white-space: nowrap;
        color: #31415c;
        font-weight: 850;
        font-size: 13px;
        padding: 9px 13px;
        border: 1px solid var(--line);
        border-radius: 999px;
        background: #fbfdff;
    }
    .zg-hero {
        margin: 16px 0 22px;
        padding: 24px 26px;
        border-radius: 26px;
        background: rgba(255,250,240,.82);
        border: 1px solid rgba(231,217,195,.82);
        box-shadow: var(--shadow);
        position: relative;
        overflow: hidden;
    }
    .zg-hero:after {
        content: ""; position: absolute; right: -74px; top: -92px;
        width: 240px; height: 240px; border-radius: 50%;
        background: conic-gradient(from 150deg, rgba(193,138,50,.26), rgba(75,106,47,.12), transparent 68%);
    }
    .zg-eyebrow {font-size: 12px; font-weight: 900; letter-spacing: .16em; text-transform: uppercase; color: var(--primary);}
    .zg-hero h1 {margin: 10px 0 10px; font-family:"Noto Serif SC", "Songti SC", SimSun, serif; font-size: clamp(34px, 4.8vw, 58px); line-height: 1.02; letter-spacing: -.07em; text-wrap: balance;}
    .zg-hero p {max-width: 720px; color: var(--muted); font-size: 15px; margin: 0;}
    .zg-pills {display:flex; gap:9px; flex-wrap:wrap; margin-top:18px;}
    .zg-pill {display:inline-flex; align-items:center; gap:7px; padding:8px 11px; border-radius:999px; background:#f3f7fd; border:1px solid var(--line); color:#31415c; font-weight:800; font-size:12px;}

    /* Chat */
    [data-testid="stChatMessage"] {
        border: 0;
        padding: 0.15rem 0;
        background: transparent;
    }
    [data-testid="stChatMessageContent"] {
        border-radius: 22px;
        padding: 15px 18px;
        border: 1px solid rgba(223,229,238,.72);
        box-shadow: 0 12px 30px rgba(26,50,92,.07);
        background: #fff;
        max-width: min(790px, 92%);
    }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] {
        background: var(--user-bubble);
        border-color: #d6e4ff;
        box-shadow: none;
        border-top-left-radius: 8px;
    }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) [data-testid="stChatMessageContent"] {
        margin-left: auto;
        border-top-right-radius: 8px;
    }
    [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {font-size: 15px;}

    .flow-tag {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 6px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 850;
        margin: 4px 6px 0 0;
        white-space: nowrap;
    }
    .code-tag {background-color: var(--code-tag); color: var(--code-fg);}
    .model-tag {background-color: var(--model-tag); color: var(--model-fg);}

    /* Chat input */
    [data-testid="stChatInput"] textarea {
        border-radius: 18px !important;
        border: 1px solid var(--line) !important;
        background: #fbfdff !important;
        min-height: 52px !important;
    }
    [data-testid="stChatInput"] textarea:focus {
        border-color: var(--primary) !important;
        box-shadow: 0 0 0 4px rgba(26,115,232,.12) !important;
        background: #fff !important;
    }
    [data-testid="stChatInput"] {
        background: rgba(255,255,255,.82);
        backdrop-filter: blur(18px);
        border-radius: 22px;
        border: 1px solid var(--soft-line);
        box-shadow: 0 18px 42px rgba(26,50,92,.10);
        padding: 8px;
    }

    .footer {
        position: fixed;
        bottom: 10px;
        left: 50%;
        transform: translateX(-50%);
        background: rgba(255,255,255,.84);
        backdrop-filter: blur(14px);
        padding: 8px 14px;
        text-align: center;
        font-size: 12px;
        color: var(--muted);
        border: 1px solid var(--soft-line);
        border-radius: 999px;
        z-index: 100;
        box-shadow: 0 10px 30px rgba(26,50,92,.08);
    }

    @media (max-width: 760px) {
        .block-container {padding-left: .85rem; padding-right: .85rem;}
        .zg-topbar {align-items:flex-start; flex-direction: column;}
        .zg-district {white-space: normal;}
        .zg-hero {padding: 20px;}
        [data-testid="stChatMessageContent"] {max-width: 100%;}
        .footer {display:none;}
    }
</style>
""", unsafe_allow_html=True)

# 初始化混合引擎（缓存实例）
@st.cache_resource
def get_engine():
    return HybridEngine()

engine = get_engine()

# 初始化会话状态
if "messages" not in st.session_state:
    st.session_state.messages = []
if "flow_logs" not in st.session_state:
    st.session_state.flow_logs = []
if "stats" not in st.session_state:
    st.session_state.stats = {"code_calls": 0, "model_calls": 0, "tokens_saved": 0}
if "province" not in st.session_state:
    st.session_state.province = "国考副省级"
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None

# 侧边栏
with st.sidebar:
    # Logo
    st.markdown("""
    <div class="zg-sidebar-brand">
        <div class="zg-logo">桂</div>
        <div>
            <div class="zg-brand-title">折桂</div>
            <div class="zg-brand-sub">可观测的考公备考 Agent</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    # 混合统计
    st.markdown("### 📊 混合统计")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{st.session_state.stats['code_calls']}</div>
            <div class="stat-label">代码驱动调用</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{st.session_state.stats['model_calls']}</div>
            <div class="stat-label">模型驱动调用</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="stat-card">
        <div class="stat-value green">~{st.session_state.stats['tokens_saved']}</div>
        <div class="stat-label">节省 Token</div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # 考区切换
    st.markdown("### 🗺️ 考区")
    province_options = ["国考副省级", "国考地市", "湖北", "贵州", "江苏", "广东", "浙江"]
    new_province = st.selectbox(
        "选择考区",
        province_options,
        index=province_options.index(st.session_state.province),
        label_visibility="collapsed"
    )
    if new_province != st.session_state.province:
        st.session_state.province = new_province
        st.toast(f"已切换到 {new_province}")

    st.divider()

    # 功能入口
    st.markdown("### 🚀 功能")
    if st.button("📊 刷题分析", use_container_width=True):
        st.session_state.pending_prompt = "我想刷题分析"
        st.rerun()
    if st.button("📋 模考复盘", use_container_width=True):
        st.session_state.pending_prompt = "我想做模考复盘"
        st.rerun()
    if st.button("🎯 考前策略", use_container_width=True):
        st.session_state.pending_prompt = f"快考试了，我是{st.session_state.province}"
        st.rerun()
    if st.button("🗓️ 7天学习计划", use_container_width=True):
        st.session_state.pending_prompt = "请根据我的错题和模考记录生成7天学习计划"
        st.rerun()

    st.divider()

    # 清空对话
    if st.button("🗑️ 清空对话", use_container_width=True):
        st.session_state.messages = []
        st.session_state.flow_logs = []
        st.session_state.stats = {"code_calls": 0, "model_calls": 0, "tokens_saved": 0}
        st.rerun()

# 主对话区
# 顶栏
st.markdown(f"""
<div class="zg-topbar">
    <div class="zg-top-left">
        <div class="zg-logo">桂</div>
        <div>
            <div class="zg-top-title">折桂</div>
            <div class="zg-top-sub">代码驱动优先 · 路径透明 · 专注提分</div>
        </div>
    </div>
    <div class="zg-district">当前考区：{st.session_state.province}</div>
</div>
""", unsafe_allow_html=True)

if not st.session_state.messages:
    st.markdown("""
    <section class="zg-hero">
        <div class="zg-eyebrow">Zhegui Exam Review Agent</div>
        <h1>把刷题记录，变成下一步提分动作。</h1>
        <p>你可以直接输入「20 道对了 12 道」「贵州模考资料 15 对 10」或「只剩 10 天怎么安排」。折桂会把代码计算、知识库匹配和模型建议拆开展示，避免玄学式复盘。</p>
        <div class="zg-pills">
            <span class="zg-pill">📊 刷题正确率分析</span>
            <span class="zg-pill">📋 模考六步复盘</span>
            <span class="zg-pill">🎯 考前时间策略</span>
            <span class="zg-pill">🗓️ 7天学习计划</span>
            <span class="zg-pill">✅ 代码/模型路径透明</span>
        </div>
    </section>
    """, unsafe_allow_html=True)

# 显示历史消息
for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        # 如果是助手消息，显示混合路径标签
        flow_log = msg.get("flow_log", []) if msg["role"] == "assistant" else []
        if not flow_log and msg["role"] == "assistant":
            # 兼容旧会话：助手消息通常对应前一条用户消息的 flow_logs
            legacy_index = max(0, (i - 1) // 2)
            if legacy_index < len(st.session_state.flow_logs):
                flow_log = st.session_state.flow_logs[legacy_index]
        if flow_log:
            flow_tags_html = ""
            for step in flow_log:
                if step["node_type"] == "代码":
                    flow_tags_html += f'<span class="flow-tag code-tag">✅ 代码驱动：{step["tool_name"]}</span>'
                else:
                    flow_tags_html += f'<span class="flow-tag model-tag">🤖 模型驱动：{step["tool_name"]}</span>'
            st.markdown(f'<div style="margin-top: 8px; padding-top: 10px; border-top: 1px solid var(--soft-line);">{flow_tags_html}</div>', unsafe_allow_html=True)

# 用户输入
chat_prompt = st.chat_input("说说你今天刷了多少题...", key="chat_input")
prompt = st.session_state.pending_prompt or chat_prompt
if st.session_state.pending_prompt:
    st.session_state.pending_prompt = None

if prompt:
    # 显示用户消息
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.flow_logs.append([])

    # 调用混合引擎
    with st.chat_message("assistant"):
        with st.spinner("正在分析..."):
            try:
                # 运行异步引擎
                result = asyncio.run(engine.process(prompt))

                # 显示回复
                st.markdown(result["response"])

                # 保存流程日志
                flow_log_data = [
                    {
                        "node_type": step.node_type,
                        "tool_name": step.tool_name,
                        "success": step.success
                    }
                    for step in result["flow_log"]
                ]
                st.session_state.flow_logs[-1] = flow_log_data

                # 显示混合路径标签
                flow_tags_html = ""
                for step in flow_log_data:
                    if step["node_type"] == "代码":
                        flow_tags_html += f'<span class="flow-tag code-tag">✅ 代码驱动：{step["tool_name"]}</span>'
                    else:
                        flow_tags_html += f'<span class="flow-tag model-tag">🤖 模型驱动：{step["tool_name"]}</span>'
                st.markdown(f'<div style="margin-top: 8px; padding-top: 10px; border-top: 1px solid var(--soft-line);">{flow_tags_html}</div>', unsafe_allow_html=True)

                # 更新统计
                model_calls = sum(1 for s in flow_log_data if s["node_type"] == "模型")
                code_calls = sum(1 for s in flow_log_data if s["node_type"] == "代码")
                st.session_state.stats["model_calls"] += model_calls
                st.session_state.stats["code_calls"] += code_calls
                st.session_state.stats["tokens_saved"] += code_calls * 800  # 估算每次代码调用节省 800 token

                # 保存助手消息
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": result["response"],
                    "flow_log": flow_log_data
                })

            except Exception as e:
                error_msg = f"处理出错：{str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_msg
                })
                st.session_state.flow_logs.append([])

# 底栏
st.markdown("""
<div class="footer">
    折桂 — 混合引擎考公备考助手 | 代码驱动优先，节省 Token
</div>
""", unsafe_allow_html=True)
