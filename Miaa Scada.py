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

# 1---------------------------------------------------------------------------1. CONFIGURACIÓN DE PÁGINA ----------------------------------------------------------------------------------------------------------
st.set_page_config(
    page_title="MIAA - Estado de Pozos", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# 2-----------------------------------------------------------------------------------2. ESTILO CSS ----------------------------------------------------------------------------------------------------------
st.markdown("""
    <style>
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        [data-testid="stSidebarContent"] { padding-top: 0rem !important; }
        [data-testid="stSidebarNav"] { padding-top: 0rem !important; }
        .sidebar-logo { 
            display: flex; 
            justify-content: center; 
            padding: 0px !important; 
            margin-top: -70px !important; 
            margin-bottom: 10px;
        }
        .sidebar-logo img { max-width: 85%; height: auto; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; margin-bottom: 15px; }
        .status-tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 5px; font-weight: bold; }
        .status-ok { background-color: #1b5e20; color: #a5d6a7; }
        .status-err { background-color: #b71c1c; color: #ef9a9a; }
        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0; } 100% { opacity: 1; } }
        .blink_me { animation: blink 1.2s infinite; }
    </style>
""", unsafe_allow_html=True)

# 3--------------------------------------------------------------------------------3. FUNCIONES DE CONEXIÓN ----------------------------------------------------------------------------------------------------------
@st.cache_resource
def get_mysql_scada_engine():
    try:
        c = st.secrets["mysql_scada"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

@st.cache_resource
def get_postgres_conn():
    try: return psycopg2.connect(**st.secrets["postgres"])
    except: return None

# 4-------------------------------------------------------------------------------- 4. CARGA DE DATOS ----------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=600)
def cargar_mapa_pozos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        df_pozos = pd.read_sql("SELECT * FROM Diccionario_de_pozos", engine)
        nuevo_mapa = {}
        for _, row in df_pozos.iterrows():
            try:
                coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
                lat, lon = map(float, coords_str.split(','))
                coords = (lat, lon)
            except: continue
            nuevo_mapa[row['Pozos']] = {
                "coord": coords, "bomba": row['bomba'], "caudal": row['caudal'], "presion": row['presion'],
                "sumergencia": row['sumergencia'], "nivel_dinamico": row['nivel_dinamico'], "nivel_tanque": row['nivel_tanque'],
                "columna": row['columna'], "h_arranque": row['H_arranque'], "h_paro": row['H_paro'],
                "voltajes_l": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
                "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']]
            }
        return nuevo_mapa
    except: return {}

def cargar_datos_scada(mapa_pozos):
    engine = get_mysql_scada_engine()
    if not engine: return {}
    all_tags = []
    for p in mapa_pozos.values():
        for v in p.values():
            if isinstance(v, list): all_tags.extend([str(t) for t in v if t and str(t) not in ['0', 'Sin telemetria']])
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): all_tags.append(v)
    if not all_tags: return {}
    try:
        tags_str = "', '".join(list(set(all_tags)))
        query = f"SELECT r.NAME, h.VALUE, h.FECHA FROM VfiTagNumHistory_Ultimo h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_str}')"
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA'].strftime('%d/%m %H:%M') if row['FECHA'] else "N/A") for _, row in df.iterrows()}
    except: return {}

@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        df = pd.read_sql('SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"', conn)
        conn.close()
        return df.to_dict('records')
    except: return []

@st.cache_data(ttl=300)
def cargar_historico_detallado(id_pozo, mapa_pozos):
    engine = get_mysql_scada_engine()
    if not engine or id_pozo not in mapa_pozos: return pd.DataFrame()
    info = mapa_pozos[id_pozo]
    # Diccionario de tags a graficar (Sin horarios ni columna)
    tags_map = {
        info['caudal']: 'Caudal (l/s)', info['presion']: 'Presión (Kg/cm²)',
        info['sumergencia']: 'Sumergencia (m)', info['nivel_dinamico']: 'Nivel Dinámico (m)',
        info['voltajes_l'][0]: 'Volt L1', info['voltajes_l'][1]: 'Volt L2', info['voltajes_l'][2]: 'Volt L3',
        info['amperajes_l'][0]: 'Amp L1', info['amperajes_l'][1]: 'Amp L2', info['amperajes_l'][2]: 'Amp L3'
    }
    tags_validos = [str(t) for t in tags_map.keys() if t and str(t) not in ['0', 'Sin telemetria']]
    if not tags_validos: return pd.DataFrame()
    query = f"SELECT h.FECHA, r.NAME, h.VALUE FROM VfiTagNumHistory h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{' , '.join(tags_validos)}') AND h.FECHA >= DATE_SUB(NOW(), INTERVAL 3 DAY) ORDER BY h.FECHA ASC"
    df = pd.read_sql(query, engine)
    if df.empty: return df
    df['NAME'] = df['NAME'].map(tags_map)
    return df.pivot(index='FECHA', columns='NAME', values='VALUE').interpolate()

# --- 5. PROCESAMIENTO ---
sectores = cargar_sectores_poligonos()
mapa_pozos_dict = cargar_mapa_pozos_desde_db()
data_scada = cargar_datos_scada(mapa_pozos_dict)

pozos_on, pozos_off, pozos_sin_telemetria, pozos_falla_com = [], [], [], []
total_q, total_p = 0.0, 0.0
ahora = dt.datetime.utcnow() - dt.timedelta(hours=6)

for id_p, info in mapa_pozos_dict.items():
    bomba_val = str(info['bomba']).strip()
    if bomba_val == "Sin telemetria":
        info.update({'status_label': 'SIN TELEMETRÍA', 'color_final': '#808080', 'blink': False})
        pozos_sin_telemetria.append(id_p)
        continue
    
    tag_l1 = info['voltajes_l'][0]
    _, fecha_str = data_scada.get(tag_l1, (0, "N/A"))
    es_falla_com = False
    if fecha_str != "N/A":
        try:
            fecha_dt = dt.datetime.strptime(f"{ahora.year}/{fecha_str}", "%Y/%d/%m %H:%M")
            if (ahora - fecha_dt).total_seconds() / 3600 > 4: es_falla_com = True
        except: es_falla_com = True
    else: es_falla_com = True

    if es_falla_com:
        info.update({'status_label': 'FALLA COM.', 'color_final': '#FFA500', 'blink': True})
        pozos_falla_com.append(id_p)
    else:
        val_bba = data_scada.get(info['bomba'], (0, "N/A"))[0]
        if val_bba == 1:
            info.update({'status_label': 'OPERANDO', 'color_final': '#00FF00', 'blink': False})
            pozos_on.append(id_p)
            total_q += data_scada.get(info['caudal'], (0, 0))[0]
            total_p += data_scada.get(info['presion'], (0, 0))[0]
        else:
            info.update({'status_label': 'APAGADO', 'color_final': '#FF0000', 'blink': True})
            pozos_off.append(id_p)

# --- 5.5 GRÁFICA ---
if "pozo" in st.query_params:
    pozo_id = st.query_params["pozo"]
    if st.button("⬅️ Volver al Mapa"): st.query_params.clear(); st.rerun()
    st.title(f"📈 Análisis Detallado: {pozo_id}")
    df_plot = cargar_historico_detallado(pozo_id, mapa_pozos_dict)
    if not df_plot.empty:
        fig = go.Figure()
        # Hidráulica
        if 'Caudal (l/s)' in df_plot: fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Caudal (l/s)'], name="Caudal (l/s)", line=dict(color='#00ffff')))
        if 'Presión (Kg/cm²)' in df_plot: fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Presión (Kg/cm²)'], name="Presión", line=dict(color='#00ff00')))
        # Eléctrico (Eje 2)
        for c, clr in zip(['Volt L1','Volt L2','Volt L3','Amp L1','Amp L2','Amp L3'], ['#ffd700','#ffa500','#ff4500','#ff0000','#ff8c00','#ffff00']):
            if c in df_plot: fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot[c], name=c, yaxis="y2", line=dict(dash='dot', color=clr)))
        # Niveles (Eje 3)
        if 'Sumergencia (m)' in df_plot: fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Sumergencia (m)'], name="Sumergencia", yaxis="y3", line=dict(color='#ff00ff', width=3)))
        if 'Nivel Dinámico (m)' in df_plot: fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Nivel Dinámico (m)'], name="Nivel Dinámico", yaxis="y3", line=dict(color='#0000ff', dash='dash')))
        
        fig.update_layout(template="plotly_dark", height=700, yaxis=dict(title="Hidráulica"), yaxis2=dict(title="Eléctrico", overlaying="y", side="right"), yaxis3=dict(title="Nivel (m)", overlaying="y", side="right", anchor="free", position=0.95))
        st.plotly_chart(fig, use_container_width=True)
    else: st.warning("Sin datos históricos.")
    st.stop()

# 6 ------------------------------------------------------------------------------- SIDEBAR ------------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    with st.expander("🔌 ESTADO DE CONEXIONES", expanded=True):
        def tag(cond): return f'<span class="status-tag {"status-ok" if cond else "status-err"}">{"OK" if cond else "ERR"}</span>'
        st.markdown(f"**SCADA:** {tag(get_mysql_scada_engine())}", unsafe_allow_html=True)
        st.markdown(f"**Telemetría:** {tag(get_mysql_telemetria_engine())}", unsafe_allow_html=True)
        st.markdown(f"**PostgreSQL:** {tag(get_postgres_conn())}", unsafe_allow_html=True)
    if st.button("♻️ Actualizar Datos", use_container_width=True): st.cache_data.clear(); st.rerun()
    st.markdown(f'<div class="resumen-card"><h4 style="color:#00d4ff;margin:0;">RESUMEN</h4><p>Caudal: <b style="color:#00FF00;">{total_q:.2f} l/s</b></p><p>Presión: <b style="color:#FFFF00;">{total_p/max(len(pozos_on),1):.2f} Kg</b></p></div>', unsafe_allow_html=True)
    with st.expander(f"🟢 ON ({len(pozos_on)})"): [st.write(f"🟢 {p}") for p in sorted(pozos_on)]
    with st.expander(f"🔴 OFF ({len(pozos_off)})"): [st.write(f"🔴 {p}") for p in sorted(pozos_off)]
    with st.expander(f"🟠 Falla Com ({len(pozos_falla_com)})"): [st.write(f"🟠 {p}") for p in sorted(pozos_falla_com)]
    with st.expander(f"⚪ Sin Telemetría ({len(pozos_sin_telemetria)})"): [st.write(f"⚪ {p}") for p in sorted(pozos_sin_telemetria)]

# 7--------------------------------------------------------------------------------- MAPA -------------------------------------------------------------------------------------------------------------
m = folium.Map(location=[21.8820, -102.2800], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

for s in sectores:
    folium.GeoJson(json.loads(s['geo']), style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1}).add_to(m)

for id_p, info in mapa_pozos_dict.items():
    d = lambda tag: data_scada.get(tag, (0, "N/A"))
    is_st = (info['status_label'] == 'SIN TELEMETRÍA')
    q, f_q = d(info['caudal']); p, f_p = d(info['presion'])
    sumer, f_s = d(info['sumergencia']); dinam, f_d = d(info['nivel_dinamico'])
    tanq, f_t = d(info['nivel_tanque']); col, f_col = d(info['columna'])
    h_arr, f_arr = d(info['h_arranque']); h_par, f_par = d(info['h_paro'])
    v = [d(t) for t in info['voltajes_l']]; a = [d(t) for t in info['amperajes_l']]

    html_popup = f"""
    <div style="background: #050505; color: white; padding: 15px; border-radius: 12px; width: 380px; border: 1px solid {info['color_final']}; font-family: sans-serif;">
        <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 8px; margin-bottom: 10px;">
            <b style="color: #00d4ff; font-size: 16px;">POZO {id_p}</b>
            <span style="font-size: 10px; background: {info['color_final']}; color: black; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{info['status_label']}</span>
        </div>
        <div style="margin-bottom: 8px;">
            <div style="font-size: 10px; color: #888;">HIDRÁULICA</div>
            <div style="display: flex; font-size: 11px;">💧 Caudal: <b>{q:.2f} L/s</b> <span style="color:#ff0; font-size:8px; margin-left:auto;">{f_q}</span></div>
            <div style="display: flex; font-size: 11px;">🚀 Presión: <b>{p:.2f} kg</b> <span style="color:#ff0; font-size:8px; margin-left:auto;">{f_p}</span></div>
        </div>
        <div style="margin-bottom: 8px;">
            <div style="font-size: 10px; color: #888;">NIVELES</div>
            <div style="display: flex; font-size: 11px;">📏 Sumer: <b>{sumer:.1f} m</b> <span style="color:#ff0; font-size:8px; margin-left:auto;">{f_s}</span></div>
            <div style="display: flex; font-size: 11px;">📉 Dinam: <b>{dinam:.1f} m</b> <span style="color:#ff0; font-size:8px; margin-left:auto;">{f_d}</span></div>
            <div style="display: flex; font-size: 11px;">🏗️ Col: <b>{col:.1f} m</b> <span style="color:#ff0; font-size:8px; margin-left:auto;">{f_col}</span></div>
        </div>
        <table style="width: 100%; font-size: 10px; border-collapse: collapse; margin-bottom: 8px;">
            <tr style="color: #00d4ff; border-bottom: 1px solid #333;"><th>Fase</th><th>Voltaje</th><th>Amp</th></tr>
            <tr><td>L1-L2</td><td>{v[0][0]:.1f}V <span style="color:#ff0;">{v[0][1]}</span></td><td>{a[0][0]:.1f}A <span style="color:#ff0;">{a[0][1]}</span></td></tr>
            <tr><td>L2-L3</td><td>{v[1][0]:.1f}V <span style="color:#ff0;">{v[1][1]}</span></td><td>{a[1][0]:.1f}A <span style="color:#ff0;">{a[1][1]}</span></td></tr>
            <tr><td>L1-L3</td><td>{v[2][0]:.1f}V <span style="color:#ff0;">{v[2][1]}</span></td><td>{a[2][0]:.1f}A <span style="color:#ff0;">{a[2][1]}</span></td></tr>
        </table>
        <div style="text-align: center; margin-top: 10px;"><a href="./?pozo={id_p}" target="_self" style="text-decoration: none; background: #1f4068; color: white; padding: 8px 20px; border-radius: 6px; font-weight: bold; border: 1px solid #00d4ff;">📈 VER GRÁFICO</a></div>
    </div>
    """
    folium.Marker(location=info['coord'], icon=folium.DivIcon(icon_anchor=(-15, 12), html=f'<div style="font-size: 10px; font-weight: bold; color: {info["color_final"]}; text-shadow: 2px 2px #000;">{id_p}</div>')).add_to(m)
    if info['blink']:
        folium.Marker(location=info['coord'], icon=folium.DivIcon(html=f'<div style="width: 8px; height: 8px; background-color: {info["color_final"]}; border-radius: 50%; animation: blinker 1s linear infinite;"></div><style>@keyframes blinker {{50% {{opacity: 0.2;}}}}</style>'), popup=folium.Popup(html_popup, max_width=400)).add_to(m)
    else:
        folium.CircleMarker(location=info['coord'], radius=4, color=info['color_final'], fill=True, fill_color=info['color_final'], fill_opacity=1, popup=folium.Popup(html_popup, max_width=400)).add_to(m)

folium_static(m, width=None, height=750)
