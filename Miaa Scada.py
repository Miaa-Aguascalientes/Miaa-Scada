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
from streamlit_autorefresh import st_autorefresh
import hashlib

import time
import urllib.parse
from datetime import datetime, timedelta
import plotly.graph_objects as go
from folium.plugins import MousePosition, LocateControl
from streamlit_folium import st_folium



st.set_page_config(
    page_title="Sistema Scada", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 0. SECCION -------------------------------------------------------------------------------- 0. SISTEMA DE AUTENTICACIÓN HUD DEFINITIVO --------------------------------------------------------------------


# 1.  SECCION---------------------------------------------------------------------------1. CONFIGURACIÓN DE PÁGINA ----------------------------------------------------------------------------------------------------------
params = st.query_params
sector_seleccionado = params.get("sector", None)

if sector_seleccionado:
    titulo_pestaña = f"MIAA - Estado de Sector: {sector_seleccionado}"
else:
    titulo_pestaña = "MIAA - Estado de Pozos"

st.set_page_config(
    page_title=titulo_pestaña, 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="expanded"
)
count = st_autorefresh(interval=300000, limit=1000, key="scada_refresh")

# 2.  SECCION------------------------------------------------------------------------------2. FUNCIONES DE CONEXIÓN ------------------------------------------------------------------------------------------------------

# 2.1. Secretos de la base de datos de SCADA
@st.cache_resource
def get_mysql_scada_engine():
    try:
        c = st.secrets["mysql_scada"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
        with engine.connect() as conn: pass 
        return engine
    except: return None

# 2.2. Secretos de la base de datos de Telemetria 2
@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
        with engine.connect() as conn: pass 
        return engine
    except: return None

# 2.3. Secretos de la base de datos de POSTGRES
@st.cache_resource
def get_postgres_conn():
    try: 
        conn = psycopg2.connect(**st.secrets["postgres"])
        conn.close() 
        return psycopg2.connect(**st.secrets["postgres"])
    except: 
        return None
        
 # 2.4. Funcion para cargar el ultimo dato de SCADA
def cargar_datos_scada(lista_tags):
    engine = get_mysql_scada_engine()
    if not engine or not lista_tags: return {}
    try:
      
        tags_str = "', '".join(lista_tags)
        query = f"""
            SELECT r.NAME, h.VALUE, h.FECHA 
            FROM VfiTagNumHistory_Ultimo h 
            JOIN VfiTagRef r ON h.GATEID = r.GATEID 
            WHERE r.NAME IN ('{tags_str}') 
            AND h.FECHA = (SELECT MAX(FECHA) FROM VfiTagNumHistory_Ultimo WHERE GATEID = h.GATEID)
        """
        df = pd.read_sql(query, engine)
        
        return {row['NAME']: (row['VALUE'], row['FECHA'].strftime('%d/%m %H:%M') if row['FECHA'] else "N/A") for _, row in df.iterrows()}
    except Exception as e:
        return {}

# 2.5. Funcion para optener los ultimos 7 dias de valores de SCADA
def obtener_historia_7_dias(tag_name):
    engine = get_mysql_scada_engine()
    if not engine or not tag_name: return pd.DataFrame()
    try:
        query = f"""
            SELECT h.FECHA, h.VALUE 
            FROM vfitagnumhistory h
            JOIN VfiTagRef r ON h.GATEID = r.GATEID
            WHERE r.NAME = '{tag_name}'
            AND h.FECHA >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            ORDER BY h.FECHA ASC
        """
        df = pd.read_sql(query, engine)
        df['FECHA'] = pd.to_datetime(df['FECHA']) 
        return df
    except:
        return pd.DataFrame()
        
# 2.6. Funcion para optener los poligonos de los sectores y sus demas campos
@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        query = """
            SELECT sector, "Pozos_Sector", 
                   "Superficie", "Long_Red", "Vol_Prod", "U_Domesticos", 
                   "U_NoDom", "U_Tot", "Poblacion", "Cons_m3", 
                   "Faltas_Agua", "Fugas_Tot", "FTC", "FTA", 
                   "Vol_Medid", "Vol_Fact", "Kwh", "costoKw-hr", 
                   "Recaudacion", "Dotacion", "Balance_Estimado",
                   ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo 
            FROM "Sectorizacion"."Sectores_hidr"
        """
        df = pd.read_sql(query, conn)
        conn.close()
        return df.to_dict('records')
    except Exception as e:
        st.error(f"Error al cargar sectores: {e}")
        return []

# 2.7. Funcion para cambiar el formato de horas
def formato_hora(decimal):
    try:
        if decimal == "N/A" or decimal is None: return "00:00"
        horas = int(float(decimal))
        minutos = int((float(decimal) - horas) * 60)
        return f"{horas:02d}:{minutos:02d}"
    except:
        return "00:00"

# 2.8. Funcion para el color de los sectores
def get_blink_icon(color):
    return f"""
    <div style="
        width: 8px; height: 8px; 
        background-color: {color}; 
        border-radius: 50%; 
        box-shadow: 0 0 8px {color};
        animation: blinker 1s linear infinite;">
    </div>
    <style>
    @keyframes blinker {{ 50% {{ opacity: 0.2; }} }}
    </style>
    """

# 3. SECCION -------------------------------------------------------------------------------- 3. CARGA DE DATOS DE DICCIONARIOS -------------------------------------------------------------------------------------------

# 3.1 Funcion para optener la base de datos Diccionario_de_pozos  
@st.cache_data(ttl=3600) 
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
                "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']],
                "totalizado": row['totalizado']
            }
        return nuevo_mapa
    except:
        return {}

# 3.2. Funcion para optener la base de datos Diccionario_de_tanques
@st.cache_data(ttl=3600)
def cargar_tanques_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        query = "SELECT * FROM Diccionario_de_tanques"
        df_tq = pd.read_sql(query, engine)
        
        nuevo_mapa_tq = {}
        for _, row in df_tq.iterrows():
            try:

                coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
                lat, lon = map(float, coords_str.split(','))
                
                n_max = float(row['Nivel_max']) if row.get('Nivel_max') is not None else 1.0
                if n_max <= 0: n_max = 1.0

                nuevo_mapa_tq[row['TQ']] = {
                    "nombre": row['Nombre_tq'],
                    "coord": (lat, lon),
                    "tag_nivel": row['nivel_tanque'],
                    "nivel_max": n_max,
                    "sitios": row['Sitios']
                }
            except: continue
        return nuevo_mapa_tq
    except: return {}
        
# 3.3. Funcion para optener la base de datos Diccionario_de_rebombeos
@st.cache_data(ttl=3600)
def cargar_rebombeos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        query = "SELECT * FROM Diccionario_de_rebombeos"
        df_rb = pd.read_sql(query, engine)
        
        nuevo_mapa_rb = {}
        for _, row in df_rb.iterrows():
            try:
                coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
                lat, lon = map(float, coords_str.split(','))
                
                nuevo_mapa_rb[row['Rebombeo']] = {
                    "nombre": row['Nombre_rebombeo'],
                    "coord": (lat, lon),
                    "telemetria": row['Telemetria'],
                    "presion": row['presion'],
                    "nivel_tanque": row['nivel_tanque'],
                    "voltajes_l": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
                    "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']]
                }
            except: continue
        return nuevo_mapa_rb
    except: return {}

# 3.4. Funcion para optener los puntos de control de la base de datos Diccionario_puntos_de_control
@st.cache_data(ttl=5)
def cargar_puntos_de_control_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        df = pd.read_sql("SELECT * FROM Diccionario_puntos_de_control", engine)
        d_res = {}
        for _, r in df.iterrows():
            try:
                raw_c = str(r['coord']).replace('(', '').replace(')', '').replace(' ', '').strip()
                lat_s, lon_s = raw_c.split(',')
                id_reg = r.get('Serie', r.get('Registrador', 'ID'))
                d_res[str(id_reg)] = {
                    "nombre": str(r.get('Domicilio', r.get('Nombre_registrador', 'S/N'))),
                    "coord": [float(lat_s), float(lon_s)],
                    "sector": str(r['Sector']).split('.')[0].strip(),
                    "tag_p1": r.get('Presion_1'), 
                    "tag_p2": r.get('Presion_2'), 
                    "tag_q": r.get('Caudal'),     
                    "tag_vbat": r.get('bateria'), 
                    "tag_idx": r.get('indice')    
                }
            except Exception as e:
                continue
        return d_res
    except Exception as e:
        return {}

# 3.5. Funcion para optener los puntos de criticos de la base de datos Diccionario_puntos_criticos
@st.cache_data(ttl=5)
def cargar_puntos_criticos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        df = pd.read_sql("SELECT * FROM Diccionario_puntos_criticos", engine)
        d_res = {}
        for _, r in df.iterrows():
            try:
                raw_c = str(r['coord']).replace('(', '').replace(')', '').replace(' ', '').strip()
                lat_s, lon_s = raw_c.split(',')
                id_reg = r.get('Serie', r.get('Registrador', 'ID'))
                d_res[str(id_reg)] = {
                    "nombre": str(r.get('Domicilio', r.get('Nombre_registrador', 'S/N'))),
                    "coord": [float(lat_s), float(lon_s)],
                    "sector": str(r['Sector']).split('.')[0].strip(),
                    "tag_p1": r.get('Presion_1'),
                    "tag_q": r.get('Caudal'),        
                }
            except Exception as e:
                continue
        return d_res
    except Exception as e:
        return {}



# 4. SECCION -------------------------------------------------------------------------------- 4. GRAFICAR LOS TANQUES EN EL POPUP --------------------------------------------------------------------
params = st.query_params
tag_a_graficar = params.get("graficar_tanque", None)
nombre_tq = params.get("nombre", "Tanque")

if tag_a_graficar:
    import datetime
    import plotly.express as px
    import pandas as pd
    import plotly.graph_objects as go
    
    st.title(f"📊 Análisis de Nivel: {nombre_tq}")
    
    # 4.1. FILTROS DE FECHA ---
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        opcion_fecha = st.selectbox(
            "Selecciona un rango:",
            ["Hoy", "Esta Semana", "Últimos 14 días", "Este Mes", "Personalizado"],
            index=2, # <--- CAMBIO: Ahora selecciona 'Últimos 14 días' por defecto
            key="pop_selector_final_v8"
        )

    hoy = datetime.date.today()
    
    # 4.2. Lógica de selección de fechas
    if opcion_fecha == "Hoy":
        fecha_inicio = hoy
        fecha_fin = hoy
    elif opcion_fecha == "Esta Semana":
        fecha_inicio = hoy - datetime.timedelta(days=hoy.weekday())
        fecha_fin = hoy
    elif opcion_fecha == "Últimos 14 días":
        fecha_inicio = hoy - datetime.timedelta(days=14)
        fecha_fin = hoy
    elif opcion_fecha == "Este Mes":
        fecha_inicio = hoy.replace(day=1)
        fecha_fin = hoy
    else: 
        with col_f2:
            rango = st.date_input("Periodo:", value=(hoy - datetime.timedelta(days=7), hoy), max_value=hoy, key="pop_cal_v8")
            fecha_inicio, fecha_fin = rango if isinstance(rango, tuple) and len(rango)==2 else (hoy, hoy)

    # 4.3. CONSULTA A LA BASE DE DATOS
    try:
        engine = get_mysql_scada_engine()
        f_desde = f"{fecha_inicio} 00:00:00"
        f_hasta = f"{fecha_fin} 23:59:59"
        
        query = f"""
            SELECT h.FECHA, h.VALUE 
            FROM vfitagnumhistory h
            JOIN VfiTagRef r ON h.GATEID = r.GATEID
            WHERE r.NAME = '{tag_a_graficar}'
            AND h.FECHA BETWEEN '{f_desde}' AND '{f_hasta}'
            ORDER BY h.FECHA ASC
        """
        
        df_hist = pd.read_sql(query, engine)

        if not df_hist.empty:
            df_hist['FECHA'] = pd.to_datetime(df_hist['FECHA'])
            df_hist['VALUE'] = df_hist['VALUE'].round(2)
            
            # 4.4. CREACIÓN DEL GRÁFICO DE ÁREA DESVANECIDA
            fig = go.Figure()

            fig.add_trace(go.Scatter(
                x=df_hist['FECHA'],
                y=df_hist['VALUE'],
                mode='lines+markers',
                line=dict(color='#00d4ff', width=2),
                marker=dict(size=4, color='#00d4ff'),
                fill='tozeroy',
                fillcolor='rgba(0, 212, 255, 0.2)', # Efecto desvanecido
                hovertemplate="<b>%{y:.2f} m</b><extra></extra>"
            ))
            
            # 4.5. CONFIGURACIÓN DE LA LÍNEA GUÍA (PUNTEADA GRIS)
            fig.update_xaxes(
                showspikes=True, 
                spikecolor="gray", 
                spikethickness=1, 
                spikemode="across", 
                spikesnap="cursor",
                spikedash="dash", 
                showgrid=False
            )
            
            fig.update_layout(
                template="plotly_dark",
                hovermode="x unified",
                xaxis_title="Fecha y Hora",
                yaxis_title="Nivel (m)",
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                yaxis=dict(
                    tickformat=".2f",
                    showgrid=True,
                    gridcolor='#333'
                ),
                hoverlabel=dict(
                    bgcolor="#1f2c38",
                    font_size=12
                )
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            with st.expander("Ver tabla de datos detallada"):
                st.dataframe(
                    df_hist[['FECHA', 'VALUE']].sort_values(by='FECHA', ascending=False), 
                    use_container_width=True
                )
        else:
            st.warning(f"No hay datos registrados desde el {f_desde} hasta el {f_hasta}")
            
    except Exception as e:
        st.error(f"Error en la consulta: {e}")
    
    st.stop()

# 4.6. SECCION -------------------------------------------------------------------------------- 5. GRAFICAR LOS POZOS --------------------------------------------------------------------

from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pandas as pd

params = st.query_params

if "graficar_pozo" in params:
    id_pozo_graf = params["graficar_pozo"]
    nombre_pozo = params.get("nombre", id_pozo_graf)
    
    mapa_pozos_dict = cargar_mapa_pozos_desde_db()
    pozo_info = mapa_pozos_dict.get(id_pozo_graf)

    if not pozo_info:
        st.error(f"❌ No se encontró configuración para el pozo: {id_pozo_graf}")
        st.stop()

    cabecera_placeholder = st.empty()
    
    # 5.1. FILTRO DE TIEMPO
    col_f1, col_f2 = st.columns([2, 2])
    with col_f1:
        opcion_fecha = st.selectbox(
            "Rango de tiempo:", 
            ["Hoy", "Ayer", "Últimos 7 días", "Últimos 14 días", "Este Mes", "Último Mes", "Últimos 6 meses", "Personalizado"], 
            index=2, 
            key="fecha_pozo_v8"
        )

    hoy_dt = datetime.now()
    f_fin = hoy_dt
    
    if opcion_fecha == "Hoy":
        f_ini = hoy_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    elif opcion_fecha == "Ayer":
        f_ini = (hoy_dt - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        f_fin = hoy_dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
    elif opcion_fecha == "Últimos 7 días":
        f_ini = hoy_dt - timedelta(days=7)
    elif opcion_fecha == "Últimos 14 días":
        f_ini = hoy_dt - timedelta(days=14)
    elif opcion_fecha == "Este Mes":
        f_ini = hoy_dt.replace(day=1, hour=0, minute=0, second=0)
    elif opcion_fecha == "Último Mes":
        primero_este_mes = hoy_dt.replace(day=1, hour=0, minute=0, second=0)
        f_fin = primero_este_mes - timedelta(seconds=1)
        f_ini = (primero_este_mes - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0)
    elif opcion_fecha == "Últimos 6 meses":
        f_ini = hoy_dt - timedelta(days=180)
    elif opcion_fecha == "Personalizado":
        with col_f2:
            rango = st.date_input("Selecciona el periodo:", value=(hoy_dt.date() - timedelta(days=7), hoy_dt.date()), max_value=hoy_dt.date())
        if isinstance(rango, (list, tuple)) and len(rango) == 2:
            f_ini = datetime.combine(rango[0], datetime.min.time())
            f_fin = datetime.combine(rango[1], datetime.max.time())
        else:
            st.info("Selecciona el rango en el calendario.")
            st.stop()
    else:
        f_ini = hoy_dt - timedelta(days=7) 

    # 5.2. CONFIGURACIÓN Y CONSULTA
    tag_totalizado = str(pozo_info.get('totalizado', '')).strip()
    tag_caudal_real = pozo_info.get('caudal', '')
    tag_presion_real = pozo_info.get('presion', '')
    tags_voltaje = [t for t in pozo_info.get('voltajes_l', []) if t and t != 'N/A']
    tags_amperaje = [t for t in pozo_info.get('amperajes_l', []) if t and t != 'N/A']
    
    config_visual = [('caudal', "Caudal (Lps)", False, '#00d4ff'), ('presion', "Presión (Kg/cm²)", True, '#00ff00')]
    for i, t in enumerate(pozo_info.get('voltajes_l', [])):
        if t and t != 'N/A': config_visual.append((t, f"V L{i+1}", True, '#fffb00'))
    for i, t in enumerate(pozo_info.get('amperajes_l', [])):
        if t and t != 'N/A': config_visual.append((t, f"Amp L{i+1}", True, '#ff8000'))

    tags_grafico = []
    for item in config_visual:
        real_t = pozo_info.get(item[0], item[0])
        if real_t and real_t != 'N/A': tags_grafico.append({'tag': real_t, 'label': item[1], 'side': item[2], 'color': item[3]})

    tags_query = [t['tag'] for t in tags_grafico]
    if tag_totalizado and tag_totalizado != 'N/A': tags_query.append(tag_totalizado)

    if tags_query:
        try:
            engine = get_mysql_scada_engine()
            lista_tags_str = f"','".join(list(set(tags_query)))
            q = f"SELECT r.NAME as TagName, h.VALUE, h.FECHA FROM vfitagnumhistory h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{lista_tags_str}') AND h.FECHA BETWEEN '{f_ini}' AND '{f_fin}' ORDER BY h.FECHA ASC"
            df = pd.read_sql(q, engine)
            
            # --- LÓGICA DE INDICADORES ---
            val_vol, val_cau_prom, val_pre_prom = "0.00", "0.00", "0.00"
            val_v_prom, val_a_prom = "0.00", "0.00"

            if not df.empty:
                if tag_totalizado in df['TagName'].values:
                    df_tot = df[df['TagName'] == tag_totalizado].sort_values('FECHA')
                    if len(df_tot) >= 2:
                        val_vol = f"{(float(df_tot['VALUE'].iloc[-1]) - float(df_tot['VALUE'].iloc[0])):,.2f}"
                if tag_caudal_real in df['TagName'].values:
                    val_cau_prom = f"{df[df['TagName'] == tag_caudal_real]['VALUE'].mean():,.2f}"
                if tag_presion_real in df['TagName'].values:
                    val_pre_prom = f"{df[df['TagName'] == tag_presion_real]['VALUE'].mean():,.2f}"
                if tags_voltaje:
                    val_v_prom = f"{df[df['TagName'].isin(tags_voltaje)]['VALUE'].mean():,.1f}"
                if tags_amperaje:
                    val_a_prom = f"{df[df['TagName'].isin(tags_amperaje)]['VALUE'].mean():,.1f}"

            # RENDER CABECERA CORREGIDO
            cabecera_placeholder.markdown(f"""
<div style="display: flex; align-items: center; gap: 20px; margin-bottom: 25px; border-bottom: 1px solid #333; padding-bottom: 15px;">
    <h1 style="margin: 0; font-size: 32px; color: white; white-space: nowrap;">📈 Análisis Integral: <span style="color:#00d4ff;">{nombre_pozo}</span></h1>
    <div style="display: flex; gap: 12px; flex-wrap: wrap;">
        <div style="padding: 12px 18px; background: rgba(0, 212, 255, 0.05); border: 2px solid #00d4ff; border-radius: 12px; min-width: 150px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Volumen</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_vol} <small style="font-size: 12px; color: #00d4ff;">m³</small></span>
        </div>
        <div style="padding: 12px 18px; background: rgba(0, 212, 255, 0.05); border: 2px solid #00d4ff; border-radius: 12px; min-width: 150px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Caudal Promedio</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_cau_prom} <small style="font-size: 12px; color: #00d4ff;">Lps</small></span>
        </div>
        <div style="padding: 12px 18px; background: rgba(0, 255, 0, 0.05); border: 2px solid #00ff00; border-radius: 12px; min-width: 150px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Presión Promedio</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_pre_prom} <small style="font-size: 12px; color: #00ff00;">Kg</small></span>
        </div>
        <div style="padding: 12px 18px; background: rgba(255, 251, 0, 0.05); border: 2px solid #fffb00; border-radius: 12px; min-width: 150px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Voltaje Prom</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_v_prom} <small style="font-size: 12px; color: #fffb00;">V</small></span>
        </div>
        <div style="padding: 12px 18px; background: rgba(255, 128, 0, 0.05); border: 2px solid #ff8000; border-radius: 12px; min-width: 150px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Amperaje Prom</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_a_prom} <small style="font-size: 12px; color: #ff8000;">A</small></span>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

            # --- GRÁFICO PLOTLY ---
            if not df.empty:
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                for t in tags_grafico:
                    dft = df[df['TagName'] == t['tag']]
                    if not dft.empty:
                        fig.add_trace(
                            go.Scatter(
                                x=dft['FECHA'], y=dft['VALUE'], name=t['label'], 
                                mode='lines+markers' if "Amp" in t['label'] else 'lines',
                                line=dict(color=t['color'], width=2.5)
                            ), 
                            secondary_y=t['side']
                        )
                
                fig.update_layout(
                    template="plotly_dark", height=650, paper_bgcolor='rgba(0,0,0,0)', 
                    plot_bgcolor='rgba(0,0,0,0)', hovermode="x unified",
                    legend=dict(orientation="h", y=1.08, x=0, xanchor="left"),
                    margin=dict(l=60, r=60, t=100, b=50)
                )
                
                fig.update_yaxes(title_text="<b>Caudal (Lps)</b>", secondary_y=False, color='#00d4ff', showgrid=True, gridcolor='#333')
                fig.update_yaxes(title_text="<b>Presión / Eléctricos</b>", secondary_y=True, color='#00ff00', showgrid=False)
                fig.update_xaxes(title_text="Tiempo", showgrid=True, gridcolor='#333')
                
                st.plotly_chart(fig, use_container_width=True)

        except Exception as e: st.error(f"Error: {e}")
    st.stop()
    
# 5. SECCION------------------------------------------------------------------------------5. ESTILO CSS ----------------------------------------------------------------------------------------------------------
st.markdown("""
    <style>
        [data-testid="collapsedControl"], button[kind="headerNoPadding"], [data-testid="stSidebarCollapseButton"] {
            display: none !important;
        }
        header { visibility: hidden !important; height: 0px !important; }
        .stApp { background-color: #000000; color: white; }
        
        .block-container {
            padding-top: 0rem !important;
            margin-top: 15px !important; /* Subimos el inicio de la página al máximo */
            max-width: 100% !important;
        }

        .mapa-area iframe { 
            margin-top: 90px !important; /* Ajusta este para subir el mapa al ras */
            border: 1px solid #1f4068 !important;
            height: 85vh !important;
        }

        /* Evitamos que las columnas de sectores se rompan */
            .mapa-area [data-testid="column"] {
            flex: 1 1 0% !important;
        }

        /* 5. TÍTULO SUPERIOR (BARRA FIJA) */
        .titulo-superior {
            position: fixed;
            top: 0px; 
            left: calc(50% + 160px); 
            transform: translateX(-50%);
            z-index: 1000;
            color: #00d4ff; 
            font-size: 1.5rem;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 2px;
            text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
            background-color: #000000; /* Fondo sólido para que no haya transparencias feas */
            width: 100%;
            text-align: center;
            padding: 10px 0;
            border-bottom: 1px solid #1f4068;
        }

        /* CONTENEDOR DE INDICADORES (HUD FIJO) */
        .contenedor-indicadores {
           position: fixed;
           top: 65px; 
           left: 320px;
           right: 0;
           display: flex;
           justify-content: center;
           align-items: center;
           gap: 15px; /* <--- Aumenta esto para despegarlos (puedes probar 10px o 15px) */
           z-index: 1001;
           background: transparent; /* Quita el fondo negro del contenedor para que se vea el hueco */
           padding: 0 15px;
         }

        .card-indicador {
           flex: 1;
         /* Cambia el borde a uno más brillante para que se note la separación */
           border: 1px solid #1f4068; 
           background: linear-gradient(180deg, rgba(11, 26, 41, 0.95) 0%, rgba(0, 0, 0, 1) 100%);
           padding: 8px 5px;
           text-align: center;
           border-radius: 10px; /* <--- Añade esto para redondear las esquinas y que no parezca tabla */
           box-shadow: 0px 4px 10px rgba(0, 0, 0, 0.5); /* Sombra para dar volumen */
        }
        .card-indicador:first-child { border-left: 1px solid #1f4068; }

        .card-label { color: #888888; font-size: 0.7rem; font-weight: bold; text-transform: uppercase; margin: 0; }
        .card-value { font-family: 'Courier New', monospace; font-size: 1.5rem; font-weight: bold; margin: 0; }
        
        .val-on { color: #00ff00; text-shadow: 0 0 8px rgba(0, 255, 0, 0.5); }
        .val-off { color: #ff0000; text-shadow: 0 0 8px rgba(255, 0, 0, 0.5); }
        .val-falla { color: #ffaa00; text-shadow: 0 0 8px rgba(255, 170, 0, 0.5); }
        .val-sin { color: #ffffff; }

        /* ESTO SUBE EL MAPA A LA FUERZA */
        .mapa-principal-ajuste {
            margin-top: -200px !important; /* Margen negativo agresivo para eliminar el hueco */
            z-index: 1;
        }
        /* Ajuste específico para el iframe de Folium */
        .mapa-principal-ajuste iframe {
            border: 1px solid #1f4068 !important;
            border-top: none !important;
        }

        /* 6. SIDEBAR - CONTENIDO PEGADO AL LOGO */
        [data-testid="stSidebarContent"] {
            padding-top: 30px !important; 
        }

        [data-testid="stSidebar"] { 
            background-color: #0b1a29 !important; 
            border-right: 2px solid #1f4068; 
        }

        /* Ajuste Sidebar */
       .sidebar-logo { 
           position: fixed; 
           top: 20px; 
           left: 40px; 
           width: 250px;  /* <--- REDUCE ESTE VALOR (ej. 200px) */
           height: 80px;  /* <--- REDUCE ESTE VALOR (ej. 60px) para que sea menos alto */
           z-index: 999999; 
           display: flex; 
           justify-content: center; 
           align-items: center;
           background-color: #0b1a29; 
           border-bottom: 1px solid #1f4068;
         }
         
        .status-tag { 
            font-size: 10px; 
            padding: 2px 6px; 
            border-radius: 4px; 
            margin-left: 5px; 
            font-weight: bold; 
        }
        
        .status-ok { background-color: #1b5e20; color: #a5d6a7; }
        .status-err { background-color: #b71c1c; color: #ef9a9a; }
        
        .section-header { 
            padding: 10px; 
            border-radius: 3px; 
            font-weight: bold; 
            margin-bottom: 5px; 
            color: white; 
        }

        /* ANIMACIÓN DE PARPADEO */
        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0; } 100% { opacity: 1; } }
        .blink_me { animation: blink 1.2s infinite; }

    </style>
""", unsafe_allow_html=True)
# 6. SECCION----------------------------------------------------------------- 6. PROCESAMIENTO (MODIFICADO) -----------------------------------------------------------------
# 6.1. Carga de datos base
sectores = cargar_sectores_poligonos()
mapa_pozos_dict = cargar_mapa_pozos_desde_db()
mapa_tanques_dict = cargar_tanques_desde_db()
mapa_rebombeos_dict = cargar_rebombeos_desde_db()

# 6.2. Recolección de tags para la consulta masiva
tags_a_consultar = []

for p in mapa_pozos_dict.values():
    # 6.3. Añadimos los campos que te faltaban: nivel_dinamico, sumergencia y columna
    tags_a_consultar.extend([
        p['bomba'], 
        p['caudal'], 
        p['presion'], 
        p['nivel_tanque'],
        p['nivel_dinamico'],
        p['sumergencia'],
        p['columna']
    ])
    # 6.4. Voltajes y amperajes
    tags_a_consultar.extend(p['voltajes_l'] + p['amperajes_l'])

# 6.5. Tags de Tanques
for t in mapa_tanques_dict.values():
    if t['tag_nivel']: tags_a_consultar.append(t['tag_nivel'])

# 6.6. Tags de Rebombeos
for r in mapa_rebombeos_dict.values():
    tags_a_consultar.extend([r['presion'], r['nivel_tanque']])
    tags_a_consultar.extend(r['voltajes_l'] + r['amperajes_l'])

# 6.7. Limpieza de la lista
tags_finales = list(set([str(t).strip() for t in tags_a_consultar if t and str(t) not in ['0', 'Sin telemetria', 'None']]))

# 6.8. Consulta al SCADA pasando la LISTA corregida
data_scada = cargar_datos_scada(tags_finales)

# 6.9. Inicialización de contadores
pozos_on, pozos_off, pozos_sin_telemetria, pozos_falla_com = [], [], [], []
total_q, total_p = 0.0, 0.0

import datetime as dt
ahora = dt.datetime.utcnow() - dt.timedelta(hours=6) 

# 6.10. LÓGICA DE POZOS
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
        val_bba, _ = data_scada.get(info['bomba'], (0, "N/A"))
        if val_bba == 1:
            info.update({'status_label': 'OPERANDO', 'color_final': '#00FF00', 'blink': False})
            pozos_on.append(id_p)
            total_q += data_scada.get(info['caudal'], (0, ""))[0]
            total_p += data_scada.get(info['presion'], (0, ""))[0]
        else:
            info.update({'status_label': 'APAGADO', 'color_final': '#FF0000', 'blink': True})
            pozos_off.append(id_p)

# 6.11. LÓGICA DE REBOMBEOS (CORREGIDA) 
for id_rb, info in mapa_rebombeos_dict.items():

    telemetria_status = str(info.get('telemetria', '')).strip().lower()
    
    if telemetria_status == "sin telemetria":
        info.update({
            'status_label': 'SIN TELEMETRÍA', 
            'color_final': '#808080',  # Color Gris
            'blink': False
        })
    else:
        # 6.12. Si tiene telemetría, aplicar la lógica de presión actual
        pres_val, _ = data_scada.get(info['presion'], (0, "N/A"))
        if pres_val < 0.10:
            info.update({
                'status_label': 'APAGADO', 
                'color_final': '#FF0000', 
                'blink': True
            })
        else:
            info.update({
                'status_label': 'OPERANDO', 
                'color_final': '#00FF00', 
                'blink': False
            })


# 7. SECCION ------------------------------------------------------------------7. DETALLE DE SECTOR -------------------------------------------------------------------------------------------
if sector_seleccionado:
    # 7.1. Estilos CSS: Ajuste agresivo para subir el mapa al ras de los indicadores
    st.markdown(
        f"""
        <style>
            [data-testid="stSidebar"] {{display: none;}}
            header {{visibility: hidden;}}
            .stAppDeployButton {{display:none;}}
            #MainMenu {{visibility: hidden;}}
            footer {{visibility: hidden;}}
            
            /* Ajuste del contenedor principal para eliminar espacio superior */
            .block-container {{
                padding-top: 0px !important;
                padding-bottom: 0px !important;
                margin-top: -100px !important; /* Aumentamos el recorte superior */
            }}
            
            .contenedor-centrado {{
                text-align: center;
                margin-bottom: 0px;
            }}
            
            .titulo-sector {{
                margin-top: 10px !important;
                font-size: 1.8rem;
                font-weight: 800;
                color: #00d4ff;
                margin: 10px;
                text-transform: uppercase;
            }}

            /* ELIMINAR EL MARGEN DE LA COLUMNA DEL MAPA */
            .col-mapa-offset {{
                margin-top: 0px !important; /* Cambiado de 40px a 0px */
            }}

            /* Ajuste para que el mapa ocupe más espacio visual hacia arriba */
            .stFolium {{
                margin-top: -10px !important;
            }}            

            hr {{
                margin-top: 2px !important;
                margin-bottom: 5px !important;
                border: 0;
                border-top: 1px solid #1f4068;
            }}
            /* Dentro del bloque <style> */

            .card-indicador {{
                background: rgba(16, 33, 54, 0.8); /* Fondo oscuro semitransparente */
                padding: 10px;
                border-radius: 8px;
                border: 1px solid #1f4068;
                text-align: center;
                margin-bottom: 5px;
            }}

            .label-indicador {{
                color: #ffffff; 
                font-size: 0.8rem; 
                margin: 0;
                text-transform: uppercase;
                letter-spacing: 0.5px;
              }}

             .value-indicador {{
                color: #00ffcc; 
                font-size: 1.1rem; 
                font-weight: bold; 
                margin: 0;
              }}
              
              /* Agrega esto dentro de tu bloque <style> en el st.markdown inicial */
              [data-testid="column"]:nth-child(2) {{
              margin-top: 0px !important;
              }}

             /* Reducir el padding de los gráficos de Plotly para aprovechar el ancho */
            .js-plotly-plot {{
            margin-bottom: 10px !important;
            }}

        </style>
        <div class="contenedor-centrado">
            <h1 class="titulo-sector">ANÁLISIS DE SECTOR: {sector_seleccionado}</h1>
        </div>
        """, unsafe_allow_html=True
    )
    
    sec_id = str(sector_seleccionado).split('.')[0].strip()
    datos_s = next((s for s in sectores if str(s['sector']).strip() == sec_id), None)

# 7.2. Métricas de cabecera
    if datos_s:
        st.markdown('<div class="metrics-row">', unsafe_allow_html=True)
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        
        with c1: 
            st.markdown(f'<div class="card-indicador"><p class="label-indicador">Población</p><p class="value-indicador">{datos_s.get("Poblacion", 0):,.0f}</p></div>', unsafe_allow_html=True)
        with c2: 
            st.markdown(f'<div class="card-indicador"><p class="label-indicador">U. Totales</p><p class="value-indicador">{datos_s.get("U_Tot", 0):,.0f}</p></div>', unsafe_allow_html=True)
        with c3: 
            st.markdown(f'<div class="card-indicador"><p class="label-indicador">U. Domésticos</p><p class="value-indicador">{datos_s.get("U_Domesticos", 0):,.0f}</p></div>', unsafe_allow_html=True)
        with c4: 
            st.markdown(f'<div class="card-indicador"><p class="label-indicador">Consumo m³</p><p class="value-indicador">{datos_s.get("Cons_m3", 0):,.1f}</p></div>', unsafe_allow_html=True) 
        with c5: 
            st.markdown(f'<div class="card-indicador"><p class="label-indicador">Dotación</p><p class="value-indicador">{datos_s.get("Dotacion", 0):,.1f}</p></div>', unsafe_allow_html=True)
        with c6: 
            st.markdown(f'<div class="card-indicador"><p class="label-indicador">Balance</p><p class="value-indicador">{datos_s.get("Balance_Estimado", 0):,.1f}%</p></div>', unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
        st.divider()
        

        # 7.3. Selectores superiores
        dict_reg_all = cargar_puntos_de_control_desde_db() 
        dict_reg = {k: v for k, v in dict_reg_all.items() if str(v.get('sector')).strip() == str(sec_id).strip()}
        reg_nombres = {v['nombre']: k for k, v in dict_reg.items()}
        opciones_equipo = list(reg_nombres.keys())
        c_vacia, c_sel1, c_sel2 = st.columns([1.0, 150.00, 150.00])
        with c_sel1:
            opcion_fecha = st.selectbox("Rango de fechas:", ["Hoy", "Esta Semana", "Últimos 14 días", "Este Mes", "Personalizado"], index=2, key="f_sector_full")
        with c_sel2:
            if not opciones_equipo:
                sel_r = None
                st.selectbox("Equipo punto de control:", ["Sin equipos en este sector"], key="sel_reg_full", disabled=True)
            else:
                sel_r = st.selectbox("Equipo punto de control:", opciones_equipo, key="sel_reg_full")

        # 7.4. Layout: Mapa e Histórico
        col_izq, col_der = st.columns([1.0, 1.0])
        
        with col_izq:
            st.markdown('<div class="col-mapa-offset">', unsafe_allow_html=True)

            #  LÓGICA DE PERSISTENCIA PARA EL POPUP ---
            if "ultimo_clic_sv" not in st.session_state:
                st.session_state.ultimo_clic_sv = None
            
            #  Preparar el objeto mapa (No dibuja nada todavía)
            m_sec = folium.Map(
                location=[21.8820, -102.2800], 
                zoom_start=12, 
                tiles=None,
                height=350 
            )

            #  Configurar capas en el objeto m_sec
            folium.TileLayer(
                tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
                attr='Google', name='Vista Satélite', overlay=False, control=True
            ).add_to(m_sec)

            folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                attr='Esri', name='Satélite (Esri)', overlay=False, control=True
            ).add_to(m_sec)

            folium.TileLayer(
                tiles="CartoDB dark_matter", name="Vista Nocturna", attr="CartoDB", 
                overlay=False, control=True
            ).add_to(m_sec)

            #  DIBUJAR EL SECTOR SELECCIONADO (GeoJSON)
            if datos_s and datos_s.get('geo'):
                try:
                    geo_data = json.loads(datos_s['geo'])
                    folium_geo = folium.GeoJson(
                        geo_data, 
                        style_function=lambda x: {
                            'fillColor': '#00d4ff', 
                            'color': '#ffffff', 
                            'weight': 2, 
                            'fillOpacity': 0.15
                        },
                        name="Límites del Sector"
                    ).add_to(m_sec)
                    
                    # Ajustar la vista automáticamente al sector
                    m_sec.fit_bounds(folium_geo.get_bounds())
                except Exception:
                    pass

            # 7.5. CARGA DATOS SCADA (FILTRADOS)
            tags_para_scada = []
            for r in dict_reg.values():
                for k in ['tag_p1', 'tag_p2', 'tag_q', 'tag_vbat']:
                    if r.get(k): tags_para_scada.append(r.get(k))
            
            mapa_pc_all = cargar_puntos_criticos_desde_db()
            dict_pc_sec = {k: v for k, v in mapa_pc_all.items() if str(v.get('sector')).strip() == str(sec_id).strip()}
            for pc in dict_pc_sec.values():
                if pc.get('tag_p1'): tags_para_scada.append(pc.get('tag_p1'))

            scada_res_reg = cargar_datos_scada(list(set(tags_para_scada)))

            # 7.6. Marcadores de puntos de control
            for r in dict_reg.values():
                def get_rv(tk):
                    v, f = scada_res_reg.get(r.get(tk), (0.0, "N/A"))
                    try: return float(v), f
                    except: return 0.0, f

                rp1, fp1 = get_rv('tag_p1'); rcau, fq = get_rv('tag_q'); rbat, fb = get_rv('tag_vbat')
                
                html_popup_reg = f"""
                <div style="background:#000; color:white; padding:12px; border-radius:10px; border:1px solid #00FFFF; width:250px; font-family:sans-serif;">
                    <b style="color:#00FFFF; font-size:14px;">{r['nombre']}</b>
                    <hr style="opacity:0.2; margin:8px 0;">
                    <div style="font-size:11px;">
                        💧 Caudal: <b>{rcau:.2f} L/s</b><br><span style="color:#FFFF00;">{fq}</span><br><br>
                        🚀 Presión: <b>{rp1:.2f} kg</b><br><span style="color:#FFFF00;">{fp1}</span><br><br>
                        🔋 Bat: <b>{rbat:.2f} V</b><br><span style="color:#FFFF00;">{fb}</span>
                    </div>
                </div>
                """
                folium.Marker(
                    location=r['coord'], 
                    icon=folium.Icon(color='cadetblue', icon='star', prefix='fa'), 
                    popup=folium.Popup(html_popup_reg, max_width=300)
                ).add_to(m_sec)

            # 7.7 Marcadores de Puntos Críticos
            for id_pc, pc in dict_pc_sec.items():
                val_p, fec_p = scada_res_reg.get(pc['tag_p1'], (0.0, "N/A"))
                html_pc = f"""
                <div style="background:#000; color:white; padding:10px; border-radius:8px; border:1px solid #FF00FF; width:180px; font-family:sans-serif;">
                    <b style="color:#FF00FF; font-size:13px;">PUNTO CRÍTICO</b><br>
                    <small>{pc['nombre']}</small><br>
                    <hr style="opacity:0.2; margin:5px 0;">
                    Presión: <b style="color:#FF00FF;">{val_p:.2f} kg</b><br>
                    <span style="color:#FFFF00; font-size:9px;">{fec_p}</span>
                </div>
                """
                folium.RegularPolygonMarker(
                    location=pc['coord'], number_of_sides=3, radius=7, color='#FF00FF',
                    fill=True, fill_color='#FF00FF', popup=folium.Popup(html_pc, max_width=250)
                ).add_to(m_sec)

            # 7.8. Marcadores de Pozos
            ids_p = [p.strip() for p in datos_s.get('Pozos_Sector', '').split(',')] if datos_s.get('Pozos_Sector') else []
            for id_p in ids_p:
                if id_p in mapa_pozos_dict:
                    info = mapa_pozos_dict[id_p]
                    def ds(tag):
                        val, fec = data_scada.get(tag, (0.0, "N/A"))
                        try: return float(val), fec
                        except: return 0.0, fec

                    q, f_q = ds(info['caudal']); p, f_p = ds(info['presion'])
                    tanq, f_t = ds(info.get('nivel_tanque')); dinam, f_d = ds(info.get('nivel_dinamico'))
                    v = [ds(info.get(f'v{i}')) for i in range(1, 4)]; a = [ds(info.get(f'a{i}')) for i in range(1, 4)]

                    html_popup_sec = f"""
                    <div style="background: #050505; color: white; padding: 15px; border-radius: 12px; width: 380px; border: 1px solid {info['color_final']}; font-family: sans-serif;">
                        <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 8px; margin-bottom: 10px;">
                            <b style="color: #00d4ff; font-size: 16px;">POZO {id_p}</b>
                            <span style="font-size: 10px; background: {info['color_final']}; color: black; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{info['status_label']}</span>
                        </div>
                        <div style="margin-bottom: 12px;">
                            <div style="font-size: 10px; color: #888; margin-bottom: 4px;">HIDRÁULICA</div>
                            <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                                <span>💧 Caudal: <b>{q:.2f} L/s</b></span>
                                <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_q}</span>
                            </div>
                            <div style="display: flex; align-items: baseline; font-size: 11px;">
                                <span>🚀 Presión: <b>{p:.2f} kg</b></span>
                                <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_p}</span>
                            </div>
                        </div>
                        <div>
                            <div style="font-size: 10px; color: #888; margin-bottom: 4px;">ELÉCTRICO</div>
                            <table style="width: 100%; font-size: 10px; border-collapse: collapse;">
                                <tr style="color: #00d4ff; border-bottom: 1px solid #333; text-align: left;">
                                    <th style="padding: 4px;">Fase</th><th style="padding: 4px;">V / Act.</th><th style="padding: 4px;">A / Act.</th>
                                </tr>
                                <tr><td>L1-L2</td><td>{v[0][0]:.1f}V <small style="color:#FFFF00;">{v[0][1]}</small></td><td>{a[0][0]:.1f}A <small style="color:#FFFF00;">{a[0][1]}</small></td></tr>
                                <tr><td>L2-L3</td><td>{v[1][0]:.1f}V <small style="color:#FFFF00;">{v[1][1]}</small></td><td>{a[1][0]:.1f}A <small style="color:#FFFF00;">{a[1][1]}</small></td></tr>
                                <tr><td>L3-L1</td><td>{v[2][0]:.1f}V <small style="color:#FFFF00;">{v[2][1]}</small></td><td>{a[2][0]:.1f}A <small style="color:#FFFF00;">{a[2][1]}</small></td></tr>
                            </table>
                        </div>
                    </div>
                    """
                    if info.get('blink'):
                        folium.Marker(
                            location=info['coord'], 
                            icon=folium.DivIcon(html=get_blink_icon(info['color_final'])), 
                            popup=folium.Popup(html_popup_sec, max_width=400)
                        ).add_to(m_sec)
                    else:
                        folium.CircleMarker(
                            location=info['coord'], 
                            radius=6, color=info['color_final'], 
                            fill=True, fill_opacity=1, 
                            popup=folium.Popup(html_popup_sec, max_width=400)
                        ).add_to(m_sec)

            # --- 7.9. INSERCIÓN DEL MARCADOR DINÁMICO (Antes de renderizar) ---
            if st.session_state.get("ultimo_clic_sv"):
                try:
                    c_lat = st.session_state.ultimo_clic_sv["lat"]
                    c_lng = st.session_state.ultimo_clic_sv["lng"]
                    
                    sv_url = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={c_lat},{c_lng}"
            
                    html_popup_sv = f"""
                    <div style="background:#000; color:white; padding:10px; border-radius:8px; border:1px solid #00d4ff; width:180px; font-family:sans-serif;">
                        <b style="color:#00d4ff; font-size:12px;">COORDENADAS</b><br>
                        <code style="font-size:10px;">{c_lat:.5f}, {c_lng:.5f}</code><br><br>
                        <a href="{sv_url}" target="_blank" 
                           style="display:block; text-align:center; background:#00d4ff; color:black; padding:8px; border-radius:5px; text-decoration:none; font-weight:bold; font-size:10px;">
                           🚹 ABRIR STREET VIEW
                        </a>
                    </div>
                    """
                    folium.Marker(
                        location=[c_lat, c_lng],
                        popup=folium.Popup(html_popup_sv, max_width=200),
                        icon=folium.Icon(color='blue', icon='map-marker', prefix='fa'),
                        tooltip="Click para ver Street View"
                    ).add_to(m_sec)
                except Exception:
                    pass 

            #  CONTROLES Y RENDERIZADO FINAL ---
            folium.LayerControl(position='topright', collapsed=False).add_to(m_sec)
            from folium.plugins import Fullscreen
            Fullscreen(position='topleft').add_to(m_sec)

            salida = st_folium(
                m_sec, 
                width="100%", 
                height=330, 
                key="mapa_miaa_interactivo_v4",
                returned_objects=["last_clicked"]
            )

            #  CAPTURA DE EVENTO ---
            if salida and salida.get("last_clicked"):
                nuevo_clic = salida["last_clicked"]
                if st.session_state.get("ultimo_clic_sv") != nuevo_clic:
                    st.session_state.ultimo_clic_sv = nuevo_clic
                    st.rerun()
            
            st.markdown('</div>', unsafe_allow_html=True)
            


# 7.10. ----------------------------------------- Sección de Gráficos Históricos puntos de control -------------------------------------------------------------------------------------------------
        with col_der:
            hoy = datetime.now().date()
            if opcion_fecha == "Hoy": f_ini_h, f_fin_h = hoy, hoy
            elif opcion_fecha == "Esta Semana": f_ini_h, f_fin_h = hoy - timedelta(days=hoy.weekday()), hoy
            elif opcion_fecha == "Últimos 14 días": f_ini_h, f_fin_h = hoy - timedelta(days=14), hoy
            elif opcion_fecha == "Este Mes": f_ini_h, f_fin_h = hoy.replace(day=1), hoy
            else:
                rango = st.date_input("Periodo:", value=(hoy - timedelta(days=7), hoy), max_value=hoy, key="date_hist_f")
                f_ini_h, f_fin_h = rango if isinstance(rango, tuple) and len(rango)==2 else (hoy, hoy)

            # --- OBTENCIÓN DE DATOS REGISTRADOR (Punto de Control) ---
            # Verificamos que sel_r sea válido y exista en nuestro diccionario filtrado
            if sel_r and sel_r in reg_nombres:
                r_info = dict_reg[reg_nombres[sel_r]]
                t_q, t_p1, t_p2 = r_info.get('tag_q'), r_info.get('tag_p1'), r_info.get('tag_p2')
                tags_grafico = [t for t in [t_q, t_p1, t_p2] if t]

                if tags_grafico:
                    try:
                        engine_h = get_mysql_scada_engine()
                        tags_in = "', '".join(tags_grafico)
                        q_hist = f"""
                            SELECT h.FECHA, h.VALUE, r.NAME as TAG 
                            FROM vfitagnumhistory h 
                            JOIN VfiTagRef r ON h.GATEID = r.GATEID 
                            WHERE r.NAME IN ('{tags_in}') 
                            AND h.FECHA BETWEEN '{f_ini_h} 00:00:00' AND '{f_fin_h} 23:59:59' 
                            ORDER BY h.FECHA ASC
                        """
                        df_h = pd.read_sql(q_hist, engine_h)
                        
                        if not df_h.empty:
                            st.markdown(f"<h3 style='color:#00d4ff; font-size:16px; margin-bottom:0;'>Gráfico punto de Control:</h3>", unsafe_allow_html=True)
                            fig = go.Figure()
                            
                            # Línea de Caudal
                            if t_q and not df_h[df_h['TAG'] == t_q].empty:
                                df_q = df_h[df_h['TAG'] == t_q]
                                fig.add_trace(go.Scatter(x=df_q['FECHA'], y=df_q['VALUE'], name="Caudal (lps)", 
                                                       line=dict(color='#00d4ff', width=2), hovertemplate='%{y:.2f} L/s'))
                            
                            # Línea de Presión P1
                            if t_p1 and not df_h[df_h['TAG'] == t_p1].empty:
                                df_p1 = df_h[df_h['TAG'] == t_p1]
                                fig.add_trace(go.Scatter(x=df_p1['FECHA'], y=df_p1['VALUE'], name="Presión P1", 
                                                       yaxis="y2", line=dict(color='#ff00ff', width=2), hovertemplate='%{y:.2f} kg'))
                            
                            # Línea de Presión P2
                            if t_p2 and not df_h[df_h['TAG'] == t_p2].empty:
                                df_p2 = df_h[df_h['TAG'] == t_p2]
                                fig.add_trace(go.Scatter(x=df_p2['FECHA'], y=df_p2['VALUE'], name="Presión P2", 
                                                       yaxis="y2", line=dict(color='#00ff00', width=2), hovertemplate='%{y:.2f} kg'))

                            fig.update_layout(
                                paper_bgcolor='black', plot_bgcolor='black', height=300,
                                margin=dict(l=50, r=50, t=30, b=10),
                                hovermode="x unified",
                                hoverlabel=dict(bgcolor="rgba(30, 30, 30, 0.8)", font_size=12, font_color="white"),
                                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(color="white", size=10)),
                                xaxis=dict(showgrid=True, gridcolor='rgba(255, 255, 255, 0.1)', color="white"),
                                yaxis=dict(title="Caudal (L/s)", color="#00d4ff", showgrid=True, gridcolor='rgba(255, 255, 255, 0.1)'),
                                yaxis2=dict(title="Presión (kg)", side="right", color="#ff00ff", overlaying="y", showgrid=False)
                            )
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.warning(f"No hay datos históricos para {sel_r} en el periodo seleccionado.")

                    except Exception as e: 
                        st.error(f"Error en Histórico de Control: {e}")
            else:
                st.info("Seleccione un equipo del sector actual para ver el gráfico histórico.")

# 7.11. ------------------ GRÁFICO 2: HISTÓRICO PUNTOS CRÍTICOS -----------------------------------------------------------------------------------------------------------------------------------
            if dict_pc_sec:
                tags_pc = [v['tag_p1'] for v in dict_pc_sec.values() if v.get('tag_p1')]
                
                if tags_pc:
                    try:
                        tags_pc_in = "', '".join(tags_pc)
                        q_hist_pc = f"SELECT h.FECHA, h.VALUE, r.NAME as TAG FROM vfitagnumhistory h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_pc_in}') AND h.FECHA BETWEEN '{f_ini_h} 00:00:00' AND '{f_fin_h} 23:59:59' ORDER BY h.FECHA ASC"
                        df_pc_h = pd.read_sql(q_hist_pc, engine_h)

                        if not df_pc_h.empty:
                            st.markdown(f"<h3 style='color:#00d4ff; font-size:16px; margin-bottom:0;'>Puntos criticos del sector:</h3>", unsafe_allow_html=True)
                            fig_pc = go.Figure()
                            tag_to_name = {v['tag_p1']: v['nombre'] for v in dict_pc_sec.values()}

                            for tag in tags_pc:
                                df_temp = df_pc_h[df_pc_h['TAG'] == tag]
                                if not df_temp.empty:
                                    fig_pc.add_trace(go.Scatter(
                                        x=df_temp['FECHA'], 
                                        y=df_temp['VALUE'], 
                                        name=tag_to_name.get(tag, tag),
                                        mode='lines',
                                        line=dict(width=2),
                                        hovertemplate='<b>%{fullData.name}</b><br>Presión: %{y:.2f} kg<extra></extra>'
                                    ))

                            fig_pc.update_layout(
                                paper_bgcolor='black', plot_bgcolor='black', height=300,
                                margin=dict(l=50, r=50, t=40, b=10),
                                hovermode="x unified",
                                hoverlabel=dict(bgcolor="rgba(30, 30, 30, 0.8)", font_size=12, font_color="white"),
                                legend=dict(
                                    orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                                    font=dict(color="white", size=9),
                                    itemclick="toggle", 
                                    itemdoubleclick="toggleothers"
                                ),
                                xaxis=dict(showgrid=True, gridcolor='rgba(255, 255, 255, 0.1)', color="white"),
                                yaxis=dict(title="Presión PC (kg)", color="#FF00FF", showgrid=True, gridcolor='rgba(255, 255, 255, 0.1)')
                            )
                            st.plotly_chart(fig_pc, use_container_width=True)
                    except Exception as e: 
                        st.error(f"Error en Puntos Críticos: {e}")

    st.stop()
    
# 8. SECCION ------------------------------------------------------------------------------- 8. SIDEBAR BARRA LATERAL IZQUIERDA ------------------------------------------------------------------------------------------
st.set_page_config(layout="wide", initial_sidebar_state="expanded")
st.markdown("""
    <style>
        /* 1. ELIMINAR EL TIRADOR DE REDIMENSIÓN */
        /* Buscamos el elemento que permite arrastrar la barra y lo desactivamos */
        [data-testid="stSidebarResizer"] {
            display: none !important;
            pointer-events: none !important;
        }
        
        /* 2. FORZAR ANCHO ESTÁTICO E INAMOVIBLE */
        section[data-testid="stSidebar"] {
            width: 300px !important;
            min-width: 300px !important;
            max-width: 300px !important;
            /* Evita que el usuario seleccione texto o interactúe con el borde */
            user-select: none; 
        }

        /* 3. BLOQUEAR EL CURSOR DE REDIMENSIÓN */
        /* A veces el cursor cambia a flechas laterales; esto lo devuelve a la normalidad */
        html, body {
            cursor: default !important;
        }

    
        /* 1. AJUSTE DINÁMICO DEL MAPA AL MARGEN DERECHO */
        [data-testid="stMain"] {
            margin-left: 0px !important;
            /* Restamos el ancho de la barra para que el contenido no desborde */
            width: calc(100% - 0px) !important; 
            padding-right: 2rem !important; /* Espacio de seguridad a la derecha */
        }

        /* 2. ASEGURAR QUE EL CONTENEDOR DE STREAMLIT USE TODO EL ANCHO DISPONIBLE */
        .block-container {
            max-width: 100% !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }

        /* 3. ARREGLAR EL CONTROL DE CAPAS (LayerControl) */
        /* Forzamos que el cuadro de capas de Folium siempre esté visible y no se desborde */
        .leaflet-control-layers {
            margin-right: 20px !important; /* Separa el cuadro del borde derecho de la pantalla */
            border: 2px solid rgba(0,255,255,0.5) !important; /* Opcional: Estilo futurista */
            background: rgba(0, 0, 0, 0.8) !important; /* Fondo oscuro para que combine con tu HUD */
            color: white !important;
        }

        /* Cambiar color de los textos dentro del selector de capas para que se vean en fondo oscuro */
        .leaflet-control-layers-list, .leaflet-control-layers-base, .leaflet-control-layers-overlays {
            color: white !important;
        }
        
        /* 4. RESPONSIVIDAD PARA PANTALLAS PEQUEÑAS */
        @media (max-width: 991px) {
            [data-testid="stMain"] {
                margin-left: 350px !important;
                width: calc(100% - 350px) !important;
            }
        }
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    # 8.1. Contenedor del logo
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)

    # 8.2. Inicializamos variables de estado (Solo si no existen)
    if 'centro_mapa' not in st.session_state:
        st.session_state.centro_mapa = [21.8820, -102.2800]
        st.session_state.zoom_inicial = 12.5
    
    # 8.3. ESTADO DE LAS CONEXIONES
    with st.expander("🔌 Estado de las Conexiones", expanded=True):
        status_mysql_scada = "OK" if get_mysql_scada_engine() else "ERROR"
        status_mysql_tele = "OK" if get_mysql_telemetria_engine() else "ERROR"
        status_postgres = "OK" if get_postgres_conn() else "ERROR"

        def render_status_line(label, status):
            cls = "status-ok" if status == "OK" else "status-err"
            html = f"""
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                <span style="font-weight: bold; font-size: 13px;">{label}</span>
                <span class="status-tag {cls}">{status}</span>
            </div>
            """
            st.markdown(html, unsafe_allow_html=True)

        render_status_line("BD-Scada:", status_mysql_scada)
        render_status_line("BD-Diccionarios:", status_mysql_tele)
        render_status_line("BD-PostgreSQL:", status_postgres)
    
    # --- BUSCADORES ---
    
    # 8.4. Buscador de Pozos
    lista_pozos_nombres = sorted(list(mapa_pozos_dict.keys()))
    pozo_buscado = st.selectbox(
        "🔍 Localizar Pozo",
        options=[""] + lista_pozos_nombres,
        format_func=lambda x: "Seleccionar Pozo..." if x == "" else f"📍 {x}"
    )

    # 8.4.1 Buscador de Tanques
    lista_tanques_nombres = sorted(list(mapa_tanques_dict.keys()))
    tanque_buscado = st.selectbox(
        "💧 Localizar Tanque",
        options=[""] + lista_tanques_nombres,
        format_func=lambda x: "Seleccionar Tanque..." if x == "" else f"📦 {x} - {mapa_tanques_dict[x]['nombre']}"
    )

    # 8.4.2 Buscador de Rebombeos
    lista_rebombeos_nombres = sorted(list(mapa_rebombeos_dict.keys()))
    rebombeo_buscado = st.selectbox(
        "🚀 Localizar Rebombeo",
        options=[""] + lista_rebombeos_nombres,
        format_func=lambda x: "Seleccionar Rebombeo..." if x == "" else f"🔄 {x}"
    )

    # 8.5. Buscador de Sectores
    lista_sectores = sorted([s['sector'] for s in sectores])
    sector_buscado = st.selectbox(
        "🏘️ Localizar Sector",
        options=[""] + lista_sectores,
        format_func=lambda x: "Seleccionar Sector..." if x == "" else f" {x}",
        key="busqueda_sectores"
    )

    # 8.6. ASIGNACIÓN DE POSICIÓN Y PRIORIDAD
    datos_sector_resaltado = None
    
    if pozo_buscado:
        st.session_state.centro_mapa = mapa_pozos_dict[pozo_buscado]['coord']
        st.session_state.zoom_inicial = 18
    elif tanque_buscado:
        st.session_state.centro_mapa = mapa_tanques_dict[tanque_buscado]['coord']
        st.session_state.zoom_inicial = 18
    elif rebombeo_buscado:
        st.session_state.centro_mapa = mapa_rebombeos_dict[rebombeo_buscado]['coord']
        st.session_state.zoom_inicial = 18
    elif sector_buscado:
        datos_s = next((s for s in sectores if s['sector'] == sector_buscado), None)
        if datos_s:
            datos_sector_resaltado = datos_s
            try:
                geom = json.loads(datos_s['geo'])
                coords_raw = geom['coordinates'][0][0][0] if geom['type'] == 'MultiPolygon' else geom['coordinates'][0][0]
                st.session_state.centro_mapa = [coords_raw[1], coords_raw[0]]
                st.session_state.zoom_inicial = 14.5
            except:
                pass
    else:
        # Si no hay nada seleccionado, mantener vista general
        st.session_state.centro_mapa = [21.8820, -102.2800]
        st.session_state.zoom_inicial = 12.5
        
    # 8.7. BOTON ACTUALIZAR ---
    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()
        
    # 8.8. CONTROL DE CAPAS ---
    with st.expander("🗺️ Control de Capas", expanded=False):
        ver_sectores = st.checkbox("Mostrar Sectores", value=True)
        ver_pozos = st.checkbox("Mostrar Pozos", value=True)
        ver_tanques = st.checkbox("Mostrar Tanques", value=False)
        ver_rebombeos = st.checkbox("Mostrar Rebombeos", value=False) # Activado por defecto para facilitar localización
    
    # 8.9. LISTADO DE ESTADOS ---
    with st.expander(f"🟢 Bombas ON ({len(pozos_on)})", expanded=False):
        for p in sorted(pozos_on): 
            st.write(f"🟢 {p}")
    
    with st.expander(f"🔴 Bombas OFF ({len(pozos_off)})", expanded=False):
        for p in sorted(pozos_off): 
            st.write(f"🔴 {p}")

    if pozos_falla_com:
        with st.expander(f"⚠️ Falla de Com. ({len(pozos_falla_com)})", expanded=False):
            for p in sorted(pozos_falla_com):
                st.write(f"🟠 {p}")
    
    if pozos_sin_telemetria:
        with st.expander(f"⚪ Sin Telemetría ({len(pozos_sin_telemetria)})", expanded=False):
            for p in sorted(pozos_sin_telemetria): 
                st.write(f"⚪ {p}")
                
# 9.  SECCION--------------------------------------------------------------------------------- 9. MAPA PRINCIPAL -----------------------------------------------------------------------------------------------------------
st.markdown('<div class="titulo-superior">SISTEMA SCADA - AGUASCALIENTES</div>', unsafe_allow_html=True)

# Indicadores usando el sistema de Grid para que ocupen todo el ancho
c_total = total_q if 'total_q' in locals() else 0.0
p_prom = (total_p / max(len(pozos_on), 1)) if 'total_p' in locals() else 0.0

# Render de indicadores
st.markdown(f"""
    <div class="contenedor-indicadores">
        <div class="card-indicador"><p style="color:#ffffff; font-size:0.8rem; margin:0;">💧 Caudal total</p><p style="color:#00ffcc; font-size:1.1rem; font-weight:bold; margin:0;">{c_total:.1f} l/s</p></div>
        <div class="card-indicador"><p style="color:#ffffff; font-size:0.8rem; margin:0;">📉 Presión promedio</p><p style="color:#ffff00; font-size:1.1rem; font-weight:bold; margin:0;">{p_prom:.2f} kg</p></div>
        <div class="card-indicador"><p style="color:#ffffff; font-size:0.8rem; margin:0;">🟢 Sitios encendidos</p><p style="color:#00ff00; font-size:1.1rem; font-weight:bold; margin:0;">{len(pozos_on)}</p></div>
        <div class="card-indicador"><p style="color:#ffffff; font-size:0.8rem; margin:0;">🔴 Sitios apagados</p><p style="color:#ff0000; font-size:1.1rem; font-weight:bold; margin:0;">{len(pozos_off)}</p></div>
        <div class="card-indicador"><p style="color:#ffffff; font-size:0.8rem; margin:0;">⚠️ Sitios con falla de comunicación</p><p style="color:#ffaa00; font-size:1.1rem; font-weight:bold; margin:0;">{len(pozos_falla_com)}</p></div>
        <div class="card-indicador"><p style="color:#ffffff; font-size:0.8rem; margin:0;">⚪ Sitios sin telemetria</p><p style="color:#ffffff; font-size:1.1rem; font-weight:bold; margin:0;">{len(pozos_sin_telemetria)}</p></div>
    </div>
""", unsafe_allow_html=True)

st.markdown('<div class="mapa-area">', unsafe_allow_html=True)
col_mapa, col_capas = st.columns([0.94, 0.06])

with col_mapa:
    m = folium.Map(
        location=st.session_state.centro_mapa, 
        zoom_start=st.session_state.zoom_inicial, 
        
    )

    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
        attr='Google',
        name='Vista Satélite',
        overlay=False,
        control=True
    ).add_to(m)

    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satélite (Esri)',
        overlay=False,
        control=True
    ).add_to(m)

            # 2. Capas de Fondo (Selectors)
    folium.TileLayer(
        tiles="CartoDB dark_matter",
        name="Vista Nocturna",
        attr="CartoDB",
        overlay=False,
        control=True
    ).add_to(m)

    Fullscreen().add_to(m)


# 9.2. Añadir el resaltado del sector si existe
    if datos_sector_resaltado:
        folium.GeoJson(
            json.loads(datos_sector_resaltado['geo']),
            style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#ffffff', 'weight': 3, 'fillOpacity': 0.4}
        ).add_to(m)

    # 9.3. FUNCIÓN PARA HORARIO 00:00
    def formato_hora(decimal):
        try:
            if decimal == "N/A" or decimal is None: return "00:00"
            horas = int(float(decimal))
            minutos = int((float(decimal) - horas) * 60)
            return f"{horas:02d}:{minutos:02d}"
        except:
            return "00:00"

    # 9.4. FUNCIÓN PARA ICONO PARPADEANTE PEQUEÑO (8px)
    def get_blink_icon(color):
        return f"""
        <div style="
            width: 8px; height: 8px; 
            background-color: {color}; 
            border-radius: 50%; 
            box-shadow: 0 0 8px {color};
            animation: blinker 1s linear infinite;">
        </div>
        <style>
        @keyframes blinker {{ 50% {{ opacity: 0.2; }} }}
        </style>
        """

# 9.5. RENDERIZADO DE SECTORES EN EL MAPA PRINCIPAL   --------------------------------------------

def get_sector_style(feature, visible):
    return {
        'fillColor': '#00d4ff',
        'color': '#00d4ff' if visible else 'transparent',
        'weight': 1.5 if visible else 0,
        'fillOpacity': 0.12 if visible else 0.01,
    }

sectores_data = cargar_sectores_poligonos()

if sectores_data:
    fg_sectores = folium.FeatureGroup(name="Sectores Hidráulicos", z_index=1)
    
    for s in sectores_data:
        try:
            if not s.get('geo'): continue
            
            nombre_sec = s['sector']
            geo_dict = json.loads(s['geo'])
            
            sector_encoded = urllib.parse.quote(nombre_sec)
            url_acceso = f"/?sector={sector_encoded}&access=granted&role={st.session_state.rol}"
            
            html_popup = f"""
            <div style="font-family: 'Segoe UI', sans-serif; width: 220px; background-color: #0b1a29; color: white; padding: 12px; border-radius: 10px; border: 1px dashed #00d4ff;">
                <h4 style="margin:0 0 8px 0; color:#00d4ff; text-align:center;">{nombre_sec}</h4>
                <table style="width:100%; font-size: 11px; margin-bottom: 10px; border-collapse: collapse;">
                    <tr><td><b>Población:</b></td><td style="text-align:right;">{s.get('Poblacion', 0):,.0f}</td></tr>
                    <tr><td><b>Pozos:</b></td><td style="text-align:right;">{s.get('Pozos_Sector', 0)}</td></tr>
                    <tr><td><b>Fugas:</b></td><td style="text-align:right; color:#ff4b4b;">{s.get('Fugas_Tot', 0)}</td></tr>
                </table>
                
                <a href="{url_acceso}" target="_blank" 
                   style="display: block; text-align: center; background-color: #00d4ff; color: #0b1a29; 
                          text-decoration: none; font-weight: bold; font-size: 12px; padding: 8px; 
                          border-radius: 5px; transition: 0.3s;">
                   🚀 ABRIR SECTOR
                </a>
            </div>
            """
            estilo = {
                'fillColor': '#00d4ff',
                'color': '#00d4ff' if ver_sectores else 'transparent',
                'weight': 1.5 if ver_sectores else 0,
                'fillOpacity': 0.12 if ver_sectores else 0.0001 # Invisible pero "clicable"
            }

            folium.GeoJson(
                geo_dict,
                style_function=lambda x, stl=estilo: stl,
                highlight_function=lambda x: {
                    'fillColor': '#00d4ff', 
                    'color': '#ffffff', 
                    'weight': 3, 
                    'fillOpacity': 0.4
                },
                tooltip=f"Sector: {nombre_sec}",
                popup=folium.Popup(html_popup, max_width=260)
            ).add_to(fg_sectores)

        except Exception:
            continue

    fg_sectores.add_to(m)
    
# 9.6. RENDERIZADO DE POZOS EN EL MAPA PRINCIPAL  ---------------------------------------------------------------------------------------------
    for id_p, info in mapa_pozos_dict.items():
        if ver_pozos:  # Si el checkbox está activo, dibujamos todo
            d = lambda tag: data_scada.get(tag, (0, "N/A"))
            is_st = (info['status_label'] == 'SIN TELEMETRÍA')
            q, f_q = d(info['caudal']) if not is_st else (0.0, "N/A")
            p, f_p = d(info['presion']) if not is_st else (0.0, "N/A")
            sumer, f_s = d(info['sumergencia']) if not is_st else (0.0, "N/A")
            dinam, f_d = d(info['nivel_dinamico']) if not is_st else (0.0, "N/A")
            tanq, f_t = d(info['nivel_tanque']) if not is_st else (0.0, "N/A")
            col, f_col = d(info['columna']) if not is_st else (0.0, "N/A")
            h_arr_val, f_h_arr = d(info['h_arranque']) if not is_st else (0.0, "N/A")
            h_par_val, f_h_par = d(info['h_paro']) if not is_st else (0.0, "N/A")
            h_arr_fmt = formato_hora(h_arr_val)
            h_par_fmt = formato_hora(h_par_val)
            v = [d(t) for t in info['voltajes_l']] if not is_st else [(0.0, "N/A")]*3
            a = [d(t) for t in info['amperajes_l']] if not is_st else [(0.0, "N/A")]*3

            # SOLUCIÓN AL LOGIN: Incluimos access=granted y el rol actual en la URL
            rol_actual = st.session_state.get('rol', 'usuario')
            nombre_codificado = urllib.parse.quote(id_p)
            
            url_pozo_graf = f"?graficar_pozo={id_p}&nombre={nombre_codificado}&access=granted&role={rol_actual}"

            html_popup = f"""
                <div style="background: #050505; color: white; padding: 15px; border-radius: 12px; width: 380px; border: 1px solid {info['color_final']}; font-family: sans-serif;">
                    <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 8px; margin-bottom: 10px;">
                        <b style="color: #00d4ff; font-size: 16px;">POZO {id_p}</b>
                        <span style="font-size: 10px; background: {info['color_final']}; color: black; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{info['status_label']}</span>
                    </div>
                    
                    <div style="margin-bottom: 12px;">
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px;">HIDRÁULICA</div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                            <span>💧 Caudal: <b>{q:.2f} L/s</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_q}</span>
                        </div>
                        <div style="display: flex; align-items: baseline; font-size: 11px;">
                            <span>🚀 Presión: <b>{p:.2f} kg</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_p}</span>
                        </div>
                    </div>

                    <div style="margin-bottom: 12px;">
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px;">NIVELES</div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                            <span>🔋 Nivel de Tanque:<b>{tanq:.2f} mts</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_t}</span>
                        </div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                            <span>📉 Nivel Dinámico/Estatico: <b>{dinam:.2f} m</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_d}</span>
                        </div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                            <span>📏 Sumergencia: <b>{sumer:.2f} m</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_s}</span>
                        </div>
                        <div style="display: flex; align-items: baseline; font-size: 11px;">
                            <span>🏗️ Longitud de Columna: <b>{col:.2f} m</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_col}</span>
                        </div>
                    </div>

                    <div style="margin-bottom: 12px;">
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px;">ELÉCTRICO</div>
                        <table style="width: 100%; font-size: 10px; border-collapse: collapse; margin-bottom: 8px;">
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
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px; border-top: 1px solid #222; padding-top: 5px;">HORARIOS</div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                            <span>▶️ Arranque: <b>{h_arr_fmt}</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_h_arr}</span>
                        </div>
                        <div style="display: flex; align-items: baseline; font-size: 11px;">
                            <span>⏹️ Paro: <b>{h_par_fmt}</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_h_par}</span>
                        </div>

                        <div style="border-top: 1px solid #333; padding-top: 10px;">
                        <a href="{url_pozo_graf}" target="_blank" style="text-decoration: none;">
                            <div style="background: #00d4ff; color: #050a10; text-align: center; padding: 10px; border-radius: 6px; font-weight: bold; font-size: 12px;">
                                📊 VER ANÁLISIS HISTÓRICO
                            </div>
                        </a>
                    </div>
                </div>
                """

            folium.Marker(
                location=info['coord'],
                icon=folium.DivIcon(
                    icon_size=(150,36),
                    icon_anchor=(-12, 10),
                    html=f'<div style="font-size: 9px; font-weight: bold; color: {info["color_final"]}; white-space: nowrap; text-shadow: 1px 1px #000; pointer-events: none;">{id_p}</div>'
                )
            ).add_to(m)

            if info.get('blink'):
                folium.Marker(
                    location=info['coord'],
                    icon=folium.DivIcon(html=get_blink_icon(info['color_final'])),
                    popup=folium.Popup(html_popup, max_width=450)
                ).add_to(m)
            else:
                folium.CircleMarker(
                    location=info['coord'],
                    radius=4,
                    color=info['color_final'],
                    fill=True,
                    fill_color=info['color_final'],
                    fill_opacity=1,
                    popup=folium.Popup(html_popup, max_width=450)
                ).add_to(m)

# 9.7. RENDERIZADO DE TANQUES EN EL MAPA PRINCIPAL ---------------------------------------------------------------------------------------
    if ver_tanques:
        for id_tq, info in mapa_tanques_dict.items():
            try:
                val_nivel, fecha_tq = data_scada.get(info['tag_nivel'], (0, "N/A"))
                n_max = info['nivel_max'] if info['nivel_max'] else 1.0
                porcentaje = (val_nivel / n_max) * 100
                
                url_grafico = (
                    f"?graficar_tanque={info['tag_nivel']}"
                    f"&nombre={info['nombre'].replace(' ', '%20')}"
                    f"&access=granted"
                    f"&role={st.session_state.get('rol', 'usuario')}"
                )

                html_popup_tq = f"""
                <div style="background: #050505; color: white; padding: 12px; border-radius: 10px; width: 250px; border: 2px solid #00d4ff; font-family: sans-serif;">
                    <b style="color: #00d4ff; font-size: 14px;">TANQUE: {info['nombre']}</b><br>
                    <hr style="border: 0.5px solid #333;">
                    <div style="font-size: 12px; margin-bottom: 10px;">
                        💧 Nivel Actual: <b>{val_nivel:.2f} m</b>
                    </div>
                    
                    <div style="text-align: center;">
                        <a href="{url_grafico}" target="_blank" 
                           style="background-color: #00d4ff; color: black; padding: 10px; 
                                  text-decoration: none; border-radius: 5px; font-weight: bold; 
                                  font-size: 11px; display: inline-block; width: 90%; border: 1px solid #00d4ff;">
                            📊 VER GRÁFICO HISTÓRICO
                        </a>
                    </div>
                    <div style="margin-top: 10px; font-size: 9px; color: #888; text-align: center;">ID: {id_tq}</div>
                </div>
                """
                
                folium.RegularPolygonMarker(
                    location=info['coord'],
                    number_of_sides=6, radius=5, color="#00d4ff", fill=True, fill_color="#00d4ff",
                    popup=folium.Popup(html_popup_tq, max_width=300),
                    tooltip=f"Tanque: {info['nombre']}"
                ).add_to(m)

                folium.Marker(
                    location=info['coord'],
                    icon=folium.DivIcon(
                        icon_anchor=(20, -10),
                        html=f'<div style="font-size: 9px; font-weight: bold; color: #00d4ff; text-shadow: 1px 1px #000;">{id_tq}</div>'
                    )
                ).add_to(m)
            except: continue
            
# 9.8.  RENDERIZADO DE REBOMBEOS EN EL MAPA PRINCIPAL --------------------------------------------------------------------------------------
    if ver_rebombeos:
        for id_rb, info in mapa_rebombeos_dict.items():
            try:
                d = lambda tag: data_scada.get(tag, (0, "N/A"))
                pres, f_p = d(info['presion'])
                ntq, f_t = d(info['nivel_tanque'])
                v_rb = [d(t) for t in info['voltajes_l']]
                a_rb = [d(t) for t in info['amperajes_l']]

                html_popup_rb = f"""
                <div style="background: #050505; color: white; padding: 12px; border-radius: 10px; width: 300px; border: 2px solid {info['color_final']}; font-family: sans-serif;">
                    <div style="display: flex; justify-content: space-between;">
                        <b style="color: {info['color_final']}; font-size: 14px;">REBOMBEO: {id_rb}</b>
                        <span style="font-size: 10px; background: {info['color_final']}; color: black; padding: 2px 6px; border-radius: 4px; font-weight: bold;">{info['status_label']}</span>
                    </div>
                    <hr style="border: 0.5px solid #333; margin: 8px 0;">
                    <div style="font-size: 11px; margin-bottom: 5px;">
                        🚀 Presión: <b>{pres:.2f} kg</b> <span style="color:#FFFF00; font-size:8px;">{f_p}</span><br>
                        🔋 Nivel Tanque: <b>{ntq:.2f} m</b> <span style="color:#FFFF00; font-size:8px;">{f_t}</span>
                    </div>
                    <table style="width: 100%; font-size: 9px; border-collapse: collapse; margin-top: 5px;">
                        <tr style="color: #00d4ff; border-bottom: 1px solid #333; text-align: left;">
                            <th>Fase</th><th>Voltaje</th><th>Amp</th>
                        </tr>
                        <tr><td>L1-L2</td><td>{v_rb[0][0]:.0f}V</td><td>{a_rb[0][0]:.1f}A</td></tr>
                        <tr><td>L2-L3</td><td>{v_rb[1][0]:.0f}V</td><td>{a_rb[1][0]:.1f}A</td></tr>
                        <tr><td>L1-L3</td><td>{v_rb[2][0]:.0f}V</td><td>{a_rb[2][0]:.1f}A</td></tr>
                    </table>
                </div>
                """
                if info.get('blink'):
                    folium.Marker(location=info['coord'], icon=folium.DivIcon(html=get_blink_icon(info['color_final'])), popup=folium.Popup(html_popup_rb, max_width=350)).add_to(m)
                else:
                    folium.RegularPolygonMarker(location=info['coord'], number_of_sides=4, radius=6, color=info['color_final'], fill=True, fill_color=info['color_final'], popup=folium.Popup(html_popup_rb, max_width=350)).add_to(m)
                
                folium.Marker(location=info['coord'], icon=folium.DivIcon(icon_anchor=(-15, 15), html=f'<div style="font-size: 10px; font-weight: bold; color: {info["color_final"]}; text-shadow: 1px 1px #000;">{id_rb}</div>')).add_to(m)
            except:
                continue
                MousePosition().add_to(m_sec)
           
    folium.LayerControl(position='topright', collapsed=False).add_to(m)          
    folium_static(m, width=None, height=750)
