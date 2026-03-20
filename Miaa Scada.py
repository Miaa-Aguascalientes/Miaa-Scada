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

# 1---------------------------------------------------------------------------1. CONFIGURACIÓN DE PÁGINA ----------------------------------------------------------------------------------------------------------
st.set_page_config(
    page_title="MIAA - Estado de Pozos", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# 2-----------------------------------------------------------------------------------2. ESTILO CSS GENERAL ----------------------------------------------------------------------------------------------------------
st.markdown("""
    <style>
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        [data-testid="stSidebarContent"] { padding-top: 0rem !important; }
        .sidebar-logo { display: flex; justify-content: center; margin-top: -70px !important; margin-bottom: 10px; }
        .sidebar-logo img { max-width: 85%; height: auto; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; margin-bottom: 15px; }
        .status-tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
        .status-ok { background-color: #1b5e20; color: #a5d6a7; }
        .status-err { background-color: #b71c1c; color: #ef9a9a; }
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
                lat, lon = map(float, str(row['coord']).strip("()").split(','))
                nuevo_mapa[row['Pozos']] = {
                    "coord": (lat, lon), "bomba": row['bomba'], "caudal": row['caudal'],
                    "presion": row['presion'], "sumergencia": row['sumergencia'],
                    "nivel_dinamico": row['nivel_dinamico'], "nivel_tanque": row['nivel_tanque'],
                    "columna": row['columna'], "h_arranque": row['H_arranque'], "h_paro": row['H_paro'],
                    "voltajes_l": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
                    "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']]
                }
            except: continue
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
        query = f"SELECT r.NAME, h.VALUE, h.FECHA FROM VfiTagNumHistory_Ultimo h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_str}') AND h.FECHA = (SELECT MAX(FECHA) FROM VfiTagNumHistory_Ultimo WHERE GATEID = h.GATEID)"
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

# 5-------------------------------------------------------------------------------- 5. PROCESAMIENTO ----------------------------------------------------------------------------------------------------------
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

    # Lógica de Falla de Comunicación
    tag_l1 = info['voltajes_l'][0]
    _, fecha_str = data_scada.get(tag_l1, (0, "N/A"))
    es_falla_com = True
    if fecha_str != "N/A":
        try:
            f_dt = dt.datetime.strptime(f"{ahora.year}/{fecha_str}", "%Y/%d/%m %H:%M")
            if (ahora - f_dt).total_seconds() / 3600 <= 4: es_falla_com = False
        except: pass

    if es_falla_com:
        info.update({'status_label': 'FALLA COM.', 'color_final': '#FFA500', 'blink': True})
        pozos_falla_com.append(id_p)
    else:
        val_bba, _ = data_scada.get(info['bomba'], (0, "N/A"))
        if val_bba == 1:
            info.update({'status_label': 'OPERANDO', 'color_final': '#00FF00', 'blink': False})
            pozos_on.append(id_p)
            total_q += data_scada.get(info['caudal'], (0, ""))[0]
            total_p += data_scada.get(info['presion'], (0, ""))[0]
        else:
            # AQUÍ SE ACTIVA EL PARPADEO PARA LOS ROJOS
            info.update({'status_label': 'APAGADO', 'color_final': '#FF0000', 'blink': True})
            pozos_off.append(id_p)
            
# 6 ------------------------------------------------------------------------------- 6. SIDEBAR ------------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    
    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

    st.markdown(f'<div class="resumen-card"><h4 style="color:#00d4ff;margin:0;">RESUMEN</h4><p>Caudal: <b style="color:#00FF00;">{total_q:.2f} l/s</b><br>Presión: <b style="color:#FFFF00;">{total_p/max(len(pozos_on),1):.2f} kg</b></p></div>', unsafe_allow_html=True)
    
    with st.expander(f"🟢 ON ({len(pozos_on)})"):
        for p in sorted(pozos_on): st.write(f"🟢 {p}")
    with st.expander(f"🔴 OFF ({len(pozos_off)})"):
        for p in sorted(pozos_off): st.write(f"🔴 {p}")
    if pozos_falla_com:
        with st.expander(f"⚠️ FALLA COM ({len(pozos_falla_com)})"):
            for p in sorted(pozos_falla_com): st.write(f"🟠 {p}")

# 7--------------------------------------------------------------------------------- 7. MAPA -------------------------------------------------------------------------------------------------------------
m = folium.Map(location=[21.8820, -102.2800], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

# --- INYECCIÓN DE CSS ULTRA-FORZADA ---
# Definimos la animación y la aplicamos a cualquier elemento con la clase .blink_me
# Pero también atacamos directamente al 'path' de Leaflet que es lo que realmente se dibuja.
estilo_final = """
<style>
@keyframes blinker_miaa {
    0% { opacity: 1.0; }
    50% { opacity: 0.1; }
    100% { opacity: 1.0; }
}
.blink_me {
    animation: blinker_miaa 1s linear infinite !important;
}
/* Esta línea es crítica: obliga al motor SVG del mapa a animar el círculo */
.leaflet-interactive.blink_me {
    animation: blinker_miaa 1s linear infinite !important;
}
</style>
"""
m.get_root().header.add_child(folium.Element(estilo_final))

for s in sectores:
    folium.GeoJson(json.loads(s['geo']), style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1}).add_to(m)

for id_p, info in mapa_pozos_dict.items():
    d = lambda tag: data_scada.get(tag, (0, "N/A"))
    is_st = (info['status_label'] == 'SIN TELEMETRÍA')
    q, _ = d(info['caudal']) if not is_st else (0.0, "N/A")
    p, _ = d(info['presion']) if not is_st else (0.0, "N/A")

    html_popup = f"<div style='background:#000;color:#fff;padding:10px;'><b>POZO {id_p}</b><br>Status: {info['status_label']}</div>"

    # APLICACIÓN DE CLASE DINÁMICA
    clase_animacion = "blink_me" if info.get('blink') else ""

    folium.CircleMarker(
        location=info['coord'],
        radius=8, # Un poco más grande para que se note
        color=info['color_final'],
        fill=True,
        fill_color=info['color_final'],
        fill_opacity=1,
        weight=3,
        class_name=clase_animacion, # CLAVE
        popup=folium.Popup(html_popup, max_width=200)
    ).add_to(m)

    folium.map.Marker(
        location=info['coord'],
        icon=folium.DivIcon(html=f'<div style="font-size:10px; font-weight:bold; color:{info["color_final"]}; transform:translate(12px, -10px);">{id_p}</div>')
    ).add_to(m)

folium_static(m, width=None, height=750)
