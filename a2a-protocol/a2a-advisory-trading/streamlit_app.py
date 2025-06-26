# ABOUTME: Streamlit web interface for A2A Advisory Trading platform
# ABOUTME: Provides a user-friendly frontend for portfolio analysis and trade execution

import streamlit as st
import os
import sys
import asyncio
import boto3
import json
from datetime import datetime, timedelta
import time
from queue import Queue
import concurrent.futures
from typing import List, Dict, Optional
import aiohttp
import threading
import uuid
import pandas as pd
import textwrap
from dotenv import load_dotenv
import warnings
import logging

# Configure logging to suppress Streamlit threading warnings
logging.basicConfig(level=logging.WARNING)
logging.getLogger("streamlit").setLevel(logging.ERROR)
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)

# Suppress specific warnings
warnings.filterwarnings("ignore", message=".*missing ScriptRunContext.*")
warnings.filterwarnings("ignore", category=UserWarning, module="streamlit")

# Load environment variables
load_dotenv()

# Import classes from CLI with modifications
region = os.environ.get("AWS_REGION", "us-east-1")
app_name = os.environ.get("APP_NAME", "adt")
env_name = os.environ.get("ENV_NAME", "dev")

# Page configuration
st.set_page_config(
    page_title="A2A Advisory Trading",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 1rem;
    }
    .log-container {
        background-color: #0e1117;
        border-radius: 0.5rem;
        padding: 1rem;
        margin: 0.5rem 0;
        font-family: 'Courier New', monospace;
        font-size: 0.8rem;
        max-height: 300px;
        overflow-y: auto;
    }
    .result-card {
        background-color: #262730;
        border-radius: 0.5rem;
        padding: 1.5rem;
        margin: 1rem 0;
        border: 1px solid #464646;
    }
    .metric-container {
        text-align: center;
        padding: 1rem;
        background-color: #1e1e2e;
        border-radius: 0.5rem;
        margin: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)


class StreamlitLogStreamReader:
    """Modified LogStreamReader for Streamlit integration"""
    def __init__(self, log_placeholder=None):
        self.cloudwatch_logs = boto3.client('logs')
        self.log_groups = [
            f'/aws/lambda/{app_name}-{env_name}-PortfolioManagerAgent',
            f'/aws/lambda/{app_name}-{env_name}-MarketAnalysisAgent',
            f'/aws/lambda/{app_name}-{env_name}-RiskAssessmentAgent',
            f'/aws/lambda/{app_name}-{env_name}-TradeExecutionAgent'
        ]
        self.log_queue = Queue()
        self._stop_event = threading.Event()
        self.seen_events = set()
        self.retry_count = 0
        self.max_retries = 5
        self.empty_responses = 0
        self.max_empty_responses = 3
        self.log_placeholder = log_placeholder
        self.logs_buffer = []

    def stop(self):
        self._stop_event.set()

    def is_running(self):
        return not self._stop_event.is_set()

    def set_log_groups(self, log_groups):
        self.log_groups = log_groups

    def get_log_events(self, log_group: str, start_time: int) -> List[Dict]:
        try:
            if self.retry_count > 0:
                backoff_time = min(1.5 ** self.retry_count, 2)
                for _ in range(int(backoff_time * 10)):
                    if not self.is_running():
                        return []
                    time.sleep(0.1)

            # Debug: Log the request
            print(f"Fetching logs from {log_group} starting at {start_time}")
            
            response = self.cloudwatch_logs.filter_log_events(
                logGroupName=log_group,
                startTime=start_time,
                interleaved=True
            )
            self.retry_count = 0
            new_events = []
            for event in response.get('events', []):
                event_id = f"{event['timestamp']}-{event['message']}"
                if event_id not in self.seen_events:
                    self.seen_events.add(event_id)
                    new_events.append(event)
            
            # Debug: Log results
            if new_events:
                print(f"Found {len(new_events)} new events from {log_group}")
            
            return new_events
        except Exception as e:
            print(f"Error fetching logs from {log_group}: {str(e)}")
            self.retry_count += 1
            if self.retry_count <= self.max_retries:
                return self.get_log_events(log_group, start_time)
            else:
                # Add error to session state for visibility
                if 'current_logs' in st.session_state:
                    error_log = {
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'group': 'ERROR',
                        'message': f'Failed to fetch logs from {log_group}: {str(e)}',
                        'full_text': f'[ERROR] Failed to fetch logs from {log_group}: {str(e)}'
                    }
                    st.session_state.current_logs.append(error_log)
                return []

    def stream_log_group(self, log_group: str, start_time: int):
        last_timestamp = start_time
        empty_responses = 0

        while self.is_running():
            try:
                events = self.get_log_events(log_group, last_timestamp)
                if not self.is_running():
                    break
                if events:
                    empty_responses = 0
                    for event in events:
                        self.log_queue.put({
                            'timestamp': event['timestamp'],
                            'group': log_group,
                            'message': event['message'].strip()
                        })
                        last_timestamp = max(last_timestamp, event['timestamp'] + 1)
                    for _ in range(5):
                        if not self.is_running():
                            break
                        time.sleep(0.1)
                else:
                    empty_responses += 1
                    sleep_time = min(0.5 * (1.5 ** empty_responses), 2)
                    for _ in range(int(sleep_time * 10)):
                        if not self.is_running():
                            break
                        time.sleep(0.1)
            except Exception as e:
                if not self.is_running():
                    break
                time.sleep(0.25)

    def update_logs_display(self):
        """Update Streamlit log display"""
        while self.is_running():
            try:
                if not self.log_queue.empty():
                    log = self.log_queue.get()
                    timestamp = datetime.fromtimestamp(log['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    group_name = log['group'].split('/')[-1]
                    log_entry = {
                        'timestamp': timestamp,
                        'group': group_name,
                        'message': log['message'],
                        'full_text': f"[{timestamp}] [{group_name}] {log['message']}"
                    }
                    self.logs_buffer.append(log_entry)
                    
                    # Keep only last 200 logs
                    if len(self.logs_buffer) > 200:
                        self.logs_buffer = self.logs_buffer[-200:]
                    
                    # Update session state for persistent display
                    if 'current_logs' in st.session_state:
                        st.session_state.current_logs = self.logs_buffer.copy()
                    
                    # Update display if placeholder is set
                    if self.log_placeholder:
                        try:
                            # Format logs for display
                            formatted_logs = "\n".join([log['full_text'] for log in self.logs_buffer])
                            self.log_placeholder.text(formatted_logs)
                        except:
                            # If we can't update due to context issues, just skip
                            pass
                        
                for _ in range(2):
                    if not self.is_running():
                        break
                    time.sleep(0.05)
            except Exception as e:
                if not self.is_running():
                    break
                time.sleep(0.1)


def init_session_state():
    """Initialize session state variables"""
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    if 'api_id' not in st.session_state:
        st.session_state.api_id = os.environ.get("PORTFOLIO_MANAGER_API_ID", "")
    if 'processing' not in st.session_state:
        st.session_state.processing = False
    if 'trade_confirmation' not in st.session_state:
        st.session_state.trade_confirmation = None
    if 'current_logs' not in st.session_state:
        st.session_state.current_logs = []
    if 'log_filter' not in st.session_state:
        st.session_state.log_filter = "all"
    if 'auto_scroll' not in st.session_state:
        st.session_state.auto_scroll = True
    if 'log_streaming' not in st.session_state:
        st.session_state.log_streaming = False
    if 'debug_mode' not in st.session_state:
        st.session_state.debug_mode = False


def get_lambda_color(lambda_name):
    """Get color for Lambda function"""
    # Extract the agent name from full log group name
    if "PortfolioManagerAgent" in lambda_name:
        return "#FF6B6B"  # Red
    elif "MarketAnalysisAgent" in lambda_name:
        return "#4ECDC4"  # Teal
    elif "RiskAssessmentAgent" in lambda_name:
        return "#FFE66D"  # Yellow
    elif "TradeExecutionAgent" in lambda_name:
        return "#95E1D3"  # Green
    else:
        return "#FFFFFF"  # White for others


def format_log_entry(log_entry):
    """Format a single log entry with color coding"""
    color = get_lambda_color(log_entry['group'])
    return f'<span style="color: {color};">[{log_entry["timestamp"]}] [{log_entry["group"]}]</span> {log_entry["message"]}'


def fetch_recent_logs(start_time=None, task_id=None):
    """Fetch recent logs from CloudWatch"""
    try:
        cloudwatch = boto3.client('logs')
        log_groups = [
            f'/aws/lambda/{app_name}-{env_name}-PortfolioManagerAgent',
            f'/aws/lambda/{app_name}-{env_name}-MarketAnalysisAgent',
            f'/aws/lambda/{app_name}-{env_name}-RiskAssessmentAgent',
            f'/aws/lambda/{app_name}-{env_name}-TradeExecutionAgent'
        ]
        
        # Use provided start_time or default to last 5 minutes
        end_time = int(time.time() * 1000)
        if start_time is None:
            start_time = end_time - (5 * 60 * 1000)
        
        new_logs = []
        
        for log_group in log_groups:
            try:
                # Build filter pattern if task_id provided
                kwargs = {
                    'logGroupName': log_group,
                    'startTime': start_time,
                    'endTime': end_time,
                    'limit': 100
                }
                
                if task_id:
                    kwargs['filterPattern'] = task_id
                
                response = cloudwatch.filter_log_events(**kwargs)
                
                for event in response.get('events', []):
                    timestamp = datetime.fromtimestamp(event['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    group_name = log_group.split('/')[-1]
                    log_entry = {
                        'timestamp': timestamp,
                        'group': group_name,
                        'message': event['message'].strip(),
                        'full_text': f"[{timestamp}] [{group_name}] {event['message'].strip()}"
                    }
                    new_logs.append(log_entry)
                    
            except Exception as e:
                # Only add error if it's not a simple "no logs found" situation
                if "ResourceNotFoundException" not in str(e):
                    error_log = {
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'group': 'ERROR',
                        'message': f'Failed to fetch from {log_group}: {str(e)}',
                        'full_text': f'[ERROR] Failed to fetch from {log_group}: {str(e)}'
                    }
                    new_logs.append(error_log)
        
        # Sort by timestamp and update session state
        new_logs.sort(key=lambda x: x['timestamp'])
        if 'current_logs' not in st.session_state:
            st.session_state.current_logs = []
        
        # Remove duplicates based on full_text
        existing_texts = {log['full_text'] for log in st.session_state.current_logs}
        unique_new_logs = [log for log in new_logs if log['full_text'] not in existing_texts]
        
        st.session_state.current_logs.extend(unique_new_logs)
        
        # Keep only last 1000 logs
        if len(st.session_state.current_logs) > 1000:
            st.session_state.current_logs = st.session_state.current_logs[-1000:]
        
        return len(unique_new_logs)  # Return count of new logs
            
    except Exception as e:
        st.error(f"Error fetching logs: {str(e)}")
        return 0


def extract_market_data(artifacts):
    """Extract market analysis data from artifacts"""
    market_data = {
        "summary": "",
        "tags": [],
        "sentiment": "unknown"
    }

    for artifact in artifacts:
        if artifact.get("name") == "Market Summary":
            for part in artifact.get("parts", []):
                if part.get("kind") == "text":
                    summary_text = part.get("text", "")
                    market_data["summary"] = summary_text
                elif part.get("kind") == "data":
                    data = part.get("data", {})
                    tags = data.get("tags", [])
                    sentiment = data.get("sentiment", "unknown")
                    market_data["tags"] = tags
                    market_data["sentiment"] = sentiment

    return market_data


def extract_risk_data(artifacts):
    """Extract risk assessment data from artifacts"""
    risk_data = {
        "score": "N/A",
        "rating": "unknown",
        "factors": [],
        "explanation": ""
    }

    for artifact in artifacts:
        if artifact.get("name") == "Risk Assessment":
            for part in artifact.get("parts", []):
                if part.get("kind") == "text":
                    text_content = part.get("text", "")
                    try:
                        json_data = json.loads(text_content)
                        risk_data["score"] = json_data.get("score", "N/A")
                        risk_data["rating"] = json_data.get("rating", "unknown")
                        risk_data["factors"] = json_data.get("factors", [])
                        risk_data["explanation"] = json_data.get("explanation", "")
                    except json.JSONDecodeError:
                        pass

    return risk_data


def extract_trade_execution(artifacts):
    """Extract trade execution data from artifacts"""
    trade_data = {
        "status": "N/A",
        "confirmationId": "unknown"
    }

    for artifact in artifacts:
        if artifact.get("name") == "Trade Execution":
            for part in artifact.get("parts", []):
                if part.get("kind") == "text":
                    text_content = part.get("text", "")
                    try:
                        json_data = json.loads(text_content)
                        trade_data["status"] = json_data.get("status", "N/A")
                        trade_data["confirmationId"] = json_data.get("confirmationId", "unknown")
                    except json.JSONDecodeError:
                        pass

    return trade_data


def generate_cloudwatch_log_link(log_group: str, task_id: str, region: str = 'us-east-1', start_time: int = None) -> str:
    """Generate CloudWatch console link"""
    encoded_log_group = log_group.replace('/', '$252F')
    end_time = int(time.time() * 1000)
    if not start_time:
        start_time = end_time - (5 * 60 * 1000)

    base_url = f"https://{region}.console.aws.amazon.com/cloudwatch/home"
    query_params = (
        f"?region={region}#logsV2:log-groups/log-group/{encoded_log_group}"
        f"/log-events$3FstartTime$3D{start_time}$26endTime$3D{end_time}"
        f"$26filterPattern$3D{task_id}"
    )
    return base_url + query_params


def generate_dynamodb_link(table_name: str, region: str = 'us-east-1', task_id: str = None) -> str:
    """Generate DynamoDB console link"""
    base_url = f"https://{region}.console.aws.amazon.com/dynamodbv2/home"
    query_params = (
        f"?region={region}#item-explorer"
        f"?table={table_name}"
    )
    if task_id:
        query_params += f"&filter=task_id%3D%3D%22{task_id}%22"
    return base_url + query_params


def show_agent_activity(agent_name, active=True):
    """Show agent activity indicator"""
    if active:
        return f"🟢 {agent_name} is processing..."
    else:
        return f"✅ {agent_name} completed"


async def send_request(api_url: str, question: str, log_container=None):
    """Send request to Portfolio Manager API"""
    try:
        # Start looking for logs from now
        start_time = int(datetime.now().timestamp() * 1000)
        
        # Set streaming status
        st.session_state.log_streaming = True
        
        # Add initial status log
        if 'current_logs' not in st.session_state:
            st.session_state.current_logs = []
        
        # Show processing status
        status_container = st.container()
        with status_container:
            st.info("🔄 Processing your request...")
            agent_status = st.empty()
            agent_status.markdown(show_agent_activity("Portfolio Manager"))
        
        task_id = f"streamlit-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        payload = {
            "jsonrpc": "2.0",
            "id": task_id,
            "method": "message/send",
            "params": {
                "skill": "portfolio-orchestration",
                "message": {
                    "id": task_id,
                    "user_input": question,
                    "created_at": datetime.now().isoformat(),
                    "modified_at": datetime.now().isoformat(),
                    "kind": "task"
                }
            }
        }

        async with aiohttp.ClientSession() as session:
            # Phase 1: Analysis
            async with session.post(api_url, json=payload, headers={"Content-Type": "application/json"}) as response:
                raw_response_data = await response.json()
                # Unwrap A2A .result.message envelope
                if "result" in raw_response_data and "message" in raw_response_data["result"]:
                    response_data = raw_response_data["result"]["message"]
                else:
                    response_data = raw_response_data

                # Update status
                agent_status.markdown(show_agent_activity("Portfolio Manager", False))

                # Reset streaming status
                st.session_state.log_streaming = False
                
                # Wait a bit for logs to be written
                await asyncio.sleep(3)
                
                # Fetch all logs from this execution
                st.info("📥 Downloading execution logs...")
                log_count = fetch_recent_logs(start_time, task_id)
                
                if log_count > 0:
                    st.success(f"✅ Downloaded {log_count} log entries. Check the Logs tab for details.")
                else:
                    st.warning("⚠️ No logs found. They may still be processing or there might be a permissions issue.")
                
                return response_data, task_id, start_time

    except Exception as e:
        st.session_state.log_streaming = False
        st.error(f"Error: {str(e)}")
        return None, None, None


async def handle_trade_confirmation(api_url: str, response_data: dict, trade_details: dict, log_container=None):
    """Handle trade confirmation phase"""
    try:
        # Set streaming status
        st.session_state.log_streaming = True
        
        new_start_time = int(datetime.now().timestamp() * 1000)
        task_id = response_data.get("session_id") or response_data.get("id", "")
        
        # Show processing status
        st.info("🔄 Executing trade...")
        agent_status = st.empty()
        agent_status.markdown(show_agent_activity("Trade Execution"))
        
        trade_payload = {
            "jsonrpc": "2.0",
            "id": response_data.get("session_id") or f"{response_data.get('id', '')}-trade",
            "method": "message/send",
            "params": {
                "skill": "portfolio-orchestration",
                "message": {
                    "id": response_data.get("session_id") or response_data.get("id", ""),
                    "contextId": response_data.get("session_id") or response_data.get("id", ""),
                    "user_input": response_data.get("user_input", ""),
                    "trade_confirmation_phase": True,
                    "trade_details": trade_details,
                    "created_at": datetime.now().isoformat(),
                    "modified_at": datetime.now().isoformat(),
                    "kind": "task"
                }
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=trade_payload, headers={"Content-Type": "application/json"}) as trade_response:
                trade_raw = await trade_response.json()
                if "result" in trade_raw and "message" in trade_raw["result"]:
                    trade_result = trade_raw["result"]["message"]
                else:
                    trade_result = trade_raw
                
                # Update status
                agent_status.markdown(show_agent_activity("Trade Execution", False))
                
                # Reset streaming status
                st.session_state.log_streaming = False
                
                # Wait for logs and fetch
                await asyncio.sleep(3)
                log_count = fetch_recent_logs(new_start_time, task_id)
                
                if log_count > 0:
                    st.success(f"✅ Downloaded {log_count} trade execution log entries.")
                
                return trade_result, new_start_time
                
    except Exception as e:
        st.session_state.log_streaming = False
        st.error(f"Trade execution error: {str(e)}")
        return None, None


def display_analysis_results(response_data: dict):
    """Display analysis results in a formatted way"""
    # First show which agents were invoked
    agent_outputs = response_data.get("agent_outputs", {}) or response_data.get("analysis_results", {})
    
    if agent_outputs:
        invoked_agents = []
        for agent, result in agent_outputs.items():
            if result.get("status") == "completed":
                if agent.lower() in ["marketsummary", "market-summary"]:
                    invoked_agents.append("Market Analysis")
                elif agent.lower() in ["riskevaluation", "risk-evaluation"]:
                    invoked_agents.append("Risk Assessment")
                elif agent.lower() in ["executetrader", "trade-execution"]:
                    invoked_agents.append("Trade Execution")
        
        if invoked_agents:
            st.success(f"✅ Agents invoked: {', '.join(invoked_agents)}")
    
    col1, col2 = st.columns(2)
    
    # Market Analysis
    for agent, result in agent_outputs.items():
        if result.get("status") == "completed":
            response = result.get("response", {})
            
            if agent.lower() in ["marketsummary", "market-summary"]:
                market_data = extract_market_data(response)
                with col1:
                    st.markdown("### 📈 Market Analysis")
                    with st.container():
                        st.markdown(f"**Summary:**")
                        st.markdown(market_data.get("summary", ""))
                        
                        if market_data.get("tags"):
                            st.markdown("**Tags:** " + ", ".join([f"`{tag}`" for tag in market_data.get("tags", [])]))
                        
                        sentiment = market_data.get("sentiment", "unknown")
                        sentiment_color = "🟢" if sentiment == "positive" else "🔴" if sentiment == "negative" else "🟡"
                        st.markdown(f"**Sentiment:** {sentiment_color} {sentiment.capitalize()}")
            
            elif agent.lower() in ["riskevaluation", "risk-evaluation"]:
                risk_data = extract_risk_data(response)
                with col2:
                    st.markdown("### ⚠️ Risk Assessment")
                    with st.container():
                        # Risk metrics
                        score = risk_data.get("score", "N/A")
                        rating = risk_data.get("rating", "unknown")
                        
                        # Color code based on rating
                        if rating.lower() == "low":
                            rating_color = "🟢"
                        elif rating.lower() == "moderate":
                            rating_color = "🟡"
                        elif rating.lower() == "high":
                            rating_color = "🔴"
                        else:
                            rating_color = "⚪"
                        
                        metric_col1, metric_col2 = st.columns(2)
                        with metric_col1:
                            st.metric("Risk Score", score)
                        with metric_col2:
                            st.metric("Rating", f"{rating_color} {rating}")
                        
                        if risk_data.get("factors"):
                            st.markdown("**Risk Factors:**")
                            for factor in risk_data.get("factors", []):
                                st.markdown(f"• {factor}")
                        
                        if risk_data.get("explanation"):
                            st.markdown("**Explanation:**")
                            st.markdown(risk_data.get("explanation", ""))


def display_trade_results(trade_result: dict):
    """Display trade execution results"""
    if trade_result.get("status") == "completed":
        trade_info = trade_result.get("agent_outputs", {}).get("ExecuteTrade", {}).get("response", {})
        
        if isinstance(trade_info, dict):
            st.success("✅ Trade Executed Successfully!")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Symbol", trade_info.get("symbol", ""))
            with col2:
                st.metric("Quantity", trade_info.get("quantity", ""))
            with col3:
                st.metric("Confirmation ID", trade_info.get("confirmationId", ""))
            
            if trade_info.get("timestamp"):
                st.info(f"Executed at: {trade_info.get('timestamp')}")
        else:
            st.success("✅ Trade Executed Successfully!")
            st.info(str(trade_info))
    else:
        st.error("❌ Trade Execution Failed")
        error_msg = trade_result.get("agent_outputs", {}).get("ExecuteTrade", {}).get("error", "Unknown error")
        st.error(f"Error: {error_msg}")


def main():
    init_session_state()
    
    # Header
    st.markdown("# 📈 A2A Advisory Trading")
    st.markdown("*Powered by AWS Bedrock and Agent2Agent Protocol*")
    
    # Sidebar for configuration and logs
    with st.sidebar:
        st.markdown("## ⚙️ Configuration")
        
        # API ID configuration
        api_id = st.text_input(
            "Portfolio Manager API ID",
            value=st.session_state.api_id,
            help="Enter the API Gateway ID for the Portfolio Manager agent"
        )
        
        if api_id:
            st.session_state.api_id = api_id
            st.success("✓ API ID configured")
        else:
            st.error("⚠️ Please enter an API ID")
        
        st.markdown("---")
        st.markdown("### 📊 AWS Resources")
        st.markdown(f"**Region:** {region}")
        st.markdown(f"**Environment:** {env_name}")
        st.markdown(f"**App Name:** {app_name}")
        
        # Clear conversation button
        if st.button("🗑️ Clear Conversation"):
            st.session_state.messages = []
            st.session_state.trade_confirmation = None
            st.rerun()
        
        # Debug mode toggle
        st.session_state.debug_mode = st.checkbox("🐛 Debug Mode", value=st.session_state.debug_mode)
        
    
    # Main content area
    if not api_id:
        st.warning("⚠️ Please configure your API ID in the sidebar to continue.")
        return
    
    # Create tabs for different views
    tab1, tab2, tab3 = st.tabs(["💬 Chat", "📋 Logs", "📚 Help"])
    
    with tab1:
        # Display conversation history
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.markdown(message["content"])
                else:
                    # For assistant messages, check if it's analysis or trade results
                    if "analysis_results" in message:
                        display_analysis_results(message["analysis_results"])
                    elif "trade_results" in message:
                        display_trade_results(message["trade_results"])
                    else:
                        st.markdown(message["content"])
        
        # Trade confirmation interface
        if st.session_state.trade_confirmation:
            with st.form("trade_confirmation"):
                st.markdown("### 📝 Trade Confirmation")
                st.markdown("Please confirm the trade details:")
                
                trade_details = st.session_state.trade_confirmation["trade_details"]
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    symbol = st.text_input("Symbol", value=trade_details.get("symbol", ""))
                
                with col2:
                    action = st.selectbox("Action", ["buy", "sell"], 
                                        index=0 if trade_details.get("action", "buy").lower() == "buy" else 1)
                
                with col3:
                    quantity = st.number_input("Quantity", min_value=1, value=int(trade_details.get("quantity", 1)))
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("✅ Confirm Trade", type="primary"):
                        st.session_state.processing = True
                        updated_trade_details = {
                            "symbol": symbol.upper(),
                            "action": action,
                            "quantity": quantity
                        }
                        
                        # Execute trade
                        api_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/{env_name}/message/send"
                        
                        with st.spinner("Executing trade..."):
                            st.info("💡 Check the **Logs** tab to see trade execution activity")
                            
                            # Run async function
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            
                            trade_result, start_time = loop.run_until_complete(
                                handle_trade_confirmation(
                                    api_url,
                                    st.session_state.trade_confirmation["response_data"],
                                    updated_trade_details,
                                    None
                                )
                            )
                            
                            if trade_result:
                                st.session_state.messages.append({
                                    "role": "assistant",
                                    "trade_results": trade_result
                                })
                                display_trade_results(trade_result)
                        
                        st.session_state.trade_confirmation = None
                        st.session_state.processing = False
                
                with col2:
                    if st.form_submit_button("❌ Cancel"):
                        st.session_state.trade_confirmation = None
                        st.info("Trade cancelled.")
                        st.rerun()
        
        # User input
        if not st.session_state.processing and not st.session_state.trade_confirmation:
            user_input = st.chat_input("Ask your portfolio question...")
            
            if user_input:
                # Add user message to history
                st.session_state.messages.append({"role": "user", "content": user_input})
                
                # Display user message
                with st.chat_message("user"):
                    st.markdown(user_input)
                
                # Process request
                st.session_state.processing = True
                
                api_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/{env_name}/message/send"
                
                with st.chat_message("assistant"):
                    with st.spinner("Analyzing your request..."):
                        
                        # Run async function
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        response_data, task_id, start_time = loop.run_until_complete(
                            send_request(api_url, user_input, None)
                        )
                        
                        if response_data:
                            # Debug mode: show raw response
                            if st.session_state.debug_mode:
                                with st.expander("🐛 Debug: Raw Response", expanded=False):
                                    st.json(response_data)
                            
                            # Check if trade confirmation is needed
                            if response_data.get("status") == "pending" and response_data.get("trade_details"):
                                st.session_state.trade_confirmation = {
                                    "response_data": response_data,
                                    "trade_details": response_data.get("trade_details", {})
                                }
                                st.info("📝 Trade confirmation required. Please review the details above.")
                            else:
                                # Display analysis results
                                display_analysis_results(response_data)
                                st.session_state.messages.append({
                                    "role": "assistant",
                                    "analysis_results": response_data
                                })
                            
                            # Display CloudWatch links
                            with st.expander("🔗 CloudWatch Logs"):
                                for log_group in [
                                    f'/aws/lambda/{app_name}-{env_name}-PortfolioManagerAgent',
                                    f'/aws/lambda/{app_name}-{env_name}-MarketAnalysisAgent',
                                    f'/aws/lambda/{app_name}-{env_name}-RiskAssessmentAgent',
                                    f'/aws/lambda/{app_name}-{env_name}-TradeExecutionAgent'
                                ]:
                                    log_link = generate_cloudwatch_log_link(log_group, task_id, start_time=start_time)
                                    st.markdown(f"[{log_group}]({log_link})")
                
                st.session_state.processing = False
                st.rerun()
    
    with tab2:
        st.markdown("### 📋 Execution Logs")
        
        # Status bar
        status_col1, status_col2, status_col3 = st.columns([1, 1, 2])
        with status_col1:
            if st.session_state.log_streaming:
                st.info("⏳ **Processing** - Logs will download after completion")
            else:
                st.success("✅ **Ready** - Logs from completed requests")
        
        with status_col2:
            if st.button("🔄 Refresh"):
                fetch_recent_logs()
                st.rerun()
        
        with status_col3:
            if st.button("🗑️ Clear All"):
                st.session_state.current_logs = []
                st.rerun()
        
        # Log statistics
        if st.session_state.current_logs:
            col1, col2, col3, col4, col5 = st.columns(5)
            
            # Count logs by Lambda - look for the actual log group names
            log_counts = {}
            for log in st.session_state.current_logs:
                group = log['group']
                log_counts[group] = log_counts.get(group, 0) + 1
            
            # Map the full names to short names
            portfolio_count = log_counts.get(f"{app_name}-{env_name}-PortfolioManagerAgent", 0)
            market_count = log_counts.get(f"{app_name}-{env_name}-MarketAnalysisAgent", 0)
            risk_count = log_counts.get(f"{app_name}-{env_name}-RiskAssessmentAgent", 0)
            trade_count = log_counts.get(f"{app_name}-{env_name}-TradeExecutionAgent", 0)
            
            with col1:
                st.metric("Total", len(st.session_state.current_logs))
            with col2:
                st.metric("Portfolio", portfolio_count)
            with col3:
                st.metric("Market", market_count)
            with col4:
                st.metric("Risk", risk_count)
            with col5:
                st.metric("Trade", trade_count)
            
            # Display all logs
            st.markdown("---")
            
            # Filter controls
            filter_col1, filter_col2 = st.columns([3, 1])
            with filter_col1:
                search_term = st.text_input("Search logs", placeholder="Enter search term...", key="log_search")
            with filter_col2:
                # Create downloadable content
                log_content = "\n".join([log['full_text'] for log in st.session_state.current_logs])
                st.download_button(
                    label="📥 Download",
                    data=log_content,
                    file_name=f"a2a_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    mime="text/plain"
                )
            
            # Display filtered logs
            filtered_logs = st.session_state.current_logs
            if search_term:
                filtered_logs = [log for log in filtered_logs if search_term.lower() in log['full_text'].lower()]
            
            # Simple text area display for better performance
            log_text = "\n".join([log['full_text'] for log in filtered_logs])
            
            st.text_area(
                "Log Output",
                value=log_text,
                height=500,
                key="log_display",
                help="Logs are fetched every 2 seconds during processing"
            )
            
            st.caption(f"Showing {len(filtered_logs)} of {len(st.session_state.current_logs)} logs • Auto-refreshes during processing")
        else:
            st.info("No logs yet. Submit a query in the Chat tab to see logs appear here.")
            st.markdown("Logs will automatically stream every 2 seconds while processing your request.")
    
    with tab3:
        st.markdown("### 📚 How to Use A2A Advisory Trading")
        
        st.markdown("""
        #### 🎯 Query Types
        
        **Market Analysis:**
        - "What's the current market situation in biotech?"
        - "How is the tech sector performing?"
        - "Tell me about renewable energy market trends"
        
        **Risk Assessment:**
        - "What are the risks of investing in healthcare?"
        - "Evaluate the risk of AAPL stock"
        - "Is it safe to invest in emerging markets?"
        
        **Trade Execution:**
        - "Buy 100 shares of MSFT"
        - "I want to sell 50 shares of GOOGL"
        - "Execute a buy order for TSLA"
        
        #### 💡 Tips
        - Be specific with your questions for better results
        - Include context about your investment goals
        - For trades, always specify the symbol, action, and quantity
        - Review all analysis before confirming trades
        
        #### ⚠️ Disclaimer
        This is a demonstration tool for the A2A protocol implementation. 
        Not intended for actual investment advice.
        """)


if __name__ == "__main__":
    main()