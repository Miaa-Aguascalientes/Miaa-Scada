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

# 1. CONFIGURACIÓN DE PÁGINA 
st.set_page_config(
    page_title="MIAA - Estado de Pozos", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# 2. ESTILO CSS (Tu diseño original intacto)
st.markdown("""
    <style>
        .titulo-superior {
            position: fixed; top: 15px; left: 50%; transform: translateX(-50%);
            z-index: 9999999; color: #00d4ff; font-size: 1.5rem; font-weight: bold;
            text-transform: uppercase; letter-spacing: 2px; white-space: nowrap;
            text-shadow: 0 0 10px rgba(0, 212, 255, 0.5); animation: glow 2s ease-in-out infinite alternate;
        }
        @keyframes glow {
            from { text-shadow: 0 0 5px #00d4ff; transform: translateX(-50%) scale(1); }
            to { text-shadow: 0 0 15px #00d4ff; transform: translateX(-50%) scale(1.02); }
        }
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        [data-testid="stSidebarContent"] { padding-top: 0rem !important; }
        .sidebar-logo { display: flex; justify-content: center; padding: 0px !important; margin-top: -70px !important; margin-bottom: 10px; }
        .sidebar-logo img { max-width: 85%; height: auto; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; margin-bottom: 15px; }
        .status-tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 5px; font-weight: bold; }
        .status-ok { background-color: #1b5e20; color: #a5d6a7; }
        .status-err { background-color: #b71c1c; color: #ef9a9a; }
    </style>
""", unsafe_allow_html=True)

# 3. FUNCIONES DE CONEXIÓN
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

# 4. CARGA DE DATOS
@st.cache_data(ttl=600)
def cargar_mapa_pozos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        df_pozos = pd.read_sql("SELECT * FROM Diccionario_de_pozos", engine)
        nuevo_mapa = {}
        for _, row in df_pozos.iterrows():
            try:
                lat, lon = map(float, str(row['coord']).strip().replace('(', '').replace(')', '').split(','))
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

# 5. PROCESAMIENTO
sectores = cargar_sectores_poligonos()
mapa_pozos_dict = cargar_mapa_pozos_desde_db()
data_scada = cargar_datos_scada(mapa_pozos_dict)

pozos_on, pozos_off, pozos_sin_tele, pozos_falla_com = [], [], [], []
total_q, total_p = 0.0, 0.0
ahora = dt.datetime.utcnow() - dt.timedelta(hours=6)

for id_p, info in mapa_pozos_dict.items():
    bomba_val = str(info['bomba']).strip()
    if bomba_val == "Sin telemetria":
        info.update({'status_label': 'SIN TELEMETRÍA', 'color_final': '#808080', 'blink': False})
        pozos_sin_tele.append(id_p)
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
        val_bba, _ = data_scada.get(info['bomba'], (0, "N/A"))
        q_val = data_scada.get(info['caudal'], (0, "N/A"))[0]
        p_val = data_scada.get(info['presion'], (0, "N/A"))[0]
        if val_bba == 1:
            info.update({'status_label': 'OPERANDO', 'color_final': '#00FF00', 'blink': False})
            pozos_on.append(id_p)
            total_q += q_val
            total_p += p_val
        else:
            info.update({'status_label': 'APAGADO', 'color_final': '#FF0000', 'blink': True})
            pozos_off.append(id_p)

# --- CONTROL DE VISTA DE DETALLE (PARA QUE EL MAPA NO SALGA EN BLANCO) ---
query_params = st.query_params
if "sector_id" in query_params:
    sector_sel = query_params["sector_id"]
    st.title(f"📊 Detalle del Sector: {sector_sel}")
    st.info("Información técnica detallada desde PostgreSQL")
    # Aquí puedes agregar más lógica de visualización para el sector
    if st.button("⬅️ Volver al Mapa"):
        st.query_params.clear()
        st.rerun()
    st.stop()

# 6. SIDEBAR
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.markdown(f'<div class="resumen-card"><h4 style="color:#00d4ff; margin:0;">RESUMEN GLOBAL</h4><p>Caudal: <b style="color:#00FF00;">{total_q:.2f} l/s</b></p></div>', unsafe_allow_html=True)

# 7. MAPA Y DASHBOARD
st.markdown('<div class="titulo-superior">Sistema de monitoreo - Aguascalientes</div>', unsafe_allow_html=True)
col_mapa, col_capas = st.columns([8.5, 1.5])
with col_capas:
    st.markdown("### 🗺️ Capas")
    ver_sectores = st.checkbox("Sectores", value=True)
    ver_pozos = st.checkbox("Pozos", value=True)
    ver_etiquetas = st.checkbox("ID Pozos", value=True)

with col_mapa:
    m = folium.Map(location=[21.8820, -102.2800], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)

    def formato_hora(decimal):
        try:
            h = int(float(decimal))
            m = int((float(decimal) - h) * 60)
            return f"{h:02d}:{m:02d}"
        except: return "00:00"

    def get_blink_icon(color):
        return f'<div style="width: 8px; height: 8px; background-color: {color}; border-radius: 50%; box-shadow: 0 0 8px {color}; animation: blinker 1s linear infinite;"></div><style>@keyframes blinker {{ 50% {{ opacity: 0.2; }} }}</style>'

    # RENDERIZADO DE SECTORES
    if ver_sectores:
        for s in sectores:
            nombre_s = s['sector']
            url_s = f"./?sector_id={urllib.parse.quote(str(nombre_s))}"
            html_s = f"""<div style="font-family:sans-serif; color:white; background:#0b1a29; padding:10px; border-radius:5px; border:1px solid #00d4ff;">
                <h4 style="margin:0; color:#00d4ff;">Sector: {nombre_s}</h4><hr style="border:0.5px solid #333; margin:8px 0;">
                <a href="{url_s}" target="_self" style="display:block; text-align:center; background:#00d4ff; color:black; padding:8px; text-decoration:none; border-radius:4px; font-weight:bold;">Consultar Sector</a>
            </div>"""
            folium.GeoJson(json.loads(s['geo']), style_function=lambda x: {'fillColor':'#00d4ff','color':'#00d4ff','weight':1,'fillOpacity':0.1},
                           popup=folium.Popup(html_s, max_width=250)).add_to(m)

    # RENDERIZADO DE POZOS (TU POPUP ORIGINAL COMPLETO)
    for id_p, info in mapa_pozos_dict.items():
        d = lambda tag: data_scada.get(tag, (0, "N/A"))
        is_st = (info['status_label'] == 'SIN TELEMETRÍA')
        q, f_q = d(info['caudal']) if not is_st else (0.0, "N/A")
        p, f_p = d(info['presion']) if not is_st else (0.0, "N/A")
        sumer, f_s = d(info['sumergencia']) if not is_st else (0.0, "N/A")
        dinam, f_d = d(info['nivel_dinamico']) if not is_st else (0.0, "N/A")
        tanq, f_t = d(info['nivel_tanque']) if not is_st else (0.0, "N/A")
        col, f_col = d(info['columna']) if not is_st else (0.0, "N/A")
        h_arr_fmt = formato_hora(d(info['h_arranque'])[0]) if not is_st else "00:00"
        h_par_fmt = formato_hora(d(info['h_paro'])[0]) if not is_st else "00:00"
        v = [d(t) for t in info['voltajes_l']] if not is_st else [(0.0, "N/A")]*3
        a = [d(t) for t in info['amperajes_l']] if not is_st else [(0.0, "N/A")]*3

        html_popup = f"""
        <div style="background:#050505; color:white; padding:15px; border-radius:12px; width:380px; border:1px solid {info['color_final']}; font-family:sans-serif;">
            <div style="display:flex; justify-content:space-between; border-bottom:1px solid #333; padding-bottom:8px; margin-bottom:10px;">
                <b style="color:#00d4ff; font-size:16px;">POZO {id_p}</b>
                <span style="font-size:10px; background:{info['color_final']}; color:black; padding:2px 8px; border-radius:4px; font-weight:bold;">{info['status_label']}</span>
            </div>
            <div style="font-size:10px; color:#888;">HIDRÁULICA</div>
            <div style="display:flex; font-size:11px; margin-bottom:3px;"><span>💧 Caudal: <b>{q:.2f} L/s</b></span><span style="color:#FFFF00; font-size:8px; margin-left:auto;">{f_q}</span></div>
            <div style="display:flex; font-size:11px;"><span>🚀 Presión: <b>{p:.2f} kg</b></span><span style="color:#FFFF00; font-size:8px; margin-left:auto;">{f_p}</span></div>
            <div style="font-size:10px; color:#888; margin-top:10px;">NIVELES</div>
            <div style="display:flex; font-size:11px;"><span>📏 Sumergencia: <b>{sumer:.1f} m</b></span><span style="color:#FFFF00; font-size:8px; margin-left:auto;">{f_s}</span></div>
            <div style="display:flex; font-size:11px;"><span>🔋 Tanque: <b>{tanq:.1f} mts</b></span><span style="color:#FFFF00; font-size:8px; margin-left:auto;">{f_t}</span></div>
            <div style="font-size:10px; color:#888; margin-top:10px;">ELÉCTRICO</div>
            <table style="width:100%; font-size:10px; border-collapse:collapse;">
                <tr style="color:#00d4ff; border-bottom:1px solid #333;"><th>Fase</th><th>Voltaje</th><th>Amp</th></tr>
                <tr><td>L1-L2</td><td>{v[0][0]:.1f}V</td><td>{a[0][0]:.1f}A</td></tr>
                <tr><td>L2-L3</td><td>{v[1][0]:.1f}V</td><td>{a[1][0]:.1f}A</td></tr>
            </table>
            <div style="font-size:10px; color:#888; margin-top:10px; border-top:1px solid #222;">HORARIOS</div>
            <div style="display:flex; font-size:11px;"><span>▶️ Arranque: <b>{h_arr_fmt}</b></span></div>
            <div style="display:flex; font-size:11px;"><span>⏹️ Paro: <b>{h_par_fmt}</b></span></div>
        </div>
        """
        if ver_pozos:
            icon_html = get_blink_icon(info['color_final']) if info.get('blink') else f'<div style="width:8px; height:8px; background:{info["color_final"]}; border-radius:50%;"></div>'
            folium.Marker(location=info['coord'], icon=folium.DivIcon(html=icon_html), popup=folium.Popup(html_popup, max_width=450)).add_to(m)
        if ver_etiquetas:
            folium.Marker(location=info['coord'], icon=folium.DivIcon(icon_anchor=(-12,10), html=f'<div style="font-size:9px; font-weight:bold; color:{info["color_final"]}; text-shadow:1px 1px #000;">{id_p}</div>')).add_to(m)

    folium_static(m, width=None, height=750)
