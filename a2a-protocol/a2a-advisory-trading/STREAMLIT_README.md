# A2A Advisory Trading - Streamlit Web Interface

A modern web interface for the A2A Advisory Trading platform built with Streamlit, providing an intuitive alternative to the command-line interface.

## Overview

The Streamlit web interface offers a user-friendly way to interact with the A2A Advisory Trading system, featuring:
- 💬 Natural language chat interface
- 📊 Post-execution log analysis  
- ✅ Interactive trade confirmation
- 🔍 Detailed agent activity tracking
- 📈 Formatted analysis results

## Prerequisites

- Python 3.12 or higher
- AWS credentials configured (via AWS CLI or environment variables)
- Deployed A2A Advisory Trading infrastructure
- Access to CloudWatch Logs

## Installation

### Using Poetry (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd 3P-Agentic-Frameworks/a2a-protocol/a2a-advisory-trading

# Install dependencies
poetry install

# Run the application
poetry run streamlit run streamlit_app.py
```

### Using pip

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
streamlit run streamlit_app.py
```

## Configuration

### Environment Variables

Create a `.env` file in the project root with the following variables:

```bash
# AWS Configuration
AWS_REGION=us-east-1                    # AWS region where infrastructure is deployed
APP_NAME=adt                            # Application name prefix
ENV_NAME=dev                            # Environment name (dev, staging, prod)

# Optional: Pre-configure API Gateway ID
PORTFOLIO_MANAGER_API_ID=<your-api-id>  # Skip API discovery if known
```

### AWS Permissions

Ensure your AWS credentials have the following permissions:
- `logs:DescribeLogGroups` - For discovering log groups
- `logs:FilterLogEvents` - For reading CloudWatch logs
- `apigateway:GET` - For API Gateway discovery (if not using PORTFOLIO_MANAGER_API_ID)

## Features

### 1. Chat Interface
- Natural language input for trading requests
- Supports market analysis, risk assessment, and trade execution
- Message history with formatting for better readability

### 2. Agent Activity Tracking
- Real-time indicators showing which agents are processing
- Visual feedback during task execution
- Agent completion status

### 3. Log Analysis
- Automatic log collection after execution
- Agent-specific log counts
- Detailed execution timeline
- Export capabilities for further analysis

### 4. Trade Confirmation
- Interactive form for trade approval
- Clear display of trade details
- Safety confirmation before execution
- Immediate feedback on trade status

### 5. Response Formatting
- Structured display of analysis results
- Expandable sections for detailed information
- Links to AWS resources
- Raw response data available in debug mode

## Usage Guide

### Starting a Session

1. Launch the application:
   ```bash
   streamlit run streamlit_app.py
   ```

2. Open your browser to `http://localhost:8501`

3. The interface will automatically discover and configure the API endpoints

### Making Requests

#### Market Analysis
```
"Analyze the technology sector outlook"
"What's the market trend for renewable energy?"
"Show me analysis for AAPL"
```

#### Risk Assessment
```
"Assess the risk of investing in emerging markets"
"What's the risk profile for TSLA?"
"Evaluate portfolio risk with 60% stocks, 40% bonds"
```

#### Trade Execution
```
"Buy 100 shares of MSFT"
"Sell 50 shares of GOOGL"
"Execute a trade for 200 shares of AMZN"
```

### Understanding the Interface

#### Main Chat Area
- Type your requests in natural language
- View formatted responses with clear sections
- See agent activity indicators during processing

#### Logs Tab
- View execution logs after completion
- See which agents were invoked
- Check log counts per agent
- Download logs for offline analysis

#### Help Tab
- Quick reference for supported queries
- Example requests for each agent type
- Tips for effective usage

### Trade Confirmation Workflow

1. **Request a trade** through the chat interface
2. **Review the analysis** provided by the system
3. **Confirm details** in the trade confirmation form:
   - Symbol
   - Action (buy/sell)
   - Quantity
   - Price (optional)
4. **Submit** to execute the trade
5. **View results** in the response area

## Troubleshooting

### Common Issues

#### "Failed to discover Portfolio Manager API ID"
- Ensure your AWS infrastructure is deployed
- Check AWS credentials and permissions
- Verify the APP_NAME and ENV_NAME match your deployment
- Set PORTFOLIO_MANAGER_API_ID manually in .env

#### "No logs found for this execution"
- Wait a few seconds after execution completes
- Ensure CloudWatch Logs permissions are configured
- Check if the Lambda functions are creating logs

#### Streamlit Threading Warnings
- These are suppressed by default but are harmless
- Related to background thread usage for async operations

#### Poetry Installation Issues
- Ensure Python 3.12+ is installed
- Try `poetry update` if dependencies conflict
- Use pip installation as an alternative

### Debug Mode

Enable debug mode to see raw API responses:
1. Check "Show Debug Info" in the sidebar
2. Raw JSON responses will appear below formatted results

## Development

### Running in Development Mode

```bash
# Enable auto-reload
streamlit run streamlit_app.py --server.runOnSave true

# Custom port
streamlit run streamlit_app.py --server.port 8080

# Enable debug logging
STREAMLIT_LOG_LEVEL=debug streamlit run streamlit_app.py
```

### Project Structure

```
streamlit_app.py          # Main application file
requirements.txt          # Python dependencies
pyproject.toml           # Poetry configuration
.env                     # Environment configuration (not in git)
```

### Key Components

- `StreamlitLogStreamReader`: Handles CloudWatch log retrieval
- `send_request()`: Manages async API communication
- `display_analysis_results()`: Formats and displays responses
- `handle_trade_confirmation()`: Interactive trade workflow

## Comparison with CLI

| Feature | CLI | Streamlit |
|---------|-----|-----------|
| Interface | Command-line | Web browser |
| Log Viewing | Real-time streaming | Post-execution download |
| Trade Confirmation | Terminal prompts | Interactive forms |
| Response Format | Colored text | Structured UI |
| Session History | Not preserved | Maintained in browser |
| Debug Mode | Always visible | Toggle option |
| Multi-tasking | Sequential | Tabbed interface |

## Best Practices

1. **Clear Requests**: Be specific in your requests for better agent routing
2. **One Company at a Time**: Process single companies/sectors per request
3. **Review Before Trading**: Always review analysis before confirming trades
4. **Check Logs**: Use the Logs tab to understand agent interactions
5. **Session Management**: Your chat history is preserved during the session

## Support

For issues or questions:
1. Check the Help tab in the application
2. Review CloudWatch Logs for detailed error messages
3. Consult the main [README.md](README.md) for infrastructure details
4. Open an issue in the project repository