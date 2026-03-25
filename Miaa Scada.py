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

# 1  SECCION---------------------------------------------------------------------------1. CONFIGURACIÓN DE PÁGINA ----------------------------------------------------------------------------------------------------------
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

# 2  SECCION-----------------------------------------------------------------------------------2. ESTILO CSS ----------------------------------------------------------------------------------------------------------
st.markdown("""
    <style>

        .titulo-superior {
            position: fixed;
            top: 15px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 9999999;
            color: #00d4ff; /* Azul vivo / Cyan */
            font-size: 1.5rem;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 2px;
            white-space: nowrap;
            text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
            /* Animación de pulso */
            animation: glow 2s ease-in-out infinite alternate;
          }

        @keyframes glow {
            from {
                text-shadow: 0 0 5px #00d4ff, 0 0 10px #00d4ff;
                transform: translateX(-50%) scale(1);
          }
            to {
              text-shadow: 0 0 15px #00d4ff, 0 0 25px #0077ff;
              transform: translateX(-50%) scale(1.02);
          }
        }
    
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
            margin-top: -70px !important; /* Ajuste negativo para compensar el contenedor */
            margin-bottom: 10px;
        }

        /* Maximizar el ancho del contenedor principal */
           .block-container {
           padding-top: 1rem !important;
           padding-bottom: 0rem !important;
           padding-left: 1rem !important;
           padding-right: 1rem !important;
}

/* Forzar que las columnas no se encimen */
[data-testid="column"] {
    width: 100% !important;
    flex: 1 1 auto !important;
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

# 3  SECCION--------------------------------------------------------------------------------3. FUNCIONES DE CONEXIÓN ------------------------------------------------------------------------------------------------------
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

# 4 SECCION -------------------------------------------------------------------------------- 4. CARGA DE DATOS ----------------------------------------------------------------------------------------------------------
# DICCIONARIO POZOS
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

# DICCIONARIO DE TANQUES
@st.cache_data(ttl=600)
def cargar_tanques_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        query = "SELECT * FROM Diccionario_de_tanques"
        df_tq = pd.read_sql(query, engine)
        
        nuevo_mapa_tq = {}
        for _, row in df_tq.iterrows():
            try:
                # Limpiar y separar coordenadas
                coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
                lat, lon = map(float, coords_str.split(','))
                
                # Validación de Nivel Máximo para evitar división por cero o error
                n_max = float(row['Nivel_max']) if row.get('Nivel_max') is not None else 1.0
                if n_max <= 0: n_max = 1.0

                nuevo_mapa_tq[row['TQ']] = {
                    "nombre": row['Nombre_tq'],
                    "coord": (lat, lon),
                    "tag_nivel": row['nivel_tanque'], # Usamos el campo nivel_tanque
                    "nivel_max": n_max,
                    "sitios": row['Sitios']
                }
            except: continue
        return nuevo_mapa_tq
    except: return {}

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
        # Añadimos los campos numéricos solicitados en la consulta
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


# 5 SECCION------------------------------------------------------- 5. PROCESAMIENTO (OPTIMIZADO: TABLA ÚLTIMO VALOR + LÓGICA L1 + ZONA HORARIA) -----------------------------------------------------------------

# Carga de datos base
sectores = cargar_sectores_poligonos()
mapa_pozos_dict = cargar_mapa_pozos_desde_db()
mapa_tanques_dict = cargar_tanques_desde_db()
data_scada = cargar_datos_scada(mapa_pozos_dict)

# Unimos todos los tags (pozos + tanques) para una sola consulta al SCADA
tags_tanques = [t['tag_nivel'] for t in mapa_tanques_dict.values() if t['tag_nivel']]
# (Asegúrate de que tu función cargar_datos_scada incluya estos tags en la consulta)
data_scada = cargar_datos_scada({**mapa_pozos_dict, **mapa_tanques_dict})
# Inicialización de listas y contadores para el resumen
pozos_on = []
pozos_off = []
pozos_sin_telemetria = []
pozos_falla_com = []
total_q = 0.0
total_p = 0.0

# Ajuste de Hora Local (Aguascalientes UTC-6)
# Esto evita que datos recientes se marquen como falla por el desfase del servidor
import datetime as dt
ahora = dt.datetime.utcnow() - dt.timedelta(hours=6) 

for id_p, info in mapa_pozos_dict.items():
    bomba_val = str(info['bomba']).strip()
    
    # FILTRO INICIAL: SIN TELEMETRÍA
    if bomba_val == "Sin telemetria":
        info.update({
            'status_label': 'SIN TELEMETRÍA', 
            'color_final': '#808080', 
            'blink': False
        })
        pozos_sin_telemetria.append(id_p)
        continue

    # VALIDACIÓN DE COMUNICACIÓN (SOLO L1)
    tag_l1 = info['voltajes_l'][0]
    _, fecha_str = data_scada.get(tag_l1, (0, "N/A"))
    
    es_falla_com = False
    if fecha_str != "N/A":
        try:
            # Convertimos la fecha del SCADA (ej. "20/03 08:29") usando el año actual
            fecha_dt = dt.datetime.strptime(f"{ahora.year}/{fecha_str}", "%Y/%d/%m %H:%M")
            
            # Calculamos la antigüedad del dato en horas
            diff = ahora - fecha_dt
            horas_atras = diff.total_seconds() / 3600
            
            # Si el último dato de L1 es de hace más de 4 horas -> FALLA COM.
            if horas_atras > 4:
                es_falla_com = True
        except:
            # Si hay error al procesar la fecha, se marca como falla por precaución
            es_falla_com = True
    else:
        # Si no hay fecha registrada para L1, no hay comunicación
        es_falla_com = True

    #  ASIGNACIÓN DE ESTADO FINAL Y PARPADEO
    if es_falla_com:
        # FALLA DE COMUNICACIÓN: Naranja y Parpadea
        info.update({
            'status_label': 'FALLA COM.', 
            'color_final': '#FFA500', 
            'blink': True
        })
        pozos_falla_com.append(id_p)
    else:
        # Si hay comunicación (< 4h), evaluamos si la bomba está encendida
        val_bba, _ = data_scada.get(info['bomba'], (0, "N/A"))
        q_val = data_scada.get(info['caudal'], (0, "N/A"))[0]
        p_val = data_scada.get(info['presion'], (0, "N/A"))[0]
        
        if val_bba == 1:
            # OPERANDO: Verde y Fijo
            info.update({
                'status_label': 'OPERANDO', 
                'color_final': '#00FF00', 
                'blink': False
            })
            pozos_on.append(id_p)
            total_q += q_val
            total_p += p_val
        else:
            # APAGADO: Rojo y Parpadea
            info.update({
                'status_label': 'APAGADO', 
                'color_final': '#FF0000', 
                'blink': True
            })
            pozos_off.append(id_p)

# --- FUNCIONES DE UTILIDAD (Mover arriba de la sección 5.5) ---

def formato_hora(decimal):
    try:
        if decimal == "N/A" or decimal is None: return "00:00"
        horas = int(float(decimal))
        minutos = int((float(decimal) - horas) * 60)
        return f"{horas:02d}:{minutos:02d}"
    except:
        return "00:00"

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

# 5.5 SECCIÓN ------------------------------------------- VISTA DETALLE DEL SECTOR (NUEVA PESTAÑA) -------------------------------------------
if sector_seleccionado:
    st.markdown(f'<div class="titulo-superior">Análisis de Sector: {sector_seleccionado}</div>', unsafe_allow_html=True)
    
    datos_s = next((s for s in sectores if s['sector'] == sector_seleccionado), None)
    
    if datos_s:
        st.markdown("""
            <style>
                .block-container { padding-top: 3.5rem !important; }
                .micro-card {
                    background: #0b1a29; border: 1px solid #1f4068;
                    border-radius: 5px; padding: 8px; text-align: center;
                    margin-top: -10px; margin-bottom: 5px;
                }
                .micro-label { color: #888; font-size: 10px; text-transform: uppercase; margin-bottom: 2px; }
                .micro-value { color: #00d4ff; font-size: 15px; font-weight: bold; }
                hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
            </style>
        """, unsafe_allow_html=True)

        def micro_metric(label, value):
            st.markdown(f'<div class="micro-card"><div class="micro-label">{label}</div><div class="micro-value">{value}</div></div>', unsafe_allow_html=True)

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1: micro_metric("Población", f"{datos_s.get('Poblacion', 0):,.0f}")
        with c2: micro_metric("U. Totales", f"{datos_s.get('U_Tot', 0):,.0f}")
        with c3: micro_metric("U. Domésticos", f"{datos_s.get('U_Domesticos', 0):,.0f}")
        with c4: micro_metric("Consumo m³", f"{datos_s.get('Cons_m3', 0):,.1f}")
        with c5: micro_metric("Dotación", f"{datos_s.get('Dotacion', 0):,.1f}")
        with c6: micro_metric("Balance", f"{datos_s.get('Balance_Estimado', 0):,.1f}%")

        st.divider()

        # --- MAPA DEL SECTOR ---
        ids_pozos = [p.strip() for p in datos_s.get('Pozos_Sector', '').split(',')] if datos_s.get('Pozos_Sector') else []
        m_sec = folium.Map(location=[21.8820, -102.2800], zoom_start=14, tiles="CartoDB dark_matter")
        Fullscreen().add_to(m_sec)
        
        geojson_sector = folium.GeoJson(
            json.loads(datos_s['geo']),
            style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#ffffff', 'weight': 2, 'fillOpacity': 0.1}
        ).add_to(m_sec)

        for id_p in ids_pozos:
            if id_p in mapa_pozos_dict:
                info = mapa_pozos_dict[id_p]
                
                # --- EXTRACCIÓN DE DATOS PARA EL POPUP ---
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

                # Tu HTML personalizado integrado
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
                    <div style="margin-bottom: 12px;">
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px;">NIVELES</div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                            <span>📏 Sumergencia: <b>{sumer:.1f} m</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_s}</span>
                        </div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                            <span>📉 Dinámico: <b>{dinam:.1f} m</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_d}</span>
                        </div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                            <span>🏗️ Columna: <b>{col:.1f} m</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_col}</span>
                        </div>
                        <div style="display: flex; align-items: baseline; font-size: 11px;">
                            <span>🔋 Tanque: <b>{tanq:.1f} mts</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_t}</span>
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
                    </div>
                </div>
                """

                # Marcador con lógica de parpadeo (Blink)
                if info.get('blink'):
                    folium.Marker(
                        location=info['coord'],
                        icon=folium.DivIcon(html=get_blink_icon(info['color_final'])),
                        popup=folium.Popup(html_popup_sec, max_width=450)
                    ).add_to(m_sec)
                else:
                    folium.CircleMarker(
                        location=info['coord'], radius=5, color=info['color_final'], 
                        fill=True, fill_color=info['color_final'], fill_opacity=1,
                        popup=folium.Popup(html_popup_sec, max_width=450)
                    ).add_to(m_sec)
                
                # Etiqueta de ID
                folium.Marker(
                    location=info['coord'],
                    icon=folium.DivIcon(
                        icon_anchor=(-12, 12),
                        html=f'<div style="font-size: 9px; font-weight: bold; color: {info["color_final"]}; text-shadow: 1px 1px #000;">{id_p}</div>'
                    )
                ).add_to(m_sec)

        try:
            m_sec.fit_bounds(geojson_sector.get_bounds())
        except: pass

        folium_static(m_sec, width=None, height=750)
    else:
        st.error(f"No se encontró información para el sector {sector_seleccionado}")
    
    st.stop()
    
# 6 SECCION ------------------------------------------------------------------------------- 6. SIDEBAR BARRA LATERAL IZQUIERDA ------------------------------------------------------------------------------------------
with st.sidebar:
    # Contenedor del logo
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)

    # --- RESUMEN GLOBAL ---
    st.markdown(f"""
        <div class="resumen-card">
            <h4 style="color:#00d4ff; margin-top:0;">RESUMEN GLOBAL</h4>
            <p>Caudal Total: <b style="color:#00FF00;">{total_q:.2f} l/s</b></p>
            <p>Presión Prom: <b style="color:#FFFF00;">{total_p/max(len(pozos_on),1):.2f} Kg/cm²</b></p>
        </div>
    """, unsafe_allow_html=True)
    
    # --- ESTADO DE LAS CONEXIONES (ALINEADO A LA DERECHA) ---    
    with st.expander("🔌 Estado de las Conexiones", expanded=True):
        status_mysql_scada = "OK" if get_mysql_scada_engine() else "ERROR"
        status_mysql_tele = "OK" if get_mysql_telemetria_engine() else "ERROR"
        status_postgres = "OK" if get_postgres_conn() else "ERROR"

        def render_status_line(label, status):
            cls = "status-ok" if status == "OK" else "status-err"
            # Flexbox para empujar el tag a la derecha
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
    centro_mapa = [21.8820, -102.2800]
    zoom_inicial = 12.5

    # 1. Localizar Sitio (Pozo)
    lista_pozos_nombres = sorted(list(mapa_pozos_dict.keys()))
    pozo_buscado = st.selectbox(
        "🔍 Localizar Sitio",
        options=[""] + lista_pozos_nombres,
        format_func=lambda x: "Seleccionar Sitio..." if x == "" else f" {x}"
    )

    if pozo_buscado and pozo_buscado in mapa_pozos_dict:
        centro_mapa = mapa_pozos_dict[pozo_buscado]['coord']
        zoom_inicial = 17 

# --- BUSCADOR DE SECTORES (LOCALIZADOR) ---
    lista_sectores = sorted([s['sector'] for s in sectores])
    sector_buscado = st.selectbox(
        "🏘️ Localizar Sector",
        options=[""] + lista_sectores,
        format_func=lambda x: "Seleccionar Sector..." if x == "" else f" {x}",
        key="busqueda_sectores"
    )

    # Variables de control del mapa
    centro_mapa = [21.8820, -102.2800]
    zoom_inicial = 12.5
    datos_sector_resaltado = None # Variable para guardar la geometría a resaltar

    if sector_buscado:
        datos_s = next((s for s in sectores if s['sector'] == sector_buscado), None)
        if datos_s:
            datos_sector_resaltado = datos_s # Guardamos para el mapa
            try:
                geom = json.loads(datos_s['geo'])
                # Inversión de coordenadas para Folium [lat, lon]
                coords_raw = geom['coordinates'][0][0][0] if geom['type'] == 'MultiPolygon' else geom['coordinates'][0][0]
                centro_mapa = [coords_raw[1], coords_raw[0]]
                zoom_inicial = 14.5
            except:
                pass
    
    # Lógica de posicionamiento para POZOS (mantiene prioridad si se busca un pozo)
    if pozo_buscado and pozo_buscado in mapa_pozos_dict:
        centro_mapa = mapa_pozos_dict[pozo_buscado]['coord']
        zoom_inicial = 17
        
# --- BOTON PARA REFRESCAR LAS CONEXIONES DE TODO EL PANEL ---
    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()
        
# --- CONTROL DE CAPAS DEL MAPA ---
    with st.expander("🗺️ Control de Capas", expanded=False):
        ver_sectores = st.checkbox("Mostrar Sectores", value=True)
        ver_pozos = st.checkbox("Mostrar Pozos", value=True)
        ver_etiquetas = st.checkbox("Mostrar ID Pozos", value=True)
    
   # Sección de Bombas ON
    with st.expander(f"🟢 Bombas ON ({len(pozos_on)})", expanded=False):
        for p in sorted(pozos_on): 
            st.write(f"🟢 {p}")
    
    # Sección de Bombas OFF
    with st.expander(f"🔴 Bombas OFF ({len(pozos_off)})", expanded=False):
        for p in sorted(pozos_off): 
            st.write(f"🔴 {p}")

    # Nueva Sección: Falla de Comunicación
    if pozos_falla_com:
        with st.expander(f"⚠️ Falla de Com. ({len(pozos_falla_com)})", expanded=False):
            for p in sorted(pozos_falla_com):
                st.write(f"🟠 {p}")
    
    # Sección Sin Telemetría
    if pozos_sin_telemetria:
        with st.expander(f"⚪ Sin Telemetría ({len(pozos_sin_telemetria)})", expanded=False):
            for p in sorted(pozos_sin_telemetria): 
                st.write(f"⚪ {p}")

# 7  SECCION--------------------------------------------------------------------------------- 7. MAPA PRINCIPAL ------------------------------------------------------------------------------------------------------------
# DASHBOARD
st.markdown('<div class="titulo-superior">Sistema de monitoreo - Aguascalientes</div>', unsafe_allow_html=True)
# Proporción ultra-ancha para el mapa (90% mapa, 10% capas)
col_mapa, col_capas = st.columns([0.9, 0.1], gap="small")

with col_mapa:
    # Usamos las variables dinámicas centro_mapa y zoom_inicial definidas en el buscador
    m = folium.Map(location=centro_mapa, zoom_start=zoom_inicial, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)

    # Si hay un sector seleccionado en el buscador, lo resaltamos con un estilo especial
    if datos_sector_resaltado:
        folium.GeoJson(
            json.loads(datos_sector_resaltado['geo']),
            name="Sector Resaltado",
            style_function=lambda x: {
                'fillColor': '#00d4ff',
                'color': '#ffffff',  # Borde blanco para resaltar
                'weight': 4,         # Borde más grueso
                'fillOpacity': 0.4   # Relleno más intenso
            },
            tooltip=folium.Tooltip(f"SECTOR SELECCIONADO: {datos_sector_resaltado['sector']}")
        ).add_to(m)

    # FUNCIÓN PARA HORARIO 00:00
    def formato_hora(decimal):
        try:
            if decimal == "N/A" or decimal is None: return "00:00"
            horas = int(float(decimal))
            minutos = int((float(decimal) - horas) * 60)
            return f"{horas:02d}:{minutos:02d}"
        except:
            return "00:00"

    # FUNCIÓN PARA ICONO PARPADEANTE PEQUEÑO (8px)
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

# --- RENDERIZADO DE SECTORES (Solo si el checkbox está activo) ---
if ver_sectores and sectores:
    for s in sectores:
        try:
            nombre_sec = s['sector']
            url_sector = f"/?sector={urllib.parse.quote(nombre_sec)}"
            geo_data = json.loads(s['geo'])
            
            html_sector = f"""
            <div style="font-family: sans-serif; text-align: center; color: white; background: #0b1a29; padding: 10px; border-radius: 8px; border: 1px solid #00d4ff;">
                <h4 style="margin: 0; color: #00d4ff;">{nombre_sec}</h4>
                <a href="{url_sector}" target="_blank" 
                   style="display: inline-block; padding: 6px 12px; background-color: #00d4ff; color: black; 
                          text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; margin-top:5px;">
                   🚀 Ver Detalles
                </a>
            </div>
            """
            
            folium.GeoJson(
                geo_data, 
                style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1.5, 'fillOpacity': 0.1},
                highlight_function=lambda x: {'fillColor': '#00d4ff', 'color': '#ffffff', 'weight': 3, 'fillOpacity': 0.4},
                popup=folium.Popup(html_sector, max_width=250),
                tooltip=folium.Tooltip(f"Sector: {nombre_sec}", sticky=True)
            ).add_to(m)
        except:
            continue
                
        

    #  RENDERIZADO DE POZOS
    for id_p, info in mapa_pozos_dict.items():
        d = lambda tag: data_scada.get(tag, (0, "N/A"))
        is_st = (info['status_label'] == 'SIN TELEMETRÍA')
        
        # Extracción de datos y fechas (Tu diseño original)
        q, f_q = d(info['caudal']) if not is_st else (0.0, "N/A")
        p, f_p = d(info['presion']) if not is_st else (0.0, "N/A")
        sumer, f_s = d(info['sumergencia']) if not is_st else (0.0, "N/A")
        dinam, f_d = d(info['nivel_dinamico']) if not is_st else (0.0, "N/A")
        tanq, f_t = d(info['nivel_tanque']) if not is_st else (0.0, "N/A")
        col, f_col = d(info['columna']) if not is_st else (0.0, "N/A")
        
        # Horarios formateados
        h_arr_val, f_h_arr = d(info['h_arranque']) if not is_st else (0.0, "N/A")
        h_par_val, f_h_par = d(info['h_paro']) if not is_st else (0.0, "N/A")
        h_arr_fmt = formato_hora(h_arr_val)
        h_par_fmt = formato_hora(h_par_val)

        v = [d(t) for t in info['voltajes_l']] if not is_st else [(0.0, "N/A")]*3
        a = [d(t) for t in info['amperajes_l']] if not is_st else [(0.0, "N/A")]*3

        # POPUP DE LOS POZOS ------------------------------------------------------------------------------------------------------------------------------------------------------------
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
                    <span>📏 Sumergencia: <b>{sumer:.1f} m</b></span>
                    <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_s}</span>
                </div>
                <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                    <span>📉 Dinámico: <b>{dinam:.1f} m</b></span>
                    <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_d}</span>
                </div>
                <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                    <span>🏗️ Columna: <b>{col:.1f} m</b></span>
                    <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_col}</span>
                </div>
                <div style="display: flex; align-items: baseline; font-size: 11px;">
                    <span>🔋 Tanque: <b>{tanq:.1f} mts</b></span>
                    <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_t}</span>
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
            </div>
        </div>
        """

        # CAPA DE TEXTO (Etiquetas ID Pozos)
        if ver_etiquetas:
            folium.Marker(
                location=info['coord'],
                icon=folium.DivIcon(
                    icon_size=(150,36),
                    icon_anchor=(-12, 10),
                    html=f'<div style="font-size: 9px; font-weight: bold; color: {info["color_final"]}; white-space: nowrap; text-shadow: 1px 1px #000; pointer-events: none;">{id_p}</div>'
                )
            ).add_to(m)

        # CAPA DEL MARCADOR (Puntos/Blinkers)
# Solo dibujar si el checkbox de pozos está activo
    if ver_pozos:
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

    # Solo dibujar etiquetas si el checkbox de etiquetas está activo
    if ver_etiquetas:
        folium.Marker(
            location=info['coord'],
            icon=folium.DivIcon(
                icon_size=(150,36),
                icon_anchor=(-12, 10),
                html=f'<div style="font-size: 9px; font-weight: bold; color: {info["color_final"]}; text-shadow: 1px 1px #000;">{id_p}</div>'
            )
        ).add_to(m)

    # Renderizado final del mapa pozos
    
# --- RENDERIZADO DE TANQUES --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    for id_tq, info in mapa_tanques_dict.items():
        val_nivel, fecha_tq = data_scada.get(info['tag_nivel'], (0, "N/A"))
        n_max = info['nivel_max'] if info['nivel_max'] else 1.0
        porcentaje = (val_nivel / n_max) * 100
        
        # Color según nivel: Cyan si está bien, Naranja si está bajo (ej. < 20%)
        color_tq = "#00d4ff" if porcentaje > 20 else "#FFA500"

        html_popup_tq = f"""
        <div style="background: #050505; color: white; padding: 12px; border-radius: 10px; width: 250px; border: 2px solid #00d4ff; font-family: sans-serif;">
            <b style="color: #00d4ff; font-size: 14px;">TANQUE: {info['nombre']}</b><br>
            <span style="font-size: 10px; color: #888;">ID: {id_tq}</span>
            <hr style="border: 0.5px solid #333;">
            <div style="margin-top: 8px;">
                <div style="display: flex; justify-content: space-between; font-size: 12px;">
                    <span>💧 Nivel Actual:</span>
                    <b>{val_nivel:.2f} m</b>
                </div>
                <div style="background: #222; border-radius: 5px; height: 10px; margin: 8px 0;">
                    <div style="background: #00d4ff; width: {min(porcentaje, 100):.0f}%; height: 100%; border-radius: 5px;"></div>
                </div>
                <div style="font-size: 10px; color: #aaa; text-align: right;">Capacidad Máx: {n_max} m</div>
            </div>
            <div style="margin-top: 10px; font-size: 10px; color: #FFFF00;">🕒 Act: {fecha_tq}</div>
            <div style="margin-top: 5px; font-size: 9px; color: #666;">📍 Sitios: {info['sitios']}</div>
        </div>
        """

        # Marcador Cuadrado para Tanques
        folium.RegularPolygonMarker(
            location=info['coord'],
            number_of_sides=6, # <--- CAMBIA ESTO: 3=Triángulo, 4=Cuadrado, 6=Hexágono, 8=Octágono
            radius=5,
            color="#00d4ff",
            fill=True,
            fill_color="#00d4ff",
            fill_opacity=0.7,
            popup=folium.Popup(html_popup_tq, max_width=300),
            tooltip=f"Tanque: {info['nombre']}"
        ).add_to(m)

        # Etiqueta del Tanque
        folium.Marker(
            location=info['coord'],
            icon=folium.DivIcon(
                icon_anchor=(20, -10),
                html=f'<div style="font-size: 9px; font-weight: bold; color: #00d4ff; text-shadow: 1px 1px #000;">{id_tq}</div>'
            )
        ).add_to(m)
# Renderizado final del mapa tanques

    
    folium_static(m, width=None, height=750)



