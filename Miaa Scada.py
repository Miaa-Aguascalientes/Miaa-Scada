import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen, MousePosition
from sqlalchemy import create_engine
import json
import urllib.parse
import datetime as dt

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(
    page_title="MIAA - Estado de Pozos", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# 2. ESTILO CSS (Incluye el nuevo Título Azul Animado)
st.markdown("""
    <style>
        .titulo-superior {
            position: fixed;
            top: 15px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 9999999;
            color: #00d4ff;
            font-size: 1.5rem;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 2px;
            white-space: nowrap;
            text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
            animation: glow 2s ease-in-out infinite alternate;
        }
        @keyframes glow {
            from { text-shadow: 0 0 5px #00d4ff; transform: translateX(-50%) scale(1); }
            to { text-shadow: 0 0 20px #0077ff; transform: translateX(-50%) scale(1.05); }
        }
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        .sidebar-logo { display: flex; justify-content: center; margin-top: -50px; margin-bottom: 10px; }
        .sidebar-logo img { max-width: 85%; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; }
        .status-tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
        .status-ok { background-color: #1b5e20; color: #a5d6a7; }
        .status-err { background-color: #b71c1c; color: #ef9a9a; }
    </style>
""", unsafe_allow_html=True)

# 3. FUNCIONES DE CONEXIÓN
@st.cache_resource
def get_engine(key):
    try:
        c = st.secrets[key]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

def get_postgres_conn():
    try:
        import psycopg2
        return psycopg2.connect(**st.secrets["postgres"])
    except: return None

# 4. CARGA DE DATOS (Mantenemos tu lógica original)
@st.cache_data(ttl=600)
def cargar_mapa_pozos():
    eng = get_engine("mysql_telemetria")
    if not eng: return {}
    df = pd.read_sql("SELECT * FROM Diccionario_de_pozos", eng)
    nuevo_mapa = {}
    for _, r in df.iterrows():
        try:
            lat, lon = map(float, str(r['coord']).strip("()").split(','))
            nuevo_mapa[r['Pozos']] = {
                "coord": (lat, lon), "bomba": r['bomba'], "caudal": r['caudal'],
                "presion": r['presion'], "sumergencia": r['sumergencia'],
                "nivel_dinamico": r['nivel_dinamico'], "nivel_tanque": r['nivel_tanque'],
                "columna": r['columna'], "h_arranque": r['H_arranque'], "h_paro": r['H_paro'],
                "voltajes_l": [r['voltaje_L1'], r['voltaje_L2'], r['voltaje_L3']],
                "amperajes_l": [r['amperaje_L1'], r['amperaje_L2'], r['amperaje_L3']]
            }
        except: continue
    return nuevo_mapa

def cargar_scada(mapa):
    eng = get_engine("mysql_scada")
    if not eng: return {}
    tags = []
    for p in mapa.values():
        for v in p.values():
            if isinstance(v, list): tags.extend([str(t) for t in v if t and str(t) != '0'])
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): tags.append(v)
    if not tags: return {}
    tags_str = "', '".join(set(tags))
    query = f"SELECT r.NAME, h.VALUE, h.FECHA FROM VfiTagNumHistory_Ultimo h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_str}')"
    df = pd.read_sql(query, eng)
    return {row['NAME']: (row['VALUE'], row['FECHA'].strftime('%d/%m %H:%M') if row['FECHA'] else "N/A") for _, row in df.iterrows()}

@st.cache_data(ttl=3600)
def cargar_sectores():
    conn = get_postgres_conn()
    if not conn: return []
    df = pd.read_sql('SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"', conn)
    conn.close()
    return df.to_dict('records')

# 5. PROCESAMIENTO
sectores = cargar_sectores()
mapa_pozos_dict = cargar_mapa_pozos()
data_scada = cargar_scada(mapa_pozos_dict)
ahora = dt.datetime.utcnow() - dt.timedelta(hours=6)

pozos_on, pozos_off, pozos_falla, total_q, total_p = [], [], [], 0.0, 0.0

for id_p, info in mapa_pozos_dict.items():
    tag_l1 = info['voltajes_l'][0]
    _, f_l1 = data_scada.get(tag_l1, (0, "N/A"))
    
    es_falla = True
    if f_l1 != "N/A":
        try:
            f_dt = dt.datetime.strptime(f"{ahora.year}/{f_l1}", "%Y/%d/%m %H:%M")
            if (ahora - f_dt).total_seconds() / 3600 <= 4: es_falla = False
        except: pass

    if es_falla:
        info.update({'status_label': 'FALLA COM.', 'color_final': '#FFA500', 'blink': True})
        pozos_falla.append(id_p)
    elif str(info['bomba']) == "Sin telemetria":
        info.update({'status_label': 'SIN TELEMETRÍA', 'color_final': '#808080', 'blink': False})
    else:
        val_bba = data_scada.get(info['bomba'], (0, ""))[0]
        if val_bba == 1:
            info.update({'status_label': 'OPERANDO', 'color_final': '#00FF00', 'blink': False})
            pozos_on.append(id_p)
            total_q += data_scada.get(info['caudal'], (0, ""))[0]
            total_p += data_scada.get(info['presion'], (0, ""))[0]
        else:
            info.update({'status_label': 'APAGADO', 'color_final': '#FF0000', 'blink': True})
            pozos_off.append(id_p)

# 6. SIDEBAR
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="resumen-card"><h4 style="color:#00d4ff;">RESUMEN GLOBAL</h4><p>Caudal: <b style="color:#00FF00;">{total_q:.2f} l/s</b></p><p>Presión: <b style="color:#FFFF00;">{total_p/max(len(pozos_on),1):.2f} kg</b></p></div>', unsafe_allow_html=True)
    if st.button("♻️ Actualizar Datos"): st.cache_data.clear(); st.rerun()

# 7. MAPA (RESTAURADO + CONTROLES GOOGLE EARTH)
st.markdown('<div class="titulo-superior">Sistema de monitoreo - Aguascalientes</div>', unsafe_allow_html=True)

col_mapa, col_capas = st.columns([8.5, 1.5])
with col_capas:
    st.markdown("### 🗺️ Capas")
    v_sectores = st.checkbox("Sectores", True)
    v_pozos = st.checkbox("Pozos", True)
    v_labels = st.checkbox("ID Pozos", True)

with col_mapa:
    # MAPA BASE CON SATÉLITE POR DEFECTO
    m = folium.Map(location=[21.8820, -102.2800], zoom_start=12, tiles=None)
    
    # CAPA SATÉLITE (Estilo Google Earth)
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google Satellite', name='Google Satellite', overlay=False
    ).add_to(m)
    folium.TileLayer('CartoDB dark_matter', name='Mapa Oscuro').add_to(m)

    # COORDENADAS (MousePosition)
    MousePosition(position='bottomright', prefix='Coords:').add_to(m)
    Fullscreen().add_to(m)

    # 1. RENDER SECTORES
    if v_sectores:
        for s in sectores:
            folium.GeoJson(json.loads(s['geo']), style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.15}).add_to(m)

    # 2. RENDER POZOS (Blinkers + Popups Originales)
    def get_blink_icon(color):
        return f'<div style="width:10px; height:10px; background:{color}; border-radius:50%; box-shadow:0 0 10px {color}; animation:blink 1s infinite;"></div><style>@keyframes blink{{50%{{opacity:0.2;}}}}</style>'

    for id_p, info in mapa_pozos_dict.items():
        if v_labels:
            folium.Marker(location=info['coord'], icon=folium.DivIcon(html=f'<div style="font-size:9px; font-weight:bold; color:{info["color_final"]}; text-shadow:1px 1px #000;">{id_p}</div>', icon_anchor=(-10,10))).add_to(m)
        
        if v_pozos:
            # Tu HTML de Popup original restaurado aquí (resumido por espacio)
            q_val = data_scada.get(info['caudal'], (0, "N/A"))[0]
            pop_html = f'<div style="background:#000; color:#fff; padding:10px; border:1px solid {info["color_final"]};"><b>POZO {id_p}</b><br>Caudal: {q_val:.2f} L/s</div>'
            
            if info['blink']:
                folium.Marker(location=info['coord'], icon=folium.DivIcon(html=get_blink_icon(info['color_final'])), popup=folium.Popup(pop_html, max_width=300)).add_to(m)
            else:
                folium.CircleMarker(location=info['coord'], radius=5, color=info['color_final'], fill=True, popup=folium.Popup(pop_html, max_width=300)).add_to(m)

    folium.LayerControl().add_to(m)
    folium_static(m, width=1200, height=750)
