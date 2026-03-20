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

# 2. ESTILO CSS (Logo arriba y diseño oscuro)
st.markdown("""
    <style>
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        
        /* ELIMINAR ESPACIO SUPERIOR EN SIDEBAR */
        [data-testid="stSidebarContent"] { padding-top: 0rem !important; }
        
        /* LOGO AL MÁXIMO ARRIBA */
        .sidebar-logo { 
            display: flex; 
            justify-content: center; 
            padding: 0px !important; 
            margin-top: -20px !important; 
            margin-bottom: 10px;
        }
        .sidebar-logo img { max-width: 85%; height: auto; }
        
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; margin-bottom: 15px; }
        .status-tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 5px; font-weight: bold; }
        .status-ok { background-color: #1b5e20; color: #a5d6a7; }
        .status-err { background-color: #b71c1c; color: #ef9a9a; }
        .section-header { padding: 10px; border-radius: 3px; font-weight: bold; margin-bottom: 5px; color: white; }
        
        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0; } 100% { opacity: 1; } }
        .blink_me { animation: blink 1.2s infinite; }
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
    try: 
        return psycopg2.connect(**st.secrets["postgres"])
    except: return None

# 4. CARGA DE DATOS CENTRALIZADA
@st.cache_data(ttl=30)
def cargar_todo_el_sistema():
    # A. Diccionario de Pozos
    engine_tel = get_mysql_telemetria_engine()
    if not engine_tel: return None, {}, []
    df_p = pd.read_sql("SELECT * FROM Diccionario_de_pozos", engine_tel)
    
    mapa_pozos = {}
    all_tags = []
    for _, row in df_p.iterrows():
        try:
            coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
            lat, lon = map(float, coords_str.split(','))
            coords = (lat, lon)
        except: continue

        pozo_info = {
            "coord": coords, "bomba": row['bomba'], "caudal": row['caudal'],
            "presion": row['presion'], "sumergencia": row['sumergencia'],
            "nivel_dinamico": row['nivel_dinamico'], "nivel_tanque": row['nivel_tanque'],
            "columna": row['columna'], "h_arranque": row['H_arranque'], "h_paro": row['H_paro'],
            "voltajes_l": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
            "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']]
        }
        mapa_pozos[row['Pozos']] = pozo_info
        # Recolectar tags para consulta SCADA
        for k, v in pozo_info.items():
            if isinstance(v, list): all_tags.extend([str(t) for t in v if t and str(t) not in ['0', 'Sin telemetria']])
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): all_tags.append(v)

    # B. Datos SCADA (Valores actuales)
    engine_scada = get_mysql_scada_engine()
    data_scada = {}
    if engine_scada and all_tags:
        tags_str = "', '".join(list(set(all_tags)))
        query = f"""
            SELECT r.NAME, h.VALUE, h.FECHA 
            FROM vfitagnumhistory h 
            JOIN VfiTagRef r ON h.GATEID = r.GATEID 
            WHERE r.NAME IN ('{tags_str}') 
            AND h.FECHA = (SELECT MAX(FECHA) FROM vfitagnumhistory WHERE GATEID = h.GATEID)
        """
        df_s = pd.read_sql(query, engine_scada)
        data_scada = {r['NAME']: (r['VALUE'], r['FECHA'].strftime('%d/%m %H:%M')) for _, r in df_s.iterrows()}

    # C. Sectores (PostgreSQL)
    conn_pg = get_postgres_conn()
    sectores = []
    if conn_pg:
        query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
        sectores = pd.read_sql(query, conn_pg).to_dict('records')
        conn_pg.close()

    return mapa_pozos, data_scada, sectores

# --- 5. FRAGMENTO DE ACTUALIZACIÓN AUTOMÁTICA ---
@st.fragment(run_every="30s")
def renderizar_dashboard():
    mapa_pozos, data_scada, sectores = cargar_todo_el_sistema()
    if not mapa_pozos: return

    pozos_on, pozos_off, pozos_sin_t = [], [], []
    total_q, total_p = 0.0, 0.0

    # Lógica de estados
    for id_p, info in mapa_pozos.items():
        if str(info['bomba']).strip() == "Sin telemetria":
            info.update({'status_label': 'SIN TELEMETRÍA', 'color': '#808080', 'blink': False})
            pozos_sin_t.append(id_p)
        else:
            val_bba, _ = data_scada.get(info['bomba'], (0, "N/A"))
            q_val = data_scada.get(info['caudal'], (0, "N/A"))[0]
            if val_bba == 1:
                info.update({'status_label': 'OPERANDO', 'color': '#00FF00', 'blink': False})
                pozos_on.append(id_p); total_q += q_val
                total_p += data_scada.get(info['presion'], (0, ""))[0]
            else:
                info.update({'status_label': 'APAGADO', 'color': '#FF0000', 'blink': True})
                pozos_off.append(id_p)

    # SIDEBAR DINÁMICO
    with st.sidebar:
        st.markdown(f"""
        <div class="resumen-card">
            <h4 style="color:#00d4ff; margin:0;">RESUMEN GLOBAL</h4>
            <p style="font-size:10px; color:#888;">Actualizado: {datetime.now().strftime('%H:%M:%S')}</p>
            <p>Caudal: <b style="color:#00FF00;">{total_q:.2f} L/s</b></p>
            <p>Presión Prom: <b style="color:#FFFF00;">{total_p/max(len(pozos_on),1):.2f} Kg</b></p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown(f"<div class='section-header' style='background:#1b5e20;'>Bombas ON ({len(pozos_on)})</div>", unsafe_allow_html=True)
        for p in sorted(pozos_on): st.write(f"🟢 {p}")
        st.markdown(f"<div class='section-header' style='background:#b71c1c;'>Bombas OFF ({len(pozos_off)})</div>", unsafe_allow_html=True)
        for p in sorted(pozos_off): st.write(f"🔴 {p}")

    # MAPA PRINCIPAL
    m = folium.Map(location=[21.8820, -102.2800], zoom_start=14, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)

    for s in sectores:
        folium.GeoJson(json.loads(s['geo']), style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1}).add_to(m)

    for id_p, info in mapa_pozos.items():
        # Función auxiliar para obtener datos SCADA formateados
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

        # POPUP TÉCNICO COMPLETO (RESTAURADO)
        html_popup = f"""
        <div style="background: #050505; color: white; padding: 15px; border-radius: 12px; width: 380px; border: 1px solid {info['color']}; font-family: sans-serif;">
            <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 8px; margin-bottom: 10px;">
                <b style="color: #00d4ff; font-size: 16px;">POZO {id_p}</b>
                <span style="font-size: 10px; background: {info['color']}; color: black; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{info['status_label']}</span>
            </div>
            <div style="font-size: 11px; margin-bottom: 10px;">
                💧 Caudal: <b>{q:.2f} L/s</b> <span style="color:#FFFF00; font-size:9px;">({f_q})</span><br>
                🚀 Presión: <b>{p:.2f} kg</b> <span style="color:#FFFF00; font-size:9px;">({f_p})</span>
            </div>
            <div style="font-size: 10px; color: #888; border-top: 1px solid #222; padding-top: 5px;">ELÉCTRICO</div>
            <table style="width: 100%; font-size: 10px; margin-top: 5px;">
                <tr style="color:#00d4ff;"><th>Fase</th><th>Voltaje</th><th>Amperaje</th></tr>
                <tr><td>L1</td><td>{v[0][0]:.1f}V</td><td>{a[0][0]:.1f}A</td></tr>
                <tr><td>L2</td><td>{v[1][0]:.1f}V</td><td>{a[1][0]:.1f}A</td></tr>
                <tr><td>L3</td><td>{v[2][0]:.1f}V</td><td>{a[2][0]:.1f}A</td></tr>
            </table>
        </div>
        """

        folium.CircleMarker(
            location=info['coord'], radius=7, color=info['color'], fill=True, fill_opacity=1,
            class_name="blink_me" if info['blink'] else "",
            popup=folium.Popup(html_popup, max_width=400)
        ).add_to(m)
        
        folium.map.Marker(
            location=info['coord'], 
            icon=folium.DivIcon(html=f'<div style="font-size:12px; font-weight:bold; color:{info["color"]};">{id_p}</div>')
        ).add_to(m)

    folium_static(m, width=1300, height=800)

# --- 6. SIDEBAR ESTÁTICO (LOGO Y BOTONES) ---
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    
    with st.expander("🔌 CONEXIONES", expanded=False):
        sc = "OK" if get_mysql_scada_engine() else "ERR"
        tl = "OK" if get_mysql_telemetria_engine() else "ERR"
        st.write(f"SCADA: {sc} | Tel: {tl}")

    if st.button("♻️ Reiniciar Caché", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# EJECUCIÓN DEL DASHBOARD
renderizar_dashboard()
