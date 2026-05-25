import streamlit as st
import pandas as pd
import numpy_financial as npf
import datetime
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import pytz
from astral import LocationInfo
from astral.sun import sun

# Configuração da Página Web
st.set_page_config(page_title="Dashboard IP LED", layout="wide", initial_sidebar_state="expanded")

# Inicializar variável de estado para lotes dinâmicos
if 'num_lotes_extra' not in st.session_state:
    st.session_state['num_lotes_extra'] = 0

# ==========================================
# 1. FUNÇÕES DE DADOS E ASTRAL
# ==========================================
distritos_coord = {
    'Aveiro': (40.6333, -8.6500), 'Beja': (38.0167, -7.8667), 'Braga': (41.5333, -8.4167),
    'Bragança': (41.8000, -6.7500), 'Castelo Branco': (39.8167, -7.4833), 'Coimbra': (40.2167, -8.4167),
    'Évora': (38.5667, -7.9000), 'Faro': (37.0167, -7.9333), 'Guarda': (40.5333, -7.3333),
    'Leiria': (39.7500, -8.8000), 'Lisboa': (38.7000, -9.1333), 'Portalegre': (39.2833, -7.4333),
    'Porto': (41.1500, -8.6167), 'Santarém': (39.2333, -8.6833), 'Setúbal': (38.5333, -8.8833),
    'Viana do Castelo': (41.7000, -8.8333), 'Vila Real': (41.3000, -7.7500), 'Viseu': (40.6667, -7.9167)
}

@st.cache_data
def calcular_perfil_energia(distrito, dimming_ativo, p1_start, p1_end, p1_red, p2_start, p2_end, p2_red):
    def in_window(t, start, end):
        if start == end: 
            return False
        if start < end:
            return start <= t < end
        else:
            return t >= start or t < end

    lat, lon = distritos_coord.get(distrito, (38.7000, -9.1333))
    loc = LocationInfo(distrito, "Portugal", "Europe/Lisbon", lat, lon)
    tz_local = pytz.timezone(loc.timezone)

    vazio_norm_horas, vazio_dim_horas = 0.0, 0.0
    cheias_norm_horas, cheias_dim_horas = 0.0, 0.0

    f1 = 1.0 - (p1_red / 100.0) if dimming_ativo else 1.0
    f2 = 1.0 - (p2_red / 100.0) if dimming_ativo else 1.0

    min_tariff = []
    min_factor = []
    for m in range(1440):
        t = m / 60.0
        if t >= 22.0 or t < 8.0:
            min_tariff.append('V')
        else:
            min_tariff.append('C')

        factor = 1.0
        if dimming_ativo:
            if in_window(t, p2_start, p2_end):
                factor = f2
            elif in_window(t, p1_start, p1_end):
                factor = f1
        min_factor.append(factor)

    data_inicio = datetime.date(2026, 1, 1)
    for i in range(365):
        data = data_inicio + datetime.timedelta(days=i)
        s = sun(loc.observer, date=data, tzinfo=tz_local)
        liga = s['dusk'].hour + s['dusk'].minute / 60.0
        desliga = s['dawn'].hour + s['dawn'].minute / 60.0

        m_liga = int(liga * 60)
        m_desliga = int(desliga * 60)

        for m in range(m_liga, 1440):
            tar = min_tariff[m]
            fac = min_factor[m]
            if tar == 'V':
                vazio_dim_horas += fac * (1 / 60.0)
                vazio_norm_horas += 1.0 * (1 / 60.0)
            else:
                cheias_dim_horas += fac * (1 / 60.0)
                cheias_norm_horas += 1.0 * (1 / 60.0)

        for m in range(0, m_desliga):
            tar = min_tariff[m]
            fac = min_factor[m]
            if tar == 'V':
                vazio_dim_horas += fac * (1 / 60.0)
                vazio_norm_horas += 1.0 * (1 / 60.0)
            else:
                cheias_dim_horas += fac * (1 / 60.0)
                cheias_norm_horas += 1.0 * (1 / 60.0)

    return vazio_norm_horas, vazio_dim_horas, cheias_norm_horas, cheias_dim_horas

@st.cache_data
def carregar_dados_eredes():
    try:
        df = pd.read_csv("cadastro_iluminacao_publica (9).csv", sep=';', encoding='utf-8')
        df.columns = df.columns.str.strip()
        df['Potência Instalada Total (W)'] = df['Potência Instalada Total (W)'].fillna(0)
        df['Lâmpadas'] = df['Lâmpadas'].fillna(0)
        return df
    except Exception as e:
        st.error(f"Erro ao ler o ficheiro CSV. Verifique a integridade do ficheiro. Detalhe: {e}")
        return pd.DataFrame()

# ==========================================
# 2. CABEÇALHO E UI LATERAL (SIDEBAR)
# ==========================================
df_eredes = carregar_dados_eredes()
lista_concelhos = sorted(df_eredes['Concelho'].dropna().unique().tolist()) if not df_eredes.empty else ["Sem Dados"]

st.sidebar.title("Simulador IP LED")
st.sidebar.markdown("Configuração Global do Projeto")

concelho_escolhido = st.sidebar.selectbox("1. Seleção do Município", lista_concelhos)

df_concelho_temp = df_eredes[df_eredes['Concelho'] == concelho_escolhido]

if 'Freguesia' in df_concelho_temp.columns:
    lista_freguesias = ["Todas"] + sorted(df_concelho_temp['Freguesia'].dropna().unique().tolist())
    freguesia_escolhida = st.sidebar.selectbox("1.1. Seleção da Freguesia", lista_freguesias)
    if freguesia_escolhida == "Todas":
        df_filtrado = df_concelho_temp
    else:
        df_filtrado = df_concelho_temp[df_concelho_temp['Freguesia'] == freguesia_escolhida]
else:
    df_filtrado = df_concelho_temp

distrito_inferido = df_filtrado['Distrito'].iloc[0] if not df_filtrado.empty else 'Lisboa'
if distrito_inferido not in distritos_coord:
    distrito_inferido = 'Lisboa'

# --- Ajuste Fino do Parque ---
with st.sidebar.expander("2. Inventário do Parque Atual", expanded=False):
    st.caption("Ajuste as quantidades reais caso difiram dos registos da E-REDES.")
    df_agrupado_tipos = df_filtrado.groupby('Tipo de Lâmpada').agg(
        {'Lâmpadas': 'sum', 'Potência Instalada Total (W)': 'sum'}).reset_index()

    lampadas_totais = 0
    potencia_antiga_kw = 0.0
    total_led = 0
    dados_editados_tipos = []

    for index, row in df_agrupado_tipos.iterrows():
        tipo = row['Tipo de Lâmpada']
        qtd_original = int(row['Lâmpadas'])
        pot_total_original = row['Potência Instalada Total (W)']
        avg_w = pot_total_original / qtd_original if qtd_original > 0 else 0

        nova_qtd = st.number_input(f"{tipo}", min_value=0, value=qtd_original, step=50)
        dados_editados_tipos.append({'Tipo de Lâmpada': tipo, 'Lâmpadas': nova_qtd})

        if 'LED' in tipo.upper():
            total_led += nova_qtd
        else:
            lampadas_totais += nova_qtd
            potencia_antiga_kw += (nova_qtd * avg_w) / 1000.0

df_tipos_lampada = pd.DataFrame(dados_editados_tipos)
total_lampadas_concelho = lampadas_totais + total_led

# --- Mix LED ---
with st.sidebar.expander("3. Mix de Tipologias LED (%)", expanded=True):
    st.caption("Insira a distribuição (o sistema ajusta para 100% automaticamente).")
    
    perc_l1 = st.number_input("Viária Tradicional (39W) - %", 0, 100, 40)
    perc_l2 = st.number_input("Viária Circular (45W) - %", 0, 100, 10)
    perc_l3 = st.number_input("Viária Quadrada (45W) - %", 0, 100, 5)
    perc_l4 = st.number_input("Jardim I (20W) - %", 0, 100, 10)
    perc_l5 = st.number_input("Jardim II (30W) - %", 0, 100, 5)
    perc_l6 = st.number_input("Lanterna Histórica (35W) - %", 0, 100, 10)
    perc_l7 = st.number_input("Histórica Lágrima (40W) - %", 0, 100, 10)
    perc_l8 = st.number_input("Projetor I (60W) - %", 0, 100, 5)
    perc_l9 = st.number_input("Projetor II (100W) - %", 0, 100, 5)

    nomes_lista = [
        "Viária Tradicional", "Viária Circular", "Viária Quadrada", 
        "Jardim I", "Jardim II", "Lanterna Histórica", 
        "Histórica Lágrima", "Projetor I", "Projetor II"
    ]
    perc_lista = [perc_l1, perc_l2, perc_l3, perc_l4, perc_l5, perc_l6, perc_l7, perc_l8, perc_l9]
    precos_lista = [249.81, 263.39, 252.56, 175.06, 324.66, 361.25, 430.30, 330.00, 538.85]
    watts_lista = [39.0, 45.0, 45.0, 20.0, 30.0, 35.0, 40.0, 60.0, 100.0]

    st.divider()
    st.markdown("**Lotes Personalizados**")
    col_btn1, col_btn2 = st.columns(2)
    
    if col_btn1.button("Adicionar Lote"):
        st.session_state['num_lotes_extra'] += 1
    if col_btn2.button("Remover Lote") and st.session_state['num_lotes_extra'] > 0:
        st.session_state['num_lotes_extra'] -= 1

    for i in range(st.session_state['num_lotes_extra']):
        st.markdown(f"*Lote Extra {i + 1}*")
        nome_custom = st.text_input("Designação", value=f"Específico {i + 1}", key=f"nome_l{i}")
        watts_custom = st.number_input("Potência (W)", min_value=1.0, value=50.0, step=1.0, key=f"watts_l{i}")
        preco_custom = st.number_input("CAPEX Unitário (€)", min_value=1.0, value=250.0, step=10.0, key=f"preco_l{i}")
        perc_custom = st.slider("Alocação (%)", 0, 100, 0, key=f"perc_l{i}")

        nomes_lista.append(f"{nome_custom}")
        watts_lista.append(watts_custom)
        precos_lista.append(preco_custom)
        perc_lista.append(perc_custom)

    soma_perc = sum(perc_lista)
    if soma_perc == 0:
        st.error("A alocação total é de 0%. Atribua pelo menos um valor maior que 0.")
        st.stop()
    elif soma_perc != 100:
        st.warning(f"A soma dos sliders é {soma_perc}%. Proporções ajustadas automaticamente.")

    perc_lista_norm = [(p / soma_perc) * 100 for p in perc_lista]

# --- Telegestão ---
with st.sidebar.expander("4. Perfis de Regulação de Fluxo", expanded=False):
    ativar_dimming = st.checkbox("Ativar Regulação de Fluxo (Dimming)", value=True)
    if ativar_dimming:
        st.markdown("**Patamar 1**")
        p1_inicio = st.number_input("Início (h)", 0, 23, 23, key="p1_i")
        p1_fim = st.number_input("Fim (h)", 0, 23, 2, key="p1_f")
        p1_red = st.slider("Redução Fluxo (%)", 0, 80, 30, key="p1_r")
        
        st.markdown("**Patamar 2**")
        p2_inicio = st.number_input("Início (h)", 0, 23, 2, key="p2_i")
        p2_fim = st.number_input("Fim (h)", 0, 23, 6, key="p2_f")
        p2_red = st.slider("Redução Fluxo (%)", 0, 80, 50, key="p2_r")
    else:
        p1_inicio, p1_fim, p1_red = 0, 0, 0
        p2_inicio, p2_fim, p2_red = 0, 0, 0

# --- Dados Financeiros & ESCO ---
with st.sidebar.expander("5. Parâmetros Financeiros & ESCO", expanded=False):
    st.markdown("**Tarifário (Energia Ativa)**")
    preco_vazio = st.number_input("Tarifa Vazio (€/kWh)", value=0.1155, format="%.4f")
    preco_cheias = st.number_input("Tarifa Fora Vazio (€/kWh)", value=0.1519, format="%.4f")

    st.markdown("**Potência Contratada (Termo Fixo)**")
    termo_fixo = st.number_input("Custo Fixo Mensal (€/kW)", value=0.0607, step=0.10)

    st.markdown("**Macroeconomia & Horizonte Temporal**")
    anos_projeto = st.slider("Duração da Análise LCC (Anos)", min_value=5, max_value=25, value=20, help="Tempo total de análise do ciclo de vida.")
    inflacao_energia = st.number_input("Inflação Anual da Energia (%)", value=2.0, step=0.5) / 100
    taxa_atualizacao = st.number_input("Taxa de Atualização (CAL) (%)", value=4.0, step=0.5) / 100
    fator_co2 = st.number_input("Fator Emissão (kg CO2/kWh)", value=0.20, step=0.01)

    st.divider()
    st.markdown("**Modelo de Financiamento**")
    ativar_esco = st.checkbox("Ativar Modelo ESCO (CPE)", value=False,
                              help="Contrato de Performance Energética onde a empresa parceira assume o Investimento Inicial.")
    if ativar_esco:
        anos_contrato = st.slider("Duração do Contrato ESCO (Anos)", min_value=5, max_value=20, value=20)
        partilha_esco = st.slider("Partilha da Poupança p/ ESCO (%)", 50, 100, 80) / 100.0
    else:
        anos_contrato = 0
        partilha_esco = 0.0

# --- Custos de Operação (OPEX) ---
with st.sidebar.expander("6. Custos de Operação (OPEX)", expanded=False):
    st.markdown("**Taxa de Falhas Anual**")
    col_tx1, col_tx2 = st.columns(2)
    tx_falha_base = col_tx1.number_input("Cenário Base (%)", value=4.0, step=0.5) / 100
    tx_falha_led = col_tx2.number_input("Luminárias LED (%)", value=1.0, step=0.5) / 100

    st.markdown("**Custo de Intervenção/Material**")
    col_rep1, col_rep2 = st.columns(2)
    custo_rep_base = col_rep1.number_input("Cenário Base (€)", value=50.0, step=5.0)
    custo_rep_led = col_rep2.number_input("Reparação LED (€)", value=60.0, step=5.0)

    if ativar_dimming:
        st.divider()
        st.markdown("**Plataforma IoT (Telegestão)**")
        taxa_telegestao = st.slider("Luminárias com Telegestão (%)", 0, 100, 50) / 100.0
        custo_iot = st.number_input("Subscrição Anual (€/Luminária)", value=8.0, step=1.0, help="SaaS + Conectividade Telco")
        capex_iot_unit = st.number_input("Custo Instalação do Nó IoT (€)", value=80.0, step=10.0, help="CAPEX adicional unitário do hardware")
    else:
        taxa_telegestao = 0.0
        custo_iot = 0.0
        capex_iot_unit = 0.0

# ==========================================
# 3. MOTOR DE CÁLCULO DINÂMICO
# ==========================================
qtd_lista = [round(lampadas_totais * (p / 100)) for p in perc_lista_norm]
capex_iluminacao = sum(q * p for q, p in zip(qtd_lista, precos_lista))

# Hardware de Telegestão proporcional à percentagem inserida
capex_iot_total = (lampadas_totais * taxa_telegestao) * capex_iot_unit
capex_projeto_total = capex_iluminacao + capex_iot_total

potencia_led_w = sum(q * w for q, w in zip(qtd_lista, watts_lista))
potencia_led_kw = potencia_led_w / 1000.0

pot_media_led = potencia_led_w / lampadas_totais if lampadas_totais > 0 else 0
pot_media_antiga = (potencia_antiga_kw * 1000) / lampadas_totais if lampadas_totais > 0 else 0

reducao_watts_por_luminaria = pot_media_led - pot_media_antiga

vazio_norm, vazio_dim, cheias_norm, cheias_dim = calcular_perfil_energia(
    distrito_inferido, ativar_dimming, p1_inicio, p1_fim, p1_red, p2_inicio, p2_fim, p2_red
)

kwh_ano_vsap = potencia_antiga_kw * (vazio_norm + cheias_norm)
energia_ativa_ano_vsap = potencia_antiga_kw * (vazio_norm * preco_vazio + cheias_norm * preco_cheias)
custo_fixo_ano_vsap = potencia_antiga_kw * termo_fixo * 12

kwh_ano_led = potencia_led_kw * (vazio_dim + cheias_dim)
energia_ativa_ano_led = potencia_led_kw * (vazio_dim * preco_vazio + cheias_dim * preco_cheias)
custo_fixo_ano_led = potencia_led_kw * termo_fixo * 12

# Matriz temporal baseada dinamicamente no slider global
anos = list(range(anos_projeto + 1))
inv_vsap_list, energia_vsap_list, fluxos_vsap = [], [], []
inv_led_list, energia_led_list, fluxos_led = [], [], []
poupanca_ano_list = []

for ano in anos:
    if ano == 0:
        inv_vsap = 0
        energia_vsap = 0
        
        if ativar_esco:
            inv_led = 0
        else:
            inv_led = capex_projeto_total
            
        energia_led = 0

        inv_vsap_list.append(inv_vsap)
        energia_vsap_list.append(energia_vsap)
        fluxos_vsap.append(0)

        inv_led_list.append(inv_led)
        energia_led_list.append(energia_led)
        fluxos_led.append(inv_led)

        # O ano 0 regista o esforço financeiro inicial (negativo se for financiado pela Câmara)
        poupanca_ano_list.append(-inv_led)
    else:
        energia_vsap = (energia_ativa_ano_vsap + custo_fixo_ano_vsap) * ((1 + inflacao_energia) ** ano)
        energia_led = (energia_ativa_ano_led + custo_fixo_ano_led) * ((1 + inflacao_energia) ** ano)

        # Ciclo de substituição corretiva e preventiva
        if ano in [5, 10, 15, 20, 25]:
            custo_preventivo_base = (lampadas_totais * custo_rep_base)
        else:
            custo_preventivo_base = 0
            
        inv_vsap = (lampadas_totais * tx_falha_base * custo_rep_base) + custo_preventivo_base
            
        inv_led_natural = (lampadas_totais * tx_falha_led * custo_rep_led) + (lampadas_totais * taxa_telegestao * custo_iot)

        tot_vsap = inv_vsap + energia_vsap
        tot_led_natural = inv_led_natural + energia_led

        poupanca_bruta = tot_vsap - tot_led_natural

        if ativar_esco and ano <= anos_contrato:
            renda_esco = poupanca_bruta * partilha_esco
            tot_led_ano = tot_led_natural + renda_esco
            inv_led_list.append(inv_led_natural + renda_esco)
        else:
            tot_led_ano = tot_led_natural
            inv_led_list.append(inv_led_natural)

        inv_vsap_list.append(inv_vsap)
        energia_vsap_list.append(energia_vsap)
        fluxos_vsap.append(tot_vsap)

        energia_led_list.append(energia_led)
        fluxos_led.append(tot_led_ano)

        poupanca_ano_list.append(tot_vsap - tot_led_ano)

cal_vsap = npf.npv(taxa_atualizacao, fluxos_vsap)
cal_led = npf.npv(taxa_atualizacao, fluxos_led)
poupanca_liquida = cal_vsap - cal_led

# Cálculo do Payback Period (Tempo de Retorno)
poupanca_cumulativa = np.cumsum(poupanca_ano_list)
payback_ano = "Não recupera"
if ativar_esco:
    payback_ano = "Imediato"
else:
    for i, val in enumerate(poupanca_cumulativa):
        if val >= 0 and i > 0:
            payback_ano = f"{i} Anos"
            break

# ==========================================
# 4. INTERFACE PRINCIPAL (MAIN UI)
# ==========================================
if 'freguesia_escolhida' in locals() and freguesia_escolhida != "Todas":
    st.title(f"Auditoria Energética IP: Concelho de {concelho_escolhido} — {freguesia_escolhida}")
else:
    st.title(f"Auditoria Energética IP: Município de {concelho_escolhido}")

st.markdown(f"Ferramenta de Apoio à Decisão Estratégica (Análise LCC {anos_projeto} Anos)")

st.divider()
kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)

kpi1.metric("Luminárias a Substituir", f"{lampadas_totais:,.0f} un")
kpi2.metric("Potência a Abater", f"{potencia_antiga_kw:,.1f} kW")

if ativar_esco:
    kpi3.metric("Investimento Município", "0 €", f"CAPEX {capex_projeto_total:,.0f} € via ESCO", delta_color="normal")
else:
    kpi3.metric("Investimento Previsto (CAPEX)", f"{capex_projeto_total:,.0f} €")

kpi4.metric("Poupança Líquida (NPV)", f"{poupanca_liquida:,.0f} €")
kpi5.metric("Tempo de Retorno (Payback)", payback_ano)
st.divider()

tab1, tab2, tab3 = st.tabs(["1. Diagnóstico do Parque", "2. Análise Financeira", "3. Especificações Técnicas"])

with tab1:
    st.subheader("Situação Atual do Parque de Iluminação")
    df_chart = df_tipos_lampada[df_tipos_lampada['Lâmpadas'] > 0].copy()
    
    col_gauge, col_chart, col_dados = st.columns([1, 1.5, 1])

    perc_led_format = (total_led / total_lampadas_concelho) * 100 if total_lampadas_concelho > 0 else 0

    with col_gauge:
        # Gráfico de Velocímetro (Gauge) para mostrar a penetração LED atual
        fig_gauge = go.Figure(go.Indicator(
            mode = "gauge+number",
            value = perc_led_format,
            number = {'suffix': "%", 'font': {'size': 36}},
            title = {'text': "Penetração LED Atual", 'font': {'size': 18}},
            gauge = {
                'axis': {'range': [0, 100]},
                'bar': {'color': "#2ecc71"},
                'steps' : [
                    {'range': [0, 30], 'color': "#f8d7da"},
                    {'range': [30, 70], 'color': "#fff3cd"},
                    {'range': [70, 100], 'color': "#d4edda"}],
            }
        ))
        fig_gauge.update_layout(height=250, margin=dict(t=40, b=0, l=10, r=10))
        st.plotly_chart(fig_gauge, use_container_width=True)

    with col_chart:
        if not df_chart.empty:
            # Gráfico de Barras Horizontal (Substitui o Pie Chart)
            df_chart_sorted = df_chart.sort_values('Lâmpadas', ascending=True)
            fig_bar = px.bar(
                df_chart_sorted, 
                x='Lâmpadas', 
                y='Tipo de Lâmpada', 
                orientation='h',
                color='Tipo de Lâmpada',
                color_discrete_sequence=px.colors.qualitative.Set2
            )
            fig_bar.update_layout(
                margin=dict(t=20, b=0, l=0, r=0), 
                showlegend=False,
                xaxis_title="Número de Luminárias",
                yaxis_title=""
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.warning("Sem dados de parque para visualização.")

    with col_dados:
        st.markdown("**Inventário Existente**")
        st.dataframe(df_chart.style.format({'Lâmpadas': "{:,.0f}"}), use_container_width=True, hide_index=True)
        st.info(f"O município possui **{total_lampadas_concelho:,.0f}** luminárias no total.")

with tab2:
    st.subheader("Viabilidade e Retorno Financeiro")
    
    col_payback, col_impact = st.columns([2, 1])

    with col_payback:
        acumulado_vsap = np.cumsum(fluxos_vsap)
        acumulado_led = np.cumsum(fluxos_led)

        fig_payback = go.Figure()
        fig_payback.add_trace(go.Scatter(x=anos, y=acumulado_vsap, mode='lines+markers', name='Cenário Base (Manter Atual)', line=dict(color='#e74c3c')))
        fig_payback.add_trace(go.Scatter(x=anos, y=acumulado_led, mode='lines+markers', name='Projeto LED', line=dict(color='#2ecc71')))
        fig_payback.update_layout(
            title="Análise de Despesa Acumulada (Break-Even)", 
            xaxis_title="Anos de Projeto", 
            yaxis_title="Despesa Acumulada (€)",
            hovermode="x unified", 
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        fig_payback.update_xaxes(tickfont=dict(family='Arial', size=16, color='black'), title_font=dict(size=18, color='black'))
        fig_payback.update_yaxes(tickfont=dict(family='Arial', size=16, color='black'), title_font=dict(size=18, color='black'))
        
        st.plotly_chart(fig_payback, use_container_width=True)

    with col_impact:
        st.markdown("**Impacto Ambiental / Ano**")
        poupanca_kwh = kwh_ano_vsap - kwh_ano_led
        co2_ton = (poupanca_kwh * fator_co2) / 1000
        
        st.success(f"**Energia:** -{poupanca_kwh:,.0f} kWh")
        st.success(f"**Emissões:** -{co2_ton:,.0f} Ton CO2")
        st.info(f"Equivalente a plantar **{co2_ton * 45:,.0f}** árvores ou retirar **{co2_ton / 4.6:,.0f}** carros das vias.")

        st.markdown("**Desempenho Energético**")
        st.metric("Potência Média Atual", f"{pot_media_antiga:.1f} W")
        st.metric("Nova Potência Média LED", f"{pot_media_led:.1f} W", delta=f"{reducao_watts_por_luminaria:.1f} W / Luminária", delta_color="inverse")
        st.metric("Poupança Potência Contratada", f"{(custo_fixo_ano_vsap - custo_fixo_ano_led):,.0f} € / ano")

    st.markdown("---")
    
    if ativar_esco:
        st.markdown(f"**Tabela Financeira de Ciclo de Vida (Câmara paga {partilha_esco * 100:.0f}% da Poupança à ESCO durante {anos_contrato} anos)**")
    else:
        st.markdown(f"**Tabela Financeira de Ciclo de Vida ({anos_projeto} Anos)**")

    df_final = pd.DataFrame({
        'Ano': anos, 
        'Inv. Cenário Base (€)': inv_vsap_list, 
        'Energia Cenário Base (€)': energia_vsap_list,
        'Total Cenário Base (€)': fluxos_vsap, 
        'OPEX/Renda LED (€)': inv_led_list, 
        'Energia LED (€)': energia_led_list,
        'Total LED (€)': fluxos_led, 
        'Poupança Autarquia (€)': poupanca_ano_list
    }).set_index('Ano')
    
    st.dataframe(df_final.style.format("{:,.2f} €"), use_container_width=True)

    csv_data = df_final.to_csv(index=True, sep=';', decimal=',').encode('utf-8-sig')
    st.download_button(
        label="Descarregar Tabela Financeira (CSV)", 
        data=csv_data, 
        file_name=f"Auditoria_IP_{concelho_escolhido}.csv", 
        mime="text/csv"
    )

with tab3:
    st.subheader("Configurações de Engenharia e Equipamentos")
    
    col_lotes, col_curva = st.columns([1.5, 1])

    with col_lotes:
        st.markdown("**Detalhe do Investimento (CAPEX)**")
        df_lotes = pd.DataFrame({
            "Lote": nomes_lista, 
            "Alocação": perc_lista_norm, 
            "Qtd": qtd_lista, 
            "Potência": watts_lista, 
            "Preço Unit.": precos_lista,
            "CAPEX Total": [q * p for q, p in zip(qtd_lista, precos_lista)]
        })
        df_lotes = df_lotes[df_lotes['Alocação'] > 0]
        
        st.dataframe(
            df_lotes.style.format({
                "Alocação": "{:.1f}%", 
                "Qtd": "{:.0f}", 
                "Potência": "{:.0f} W", 
                "Preço Unit.": "{:,.2f} €", 
                "CAPEX Total": "{:,.2f} €"
            }), 
            use_container_width=True, 
            hide_index=True
        )
             
        if ativar_dimming and taxa_telegestao > 0:
            st.info(f"**Hardware Telegestão (Nós IoT):** {capex_iot_total:,.2f} € para {(lampadas_totais * taxa_telegestao):,.0f} luminárias.")

    with col_curva:
        st.markdown(f"**Curva de Telegestão (Ajustada ao pôr do sol de hoje em {distrito_inferido})**")
        
        lat, lon = distritos_coord.get(distrito_inferido, (38.7000, -9.1333))
        loc = LocationInfo(distrito_inferido, "Portugal", "Europe/Lisbon", lat, lon)
        tz_local = pytz.timezone(loc.timezone)
        s_hoje = sun(loc.observer, date=datetime.date.today(), tzinfo=tz_local)

        hora_liga_real = s_hoje['dusk'].hour + s_hoje['dusk'].minute / 60.0
        hora_desliga_real = s_hoje['dawn'].hour + s_hoje['dawn'].minute / 60.0

        def check_window(t, start, end):
            if start == end: 
                return False
            if start < end: 
                return start <= t < end
            else: 
                return t >= start or t < end

        x_hours = np.linspace(16, 33, 400)
        y_power = []
        hora_desliga_escala = hora_desliga_real + 24.0

        for h in x_hours:
            real_h = h if h < 24 else h - 24
            if h < hora_liga_real or h > hora_desliga_escala: 
                y_power.append(0)
            else:
                val = 100
                if ativar_dimming:
                    if check_window(real_h, p2_inicio, p2_fim): 
                        val = 100 - p2_red
                    elif check_window(real_h, p1_inicio, p1_fim): 
                        val = 100 - p1_red
                y_power.append(val)

        fig_dim = go.Figure()
        fig_dim.add_trace(
            go.Scatter(x=x_hours, y=y_power, fill='tozeroy', mode='lines', line=dict(color='#2980b9'), name='Potência')
        )
        
        fig_dim.update_layout(
            xaxis=dict(
                tickmode='array', 
                tickvals=[16, 18, 20, 22, 24, 26, 28, 30, 32], 
                ticktext=['16h', '18h', '20h', '22h', '00h', '02h', '04h', '06h', '08h']
            ),
            yaxis_title="Potência Ativa (%)", 
            yaxis_range=[0, 110], 
            height=300, 
            margin=dict(t=10, b=0, l=0, r=0)
        )
        
        st.plotly_chart(fig_dim, use_container_width=True)
        st.caption(f"**Nascer do Sol:** {s_hoje['dawn'].strftime('%H:%M')} | **Pôr do Sol:** {s_hoje['dusk'].strftime('%H:%M')}")
