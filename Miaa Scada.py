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
st.set_page_config(page_title="MIAA - SCADA Avanzado", layout="wide", initial_sidebar_state="collapsed")

# 2. ESTILO CSS (ALTA VISIBILIDAD)
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; }
        [data-testid="stHeader"] { background: rgba(0,0,0,0); }
        .header-miaa {
            text-align: center; padding: 10px; border-bottom: 2px solid #00d4ff;
            background: #0b1a29; margin-bottom: 10px;
        }
    </style>
    <div class="header-miaa">
        <h2 style="color: #00d4ff; margin:0; letter-spacing: 2px;">CENTRO DE CONTROL OPERATIVO - MIAA</h2>
    </div>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE CONFIGURACIÓN
mapa_pozos_dict = {
    "P005A": {
        "coord": (21.89147, -102.23195), 
        "corriente_bba": "PZ_RP_005_TRHDAS_BBA_CRUDO", 
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
        "corriente_bba": "PZ_006_TRC_BBA_CRUDO", 
        "caudal": "PZ_006_TRC_CAU_INS", 
        "presion": "PZ_006_TRC_PRES_INS", 
        "sumergencia": "PZ_006_TRC_SUMERG", 
        "nivel_dinamico": "PZ_006_TRC_NIV_EST",
        "nivel_tanque": "0", 
        "voltajes_l": ["PZ_006_TRC_VOL_L1_L2", "PZ_006_TRC_VOL_L2_L3", "PZ_006_TRC_VOL_L1_L3"],
        "amperajes_l": ["PZ_006_TRC_CORR_L1", "PZ_006_TRC_CORR_L2", "PZ_006_TRC_CORR_L3"]
    }
}

# 4. CARGA DE DATOS (MYSQL Y POSTGRES)
@st.cache_resource
def get_engines():
    # MySQL para Telemetría
    m = st.secrets["mysql"]
    pwd_m = urllib.parse.quote_plus(m["password"])
    engine_mysql = create_engine(f"mysql+mysqlconnector://{m['user']}:{pwd_m}@{m['host']}/{m['database']}")
    # Postgres para Sectores
    p = st.secrets["postgres"]
    conn_pg = psycopg2.connect(**p)
    return engine_mysql, conn_pg

def cargar_todo():
    e_mysql, conn_pg = get_engines()
    # Scada
    all_tags = []
    for p in mapa_pozos_dict.values():
        for k, v in p.items():
            if isinstance(v, list): all_tags.extend(v)
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): all_tags.append(v)
    
    tags_str = "', '".join(list(set(all_tags)))
    query_scada = f"SELECT r.NAME, h.VALUE, h.FECHA FROM vfitagnumhistory h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_str}') AND h.FECHA = (SELECT MAX(FECHA) FROM vfitagnumhistory WHERE GATEID = h.GATEID)"
    df_scada = pd.read_sql(query_scada, e_mysql)
    scada_dict = {row['NAME']: (row['VALUE'], row['FECHA']) for _, row in df_scada.iterrows()}
    
    # Sectores
    query_geo = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
    df_geo = pd.read_sql(query_geo, conn_pg)
    
    return scada_dict, df_geo.to_dict('records')

# --- PROCESO ---
data_scada, sectores = cargar_todo()
ahora = datetime.now()

# --- INTERFAZ ---
col_info, col_map = st.columns([1, 4])

with col_info:
    st.markdown("### 📋 Resumen")
    for id_p, info in mapa_pozos_dict.items():
        bba, f_bba = data_scada.get(info['corriente_bba'], (None, None))
        v1, f_v1 = data_scada.get(info['voltajes_l'][0], (None, None))
        
        # Color Logic
        c, label = "#808080", "GRIS"
        if bba is not None:
            if f_v1 and (ahora - f_v1).total_seconds() > 14400: c, label = "#FFFF00", "OBS"
            elif bba == 1: c, label = "#00FF00", "ON"
            else: c, label = "#FF0000", "OFF"
        
        info.update({'c': c, 'label': label})
        st.write(f"{id_p} : {label}")

with col_map:
    m = folium.Map(location=[21.8818, -102.2917], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)

    # Polígonos
    for s in sectores:
        folium.GeoJson(json.loads(s['geo']), style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.15}).add_to(m)

    # Pozos
    for id_p, info in mapa_pozos_dict.items():
        # Extracción de datos con formateo de fecha legible
        def get_val(tag):
            val, fec = data_scada.get(tag, (0, "N/A"))
            f_str = fec.strftime("%d/%m %H:%M") if isinstance(fec, datetime) else str(fec)
            return val, f_str

        bba, f_bba = get_val(info['corriente_bba'])
        q, f_q = get_val(info['caudal'])
        p, f_p = get_val(info['presion'])
        s_val, f_s = get_val(info['sumergencia'])
        d_val, f_d = get_val(info['nivel_dinamico'])
        t_val, f_t = get_val(info['nivel_tanque'])
        
        status_txt = "ENCENDIDO" if bba == 1 else "APAGADO"
        color_bba = "#00ff00" if bba == 1 else "#ff0000"

        html_popup = f"""
        <div style="background: #050505; color: white; padding: 20px; border-radius: 15px; width: 420px; border: 2px solid {info['c']}; font-family: 'Segoe UI', Tahoma, sans-serif;">
            <div style="display: flex; justify-content: space-between; border-bottom: 2px solid #333; padding-bottom: 10px; margin-bottom: 15px;">
                <b style="color: #00d4ff; font-size: 22px;">{id_p}</b>
                <div style="text-align: right;">
                    <div style="background: {color_bba}; color: black; padding: 3px 12px; border-radius: 6px; font-weight: bold; font-size: 14px;">{status_txt}</div>
                    <div style="font-size: 10px; color: {info['c']}; margin-top: 4px;">{info['label']}</div>
                </div>
            </div>

            <table style="width: 100%; margin-bottom: 20px; border-collapse: collapse;">
                <tr>
                    <td style="color: #00d4ff; font-size: 16px;">💧 Caudal:</td>
                    <td style="font-size: 18px; text-align: right;"><b>{q:.2f} L/s</b></td>
                    <td style="font-size: 11px; color: #00d4ff; text-align: right; padding-left: 10px;">{f_q}</td>
                </tr>
                <tr>
                    <td style="color: #00ff00; font-size: 16px;">🚀 Presión:</td>
                    <td style="font-size: 18px; text-align: right;"><b>{p:.2f} kg</b></td>
                    <td style="font-size: 11px; color: #00d4ff; text-align: right; padding-left: 10px;">{f_p}</td>
                </tr>
            </table>

            <div style="background: #111; padding: 10px; border-radius: 8px; margin-bottom: 15px;">
                <div style="font-size: 12px; color: #888; margin-bottom: 8px;">NIVELES DE POZO Y TANQUE</div>
                <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px;">
                    <span>Sumergencia: <b>{s_val:.1f} m</b></span><span style="color: #00d4ff; font-size: 10px;">{f_s}</span>
                </div>
                <div style="width: 100%; height: 8px; background: #333; border-radius: 4px; overflow: hidden; margin-bottom: 10px;">
                    <div style="width: {min(s_val, 100)}%; height: 100%; background: #00d4ff;"></div>
                </div>
                <div style="font-size: 13px; margin-bottom: 5px;">Dinamico: <b>{d_val:.1f} m</b> <small style="color: #00d4ff;">({f_d})</small></div>
                <div style="font-size: 13px;">Tanque Adj: <b>{t_val:.1f} m</b> <small style="color: #00d4ff;">({f_t})</small></div>
            </div>

            <div style="font-size: 11px; color: #888;">DATOS ELÉCTRICO (REF L1)</div>
            <table style="width: 100%; text-align: center; font-size: 12px; margin-top: 5px;">
                <tr style="color: #00d4ff;"><th>FASE</th><th>VOLTAJE</th><th>AMPERAJE</th></tr>
                <tr><td>L1-L2</td><td>{get_val(info['voltajes_l'][0])[0]:.1f}V</td><td>{get_val(info['amperajes_l'][0])[0]:.1f}A</td></tr>
            </table>
        </div>
        """

        folium.Marker(
            location=info['coord'],
            icon=folium.Icon(color="green" if bba==1 else "red", icon="tint", prefix="fa"),
            popup=folium.Popup(folium.IFrame(html_popup, width=450, height=520), max_width=460)
        ).add_to(m)

    folium_static(m, width=1100, height=750)
