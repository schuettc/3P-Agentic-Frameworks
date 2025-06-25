##################################################
### Global variables for naming convention
##################################################

APP_NAME ?=adt
ENV_NAME ?=dev
AWS_REGION =us-east-1

##################################################
#### DO NOT CHANGE
##################################################

IAC_DIR :=iac
LAYER_DIR = iac/agents/layers/python
CORE_DIR = iac/a2a_core

##################################################
export TF_VAR_app_name=$(APP_NAME)
export TF_VAR_env_name=$(ENV_NAME)
export TF_VAR_aws_region=$(AWS_REGION)

# Agent-specific deployment targets
AGENTS := market_analysis risk_assessment portfolio_manager trade_execution

# Configuration verification target
config:
	@echo "Current configuration:"
	@echo "APP_NAME: $$TF_VAR_app_name"
	@echo "ENV_NAME: $$TF_VAR_env_name"
	@echo "AWS_REGION: $$TF_VAR_aws_region"

##################################################
#### Deploy core
##################################################

deploy-core:
	@echo "Creating Lambda layer..."
	@rm -rf $(LAYER_DIR)
	@mkdir -p $(LAYER_DIR)
	@cp -r $(CORE_DIR) $(LAYER_DIR)/
	@python3 -m pip install --platform manylinux2014_aarch64 \
		--implementation cp \
		--python-version 3.12 \
		--only-binary=:all: \
		-r $(CORE_DIR)/requirements.txt \
		--target $(LAYER_DIR)
	@cd iac/agents/layers && zip -r a2a_layer.zip python
	@echo "Layer created successfully."

destroy-core:
	@rm -rf $(LAYER_DIR)
	@rm -f iac/agents/layers/a2a_layer.zip
	@echo "Cleaned up temporary files."

##################################################
#### Deploy agents
##################################################

deploy-market-analysis: config
	cd $(IAC_DIR)/agents/market_analysis && \
	terraform init && \
	terraform apply -auto-approve

destroy-market-analysis: config
	cd $(IAC_DIR)/agents/market_analysis && \
	terraform destroy -auto-approve

deploy-risk-assessment: config
	cd $(IAC_DIR)/agents/risk_assessment && \
	terraform init && \
	terraform apply -auto-approve

destroy-risk-assessment: config
	cd $(IAC_DIR)/agents/risk_assessment && \
	terraform destroy -auto-approve

deploy-portfolio-manager: config
	cd $(IAC_DIR)/agents/portfolio_manager && \
	terraform init && \
	terraform apply -auto-approve

destroy-portfolio-manager: config
	cd $(IAC_DIR)/agents/portfolio_manager && \
	terraform destroy -auto-approve

deploy-trade-execution: config
	cd $(IAC_DIR)/agents/trade_execution && \
	terraform init && \
	terraform apply -auto-approve

destroy-trade-execution: config
	cd $(IAC_DIR)/agents/trade_execution && \
	terraform destroy -auto-approve

.PHONY: config deploy-core deploy-shared deploy-market-analysis deploy-risk-assessment deploy-trade-execution deploy-portfolio-manager
