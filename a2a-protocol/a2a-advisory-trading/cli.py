import os
import sys
import asyncio
import boto3
import json
from datetime import datetime, timedelta
import time
from queue import Queue
import concurrent.futures
from typing import List, Dict
import aiohttp
import threading
import uuid
from pyfiglet import figlet_format
from colorama import Fore, init
import textwrap

init(autoreset=True)

region = os.environ.get("AWS_REGION", "us-east-1")
app_name = os.environ.get("APP_NAME", "adt")
env_name = os.environ.get("ENV_NAME", "dev")



class LogStreamReader:
    def __init__(self):
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
                print(f"{Fore.YELLOW}Backing off for {backoff_time:.2f} seconds before retry...")
                for _ in range(int(backoff_time * 10)):
                    if not self.is_running():
                        return []
                    time.sleep(0.1)

            print(f"{Fore.CYAN}Fetching logs from {log_group.split('/')[-1]}...")
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
            return new_events
        except Exception as e:
            self.retry_count += 1
            if self.retry_count <= self.max_retries:
                print(f"{Fore.YELLOW}Retrying log fetch for {log_group.split('/')[-1]} (attempt {self.retry_count}/{self.max_retries})")
                return self.get_log_events(log_group, start_time)
            else:
                print(f"{Fore.RED}Error reading logs from {log_group}: {str(e)}")
                return []

    def stream_log_group(self, log_group: str, start_time: int):
        last_timestamp = start_time
        empty_responses = 0

        print(f"{Fore.CYAN}Starting log streaming for {log_group.split('/')[-1]}...")

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
                    if empty_responses % self.max_empty_responses == 0:
                        print(f"{Fore.YELLOW}No new logs for {log_group.split('/')[-1]}, increasing polling interval...")
                    # Frequent checks for stop event, even during sleep
                    for _ in range(int(sleep_time * 10)):
                        if not self.is_running():
                            break
                        time.sleep(0.1)
            except Exception as e:
                print(f"{Fore.RED}Error in stream_log_group for {log_group}: {str(e)}")
                if not self.is_running():
                    break
                time.sleep(0.25)
        print(f"{Fore.GREEN}Stopped log streaming for {log_group.split('/')[-1]}.")

    def print_logs(self):
        while self.is_running():
            try:
                if not self.log_queue.empty():
                    log = self.log_queue.get()
                    timestamp = datetime.fromtimestamp(log['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    group_name = log['group'].split('/')[-1]
                    print(f"{Fore.BLUE}[{timestamp}] [{group_name}]{Fore.WHITE} {log['message']}")
                for _ in range(2):
                    if not self.is_running():
                        break
                    time.sleep(0.05)
            except Exception as e:
                print(f"{Fore.RED}Error in print_logs: {str(e)}")
                if not self.is_running():
                    break
                time.sleep(0.1)
        print(f"{Fore.GREEN}Stopped log printing.")


def print_banner():
    banner = figlet_format("A2A Advisory", font="slant")
    print(Fore.CYAN + banner)
    print(Fore.YELLOW + "=" * 60)
    print(Fore.GREEN + "A2A Protocol | Powered by AWS Bedrock")
    print(Fore.MAGENTA + "💬 Ask your portfolio questions in natural language")
    print(Fore.YELLOW + "=" * 60 + "\n")


def format_block(title: str, content: str, color=Fore.WHITE):
    print(f"\n{color}{title}")
    print(Fore.YELLOW + "-" * len(title))
    print(textwrap.fill(str(content).strip(), width=80))


def generate_cloudwatch_log_link(log_group: str, task_id: str, region: str = 'us-east-1', start_time: int = None) -> str:
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
    base_url = f"https://{region}.console.aws.amazon.com/dynamodbv2/home"
    query_params = (
        f"?region={region}#item-explorer"
        f"?table={table_name}"
    )
    if task_id:
        query_params += f"&filter=task_id%3D%3D%22{task_id}%22"
    return base_url + query_params

def extract_market_data(artifacts):
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


async def format_response(resp: dict, phase: str = "analysis") -> None:
    print("\n" + Fore.CYAN + "🧠 Portfolio Manager Response:")
    print(Fore.YELLOW + "-" * 60)
    if phase == "analysis":
        summary = resp.get("summary", "")
        agent_outputs = resp.get("agent_outputs", {}) or resp.get("analysis_results", {})
        if summary:
            format_block("📝 Based on your request, I have decomposed and delegated tasks to the following agent(s).", summary, Fore.GREEN)
        for agent, result in agent_outputs.items():
            if result.get("status") == "completed":
                response = result.get("response", {})
                if agent.lower() in ["marketsummary", "market-summary"]:
                    market_data = extract_market_data(response)
                    print(f"\n{Fore.CYAN}📈 Market Analysis Results:")
                    print(Fore.YELLOW + "-" * 40)
                    format_block("Market Summary",market_data.get("summary", ""), Fore.CYAN)
                    format_block("Tags", ", ".join(market_data.get("tags", [])), Fore.CYAN)
                    format_block("Sentiment", market_data.get("sentiment", "unknown"), Fore.CYAN)
                elif agent.lower() in ["riskevaluation", "risk-evaluation"]:
                    risk_data = extract_risk_data(response)
                    print(f"\n{Fore.RED}⚠️ Risk Assessment Results:")
                    print(Fore.YELLOW + "-" * 40)
                    format_block("Risk Score", str(risk_data.get("score", "N/A")), Fore.RED)
                    format_block("Rating", risk_data.get("rating", "unknown"), Fore.RED)
                    format_block("Risk Factors", ", ".join(risk_data.get("factors", [])), Fore.RED)
                    format_block("Explanation", risk_data.get("explanation", ""), Fore.RED)
    elif phase == "trade":
        if resp.get("status") == "completed":
            trade_result = resp.get("agent_outputs", {}).get("ExecuteTrade", {})
            print("*** Trade_result nested:", trade_result)
            trade_info = trade_result.get("response", {})
            print("*** Trade info:", trade_info)

            if trade_result.get("status") == "completed":
                print(f"\n{Fore.GREEN}✅ Trade Execution Results:")
                print(Fore.YELLOW + "-" * 40)
                # If the agent returns JSON, print fields; otherwise print the string
                if isinstance(trade_info, dict):
                    format_block("Status", trade_info.get("status", ""), Fore.GREEN)
                    format_block("Confirmation ID", trade_info.get("confirmationId", ""), Fore.GREEN)
                    format_block("Symbol", trade_info.get("symbol", ""), Fore.GREEN)
                    format_block("Quantity", str(trade_info.get("quantity", "")), Fore.GREEN)
                    format_block("Timestamp", trade_info.get("timestamp", ""), Fore.GREEN)
                else:
                    print(trade_info)
            else:
                print(f"\n{Fore.RED}❌ Trade Execution Failed:")
                print(Fore.YELLOW + "-" * 40)
                format_block("Error", trade_result.get("error", "Unknown error"), Fore.RED)
        else:
            print(f"\n{Fore.YELLOW}ℹ️ Trade Cancelled by User")


async def validate_trade_info(trade_details: dict) -> dict:
    updated_details = trade_details.copy()
    print(f"\n{Fore.YELLOW}Based on the analysis results, we need to confirm one or more information with you before proceeding to trade execution.{Fore.RESET}")

    # Validate symbol
    if not updated_details.get('symbol') or updated_details.get('symbol') == 'TBD':
        while True:
            user_input = input(f"{Fore.YELLOW}\nEnter the stock symbol: {Fore.RESET}").strip()
            if user_input:
                updated_details['symbol'] = user_input.upper()
                break
            print(f"{Fore.RED}Symbol cannot be empty.{Fore.RESET}")
    else:
        print(f"\n{Fore.YELLOW}From your initial request and analysis result, we think the following company would be of your interest of trading: {updated_details.get('symbol')}.\n{Fore.RESET}")
        confirm_symbol = input(f"{Fore.YELLOW}Is this the company you would like to trade? (y/n) {Fore.RESET}").strip()
        if confirm_symbol not in ["y", "yes"]:
            while True:
                user_input = input(f"{Fore.YELLOW}\nEnter the stock symbol: {Fore.RESET}").strip()
                if user_input:
                    updated_details['symbol'] = user_input.upper()
                    break
                print(f"{Fore.RED}Symbol cannot be empty.{Fore.RESET}")

    # Validate action
    current_action = updated_details.get('action', '').lower()
    if not current_action or current_action not in ['buy', 'sell'] or current_action == 'tbd':
        while True:
            user_input = input(f"{Fore.YELLOW}\nEnter the action (buy/sell): {Fore.RESET}").strip().lower()
            if user_input in ['buy', 'sell']:
                updated_details['action'] = user_input
                break
            print(f"{Fore.RED}Action must be either 'buy' or 'sell'.{Fore.RESET}")
    else:
        print(f"\n{Fore.YELLOW}From your initial request and analysis result, it looks like you want to initiate a {updated_details.get('action', '').lower()} action.{Fore.RESET}")
        confirm_action = input(f"{Fore.YELLOW}Can you confirm that you want to execute a {'buying' if updated_details.get('action', '').lower() == 'buy' else 'selling'} action? (y/n) {Fore.RESET}").strip()
        if confirm_action not in ["y", "yes"]:
            while True:
                user_input = input(f"{Fore.YELLOW}\nEnter the action (buy/sell): {Fore.RESET}").strip().lower()
                if user_input in ['buy', 'sell']:
                    updated_details['action'] = user_input
                    break
                print(f"{Fore.RED}Action must be either 'buy' or 'sell'.{Fore.RESET}")

    # Validate quantity
    current_quantity = updated_details.get('quantity')
    if not current_quantity or (
            not isinstance(current_quantity, (int, float)) or
            current_quantity <= 0 or
            current_quantity == 'TBD'
    ):
        while True:
            user_input = input(f"{Fore.YELLOW}\nEnter the quantity to trade: {Fore.RESET}").strip()
            try:
                quantity = int(user_input)
                if quantity <= 0:
                    print(f"{Fore.RED}Quantity must be a positive number.{Fore.RESET}")
                    continue
                updated_details['quantity'] = quantity
                break
            except ValueError:
                print(f"{Fore.RED}Please enter a valid number.{Fore.RESET}")
    else:
        print(f"\n{Fore.YELLOW}From your initial request and analysis result, it looks like you want to perform {updated_details.get('action', '').lower()} action on {updated_details.get('quantity')} shares.{Fore.RESET}")
        confirm_quantity = input(f"{Fore.YELLOW}Can you confirm a trade execution of {updated_details.get('quantity')} shares? (y/n) {Fore.RESET}").strip()
        if confirm_quantity != "y":
            while True:
                user_input = input(f"{Fore.YELLOW}\nEnter the quantity to trade: {Fore.RESET}").strip()
                try:
                    quantity = int(user_input)
                    if quantity <= 0:
                        print(f"{Fore.RED}Quantity must be a positive number.{Fore.RESET}")
                        continue
                    updated_details['quantity'] = quantity
                    break
                except ValueError:
                    print(f"{Fore.RED}Please enter a valid number.{Fore.RESET}")

    return updated_details


async def send_request(api_url: str, question: str, log_streamer: LogStreamReader):
    try:
        start_time = int((datetime.now() - timedelta(seconds=90)).timestamp() * 1000)
        print(f"{Fore.YELLOW}Initializing analysis phase...")

        task_id = f"cli-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(log_streamer.log_groups) + 1) as executor:
            futures = [
                executor.submit(log_streamer.stream_log_group, log_group, start_time)
                for log_group in log_streamer.log_groups
            ]
            printer_future = executor.submit(log_streamer.print_logs)

            async with aiohttp.ClientSession() as session:
                # Phase 1: Analysis
                async with session.post(api_url, json=payload, headers={"Content-Type": "application/json"}) as response:
                    raw_response_data = await response.json()
                    # Unwrap A2A .result.message envelope
                    if "result" in raw_response_data and "message" in raw_response_data["result"]:
                        response_data = raw_response_data["result"]["message"]
                    else:
                        response_data = raw_response_data

                    log_streamer.stop()
                    for future in futures + [printer_future]:
                        try:
                            future.result(timeout=5)
                        except:
                            pass

                    await format_response(response_data, phase="analysis")

                    print(f"\n{Fore.CYAN}CloudWatch Logs::")
                    for log_group in log_streamer.log_groups:
                        log_link = generate_cloudwatch_log_link(log_group, task_id, start_time=start_time)
                        print(f"{Fore.CYAN}• {log_group}: {Fore.BLUE}{log_link}{Fore.RESET}")

                    # If trade confirmation needed
                    if response_data.get("status") == "pending":
                        trade_details = response_data.get("trade_details", {})
                        await asyncio.sleep(1)
                        if trade_details:
                            updated_trade_details = await validate_trade_info(trade_details)
                            confirmation = input(f"\n{Fore.YELLOW}Would you like to proceed with this trade? (y/n): {Fore.RESET}").strip().lower()
                            if confirmation not in ["yes", "y"]:
                                print(f"\n{Fore.RED}Trade cancelled by user.")
                                return
                            print(f"\n{Fore.YELLOW}Initiating trade execution...")
                            trade_log_groups = [
                                f"/aws/lambda/{app_name}-{env_name}-PortfolioManagerAgent",
                                f"/aws/lambda/{app_name}-{env_name}-TradeExecutionAgent"
                            ]
                            new_log_streamer = LogStreamReader()
                            new_log_streamer.set_log_groups(trade_log_groups)
                            new_start_time = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(2)
                            new_start_time = int((datetime.now() - timedelta(seconds=5)).timestamp() * 1000)
                            with concurrent.futures.ThreadPoolExecutor(max_workers=len(trade_log_groups) + 1) as new_executor:
                                new_futures = [
                                    new_executor.submit(new_log_streamer.stream_log_group, log_group, new_start_time)
                                    for log_group in trade_log_groups
                                ]
                                new_printer_future = new_executor.submit(new_log_streamer.print_logs)
                                trade_payload = {
                                    "jsonrpc": "2.0",
                                    "id": response_data.get("session_id") or f"{task_id}-trade",
                                    "method": "message/send",
                                    "params": {
                                        "skill": "portfolio-orchestration",
                                        "message": {
                                            "id": response_data.get("session_id") or task_id,
                                            "contextId": response_data.get("session_id") or task_id,
                                            "user_input": response_data.get("user_input", ""),
                                            "trade_confirmation_phase": True,
                                            "trade_details": updated_trade_details,
                                            "created_at": datetime.now().isoformat(),
                                            "modified_at": datetime.now().isoformat(),
                                            "kind": "task"
                                        }
                                    }
                                }
                                async with session.post(api_url, json=trade_payload, headers={"Content-Type": "application/json"}) as trade_response:
                                    trade_raw = await trade_response.json()
                                    if "result" in trade_raw and "message" in trade_raw["result"]:
                                        trade_result = trade_raw["result"]["message"]
                                    else:
                                        trade_result = trade_raw
                                    await format_response(trade_result, phase="trade")

                                    new_log_streamer.stop()
                                    for future in new_futures + [new_printer_future]:
                                        try:
                                            future.result(timeout=5)
                                        except Exception:
                                            pass

                                    print(f"\n{Fore.CYAN}CloudWatch Logs:")
                                    for log_group in trade_log_groups:
                                        log_link = generate_cloudwatch_log_link(
                                            log_group,
                                            response_data.get("session_id") or task_id,
                                            start_time=new_start_time
                                        )
                                        print(f"{Fore.CYAN}• {log_group}: {Fore.BLUE}{log_link}{Fore.RESET}")

                                    print(f"\n{Fore.YELLOW}Note: Click the links above to view detailed logs and database records.{Fore.RESET}")
                                    region = os.environ.get("AWS_REGION", "us-east-1")
                                    db_link = generate_dynamodb_link(
                                        f"{app_name}-{env_name}-trade-execution",
                                        region=region,
                                        task_id=response_data.get("session_id") or task_id
                                    )
                                    print(f"{Fore.CYAN}• Trade Execution: {Fore.BLUE}{db_link}{Fore.RESET}")
                    return response_data
    except Exception as e:
        print(f"{Fore.RED}Error in send_request: {str(e)}")
        if 'log_streamer' in locals():
            log_streamer.stop()
        return None


async def main():
    try:
        print_banner()
        
        # Check for API ID in order: command line arg, env var, then prompt
        if len(sys.argv) > 1:
            api_id = sys.argv[1].strip()
            print(Fore.GREEN + f"✓ Using API ID from command line: {api_id}")
        elif os.environ.get("PORTFOLIO_MANAGER_API_ID"):
            api_id = os.environ.get("PORTFOLIO_MANAGER_API_ID").strip()
            print(Fore.GREEN + f"✓ Using API ID from environment variable: {api_id}")
        else:
            api_id = input(Fore.CYAN + "Enter your Portfolio Manager API Gateway ID (e.g., abc123xyz): ").strip()
        
        if not api_id:
            print(Fore.RED + "❌ API ID is required.")
            return

        api_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/{env_name}/message/send"

        while True:
            question = input(Fore.CYAN + f"\n💬 Enter your portfolio question (or 'exit' to quit): {Fore.RESET}").strip()
            if not question:
                print(Fore.RED + "❌ You must provide a question.")
                continue
            if question.lower() == 'exit':
                print(Fore.YELLOW + "\nThank you for using A2A Advisory! Goodbye! 👋 ✨")
                print("\n" * 4)
                break

            print(Fore.YELLOW + "\nProcessing your request... Real-time logs will appear below:\n")
            log_streamer = LogStreamReader()
            await send_request(api_url, question, log_streamer)

    except Exception as e:
        print(f"{Fore.RED}Error in main: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
