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
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        
        /* ELIMINAR ESPACIO SUPERIOR POR DEFECTO DE STREAMLIT EN SIDEBAR */
        [data-testid="stSidebarContent"] { padding-top: 0rem !important; }
        [data-testid="stSidebarNav"] { padding-top: 0rem !important; }
        
        /* AJUSTE MÁXIMO DEL LOGO HACIA ARRIBA */
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
        .section-header { padding: 10px; border-radius: 3px; font-weight: bold; margin-bottom: 5px; color: white; }
    </style>
""", unsafe_allow_html=True)

# 3--------------------------------------------------------------------------------3. FUNCIONES DE CONEXIÓN ----------------------------------------------------------------------------------------------------------
@st.cache_resource
def get_mysql_scada_engine():
    try:
        c = st.secrets["mysql_scada"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
        with engine.connect() as conn: pass 
        return engine
    except: return None

@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
        with engine.connect() as conn: pass 
        return engine
    except: return None

@st.cache_resource
def get_postgres_conn():
    try: 
        conn = psycopg2.connect(**st.secrets["postgres"])
        conn.close() 
        return psycopg2.connect(**st.secrets["postgres"])
    except: 
        return None

# 4-------------------------------------------------------------------------------- 4. CARGA DE DATOS ----------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=600)
def cargar_mapa_pozos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        query = "SELECT * FROM Diccionario_de_pozos"
        df_pozos = pd.read_sql(query, engine)
        
        nuevo_mapa = {}
        for _, row in df_pozos.iterrows():
            try:
                coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
                lat, lon = map(float, coords_str.split(','))
                coords = (lat, lon)
            except: continue

            nuevo_mapa[row['Pozos']] = {
                "coord": coords,
                "bomba": row['bomba'],
                "caudal": row['caudal'],
                "presion": row['presion'],
                "sumergencia": row['sumergencia'],
                "nivel_dinamico": row['nivel_dinamico'],
                "nivel_tanque": row['nivel_tanque'],
                "columna": row['columna'],
                "h_arranque": row['H_arranque'],
                "h_paro": row['H_paro'],
                "voltajes_l": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
                "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']]
            }
        return nuevo_mapa
    except:
        return {}

def cargar_datos_scada(mapa_pozos):
    engine = get_mysql_scada_engine()
    if not engine: return {}
    all_tags = []
    for p in mapa_pozos.values():
        for k, v in p.items():
            if isinstance(v, list): 
                all_tags.extend([str(tag) for tag in v if tag and str(tag) not in ['0', 'Sin telemetria']])
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): 
                all_tags.append(v)
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
    except: 
        return []

# 5-------------------------------------------------------------------------------- 5. PROCESAMIENTO ----------------------------------------------------------------------------------------------------------
sectores = cargar_sectores_poligonos()
mapa_pozos_dict = cargar_mapa_pozos_desde_db()
data_scada = cargar_datos_scada(mapa_pozos_dict)

pozos_on = []
pozos_off = []
pozos_sin_telemetria = []
pozos_falla_com = []
total_q = 0.0
total_p = 0.0

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
            diff = ahora - fecha_dt
            horas_atras = diff.total_seconds() / 3600
            if horas_atras > 4:
                es_falla_com = True
        except:
            es_falla_com = True
    else:
        es_falla_com = True

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
            
# 6 -------------------------------------------------------------------------------SECCION 6. SIDEBAR ------------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    
    with st.expander("🔌 ESTADO DE CONEXIONES", expanded=True):
        status_mysql_scada = "OK" if get_mysql_scada_engine() else "ERROR"
        status_mysql_tele = "OK" if get_mysql_telemetria_engine() else "ERROR"
        status_postgres = "OK" if get_postgres_conn() else "ERROR"

        def get_tag(status):
            cls = "status-ok" if status == "OK" else "status-err"
            return f'<span class="status-tag {cls}">{status}</span>'

        st.markdown(f"**SCADA:** {get_tag(status_mysql_scada)}", unsafe_allow_html=True)
        st.markdown(f"**Telemetría:** {get_tag(status_mysql_tele)}", unsafe_allow_html=True)
        st.markdown(f"**PostgreSQL:** {get_tag(status_postgres)}", unsafe_allow_html=True)

    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

    st.markdown(f"""
    <div class="resumen-card">
        <h4 style="color:#00d4ff; margin-top:0;">RESUMEN GLOBAL</h4>
        <p>Caudal Total: <b style="color:#00FF00;">{total_q:.2f} l/s</b></p>
        <p>Presión Prom: <b style="color:#FFFF00;">{total_p/max(len(pozos_on),1):.2f} Kg/cm²</b></p>
    </div>
    """, unsafe_allow_html=True)
    
    with st.expander(f"🟢 Bombas ON ({len(pozos_on)})", expanded=False):
        for p in sorted(pozos_on): st.write(f"🟢 {p}")
    
    with st.expander(f"🔴 Bombas OFF ({len(pozos_off)})", expanded=False):
        for p in sorted(pozos_off): st.write(f"🔴 {p}")

    if pozos_falla_com:
        with st.expander(f"⚠️ Falla de Com. (+4h) ({len(pozos_falla_com)})", expanded=False):
            for p in sorted(pozos_falla_com): st.write(f"🟠 {p}")
    
    if pozos_sin_telemetria:
        with st.expander(f"⚪ Sin Telemetría ({len(pozos_sin_telemetria)})", expanded=False):
            for p in sorted(pozos_sin_telemetria): st.write(f"⚪ {p}")

# 7---------------------------------------------------------------------------------SECCION 7. MAPA -------------------------------------------------------------------------------------------------------------
m = folium.Map(location=[21.8820, -102.2800], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

# INYECCIÓN DE CSS PARA EL PARPADEO EN EL MAPA
estilo_final = """
<style>
@keyframes parpadeo_miaa {
    0% { opacity: 1.0; }
    50% { opacity: 0.1; }
    100% { opacity: 1.0; }
}
.blink_me {
    animation: parpadeo_miaa 1s infinite;
}
</style>
"""
m.get_root().header.add_child(folium.Element(estilo_final))

for s in sectores:
    folium.GeoJson(
        json.loads(s['geo']), 
        style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1},
        tooltip=f"Sector: {s['sector']}"
    ).add_to(m)

for id_p, info in mapa_pozos_dict.items():
    d = lambda tag: data_scada.get(tag, (0, "N/A"))
    is_st = (info['status_label'] == 'SIN TELEMETRÍA')
    
    q, f_q = d(info['caudal']) if not is_st else (0.0, "N/A")
    p, f_p = d(info['presion']) if not is_st else (0.0, "N/A")
    sumer, f_s = d(info['sumergencia']) if not is_st else (0.0, "N/A")
    dinam, f_d = d(info['nivel_dinamico']) if not is_st else (0.0, "N/A")
    tanq, f_t = d(info['nivel_tanque']) if not is_st else (0.0, "N/A")
    col, f_col = d(info['columna']) if not is_st else (0.0, "N/A")
    h_arr, f_h_arr = d(info['h_arranque']) if not is_st else (0.0, "N/A")
    h_par, f_h_par = d(info['h_paro']) if not is_st else (0.0, "N/A")
    v = [d(t) for t in info['voltajes_l']] if not is_st else [(0.0, "N/A")]*3
    a = [d(t) for t in info['amperajes_l']] if not is_st else [(0.0, "N/A")]*3

    html_popup = f"""
    <div style="background: #050505; color: white; padding: 15px; border-radius: 12px; width: 380px; border: 1px solid {info['color_final']}; font-family: sans-serif;">
        <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 8px; margin-bottom: 10px;">
            <b style="color: #00d4ff; font-size: 16px;">POZO {id_p}</b>
            <span style="font-size: 10px; background: {info['color_final']}; color: black; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{info['status_label']}</span>
        </div>
        <div style="font-size: 11px;">
            💧 Caudal: <b>{q:.2f} L/s</b> <br>
            🚀 Presión: <b>{p:.2f} kg</b> <br>
            📏 Sumergencia: <b>{sumer:.1f} m</b> <br>
            📉 Dinámico: <b>{dinam:.1f} m</b> <br>
            🔋 Tanque: <b>{tanq:.1f} %</b> <br>
            ⚡ Voltaje L1: <b>{v[0][0]:.1f}V</b> | Amp L1: <b>{a[0][0]:.1f}A</b>
        </div>
    </div>
    """

    # Se aplica la clase CSS blink_me si el pozo tiene activado el parpadeo
    folium.CircleMarker(
        location=info['coord'],
        radius=6,
        color=info['color_final'],
        fill=True,
        fill_color=info['color_final'],
        fill_opacity=1,
        weight=2,
        class_name="blink_me" if info.get('blink', False) else "",
        popup=folium.Popup(html_popup, max_width=450)
    ).add_to(m)

    folium.map.Marker(
        location=info['coord'],
        icon=folium.DivIcon(
            icon_size=(150,36),
            icon_anchor=(0,0),
            html=f'<div style="font-size: 10px; font-weight: bold; color: {info["color_final"]}; position: absolute; left: 12px; top: -10px; white-space: nowrap;">{id_p}</div>'
        )
    ).add_to(m)

folium_static(m, width=None, height=750)
