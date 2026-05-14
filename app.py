import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Gaming Analytics Dashboard", layout="wide", page_icon="🎲")
st.title("🎲 Dynamic Gaming Analytics Dashboard")
st.markdown("Upload your raw casino betting data (CSV or Excel) to generate instant insights.")

# --- FILE UPLOADER ---
uploaded_file = st.file_uploader("Upload your Betting Data", type=['csv', 'xlsx'])

@st.cache_data
def load_and_process_data(file):
    # Load data
    if file.name.endswith('.csv'):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)
        
    # --- CURRENCY CONVERSION ---
    # Based on the rule: 100 EUR = 100 USD = 150 CAD, etc.
    conversion_rates = {
        'EUR': 100, 'USD': 100, 'CAD': 150, 'AUD': 150, 'NZD': 150,
        'NOK': 1000, 'RUB': 8000, 'ZAR': 2000, 'INR': 10000, 'BRL': 600,
        'BTC': 0.0024, 'ETH': 0.06, 'LTC': 1.8, 'BCH': 0.5, 'DOG': 1500,
        'USDT': 100, 'XRP': 250, 'BNB': 0.4, 'ADA': 400, 'TRX': 1400
    }
    
    # Calculate the multiplier to get to EUR (e.g., CAD multiplier is 100/150 = 0.666)
    multipliers = {currency: (100.0 / rate) for currency, rate in conversion_rates.items()}
    
    # Map the multiplier to the dataframe based on the 'currency' column (default to 1 if unknown)
    if 'currency' in df.columns:
        df['eur_multiplier'] = df['currency'].map(multipliers).fillna(1.0)
        df['bet_amount'] = df['bet_amount'] * df['eur_multiplier']
        df['win_amount'] = df['win_amount'] * df['eur_multiplier']

    # --- ROBUST DATETIME PARSING ---
    def get_datetime(df, date_col, time_col):
        if pd.api.types.is_datetime64_any_dtype(df[date_col]):
            return df[date_col]
        return pd.to_datetime(df[date_col].astype(str) + ' ' + df[time_col].astype(str))

    try:
        df['start_datetime'] = get_datetime(df, 'date_started', 'time_started')
        df['end_datetime'] = get_datetime(df, 'date_finished', 'time_finished')
    except Exception as e:
        st.error(f"Error parsing dates: {e}. Please ensure columns 'date_started' and 'time_started' exist.")
        st.stop()
        
    # --- REST OF THE PROCESSING ---
    df = df.sort_values(by=['player_id_casino', 'game_id', 'start_datetime'])
    df['prev_end_datetime'] = df.groupby(['player_id_casino', 'game_id'])['end_datetime'].shift(1)
    df['time_diff'] = (df['start_datetime'] - df['prev_end_datetime']).dt.total_seconds()
    
    # Session Rule: 10 MINUTES (600 SECONDS)
    df['is_new_session'] = (df['prev_end_datetime'].isna()) | (df['time_diff'] > 600)
    df['session_id'] = df['is_new_session'].cumsum()

    session_stats = df.groupby(['player_id_casino', 'game_id', 'session_id']).agg(
        session_start=('start_datetime', 'min'),
        session_end=('end_datetime', 'max'),
        number_of_bets=('round_id_casino', 'count'),
        total_bet_amount=('bet_amount', 'sum')
    ).reset_index()
    
    session_stats['duration_seconds'] = (session_stats['session_end'] - session_stats['session_start']).dt.total_seconds()

    # Clean anomalies (drop sessions > 24 hours)
    valid_sessions = session_stats[session_stats['duration_seconds'] < 86400].copy()
    valid_sessions['duration_minutes'] = valid_sessions['duration_seconds'] / 60
    df_clean = df[df['session_id'].isin(valid_sessions['session_id'])]

    # Calculate Averages
    game_sess_avg = valid_sessions.groupby('game_id').agg(
        avg_duration_minutes=('duration_minutes', 'mean'),
        avg_number_of_bets=('number_of_bets', 'mean'),
        total_volume=('total_bet_amount', 'sum')
    ).reset_index()
    
    game_bet_avg = df_clean.groupby('game_id').agg(avg_single_bet_amount=('bet_amount', 'mean')).reset_index()
    game_stats = pd.merge(game_sess_avg, game_bet_avg, on='game_id')
    
    return df, df_clean, valid_sessions, game_stats

# --- HTML GENERATOR HELPER ---
def generate_html_report(figs):
    html_content = """
    <html>
    <head>
        <title>Gaming Analytics Report</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8f9fa; margin: 0; padding: 20px; }
            h1 { text-align: center; color: #111827; }
            .chart-container { background: white; padding: 20px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
        </style>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    </head>
    <body>
        <h1>🎲 Gaming Analytics Report</h1>
    """
    for fig in figs:
        fig_html = fig.to_html(full_html=False, include_plotlyjs=False)
        html_content += f"<div class='chart-container'>{fig_html}</div>"
        
    html_content += "</body></html>"
    return html_content

# --- DASHBOARD GENERATION ---
if uploaded_file is not None:
    with st.spinner('Processing data and converting currencies to EUR...'):
        df, df_clean, valid_sessions, game_stats = load_and_process_data(uploaded_file)
        st.success("Data processed successfully! All bet and win amounts have been normalized to EUR.")
        
        # Split layout into two columns
        col1, col2 = st.columns(2)

        # 1. FUNNEL CHART
        bets_per_player = df.groupby(['player_id_casino', 'game_id']).size().reset_index(name='total_bets')
        c1 = len(bets_per_player[bets_per_player['total_bets'] == 1])
        c2 = len(bets_per_player[(bets_per_player['total_bets'] >= 2) & (bets_per_player['total_bets'] <= 10)])
        c3 = len(bets_per_player[(bets_per_player['total_bets'] >= 11) & (bets_per_player['total_bets'] <= 20)])
        c4 = len(bets_per_player[bets_per_player['total_bets'] > 20])
        
        lvl1 = c1 + c2 + c3 + c4
        lvl2 = lvl1 - c1
        lvl3 = lvl2 - c2
        lvl4 = lvl3 - c3

        fig1 = go.Figure(go.Funnel(
            y=["Started", "Continued (>1 bet)", "Engaged (>10 bets)", "Retained (>20 bets)"],
            x=[lvl1, lvl2, lvl3, lvl4],
            textposition="inside", textinfo="value+percent initial",
            marker={"color": ["#5A3E92", "#3B82F6", "#4ADE80", "#EF4444"]}
        ))
        fig1.update_layout(title="🎯 Player Funnel & Retention")

        # 2. TOP ENGAGING GAMES
        top_engaging = game_stats.sort_values('avg_duration_minutes', ascending=True).tail(10)
        fig2 = px.bar(top_engaging, x='avg_duration_minutes', y='game_id', orientation='h', 
                      title="⏱️ Top 10 Games: Avg Session Duration (mins)", color_discrete_sequence=['#3B82F6'])

        # 3. TOP VOLUME GAMES
        top_volume = game_stats.sort_values('total_volume', ascending=False).head(10)
        fig3 = px.bar(top_volume, x='game_id', y='total_volume', 
                      title="💰 Top 10 Games by Total Bet Volume (€)", color_discrete_sequence=['#10B981'])

        # 4. SPEND BEHAVIOR
        fig4 = px.scatter(game_stats, x='avg_number_of_bets', y='avg_single_bet_amount', 
                          size='total_volume', color='game_id', hover_name='game_id', 
                          title="💎 Volume vs Bet Size (Bubble size = Total Volume)")

        # 5. SESSION DISTRIBUTION
        bins_sess = [-1, 1, 3, 5, 10, 20, float('inf')]
        labels_sess = ['0-1 min', '1-3 min', '3-5 min', '5-10 min', '10-20 min', '>20 min']
        valid_sessions['Duration_Category'] = pd.cut(valid_sessions['duration_minutes'], bins=bins_sess, labels=labels_sess, right=True)
        sess_counts = valid_sessions['Duration_Category'].value_counts().reindex(labels_sess)
        fig5 = px.bar(x=sess_counts.index, y=sess_counts.values, title="📊 Session Length Distribution", color_discrete_sequence=['#818cf8'])
        fig5.update_layout(xaxis_title="Duration", yaxis_title="Number of Sessions")

        # 6. BET DISTRIBUTION (Now accurately grouped by EUR equivalent)
        bins_bet = [0, 1, 5, 20, float('inf')]
        labels_bet = ['0-1 EUR', '1-5 EUR', '5-20 EUR', '20+ EUR']
        df_clean['bet_bracket'] = pd.cut(df_clean['bet_amount'], bins=bins_bet, labels=labels_bet, include_lowest=True, right=True)
        bet_counts = df_clean['bet_bracket'].value_counts().reset_index()
        bet_counts.columns = ['Bracket', 'Count']
        fig6 = px.pie(bet_counts, values='Count', names='Bracket', hole=0.5, 
                      title="🎰 Bet Amount Distribution (in EUR)", color_discrete_sequence=['#4f46e5', '#818cf8', '#10B981', '#EF4444'])

        # --- RENDER CHARTS IN APP ---
        st.plotly_chart(fig1, use_container_width=True)
        with col1:
            st.plotly_chart(fig2, use_container_width=True)
            st.plotly_chart(fig5, use_container_width=True)
        with col2:
            st.plotly_chart(fig3, use_container_width=True)
            st.plotly_chart(fig6, use_container_width=True)
        st.plotly_chart(fig4, use_container_width=True)

        # --- EXPORT REPORT ---
        st.markdown("---")
        st.subheader("📥 Export Reports")
        st.markdown("Download a fully interactive HTML version of this report. You can share it, or open it and Print to PDF.")
        
        all_figs = [fig1, fig2, fig3, fig5, fig6, fig4]
        html_report = generate_html_report(all_figs)
        
        st.download_button(
            label="⬇️ Download Interactive Report (.html)",
            data=html_report,
            file_name="Gaming_Analytics_Report.html",
            mime="text/html",
            type="primary"
        )

else:
    st.info("Awaiting file upload. Please upload a dataset to begin.")
