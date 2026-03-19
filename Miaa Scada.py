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
st.set_page_config(page_title="MIAA - Control Maestro", layout="wide", initial_sidebar_state="collapsed")

# 2. ESTILO CSS (DARK MODE & ESTRUCTURA)
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; color: white; }
        [data-testid="stHeader"] { background: rgba(0,0,0,0); }
        .header-miaa {
            text-align: center; padding: 15px; border-bottom: 2px solid #00d4ff;
            background: #0b1a29; margin-bottom: 20px;
        }
        .stTable { background-color: #111111; border-radius: 10px; }
    </style>
    <div class="header-miaa">
        <h2 style="color: #00d4ff; margin:0; letter-spacing: 2px;">SISTEMA DE MONITOREO Y SECTORIZACIÓN - MIAA</h2>
    </div>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE CONFIGURACIÓN (POZOS)
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
            SELECT r.NAME, h.VALUE, h.FECHA FROM vfitagnumhistory h
            JOIN VfiTagRef r ON h.GATEID = r.GATEID
            WHERE r.NAME IN ('{tags_str}')
            AND h.FECHA = (SELECT MAX(FECHA) FROM vfitagnumhistory WHERE GATEID = h.GATEID)
        """
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA']) for _, row in df.iterrows()}
    except: return {}

@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
        df = pd.read_sql(query, conn)
        conn.close()
        return df.to_dict('records')
    except: return []

# --- 5. PROCESAMIENTO ---
data_scada = cargar_datos_scada()
sectores = cargar_sectores_poligonos()
ahora = datetime.now()

# --- 6. INTERFAZ: PANEL IZQUIERDO Y MAPA ---
col_info, col_map = st.columns([1, 3])

with col_info:
    st.markdown("### 📊 Estado de Pozos")
    resumen_lista = []
    for id_p, info in mapa_pozos_dict.items():
        # Verificación del estado de la bomba
        val_bba, f_bba = data_scada.get(info['bomba'], (None, None))
        
        # Colores por defecto (Gris si no hay datos)
        color_hex, icon_color, status_label, emoji = "#808080", "gray", "SIN DATOS", "⚪"

        if val_bba is not None:
            # Validación de datos obsoletos (más de 4 horas)
            if f_bba and (ahora - f_bba).total_seconds() > 14400:
                color_hex, icon_color, status_label, emoji = "#FFFF00", "orange", "OBSOLETO (+4h)", "🟡"
            elif val_bba == 1:
                color_hex, icon_color, status_label, emoji = "#28a745", "green", "ENCENDIDO", "🟢"
            else:
                color_hex, icon_color, status_label, emoji = "#dc3545", "red", "APAGADO", "🔴"

        info['color_final'] = color_hex
        info['icon_color'] = icon_color
        info['status_label'] = status_label
        
        caudal_val = data_scada.get(info['caudal'], (0,0))[0]
        resumen_lista.append({" ": emoji, "ID": id_p, "Q (L/s)": f"{caudal_val:.1f}"})

    st.table(pd.DataFrame(resumen_lista))

with col_map:
    m = folium.Map(location=[21.8900, -102.2500], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)

    # --- DIBUJAR SECTORES ---
    for s in sectores:
        folium.GeoJson(
            json.loads(s['geo']),
            name=f"Sector: {s['sector']}",
            style_function=lambda x: {
                'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1.5, 'fillOpacity': 0.1
            },
            tooltip=f"Sector: {s['sector']}"
        ).add_to(m)

    # --- DIBUJAR MARCADORES CON POPUP MEJORADO ---
    for id_p, info in mapa_pozos_dict.items():
        d = lambda tag: data_scada.get(tag, (0, "N/A"))
        q, f_q = d(info['caudal'])
        p, f_p = d(info['presion'])
        sumer, f_s = d(info['sumergencia'])
        dinam, f_d = d(info['nivel_dinamico'])
        tanq, f_t = d(info['nivel_tanque'])
        v = [d(t) for t in info['voltajes_l']]
        a = [d(t) for t in info['amperajes_l']]

        # HTML del Popup con diseño de alta visibilidad
        html_popup = f"""
        <div style="background-color: #121212; color: #ffffff; padding: 15px; border-radius: 12px; width: 330px; border: 2px solid {info['color_final']}; font-family: Arial, sans-serif;">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #444; padding-bottom: 8px; margin-bottom: 12px;">
                <span style="color: #00d4ff; font-size: 18px; font-weight: bold;">POZO {id_p}</span>
                <span style="font-size: 11px; background: {info['color_final']}; color: black; padding: 3px 10px; border-radius: 15px; font-weight: bold; text-transform: uppercase;">
                    {info['status_label']}
                </span>
            </div>
            
            <div style="margin-bottom: 12px;">
                <div style="font-size: 10px; color: #00d4ff; font-weight: bold; margin-bottom: 4px;">HIDRÁULICA</div>
                <div style="font-size: 15px; display: flex; justify-content: space-between;">
                    <span>💧 Caudal:</span> <b>{q:.2f} L/s</b>
                </div>
                <div style="font-size: 15px; display: flex; justify-content: space-between;">
                    <span>🚀 Presión:</span> <b>{p:.2f} kg/cm²</b>
                </div>
            </div>

            <div style="margin-bottom: 12px; background: #1a1a1a; padding: 8px; border-radius: 6px;">
                <div style="font-size: 10px; color: #00d4ff; font-weight: bold; margin-bottom: 6px;">NIVELES</div>
                <div style="font-size: 13px; margin-bottom: 4px;">Sumergencia: <b>{sumer:.1f} m</b></div>
                <div style="width: 100%; height: 8px; background: #333; border-radius: 4px; margin-bottom: 8px; overflow: hidden;">
                    <div style="width: {min(max(sumer, 0), 100)}%; height: 100%; background: #00d4ff; box-shadow: 0 0 5px #00d4ff;"></div>
                </div>
                <div style="font-size: 12px; color: #ccc;">Dinámico: <b>{dinam:.1f} m</b> | Tanque: <b>{tanq:.1f}%</b></div>
            </div>

            <div style="background: #000; padding: 8px; border-radius: 6px;">
                <div style="font-size: 10px; color: #00d4ff; font-weight: bold; margin-bottom: 6px;">SISTEMA ELÉCTRICO</div>
                <table style="width: 100%; font-size: 12px; text-align: center; border-collapse: collapse;">
                    <tr style="border-bottom: 1px solid #333; color: #888;"><th>Fase</th><th>Voltaje</th><th>Amperaje</th></tr>
                    <tr><td>L1-L2</td><td><b>{v[0][0]:.0f}V</b></td><td><b>{a[0][0]:.1f}A</b></td></tr>
                    <tr><td>L2-L3</td><td><b>{v[1][0]:.0f}V</b></td><td><b>{a[1][0]:.1f}A</b></td></tr>
                    <tr><td>L1-L3</td><td><b>{v[2][0]:.0f}V</b></td><td><b>{a[2][0]:.1f}A</b></td></tr>
                </table>
            </div>
            <div style="font-size: 8px; color: #555; margin-top: 8px; text-align: right;">Sincronizado: {f_q}</div>
        </div>
        """

        folium.Marker(
            location=info['coord'],
            icon=folium.Icon(color=info['icon_color'], icon='tint', prefix='fa'),
            popup=folium.Popup(folium.IFrame(html_popup, width=350, height=420), max_width=400)
        ).add_to(m)

    folium_static(m, width=1050, height=750)
