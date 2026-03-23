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

# 2-----------------------------------------------------------------------------------2. ESTILO CSS ----------------------------------------------------------------------------------------------------------
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
            to { text-shadow: 0 0 15px #0077ff; transform: translateX(-50%) scale(1.02); }
        }
    
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
        for k, v in p.items():
            if isinstance(v, list): all_tags.extend([str(tag) for tag in v if tag and str(tag) not in ['0', 'Sin telemetria']])
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): all_tags.append(v)
    if not all_tags: return {}
    try:
        tags_str = "', '".join(list(set(all_tags)))
        query = f"SELECT r.NAME, h.VALUE, h.FECHA FROM VfiTagNumHistory_Ultimo h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_str}') AND h.FECHA = (SELECT MAX(FECHA) FROM VfiTagNumHistory_Ultimo WHERE GATEID = h.GATEID)"
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA'].strftime('%d/%m %H:%M') if row['FECHA'] else "N/A") for _, row in df.iterrows()}
    except: return {}

# 5------------------------------------------------------------------------------- 5. PROCESAMIENTO ----------------------------------------------------------------------------------------------------------
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
            total_q += data_scada.get(info['caudal'], (0,0))[0]
            total_p += data_scada.get(info['presion'], (0,0))[0]
        else:
            info.update({'status_label': 'APAGADO', 'color_final': '#FF0000', 'blink': True})
            pozos_off.append(id_p)

# Lógica de Vista Detalle (URL Params)
query_params = st.query_params
if "sector_id" in query_params:
    st.title(f"Vista Detallada: {query_params['sector_id']}")
    st.info("Cargando datos técnicos del sector...")
    if st.button("⬅️ Volver al Mapa General"):
        st.query_params.clear()
        st.rerun()
    st.stop()

# 6-------------------------------------------------------------------------------SECCION 6. SIDEBAR ----------------------------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    
    with st.expander("🔌 ESTADO DE CONEXIONES", expanded=True):
        def get_tag(status):
            cls = "status-ok" if status == "OK" else "status-err"
            return f'<span class="status-tag {cls}">{status}</span>'
        st.markdown(f"**SCADA:** {get_tag('OK' if get_mysql_scada_engine() else 'ERROR')}", unsafe_allow_html=True)
        st.markdown(f"**Telemetría:** {get_tag('OK' if get_mysql_telemetria_engine() else 'ERROR')}", unsafe_allow_html=True)
        st.markdown(f"**GIS:** {get_tag('OK' if get_postgres_conn() else 'ERROR')}", unsafe_allow_html=True)

    if st.button("♻️ Actualizar Datos Real-Time", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown(f'<div class="resumen-card"><h4 style="color:#00d4ff; margin:0;">RESUMEN GLOBAL</h4><p>Caudal: <b style="color:#00FF00;">{total_q:.2f} l/s</b></p><p>Presión Prom: <b style="color:#FFFF00;">{total_p/max(len(pozos_on),1):.2f} Kg</b></p></div>', unsafe_allow_html=True)
    
    with st.expander(f"🟢 OPERANDO ({len(pozos_on)})", expanded=False):
        for p in sorted(pozos_on): st.markdown(f"<small>🟢 Pozo {p}</small>", unsafe_allow_html=True)
    with st.expander(f"🔴 APAGADOS ({len(pozos_off)})", expanded=False):
        for p in sorted(pozos_off): st.markdown(f"<small>🔴 Pozo {p}</small>", unsafe_allow_html=True)
    if pozos_falla_com:
        with st.expander(f"⚠️ FALLA COMUNICACIÓN ({len(pozos_falla_com)})", expanded=False):
            for p in sorted(pozos_falla_com): st.markdown(f"<small>🟠 Pozo {p}</small>", unsafe_allow_html=True)
    if pozos_sin_telemetria:
        with st.expander(f"⚪ SIN TELEMETRÍA ({len(pozos_sin_telemetria)})", expanded=False):
            for p in sorted(pozos_sin_telemetria): st.markdown(f"<small>⚪ Pozo {p}</small>", unsafe_allow_html=True)

# 7--------------------------------------------------------------------------------- SECCION 7. MAPA -------------------------------------------------------------------------------------------------------------
st.markdown('<div class="titulo-superior">Sistema de Monitoreo - Pozos Aguascalientes</div>', unsafe_allow_html=True)
col_mapa, col_capas = st.columns([8.5, 1.5])

with col_capas:
    st.markdown("### 🗺️ Capas")
    ver_sectores = st.checkbox("Sectores Hidráulicos", value=True)
    ver_pozos = st.checkbox("Pozos", value=True)
    ver_etiquetas = st.checkbox("Etiquetas ID", value=True)

with col_mapa:
    m = folium.Map(location=[21.8820, -102.2800], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)

    def formato_hora(decimal):
        try:
            h = int(float(decimal))
            return f"{h:02d}:{int((float(decimal)-h)*60):02d}"
        except: return "00:00"

    # RENDERIZADO DE SECTORES (CON TARGET BLANK PARA NUEVA PESTAÑA)
    if ver_sectores:
        for s in sectores:
            try:
                nombre_s = s['sector']
                url_s = f"./?sector_id={urllib.parse.quote(str(nombre_s))}"
                # CORRECCIÓN AQUÍ: target="_blank"
                pop_html = f"""
                <div style="background:#0b1a29; padding:10px; border-radius:5px; border:1px solid #00d4ff; width:200px;">
                    <h4 style="color:#00d4ff; margin:0;">Sector: {nombre_s}</h4>
                    <hr style="border:0.5px solid #333;">
                    <a href="{url_s}" target="_blank" style="display:block; text-align:center; background:#00d4ff; color:black; padding:8px; text-decoration:none; border-radius:4px; font-weight:bold; font-size:12px;">Ver Detalles Técnicos</a>
                </div>
                """
                folium.GeoJson(
                    json.loads(s['geo']), 
                    style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1},
                    highlight_function=lambda x: {'fillColor': '#00d4ff', 'color': '#ffffff', 'weight': 3, 'fillOpacity': 0.3},
                    popup=folium.Popup(pop_html, max_width=250)
                ).add_to(m)
            except: continue

    # RENDERIZADO DE POZOS (DISEÑO ORIGINAL)
    for id_p, info in mapa_pozos_dict.items():
        d = lambda tag: data_scada.get(tag, (0, "N/A"))
        is_st = (info['status_label'] == 'SIN TELEMETRÍA')
        q, f_q = d(info['caudal']) if not is_st else (0.0, "N/A")
        p, f_p = d(info['presion']) if not is_st else (0.0, "N/A")
        v = [d(t) for t in info['voltajes_l']]
        a = [d(t) for t in info['amperajes_l']]

        html_popup = f"""
        <div style="background:#050505; color:white; padding:15px; border-radius:12px; width:380px; border:1px solid {info['color_final']}; font-family:sans-serif;">
            <div style="display:flex; justify-content:space-between; border-bottom:1px solid #333; padding-bottom:8px; margin-bottom:10px;">
                <b style="color:#00d4ff; font-size:16px;">POZO {id_p}</b>
                <span style="font-size:10px; background:{info['color_final']}; color:black; padding:2px 8px; border-radius:4px; font-weight:bold;">{info['status_label']}</span>
            </div>
            <div style="margin-bottom:12px;"><div style="font-size:10px; color:#888;">HIDRÁULICA</div>
                <div style="display:flex; font-size:11px;"><span>💧 Caudal: <b>{q:.2f} L/s</b></span><span style="color:#FFFF00; font-size:8px; margin-left:auto;">{f_q}</span></div>
                <div style="display:flex; font-size:11px;"><span>🚀 Presión: <b>{p:.2f} kg</b></span><span style="color:#FFFF00; font-size:8px; margin-left:auto;">{f_p}</span></div>
            </div>
            <table style="width:100%; font-size:10px; border-collapse:collapse;">
                <tr style="color:#00d4ff; border-bottom:1px solid #333;"><th style="text-align:left;">Fase</th><th>Voltaje</th><th>Amp</th></tr>
                <tr style="border-bottom:1px solid #222;"><td>L1-L2</td><td><b>{v[0][0]:.1f}V</b></td><td><b>{a[0][0]:.1f}A</b></td></tr>
                <tr><td>L2-L3</td><td><b>{v[1][0]:.1f}V</b></td><td><b>{a[1][0]:.1f}A</b></td></tr>
            </table>
        </div>
        """
        if ver_etiquetas:
            folium.Marker(location=info['coord'], icon=folium.DivIcon(icon_anchor=(-12,10), html=f'<div style="font-size:9px; font-weight:bold; color:{info["color_final"]}; text-shadow:1px 1px #000;">{id_p}</div>')).add_to(m)
        if ver_pozos:
            folium.CircleMarker(location=info['coord'], radius=5, color=info['color_final'], fill=True, fill_opacity=1, weight=1, popup=folium.Popup(html_popup, max_width=450)).add_to(m)

    folium_static(m, width=None, height=750)
