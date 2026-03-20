import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse
from datetime import datetime
import datetime as dt
import plotly.graph_objects as go

# 1. CONFIGURACIÓN
st.set_page_config(page_title="MIAA - Estado de Pozos", layout="wide", initial_sidebar_state="expanded")

# 2. ESTILO CSS
st.markdown("""
    <style>
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        [data-testid="stSidebarContent"] { padding-top: 0rem !important; }
        .sidebar-logo { display: flex; justify-content: center; margin-top: -70px !important; margin-bottom: 10px; }
        .sidebar-logo img { max-width: 85%; height: auto; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; margin-bottom: 15px; }
        .status-tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 5px; font-weight: bold; }
        .status-ok { background-color: #1b5e20; color: #a5d6a7; }
        .status-err { background-color: #b71c1c; color: #ef9a9a; }
    </style>
""", unsafe_allow_html=True)

# 3. CONEXIONES
@st.cache_resource
def get_engine(key):
    try:
        c = st.secrets[key]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

@st.cache_resource
def get_postgres_conn():
    try: return psycopg2.connect(**st.secrets["postgres"])
    except: return None

# 4. CARGA DE DATOS
@st.cache_data(ttl=600)
def cargar_pozos_db():
    engine = get_engine("mysql_telemetria")
    if not engine: return {}
    df = pd.read_sql("SELECT * FROM Diccionario_de_pozos", engine)
    res = {}
    for _, r in df.iterrows():
        try:
            lat, lon = map(float, str(r['coord']).strip('()').split(','))
            res[r['Pozos']] = {
                "coord": (lat, lon), "bomba": r['bomba'], "caudal": r['caudal'], "presion": r['presion'],
                "sumergencia": r['sumergencia'], "nivel_dinamico": r['nivel_dinamico'], "nivel_tanque": r['nivel_tanque'],
                "columna": r['columna'], "h_arranque": r['H_arranque'], "h_paro": r['H_paro'],
                "voltajes": [r['voltaje_L1'], r['voltaje_L2'], r['voltaje_L3']],
                "amperajes": [r['amperaje_L1'], r['amperaje_L2'], r['amperaje_L3']]
            }
        except: continue
    return res

def cargar_scada_actual(mapa):
    engine = get_engine("mysql_scada")
    if not engine: return {}
    tags = []
    for p in mapa.values():
        for k, v in p.items():
            if isinstance(v, list): tags.extend([str(x) for x in v if x and str(x) not in ['0', 'Sin telemetria']])
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): tags.append(v)
    if not tags: return {}
    query = f"SELECT r.NAME, h.VALUE, h.FECHA FROM VfiTagNumHistory_Ultimo h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{f"','".join(set(tags))}')"
    df = pd.read_sql(query, engine)
    return {r['NAME']: (r['VALUE'], r['FECHA'].strftime('%d/%m %H:%M') if r['FECHA'] else "N/A") for _, r in df.iterrows()}

@st.cache_data(ttl=300)
def cargar_historico(id_p, mapa):
    engine = get_engine("mysql_scada")
    info = mapa[id_p]
    t_map = {info['caudal']: 'Caudal', info['presion']: 'Presión', info['sumergencia']: 'Sumergencia', info['nivel_dinamico']: 'Dinámico'}
    for i, v in enumerate(info['voltajes']): t_map[v] = f'Volt L{i+1}'
    for i, a in enumerate(info['amperajes']): t_map[a] = f'Amp L{i+1}'
    v_tags = [str(t) for t in t_map.keys() if t and str(t) not in ['0', 'Sin telemetria']]
    q = f"SELECT h.FECHA, r.NAME, h.VALUE FROM VfiTagNumHistory h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{f"','".join(v_tags)}') AND h.FECHA >= DATE_SUB(NOW(), INTERVAL 3 DAY)"
    df = pd.read_sql(q, engine)
    if df.empty: return df
    df['NAME'] = df['NAME'].map(t_map)
    return df.pivot(index='FECHA', columns='NAME', values='VALUE').interpolate()

# 5. PROCESAMIENTO
pozos_dict = cargar_pozos_db()
scada_data = cargar_scada_actual(pozos_dict)
on, off, st_list, falla = [], [], [], []
t_q, t_p = 0.0, 0.0
ahora = dt.datetime.utcnow() - dt.timedelta(hours=6)

for id_p, info in pozos_dict.items():
    if str(info['bomba']).strip() == "Sin telemetria":
        info.update({'status': 'SIN TELEMETRÍA', 'color': '#808080', 'blink': False})
        st_list.append(id_p); continue
    
    val_l1, f_l1 = scada_data.get(info['voltajes'][0], (0, "N/A"))
    es_falla = True
    if f_l1 != "N/A":
        try:
            f_dt = dt.datetime.strptime(f"{ahora.year}/{f_l1}", "%Y/%d/%m %H:%M")
            if (ahora - f_dt).total_seconds() / 3600 <= 4: es_falla = False
        except: pass
    
    if es_falla:
        info.update({'status': 'FALLA COM.', 'color': '#FFA500', 'blink': True}); falla.append(id_p)
    else:
        v_bba = scada_data.get(info['bomba'], (0, ""))[0]
        if v_bba == 1:
            info.update({'status': 'OPERANDO', 'color': '#00FF00', 'blink': False}); on.append(id_p)
            t_q += scada_data.get(info['caudal'], (0,0))[0]
            t_p += scada_data.get(info['presion'], (0,0))[0]
        else:
            info.update({'status': 'APAGADO', 'color': '#FF0000', 'blink': True}); off.append(id_p)

# --- VISTA GRÁFICA ---
if "pozo" in st.query_params:
    pid = st.query_params["pozo"]
    if st.button("⬅️ Volver"): st.query_params.clear(); st.rerun()
    st.title(f"📈 Análisis Detallado: {pid}")
    dfh = cargar_historico(pid, pozos_dict)
    if not dfh.empty:
        fig = go.Figure()
        if 'Caudal' in dfh: fig.add_trace(go.Scatter(x=dfh.index, y=dfh['Caudal'], name="Caudal", line=dict(color='#00ffff')))
        if 'Presión' in dfh: fig.add_trace(go.Scatter(x=dfh.index, y=dfh['Presión'], name="Presión", line=dict(color='#00ff00')))
        for c in dfh.columns:
            if 'Volt' in c or 'Amp' in c: fig.add_trace(go.Scatter(x=dfh.index, y=dfh[c], name=c, yaxis="y2", line=dict(dash='dot')))
            if 'Sumergencia' in c or 'Dinámico' in c: fig.add_trace(go.Scatter(x=dfh.index, y=dfh[c], name=c, yaxis="y3"))
        fig.update_layout(template="plotly_dark", height=600, yaxis2=dict(overlaying="y", side="right"), yaxis3=dict(overlaying="y", side="right", anchor="free", position=0.95))
        st.plotly_chart(fig, use_container_width=True)
    st.stop()

# 6. SIDEBAR
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    with st.expander("🔌 ESTADO DE CONEXIONES", expanded=True):
        def t(c): return f'<span class="status-tag {"status-ok" if c else "status-err"}">{"OK" if c else "ERR"}</span>'
        st.markdown(f"**SCADA:** {t(get_engine('mysql_scada'))}", unsafe_allow_html=True)
        st.markdown(f"**Telemetría:** {t(get_engine('mysql_telemetria'))}", unsafe_allow_html=True)
        st.markdown(f"**PostgreSQL:** {t(get_postgres_conn())}", unsafe_allow_html=True)
    st.markdown(f'<div class="resumen-card"><h4 style="color:#00d4ff;margin:0;">RESUMEN</h4><p>Q: <b>{t_q:.2f} l/s</b></p><p>P: <b>{t_p/max(len(on),1):.2f} Kg</b></p></div>', unsafe_allow_html=True)
    with st.expander(f"🟢 ON ({len(on)})"): [st.write(f"🟢 {p}") for p in sorted(on)]
    with st.expander(f"🔴 OFF ({len(off)})"): [st.write(f"🔴 {p}") for p in sorted(off)]
    with st.expander(f"🟠 Falla ({len(falla)})"): [st.write(f"🟠 {p}") for p in sorted(falla)]
    with st.expander(f"⚪ Sin Tel ({len(st_list)})"): [st.write(f"⚪ {p}") for p in sorted(st_list)]

# 7. MAPA
m = folium.Map(location=[21.8820, -102.2800], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

for id_p, info in pozos_dict.items():
    d = lambda tag: scada_data.get(tag, (0, "N/A"))
    q, fq = d(info['caudal']); p, fp = d(info['presion'])
    v = [d(t) for t in info['voltajes']]; a = [d(t) for t in info['amperajes']]
    
    popup_html = f"""<div style="background:#000; color:#fff; padding:10px; border:1px solid {info['color']}; border-radius:8px; width:300px;">
        <b style="color:#00d4ff;">POZO {id_p}</b> <small>({info['status']})</small><br><br>
        💧 Caudal: <b>{q:.2f}</b> <small style="color:#ff0;">{fq}</small><br>
        🚀 Presión: <b>{p:.2f}</b> <small style="color:#ff0;">{fp}</small><br><hr>
        <table style="width:100%; font-size:10px;">
            <tr><th>Fase</th><th>Volt</th><th>Amp</th></tr>
            {"".join([f"<tr><td>L{i+1}</td><td>{v[i][0]:.1f}V</td><td>{a[i][0]:.1f}A</td></tr>" for i in range(3)])}
        </table><br>
        <a href="./?pozo={id_p}" target="_self" style="background:#1f4068; color:#fff; padding:5px 10px; border-radius:5px; text-decoration:none; display:block; text-align:center; border:1px solid #00d4ff;">📈 VER GRÁFICA</a>
    </div>"""
    
    folium.Marker(location=info['coord'], icon=folium.DivIcon(icon_anchor=(-15, 12), html=f'<div style="font-size: 10px; font-weight: bold; color: {info["color"]}; text-shadow: 2px 2px #000;">{id_p}</div>')).add_to(m)
    if info['blink']:
        folium.Marker(location=info['coord'], icon=folium.DivIcon(html=f'<div style="width:8px; height:8px; background:{info["color"]}; border-radius:50%; animation: blinker 1s linear infinite;"></div><style>@keyframes blinker {{50% {{opacity:0.2;}}}}</style>'), popup=folium.Popup(popup_html, max_width=400)).add_to(m)
    else:
        folium.CircleMarker(location=info['coord'], radius=4, color=info['color'], fill=True, fill_color=info['color'], popup=folium.Popup(popup_html, max_width=400)).add_to(m)

folium_static(m, width=None, height=750)
