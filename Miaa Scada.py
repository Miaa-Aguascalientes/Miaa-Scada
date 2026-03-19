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

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(
    page_title="MIAA - Estado de Pozos", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# 2. ESTILO CSS (Se mantienen estilos y animaciones)
st.markdown("""
    <style>
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        .sidebar-logo { display: flex; justify-content: center; padding: 10px 0 20px 0; }
        .sidebar-logo img { max-width: 85%; height: auto; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; margin-bottom: 15px; }
        .section-header { padding: 10px; border-radius: 3px; font-weight: bold; margin-bottom: 5px; color: white; }
        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0; } 100% { opacity: 1; } }
        .blink_me { animation: blink 1.2s infinite; }
    </style>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE POZOS
mapa_pozos_dict = {
    "P005A": {
        "coord": (21.89147, -102.23195), 
        "bomba": "PZ_RP_005_TRHDAS_BBA_CRUDO", 
        "caudal": "PZ_RP_005_TRHDAS_CAU_INS", 
        "presion": "PZ_RP_005_TRHDAS_PRES_INS", 
        "sumergencia": "PZ_RP_005_TRHDAS_SUMERG", 
        "nivel_dinamico": "PZ_RP_005_TRHDAS_NIV_EST", 
        "nivel_tanque": "RB_241_NIV_TQ_R", 
        "voltajes_l": ["PZ_RP_005_TRHDAS_VOL_L1_L2", "PZ_RP_005_TRHDAS_VOL_L2_L3", "PZ_RP_005_TRHDAS_VOL_L1_L3"],
        "amperajes_l": ["PZ_RP_005_TRHDAS_CORR_L1", "PZ_RP_005_TRHDAS_CORR_L2", "PZ_RP_005_TRHDAS_CORR_L3"]
    },
    "P006": {
        "coord": (21.91504, -102.281668), 
        "bomba": "PZ_006_TRC_BBA_CRUDO", 
        "caudal": "PZ_006_TRC_CAU_INS", 
        "presion": "PZ_006_TRC_PRES_INS", 
        "sumergencia": "PZ_006_TRC_SUMERG", 
        "nivel_dinamico": "PZ_006_TRC_NIV_EST",
        "nivel_tanque": "0", 
        "voltajes_l": ["PZ_006_TRC_VOL_L1_L2", "PZ_006_TRC_VOL_L2_L3", "PZ_006_TRC_VOL_L1_L3"],
        "amperajes_l": ["PZ_006_TRC_CORR_L1", "PZ_006_TRC_CORR_L2", "PZ_006_TRC_CORR_L3"]
    }
}

# 4. FUNCIONES DE CONEXIÓN
@st.cache_resource
def get_mysql_engine():
    try:
        c = st.secrets["mysql"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

@st.cache_resource
def get_postgres_conn():
    try: return psycopg2.connect(**st.secrets["postgres"])
    except: return None

def cargar_datos_scada():
    engine = get_mysql_engine()
    if not engine: return {}
    all_tags = []
    for p in mapa_pozos_dict.values():
        for k, v in p.items():
            if isinstance(v, list): all_tags.extend(v)
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): all_tags.append(v)
    try:
        tags_str = "', '".join(list(set(all_tags)))
        query = f"""
            SELECT r.NAME, h.VALUE, h.FECHA 
            FROM vfitagnumhistory h 
            JOIN VfiTagRef r ON h.GATEID = r.GATEID 
            WHERE r.NAME IN ('{tags_str}') 
            AND h.FECHA = (SELECT MAX(FECHA) FROM vfitagnumhistory WHERE GATEID = h.GATEID)
        """
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA'].strftime('%d/%m %H:%M') if row['FECHA'] else "N/A") for _, row in df.iterrows()}
    except: return {}

@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        # Forzamos la transformación a 4326 para asegurar compatibilidad con Folium
        query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
        df = pd.read_sql(query, conn)
        conn.close()
        return df.to_dict('records')
    except Exception as e:
        st.sidebar.error(f"Error en Sectores: {e}")
        return []

# --- 5. PROCESAMIENTO ---
data_scada = cargar_datos_scada()
sectores = cargar_sectores_poligonos()

pozos_on, pozos_off = [], []
total_q, total_p = 0.0, 0.0

for id_p, info in mapa_pozos_dict.items():
    val_bba, f_bba = data_scada.get(info['bomba'], (0, "N/A"))
    q_val = data_scada.get(info['caudal'], (0, "0"))[0]
    p_val = data_scada.get(info['presion'], (0, "0"))[0]
    
    if val_bba == 1:
        info.update({'status_label': 'OPERANDO', 'color_final': '#00FF00', 'blink': False})
        pozos_on.append(id_p)
        total_q += float(q_val)
        total_p += float(p_val)
    else:
        info.update({'status_label': 'APAGADO', 'color_final': '#FF0000', 'blink': True})
        pozos_off.append(id_p)

# --- 6. SIDEBAR ---
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    st.markdown("<h2 style='color:#00d4ff; text-align:center;'>Estado de Pozos</h2>", unsafe_allow_html=True)

    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()
    
    st.divider() 
    
    st.markdown(f"""
    <div class="resumen-card">
        <h4 style="color:#00d4ff; margin-top:0;">RESUMEN GLOBAL</h4>
        <p>Caudal Total: <b style="color:#00FF00;">{total_q:.2f} l/s</b></p>
        <p>Presión Prom: <b style="color:#FFFF00;">{total_p/max(len(pozos_on),1):.2f} Kg/cm²</b></p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"<div class='section-header' style='background:#1b5e20;'>Bombas ON ({len(pozos_on)})</div>", unsafe_allow_html=True)
    for p in pozos_on: st.write(f"🟢 {p}")
    st.markdown(f"<div class='section-header' style='background:#b71c1c;'>Bombas OFF ({len(pozos_off)})</div>", unsafe_allow_html=True)
    for p in pozos_off: st.write(f"🔴 {p}")

# --- 7. MAPA ---
m = folium.Map(location=[21.8820, -102.2900], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

# Dibujar Sectores (Capa de Polígonos)
if sectores:
    for s in sectores:
        try:
            geojson_data = json.loads(s['geo'])
            folium.GeoJson(
                geojson_data,
                name=f"Sector {s['sector']}",
                style_function=lambda x: {
                    'fillColor': '#00d4ff',
                    'color': '#00d4ff',
                    'weight': 1.5,
                    'fillOpacity': 0.2
                },
                tooltip=f"Sector: {s['sector']}"
            ).add_to(m)
        except Exception as e:
            continue

# Dibujar Pozos (Marcadores)
for id_p, info in mapa_pozos_dict.items():
    d = lambda tag: data_scada.get(tag, (0, "N/A"))
    q, f_q = d(info['caudal'])
    p, f_p = d(info['presion'])
    sumer, f_s = d(info['sumergencia'])
    dinam, f_d = d(info['nivel_dinamico'])
    tanq, f_t = d(info['nivel_tanque'])
    
    v = [d(t) for t in info['voltajes_l']]
    a = [d(t) for t in info['amperajes_l']]

    html_popup = f"""
    <div style="background: #050505; color: white; padding: 15px; border-radius: 12px; width: 380px; border: 1px solid {info['color_final']}; font-family: sans-serif;">
        <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 8px; margin-bottom: 10px;">
            <b style="color: #00d4ff; font-size: 16px;">POZO {id_p}</b>
            <span style="font-size: 10px; background: {info['color_final']}; color: black; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{info['status_label']}</span>
        </div>
        
        <div style="margin-bottom: 12px;">
            <div style="font-size: 10px; color: #888; margin-bottom: 4px;">HIDRÁULICA</div>
            <div style="display: flex; align-items: baseline; font-size: 12px; margin-bottom: 3px;">
                <span>💧 Caudal: <b>{q:.2f} L/s</b></span>
                <span style="color: #FFFF00; font-size: 9px; margin-left: auto;">{f_q}</span>
            </div>
            <div style="display: flex; align-items: baseline; font-size: 12px;">
                <span>🚀 Presión: <b>{p:.2f} kg</b></span>
                <span style="color: #FFFF00; font-size: 9px; margin-left: auto;">{f_p}</span>
            </div>
        </div>
        
        <div style="margin-bottom: 12px;">
            <div style="font-size: 10px; color: #888; margin-bottom: 4px;">NIVELES</div>
            <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                <span>Sumergencia: <b>{sumer:.1f} m</b></span>
                <span style="color: #FFFF00; font-size: 9px; margin-left: auto;">{f_s}</span>
            </div>
            <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                <span>Dinámico: <b>{dinam:.1f} m</b></span>
                <span style="color: #FFFF00; font-size: 9px; margin-left: auto;">{f_d}</span>
            </div>
            <div style="display: flex; align-items: baseline; font-size: 11px;">
                <span>Tanque: <b>{tanq:.1f} %</b></span>
                <span style="color: #FFFF00; font-size: 9px; margin-left: auto;">{f_t}</span>
            </div>
        </div>
        
        <div>
            <div style="font-size: 10px; color: #888; margin-bottom: 4px;">ELÉCTRICO</div>
            <table style="width: 100%; font-size: 10px; border-collapse: collapse;">
                <tr style="color: #00d4ff; border-bottom: 1px solid #333; text-align: left;">
                    <th style="padding: 4px;">Fase</th>
                    <th style="padding: 4px;">Voltaje / Act.</th>
                    <th style="padding: 4px;">Amp / Act.</th>
                </tr>
                <tr style="border-bottom: 1px solid #222;">
                    <td style="padding: 6px 4px;">L1-L2</td>
                    <td><b>{v[0][0]:.1f}V</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{v[0][1]}</span></td>
                    <td><b>{a[0][0]:.1f}A</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{a[0][1]}</span></td>
                </tr>
                <tr style="border-bottom: 1px solid #222;">
                    <td style="padding: 6px 4px;">L2-L3</td>
                    <td><b>{v[1][0]:.1f}V</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{v[1][1]}</span></td>
                    <td><b>{a[1][0]:.1f}A</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{a[1][1]}</span></td>
                </tr>
                <tr>
                    <td style="padding: 6px 4px;">L1-L3</td>
                    <td><b>{v[2][0]:.1f}V</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{v[2][1]}</span></td>
                    <td><b>{a[2][0]:.1f}A</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{a[2][1]}</span></td>
                </tr>
            </table>
        </div>
    </div>
    """

    folium.CircleMarker(
        location=info['coord'],
        radius=7,
        color=info['color_final'],
        fill=True,
        fill_color=info['color_final'],
        fill_opacity=1,
        weight=1,
        class_name="blink_me" if info['blink'] else "",
        popup=folium.Popup(html_popup, max_width=450)
    ).add_to(m)

    folium.map.Marker(
        location=info['coord'],
        icon=folium.DivIcon(
            icon_size=(150,36),
            icon_anchor=(0,0),
            html=f'<div style="font-size: 13px; font-weight: bold; color: {info["color_final"]}; position: absolute; left: 12px; top: -10px; white-space: nowrap; text-shadow: 1px 1px #000;">{id_p}</div>'
        )
    ).add_to(m)

folium_static(m, width=1300, height=800)
