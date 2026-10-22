-- Frozen PostgreSQL schema from main dc54338; Alembic revision add_agent_is_demo.
-- For EMPTY databases only; see standalone.bootstrap.

CREATE TABLE api_keys (
	id SERIAL NOT NULL,
	user_id VARCHAR,
	chatbot_id VARCHAR,
	agent_id VARCHAR,
	api_key VARCHAR NOT NULL,
	is_active BOOLEAN NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	revoked_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id)
)

;

CREATE TABLE chat_sessions (
	session_id VARCHAR NOT NULL,
	chatbot_id VARCHAR NOT NULL,
	agent_id VARCHAR,
	user_id VARCHAR,
	session_title VARCHAR,
	display_message VARCHAR,
	created_time TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	updated_by VARCHAR,
	deleted BOOLEAN NOT NULL,
	deleted_at TIMESTAMP WITHOUT TIME ZONE,
	deleted_by VARCHAR,
	PRIMARY KEY (session_id)
)

;

CREATE TABLE chatbot_connection (
	db_id VARCHAR NOT NULL,
	user_id VARCHAR NOT NULL,
	owner_id VARCHAR,
	chatbot_id VARCHAR,
	agent_id VARCHAR,
	db_host VARCHAR NOT NULL,
	db_name VARCHAR NOT NULL,
	db_user VARCHAR NOT NULL,
	db_password VARCHAR NOT NULL,
	db_port INTEGER NOT NULL,
	db_engine VARCHAR NOT NULL,
	description TEXT,
	is_active BOOLEAN NOT NULL,
	status VARCHAR,
	description_source VARCHAR,
	description_updated_at TIMESTAMP WITHOUT TIME ZONE,
	table_count INTEGER,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	updated_by VARCHAR,
	deleted BOOLEAN NOT NULL,
	deleted_at TIMESTAMP WITHOUT TIME ZONE,
	deleted_by VARCHAR,
	PRIMARY KEY (db_id)
)

;

CREATE TABLE chatbot_details (
	user_id VARCHAR,
	chatbot_id VARCHAR NOT NULL,
	agent_id VARCHAR,
	owner_id VARCHAR,
	chatbot_name VARCHAR NOT NULL,
	system_prompt VARCHAR,
	service_description TEXT,
	provider TEXT,
	model VARCHAR,
	temperature FLOAT,
	greet_message VARCHAR,
	debug_info BOOLEAN,
	show_sql_query BOOLEAN,
	show_db_result BOOLEAN,
	graph_output BOOLEAN,
	allowed_graphs JSON,
	follow_up BOOLEAN,
	voice_input_enabled BOOLEAN,
	voice_output_enabled BOOLEAN,
	suggested_questions JSON,
	max_query_execution_time INTEGER,
	enable_query_caching BOOLEAN,
	default_max_tokens INTEGER,
	is_demo BOOLEAN,
	is_public BOOLEAN,
	allowed_domains JSON,
	fullscreen_is_public BOOLEAN,
	fullscreen_allowed_domains JSON,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	updated_by VARCHAR,
	deleted BOOLEAN NOT NULL,
	deleted_at TIMESTAMP WITHOUT TIME ZONE,
	deleted_by VARCHAR,
	PRIMARY KEY (chatbot_id)
)

;

CREATE TABLE chatbot_invitations (
	invitation_id SERIAL NOT NULL,
	chatbot_id VARCHAR NOT NULL,
	agent_id VARCHAR,
	invited_user_email VARCHAR NOT NULL,
	invited_by_email VARCHAR NOT NULL,
	role VARCHAR,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	updated_by VARCHAR,
	PRIMARY KEY (invitation_id)
)

;

CREATE TABLE chatbot_node_config (
	id SERIAL NOT NULL,
	chatbot_id VARCHAR NOT NULL,
	agent_id VARCHAR,
	user_id VARCHAR,
	node_name VARCHAR NOT NULL,
	provider VARCHAR,
	model VARCHAR,
	temperature FLOAT,
	max_tokens INTEGER,
	is_default BOOLEAN,
	prompt TEXT,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	updated_by VARCHAR,
	deleted_at TIMESTAMP WITHOUT TIME ZONE,
	deleted_by VARCHAR,
	PRIMARY KEY (id)
)

;

CREATE TABLE column_descriptions (
	user_id VARCHAR,
	chatbot_id VARCHAR NOT NULL,
	db_id VARCHAR NOT NULL,
	agent_id VARCHAR,
	table_name VARCHAR NOT NULL,
	column_descriptions JSON,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (chatbot_id, db_id, table_name)
)

;

CREATE TABLE description_generation_jobs (
	job_id VARCHAR NOT NULL,
	agent_id VARCHAR,
	db_id VARCHAR,
	status VARCHAR NOT NULL,
	description TEXT,
	error TEXT,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (job_id)
)

;

CREATE TABLE few_shot_examples (
	chatbot_id VARCHAR NOT NULL,
	db_id VARCHAR NOT NULL,
	agent_id VARCHAR,
	user_id VARCHAR,
	file_name VARCHAR,
	url VARCHAR,
	few_shot_examples TEXT,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	updated_by VARCHAR,
	deleted_at TIMESTAMP WITHOUT TIME ZONE,
	deleted_by VARCHAR,
	PRIMARY KEY (chatbot_id, db_id)
)

;

CREATE TABLE hc_column_profiles (
	chatbot_id VARCHAR NOT NULL,
	db_id VARCHAR NOT NULL,
	agent_id VARCHAR,
	table_name VARCHAR NOT NULL,
	column_profiles JSON,
	profiled_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (chatbot_id, db_id, table_name)
)

;

CREATE TABLE issued_tokens (
	token_id SERIAL NOT NULL,
	token VARCHAR NOT NULL,
	email_id VARCHAR NOT NULL,
	session_id VARCHAR NOT NULL,
	issued_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (token_id)
)

;

CREATE TABLE nl2sql_agent_health_events (
	id SERIAL NOT NULL,
	event_type VARCHAR,
	schema_version INTEGER,
	event_ts TIMESTAMP WITHOUT TIME ZONE,
	agent_id VARCHAR,
	owner_id VARCHAR,
	user_id VARCHAR,
	session_id VARCHAR,
	chat_id VARCHAR NOT NULL,
	request_id VARCHAR,
	trace_id VARCHAR,
	langsmith_run_id VARCHAR,
	query TEXT,
	refined_query TEXT,
	route VARCHAR,
	nodes_used JSON,
	db_id VARCHAR,
	db_ids JSON,
	cross_db BOOLEAN,
	sql_query TEXT,
	selected_tables JSON,
	rows_returned INTEGER,
	chart_generated BOOLEAN,
	pandas_used BOOLEAN,
	status VARCHAR,
	is_answered BOOLEAN,
	failure_category VARCHAR,
	failed_stage VARCHAR,
	failure_detail TEXT,
	from_widget BOOLEAN,
	key_type VARCHAR,
	latency_ms INTEGER,
	db_fetch_ms INTEGER,
	sql_exec_ms INTEGER,
	input_tokens INTEGER,
	output_tokens INTEGER,
	total_tokens INTEGER,
	cost_usd FLOAT,
	cost_complete BOOLEAN,
	retry_count INTEGER,
	provider VARCHAR,
	model VARCHAR,
	node_data JSON,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id)
)

;

CREATE TABLE nl2sql_logs (
	id SERIAL NOT NULL,
	session_id VARCHAR NOT NULL,
	user_id VARCHAR,
	agent_id VARCHAR,
	chat_id VARCHAR NOT NULL,
	query TEXT,
	refined_query VARCHAR,
	sql_query VARCHAR,
	db_output VARCHAR,
	response TEXT,
	graph_output JSON,
	debug_info JSON,
	chart_output JSON,
	gpt_response_time VARCHAR,
	db_fetch_time VARCHAR,
	tokens_consumed VARCHAR,
	is_graph_output BOOLEAN,
	is_debug_mode BOOLEAN,
	is_answered BOOLEAN,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	feedback VARCHAR,
	PRIMARY KEY (id)
)

;

CREATE TABLE nl2sql_owner_config (
	owner_id VARCHAR NOT NULL,
	tier_type VARCHAR NOT NULL,
	base_tier VARCHAR,
	max_agents INTEGER,
	max_llm_tokens_per_month INTEGER,
	max_team_members INTEGER,
	max_queries_per_day INTEGER,
	nl2sql_enabled BOOLEAN NOT NULL,
	nl2sql_enabled_at TIMESTAMP WITHOUT TIME ZONE,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	updated_by VARCHAR,
	PRIMARY KEY (owner_id)
)

;

CREATE TABLE report_run_groups (
	group_id VARCHAR NOT NULL,
	run_id VARCHAR NOT NULL,
	type VARCHAR NOT NULL,
	position INTEGER NOT NULL,
	PRIMARY KEY (group_id)
)

;

CREATE TABLE report_run_queries (
	query_id VARCHAR NOT NULL,
	run_id VARCHAR NOT NULL,
	group_id VARCHAR NOT NULL,
	position INTEGER NOT NULL,
	text VARCHAR NOT NULL,
	PRIMARY KEY (query_id)
)

;

CREATE TABLE report_run_results (
	id SERIAL NOT NULL,
	run_id VARCHAR NOT NULL,
	group_id VARCHAR NOT NULL,
	query_id VARCHAR NOT NULL,
	session_id VARCHAR,
	chat_id VARCHAR,
	answer VARCHAR,
	execution_details JSONB,
	response_time_ms INTEGER,
	token_usage INTEGER,
	is_answered BOOLEAN,
	error VARCHAR,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_run_results_run_query UNIQUE (run_id, query_id)
)

;

CREATE TABLE report_runs (
	run_id VARCHAR NOT NULL,
	report_id VARCHAR NOT NULL,
	agent_id VARCHAR NOT NULL,
	user_id VARCHAR NOT NULL,
	status VARCHAR NOT NULL,
	trigger VARCHAR NOT NULL,
	started_at TIMESTAMP WITHOUT TIME ZONE,
	ended_at TIMESTAMP WITHOUT TIME ZONE,
	failure_reason VARCHAR,
	overall_summary VARCHAR,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	updated_by VARCHAR,
	PRIMARY KEY (run_id)
)

;

CREATE TABLE report_settings (
	agent_id VARCHAR NOT NULL,
	max_queries_per_report INTEGER,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	updated_by VARCHAR,
	PRIMARY KEY (agent_id)
)

;

CREATE TABLE reports (
	report_id VARCHAR NOT NULL,
	agent_id VARCHAR NOT NULL,
	user_id VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	report_instructions VARCHAR,
	query_groups JSONB,
	analysis_prompt VARCHAR,
	schedule JSONB,
	next_run_at TIMESTAMP WITHOUT TIME ZONE,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	deleted BOOLEAN NOT NULL,
	updated_by VARCHAR,
	deleted_by VARCHAR,
	deleted_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (report_id)
)

;

CREATE TABLE table_descriptions (
	user_id VARCHAR,
	chatbot_id VARCHAR NOT NULL,
	db_id VARCHAR NOT NULL,
	agent_id VARCHAR,
	file_name VARCHAR,
	url VARCHAR,
	description JSON,
	entry_flags JSON,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	updated_by VARCHAR,
	deleted_at TIMESTAMP WITHOUT TIME ZONE,
	deleted_by VARCHAR,
	high_cardinality_columns JSON,
	PRIMARY KEY (chatbot_id, db_id)
)

;

CREATE TABLE usage_events (
	event_id UUID NOT NULL,
	owner_id VARCHAR(255),
	key_type VARCHAR(50),
	agent_id VARCHAR(255),
	service_id VARCHAR(255),
	service_type VARCHAR(100) NOT NULL,
	operation VARCHAR(100) NOT NULL,
	label VARCHAR(100),
	session_id VARCHAR(255),
	request_id VARCHAR(255),
	operation_id VARCHAR(255),
	timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
	metadata JSONB,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	PRIMARY KEY (event_id)
)

;

CREATE TABLE user_provider_keys (
	id UUID NOT NULL,
	owner_id VARCHAR(255) NOT NULL,
	provider VARCHAR(100) NOT NULL,
	encrypted_key TEXT NOT NULL,
	key_hash VARCHAR(64) NOT NULL,
	key_mask VARCHAR(50) NOT NULL,
	is_valid BOOLEAN DEFAULT true NOT NULL,
	last_used_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT user_provider_keys_owner_id_provider_key UNIQUE (owner_id, provider)
)

;

CREATE TABLE users (
	user_id VARCHAR NOT NULL,
	email_id VARCHAR NOT NULL,
	user_name VARCHAR,
	deleted BOOLEAN NOT NULL,
	PRIMARY KEY (user_id)
)

;

CREATE TABLE widgets_settings (
	id SERIAL NOT NULL,
	chatbot_id VARCHAR,
	agent_id VARCHAR,
	user_id VARCHAR,
	heading VARCHAR,
	sub_heading VARCHAR,
	greet_message VARCHAR,
	color VARCHAR,
	show_sources BOOLEAN,
	widget_icon VARCHAR,
	widget_avatar VARCHAR,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	deleted BOOLEAN NOT NULL,
	updated_by VARCHAR,
	deleted_by VARCHAR,
	deleted_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id)
)

;

CREATE TABLE usage_metrics (
	metric_id BIGSERIAL NOT NULL,
	event_id UUID NOT NULL,
	metric_name VARCHAR(100) NOT NULL,
	metric_value NUMERIC(20, 4) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	PRIMARY KEY (metric_id),
	FOREIGN KEY(event_id) REFERENCES usage_events (event_id) ON DELETE CASCADE
)

;
CREATE INDEX ix_api_keys_agent_id ON api_keys (agent_id);
CREATE UNIQUE INDEX ix_api_keys_api_key ON api_keys (api_key);
CREATE INDEX ix_api_keys_chatbot_id ON api_keys (chatbot_id);
CREATE INDEX ix_api_keys_user_id ON api_keys (user_id);
CREATE INDEX ix_chat_sessions_agent_id ON chat_sessions (agent_id);
CREATE INDEX ix_chat_sessions_chatbot_id ON chat_sessions (chatbot_id);
CREATE INDEX ix_chat_sessions_deleted_by ON chat_sessions (deleted_by);
CREATE INDEX ix_chat_sessions_updated_by ON chat_sessions (updated_by);
CREATE INDEX ix_chat_sessions_user_id ON chat_sessions (user_id);
CREATE INDEX ix_chatbot_connection_agent_id ON chatbot_connection (agent_id);
CREATE INDEX ix_chatbot_connection_chatbot_id ON chatbot_connection (chatbot_id);
CREATE INDEX ix_chatbot_connection_db_id ON chatbot_connection (db_id);
CREATE INDEX ix_chatbot_connection_deleted ON chatbot_connection (deleted);
CREATE INDEX ix_chatbot_connection_deleted_by ON chatbot_connection (deleted_by);
CREATE INDEX ix_chatbot_connection_owner_id ON chatbot_connection (owner_id);
CREATE INDEX ix_chatbot_connection_updated_by ON chatbot_connection (updated_by);
CREATE INDEX ix_chatbot_connection_user_id ON chatbot_connection (user_id);
CREATE INDEX ix_chatbot_details_agent_id ON chatbot_details (agent_id);
CREATE INDEX ix_chatbot_details_deleted_by ON chatbot_details (deleted_by);
CREATE INDEX ix_chatbot_details_is_demo ON chatbot_details (is_demo);
CREATE INDEX ix_chatbot_details_owner_id ON chatbot_details (owner_id);
CREATE INDEX ix_chatbot_details_updated_by ON chatbot_details (updated_by);
CREATE INDEX ix_chatbot_invitations_agent_id ON chatbot_invitations (agent_id);
CREATE INDEX ix_chatbot_invitations_chatbot_id ON chatbot_invitations (chatbot_id);
CREATE INDEX ix_chatbot_invitations_invited_by_email ON chatbot_invitations (invited_by_email);
CREATE INDEX ix_chatbot_invitations_invited_user_email ON chatbot_invitations (invited_user_email);
CREATE INDEX ix_chatbot_invitations_updated_by ON chatbot_invitations (updated_by);
CREATE INDEX ix_chatbot_node_config_agent_id ON chatbot_node_config (agent_id);
CREATE INDEX ix_chatbot_node_config_chatbot_id ON chatbot_node_config (chatbot_id);
CREATE INDEX ix_chatbot_node_config_deleted_by ON chatbot_node_config (deleted_by);
CREATE INDEX ix_chatbot_node_config_node_name ON chatbot_node_config (node_name);
CREATE INDEX ix_chatbot_node_config_updated_by ON chatbot_node_config (updated_by);
CREATE INDEX ix_chatbot_node_config_user_id ON chatbot_node_config (user_id);
CREATE INDEX ix_column_descriptions_agent_id ON column_descriptions (agent_id);
CREATE INDEX ix_column_descriptions_chatbot_id ON column_descriptions (chatbot_id);
CREATE INDEX ix_column_descriptions_db_id ON column_descriptions (db_id);
CREATE INDEX ix_column_descriptions_table_name ON column_descriptions (table_name);
CREATE INDEX ix_column_descriptions_user_id ON column_descriptions (user_id);
CREATE INDEX ix_description_generation_jobs_agent_id ON description_generation_jobs (agent_id);
CREATE INDEX ix_description_generation_jobs_db_id ON description_generation_jobs (db_id);
CREATE INDEX ix_few_shot_examples_agent_id ON few_shot_examples (agent_id);
CREATE INDEX ix_few_shot_examples_chatbot_id ON few_shot_examples (chatbot_id);
CREATE INDEX ix_few_shot_examples_db_id ON few_shot_examples (db_id);
CREATE INDEX ix_few_shot_examples_deleted_by ON few_shot_examples (deleted_by);
CREATE INDEX ix_few_shot_examples_updated_by ON few_shot_examples (updated_by);
CREATE INDEX ix_few_shot_examples_user_id ON few_shot_examples (user_id);
CREATE INDEX ix_hc_column_profiles_agent_id ON hc_column_profiles (agent_id);
CREATE INDEX ix_hc_column_profiles_chatbot_id ON hc_column_profiles (chatbot_id);
CREATE INDEX ix_hc_column_profiles_db_id ON hc_column_profiles (db_id);
CREATE INDEX ix_hc_column_profiles_table_name ON hc_column_profiles (table_name);
CREATE INDEX ix_issued_tokens_email_id ON issued_tokens (email_id);
CREATE INDEX ix_issued_tokens_session_id ON issued_tokens (session_id);
CREATE INDEX ix_issued_tokens_token ON issued_tokens (token);
CREATE INDEX ix_nl2sql_agent_health_events_agent_id ON nl2sql_agent_health_events (agent_id);
CREATE UNIQUE INDEX ix_nl2sql_agent_health_events_chat_id ON nl2sql_agent_health_events (chat_id);
CREATE INDEX ix_nl2sql_agent_health_events_db_id ON nl2sql_agent_health_events (db_id);
CREATE INDEX ix_nl2sql_agent_health_events_event_ts ON nl2sql_agent_health_events (event_ts);
CREATE INDEX ix_nl2sql_agent_health_events_failed_stage ON nl2sql_agent_health_events (failed_stage);
CREATE INDEX ix_nl2sql_agent_health_events_failure_category ON nl2sql_agent_health_events (failure_category);
CREATE INDEX ix_nl2sql_agent_health_events_is_answered ON nl2sql_agent_health_events (is_answered);
CREATE INDEX ix_nl2sql_agent_health_events_model ON nl2sql_agent_health_events (model);
CREATE INDEX ix_nl2sql_agent_health_events_owner_id ON nl2sql_agent_health_events (owner_id);
CREATE INDEX ix_nl2sql_agent_health_events_request_id ON nl2sql_agent_health_events (request_id);
CREATE INDEX ix_nl2sql_agent_health_events_route ON nl2sql_agent_health_events (route);
CREATE INDEX ix_nl2sql_agent_health_events_session_id ON nl2sql_agent_health_events (session_id);
CREATE INDEX ix_nl2sql_agent_health_events_status ON nl2sql_agent_health_events (status);
CREATE INDEX ix_nl2sql_agent_health_events_user_id ON nl2sql_agent_health_events (user_id);
CREATE INDEX ix_nl2sql_logs_agent_id ON nl2sql_logs (agent_id);
CREATE INDEX ix_nl2sql_logs_chat_id ON nl2sql_logs (chat_id);
CREATE INDEX ix_nl2sql_logs_session_id ON nl2sql_logs (session_id);
CREATE INDEX ix_nl2sql_logs_user_id ON nl2sql_logs (user_id);
CREATE INDEX ix_nl2sql_owner_config_updated_by ON nl2sql_owner_config (updated_by);
CREATE INDEX idx_run_groups_run ON report_run_groups (run_id);
CREATE INDEX ix_report_run_groups_run_id ON report_run_groups (run_id);
CREATE INDEX idx_run_queries_group ON report_run_queries (group_id);
CREATE INDEX idx_run_queries_run ON report_run_queries (run_id);
CREATE INDEX ix_report_run_queries_group_id ON report_run_queries (group_id);
CREATE INDEX ix_report_run_queries_run_id ON report_run_queries (run_id);
CREATE INDEX idx_run_results_run ON report_run_results (run_id);
CREATE INDEX ix_report_run_results_query_id ON report_run_results (query_id);
CREATE INDEX ix_report_run_results_run_id ON report_run_results (run_id);
CREATE INDEX idx_report_runs_agent ON report_runs (agent_id);
CREATE INDEX idx_report_runs_report ON report_runs (report_id);
CREATE INDEX ix_report_runs_agent_id ON report_runs (agent_id);
CREATE INDEX ix_report_runs_report_id ON report_runs (report_id);
CREATE INDEX ix_report_runs_user_id ON report_runs (user_id);
CREATE INDEX idx_reports_agent_deleted ON reports (agent_id, deleted);
CREATE INDEX ix_reports_agent_id ON reports (agent_id);
CREATE INDEX ix_reports_next_run_at ON reports (next_run_at);
CREATE INDEX ix_reports_user_id ON reports (user_id);
CREATE INDEX ix_table_descriptions_agent_id ON table_descriptions (agent_id);
CREATE INDEX ix_table_descriptions_chatbot_id ON table_descriptions (chatbot_id);
CREATE INDEX ix_table_descriptions_db_id ON table_descriptions (db_id);
CREATE INDEX ix_table_descriptions_deleted_by ON table_descriptions (deleted_by);
CREATE INDEX ix_table_descriptions_updated_by ON table_descriptions (updated_by);
CREATE INDEX ix_table_descriptions_user_id ON table_descriptions (user_id);
CREATE INDEX idx_events_agent_time ON usage_events (agent_id, timestamp) WHERE agent_id IS NOT NULL;
CREATE INDEX idx_events_key_type_time ON usage_events (key_type, timestamp) WHERE key_type IS NOT NULL;
CREATE INDEX idx_events_metadata_gin ON usage_events USING gin (metadata);
CREATE INDEX idx_events_owner_time ON usage_events (owner_id, timestamp) WHERE owner_id IS NOT NULL;
CREATE INDEX idx_events_request ON usage_events (request_id, timestamp) WHERE request_id IS NOT NULL;
CREATE INDEX idx_events_service_id ON usage_events (service_id, timestamp) WHERE service_id IS NOT NULL;
CREATE INDEX idx_events_service_op ON usage_events (service_type, operation, timestamp);
CREATE INDEX idx_events_session ON usage_events (session_id, timestamp) WHERE session_id IS NOT NULL;
CREATE INDEX idx_events_timestamp ON usage_events (timestamp);
CREATE INDEX idx_keys_owner_provider ON user_provider_keys (owner_id, provider);
CREATE INDEX ix_users_email_id ON users (email_id);
CREATE INDEX ix_widgets_settings_agent_id ON widgets_settings (agent_id);
CREATE INDEX ix_widgets_settings_chatbot_id ON widgets_settings (chatbot_id);
CREATE INDEX ix_widgets_settings_deleted ON widgets_settings (deleted);
CREATE INDEX ix_widgets_settings_deleted_by ON widgets_settings (deleted_by);
CREATE INDEX ix_widgets_settings_updated_by ON widgets_settings (updated_by);
CREATE INDEX ix_widgets_settings_user_id ON widgets_settings (user_id);
CREATE INDEX idx_metrics_event ON usage_metrics (event_id);
CREATE INDEX idx_metrics_name ON usage_metrics (metric_name);
CREATE INDEX idx_metrics_name_value ON usage_metrics (metric_name, metric_value);

CREATE UNIQUE INDEX uq_chatbot_invitations_agent_email ON chatbot_invitations (agent_id, lower(invited_user_email));
CREATE INDEX ix_chatbot_invitations_invited_user_email_lower ON chatbot_invitations (lower(invited_user_email));
